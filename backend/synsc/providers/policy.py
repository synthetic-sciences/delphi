"""Default-deny decisions for data sent to optional remote providers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
    ProviderDescriptor,
)


class NetworkPolicy(str, Enum):
    """Maximum network access available to one request."""

    OFFLINE = "offline"
    LOCAL_ONLY = "local_only"
    ALLOWLISTED = "allowlisted"
    ONLINE = "online"


class OutboundField(str, Enum):
    """Classes of application data a provider request may contain."""

    QUERY = "query"
    URL = "url"
    METADATA = "metadata"
    EXCERPTS = "excerpts"
    FULL_CONTENT = "full_content"
    CREDENTIALS = "credentials"


@dataclass(frozen=True)
class EgressRequest:
    """Facts and explicit grants used to decide one provider call."""

    network: NetworkPolicy
    classification: ContentClassification
    provider: str
    capability: ProviderCapability
    purpose: str
    fields: frozenset[OutboundField]
    source_opt_in: bool = False
    one_request_override: bool = False
    allowed_providers: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider must not be empty")
        if not self.purpose.strip():
            raise ValueError("purpose must not be empty")
        if not self.fields:
            raise ValueError("at least one outbound field is required")


@dataclass(frozen=True)
class EgressDecision:
    """Serializable result of applying policy to a provider call."""

    allowed: bool
    allowed_fields: frozenset[OutboundField]
    reason_code: str
    policy_basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "allowed_fields": sorted(item.value for item in self.allowed_fields),
            "reason_code": self.reason_code,
            "policy_basis": self.policy_basis,
        }


class EgressPolicy:
    """Evaluate provider calls without inspecting or retaining their content."""

    @staticmethod
    def _deny(reason_code: str, policy_basis: str) -> EgressDecision:
        return EgressDecision(
            allowed=False,
            allowed_fields=frozenset(),
            reason_code=reason_code,
            policy_basis=policy_basis,
        )

    @staticmethod
    def _allow(
        request: EgressRequest,
        reason_code: str,
        policy_basis: str,
    ) -> EgressDecision:
        return EgressDecision(
            allowed=True,
            allowed_fields=request.fields,
            reason_code=reason_code,
            policy_basis=policy_basis,
        )

    def evaluate(
        self,
        request: EgressRequest,
        provider: ProviderDescriptor,
    ) -> EgressDecision:
        """Return a deterministic decision without broadening requested fields."""

        if request.provider != provider.name:
            return self._deny(
                "provider_mismatch",
                "the request provider does not match the evaluated provider",
            )
        if request.capability not in provider.capabilities:
            return self._deny(
                "capability_not_supported",
                "the provider does not declare the requested capability",
            )
        if OutboundField.CREDENTIALS in request.fields:
            return self._deny(
                "forbidden_field",
                "credentials cannot be included in application payload fields",
            )
        if request.classification not in provider.accepted_classifications:
            return self._deny(
                "classification_not_supported",
                "the provider does not accept this content classification",
            )
        if provider.execution is ExecutionLocation.LOCAL:
            return self._allow(
                request,
                "local_execution",
                "local execution does not send application data off-machine",
            )
        if request.network is NetworkPolicy.OFFLINE:
            return self._deny(
                "network_offline",
                "offline policy prohibits every remote provider call",
            )
        if request.network is NetworkPolicy.LOCAL_ONLY:
            return self._deny(
                "network_local_only",
                "local-only policy prohibits remote provider calls",
            )
        if (
            request.network is NetworkPolicy.ALLOWLISTED
            and provider.name not in request.allowed_providers
        ):
            return self._deny(
                "provider_not_allowlisted",
                "the remote provider is not in the request allowlist",
            )
        if request.classification is ContentClassification.PUBLIC:
            return self._allow(
                request,
                "public_content",
                "public content is permitted by online policy",
            )
        if not request.source_opt_in:
            return self._deny(
                "source_opt_in_required",
                "non-public source content requires explicit source opt-in",
            )
        if request.classification is ContentClassification.LOCAL_SENSITIVE:
            if not request.one_request_override:
                return self._deny(
                    "one_request_override_required",
                    "local-sensitive content requires a one-request override",
                )
            return self._allow(
                request,
                "one_request_override",
                "local-sensitive content was approved for this request",
            )
        return self._allow(
            request,
            "source_opt_in",
            "non-public source content was explicitly approved",
        )
