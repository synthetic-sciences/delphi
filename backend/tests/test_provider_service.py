"""Transport-neutral provider application service tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
    ProviderDescriptor,
)
from synsc.providers.policy import NetworkPolicy
from synsc.providers.registry import ProviderNotFoundError, ProviderRegistry
from synsc.services.provider_service import evaluate_egress, list_providers


def _descriptor(
    name: str,
    execution: ExecutionLocation = ExecutionLocation.REMOTE,
) -> ProviderDescriptor:
    return ProviderDescriptor(
        name=name,
        version="1",
        capabilities=frozenset({ProviderCapability.SYNTHESIS}),
        execution=execution,
        accepted_classifications=frozenset(ContentClassification),
    )


def _registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(_descriptor("remote-b"), lambda: object())
    registry.register(_descriptor("remote-a"), lambda: object())
    return registry


def _set_deployment_policy(
    monkeypatch,
    *,
    network: NetworkPolicy,
    allowed_providers: list[str] | None = None,
) -> None:
    from synsc.services import provider_service

    monkeypatch.setattr(
        provider_service,
        "get_provider_policy_config",
        lambda: SimpleNamespace(
            network_policy=network,
            allowed_remote_providers=allowed_providers or [],
        ),
    )


def test_list_providers_is_deterministic_and_does_not_construct() -> None:
    factory = MagicMock(return_value=object())
    registry = ProviderRegistry()
    registry.register(_descriptor("z-provider"), factory)
    registry.register(_descriptor("a-provider"), lambda: object())

    providers = list_providers(registry=registry)

    assert [item["name"] for item in providers] == [
        "a-provider",
        "z-provider",
    ]
    factory.assert_not_called()


def test_evaluate_egress_returns_plain_structured_decision() -> None:
    result = evaluate_egress(
        {
            "provider": "remote-a",
            "capability": "synthesis",
            "network": "offline",
            "classification": "public",
            "purpose": "answer",
            "fields": ["excerpts"],
        },
        registry=_registry(),
    )

    assert result == {
        "allowed": False,
        "allowed_fields": [],
        "reason_code": "network_offline",
        "policy_basis": "offline policy prohibits every remote provider call",
    }


def test_evaluate_egress_parses_consent_and_allowlist(monkeypatch) -> None:
    _set_deployment_policy(
        monkeypatch,
        network=NetworkPolicy.ALLOWLISTED,
        allowed_providers=["remote-a", "remote-b"],
    )

    result = evaluate_egress(
        {
            "provider": "remote-a",
            "capability": "synthesis",
            "network": "allowlisted",
            "classification": "private",
            "purpose": "answer",
            "fields": ["metadata", "excerpts"],
            "source_opt_in": True,
            "one_request_override": False,
            "allowed_providers": ["remote-b", "remote-a", "remote-a"],
        },
        registry=_registry(),
    )

    assert result["allowed"] is True
    assert result["allowed_fields"] == ["excerpts", "metadata"]
    assert result["reason_code"] == "source_opt_in"


def test_evaluate_egress_uses_configured_network_and_allowlist_defaults(
    monkeypatch,
) -> None:
    _set_deployment_policy(
        monkeypatch,
        network=NetworkPolicy.ALLOWLISTED,
        allowed_providers=["remote-a"],
    )

    result = evaluate_egress(
        {
            "provider": "remote-a",
            "capability": "synthesis",
            "classification": "public",
            "purpose": "answer",
            "fields": ["excerpts"],
        },
        registry=_registry(),
    )

    assert result["allowed"] is True


def test_request_cannot_broaden_deployment_network_ceiling(monkeypatch) -> None:
    _set_deployment_policy(
        monkeypatch,
        network=NetworkPolicy.LOCAL_ONLY,
    )

    result = evaluate_egress(
        {
            "provider": "remote-a",
            "capability": "synthesis",
            "network": "online",
            "classification": "public",
            "purpose": "answer",
            "fields": ["excerpts"],
        },
        registry=_registry(),
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "network_local_only"


def test_request_allowlist_is_intersected_with_deployment_allowlist(
    monkeypatch,
) -> None:
    _set_deployment_policy(
        monkeypatch,
        network=NetworkPolicy.ALLOWLISTED,
        allowed_providers=["remote-a"],
    )

    result = evaluate_egress(
        {
            "provider": "remote-b",
            "capability": "synthesis",
            "network": "allowlisted",
            "classification": "public",
            "purpose": "answer",
            "fields": ["excerpts"],
            "allowed_providers": ["remote-b"],
        },
        registry=_registry(),
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "provider_not_allowlisted"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capability", "not-real"),
        ("network", "not-real"),
        ("classification", "not-real"),
        ("fields", ["not-real"]),
        ("fields", "excerpts"),
        ("source_opt_in", "yes"),
        ("allowed_providers", "remote-a"),
    ],
)
def test_evaluate_egress_rejects_invalid_values(
    field: str,
    value: object,
) -> None:
    payload: dict[str, object] = {
        "provider": "remote-a",
        "capability": "synthesis",
        "network": "online",
        "classification": "public",
        "purpose": "answer",
        "fields": ["excerpts"],
    }
    payload[field] = value

    with pytest.raises(ValueError):
        evaluate_egress(payload, registry=_registry())


def test_evaluate_egress_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown policy fields"):
        evaluate_egress(
            {
                "provider": "remote-a",
                "capability": "synthesis",
                "network": "online",
                "classification": "public",
                "purpose": "answer",
                "fields": ["excerpts"],
                "api_key": "must-not-be-accepted",
            },
            registry=_registry(),
        )


def test_evaluate_egress_requires_named_provider() -> None:
    with pytest.raises(ProviderNotFoundError, match="missing"):
        evaluate_egress(
            {
                "provider": "missing",
                "capability": "synthesis",
                "network": "online",
                "classification": "public",
                "purpose": "answer",
                "fields": ["excerpts"],
            },
            registry=_registry(),
        )


@pytest.mark.parametrize(
    "missing",
    ["provider", "capability", "classification", "purpose", "fields"],
)
def test_evaluate_egress_requires_a_complete_audit_request(
    missing: str,
) -> None:
    payload: dict[str, object] = {
        "provider": "remote-a",
        "capability": "synthesis",
        "classification": "public",
        "purpose": "answer",
        "fields": ["excerpts"],
    }
    payload.pop(missing)

    with pytest.raises(ValueError, match=missing):
        evaluate_egress(payload, registry=_registry())
