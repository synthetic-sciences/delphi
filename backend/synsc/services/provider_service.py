"""Transport-neutral provider catalog and policy inspection operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any, TypeVar

from synsc.config import get_provider_policy_config
from synsc.providers.contracts import (
    ContentClassification,
    ProviderCapability,
)
from synsc.providers.policy import (
    EgressPolicy,
    EgressRequest,
    NetworkPolicy,
    OutboundField,
)
from synsc.providers.registry import ProviderRegistry, get_provider_registry

_ALLOWED_POLICY_KEYS = frozenset(
    {
        "provider",
        "capability",
        "network",
        "classification",
        "purpose",
        "fields",
        "source_opt_in",
        "one_request_override",
        "allowed_providers",
    }
)
_EnumT = TypeVar("_EnumT", bound=Enum)
_NETWORK_POLICY_RANK = {
    NetworkPolicy.OFFLINE: 0,
    NetworkPolicy.LOCAL_ONLY: 1,
    NetworkPolicy.ALLOWLISTED: 2,
    NetworkPolicy.ONLINE: 3,
}


def list_providers(
    *,
    registry: ProviderRegistry | None = None,
) -> list[dict[str, Any]]:
    """List safe metadata without constructing provider implementations."""

    selected_registry = registry or get_provider_registry()
    return [
        descriptor.to_dict()
        for descriptor in selected_registry.list_descriptors()
    ]


def _required_string(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _enum_value(
    enum_type: type[_EnumT],
    value: object,
    field: str,
) -> _EnumT:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {value}") from exc


def _string_sequence(payload: Mapping[str, object], field: str) -> list[str]:
    value = payload.get(field)
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return [item.strip() for item in value]


def _boolean(payload: Mapping[str, object], field: str) -> bool:
    value = payload.get(field, False)
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _effective_network_policy(
    requested: NetworkPolicy,
    configured: NetworkPolicy,
) -> NetworkPolicy:
    """Apply a request restriction without exceeding the deployment ceiling."""

    if _NETWORK_POLICY_RANK[requested] <= _NETWORK_POLICY_RANK[configured]:
        return requested
    return configured


def evaluate_egress(
    payload: Mapping[str, object],
    *,
    registry: ProviderRegistry | None = None,
    policy: EgressPolicy | None = None,
) -> dict[str, Any]:
    """Parse an untrusted request and return a safe policy decision."""

    unknown = sorted(set(payload) - _ALLOWED_POLICY_KEYS)
    if unknown:
        raise ValueError(f"unknown policy fields: {', '.join(unknown)}")

    provider_name = _required_string(payload, "provider")
    capability = _enum_value(
        ProviderCapability,
        payload.get("capability"),
        "capability",
    )
    config = get_provider_policy_config()
    requested_network = _enum_value(
        NetworkPolicy,
        payload.get("network", config.network_policy.value),
        "network",
    )
    network = _effective_network_policy(
        requested_network,
        config.network_policy,
    )
    classification = _enum_value(
        ContentClassification,
        payload.get("classification"),
        "classification",
    )
    purpose = _required_string(payload, "purpose")
    fields = frozenset(
        _enum_value(OutboundField, item, "fields")
        for item in _string_sequence(payload, "fields")
    )
    if not fields:
        raise ValueError("fields must contain at least one value")

    configured_allowed_providers = frozenset(
        config.allowed_remote_providers
    )
    if "allowed_providers" in payload:
        requested_allowed_providers = frozenset(
            _string_sequence(payload, "allowed_providers")
        )
        allowed_providers = (
            configured_allowed_providers & requested_allowed_providers
        )
    else:
        allowed_providers = configured_allowed_providers

    selected_registry = registry or get_provider_registry()
    descriptor = selected_registry.get(provider_name).descriptor
    request = EgressRequest(
        network=network,
        classification=classification,
        provider=provider_name,
        capability=capability,
        purpose=purpose,
        fields=fields,
        source_opt_in=_boolean(payload, "source_opt_in"),
        one_request_override=_boolean(payload, "one_request_override"),
        allowed_providers=allowed_providers,
    )
    return (policy or EgressPolicy()).evaluate(request, descriptor).to_dict()
