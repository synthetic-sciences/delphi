"""Default-deny provider egress policy tests."""

from __future__ import annotations

import pytest

from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
    ProviderDescriptor,
)
from synsc.providers.policy import (
    EgressPolicy,
    EgressRequest,
    NetworkPolicy,
    OutboundField,
)


def _descriptor(
    *,
    name: str = "remote-test",
    execution: ExecutionLocation = ExecutionLocation.REMOTE,
    accepted: frozenset[ContentClassification] = frozenset(ContentClassification),
    capabilities: frozenset[ProviderCapability] = frozenset(
        {ProviderCapability.SYNTHESIS}
    ),
) -> ProviderDescriptor:
    return ProviderDescriptor(
        name=name,
        version="1",
        capabilities=capabilities,
        execution=execution,
        accepted_classifications=accepted,
    )


def _request(
    *,
    network: NetworkPolicy = NetworkPolicy.ONLINE,
    classification: ContentClassification = ContentClassification.PUBLIC,
    provider: str = "remote-test",
    capability: ProviderCapability = ProviderCapability.SYNTHESIS,
    fields: frozenset[OutboundField] = frozenset({OutboundField.EXCERPTS}),
    source_opt_in: bool = False,
    one_request_override: bool = False,
    allowed_providers: frozenset[str] = frozenset(),
) -> EgressRequest:
    return EgressRequest(
        network=network,
        classification=classification,
        provider=provider,
        capability=capability,
        purpose="answer",
        fields=fields,
        source_opt_in=source_opt_in,
        one_request_override=one_request_override,
        allowed_providers=allowed_providers,
    )


@pytest.mark.parametrize(
    ("network", "classification", "consent", "override", "allowed", "reason"),
    [
        (
            NetworkPolicy.OFFLINE,
            ContentClassification.PUBLIC,
            True,
            True,
            False,
            "network_offline",
        ),
        (
            NetworkPolicy.LOCAL_ONLY,
            ContentClassification.PUBLIC,
            True,
            True,
            False,
            "network_local_only",
        ),
        (
            NetworkPolicy.ONLINE,
            ContentClassification.PUBLIC,
            False,
            False,
            True,
            "public_content",
        ),
        (
            NetworkPolicy.ONLINE,
            ContentClassification.UNLISTED,
            False,
            False,
            False,
            "source_opt_in_required",
        ),
        (
            NetworkPolicy.ONLINE,
            ContentClassification.UNLISTED,
            True,
            False,
            True,
            "source_opt_in",
        ),
        (
            NetworkPolicy.ONLINE,
            ContentClassification.PRIVATE,
            False,
            False,
            False,
            "source_opt_in_required",
        ),
        (
            NetworkPolicy.ONLINE,
            ContentClassification.PRIVATE,
            True,
            False,
            True,
            "source_opt_in",
        ),
        (
            NetworkPolicy.ONLINE,
            ContentClassification.LOCAL_SENSITIVE,
            True,
            False,
            False,
            "one_request_override_required",
        ),
        (
            NetworkPolicy.ONLINE,
            ContentClassification.LOCAL_SENSITIVE,
            True,
            True,
            True,
            "one_request_override",
        ),
    ],
)
def test_remote_policy_matrix(
    network: NetworkPolicy,
    classification: ContentClassification,
    consent: bool,
    override: bool,
    allowed: bool,
    reason: str,
) -> None:
    decision = EgressPolicy().evaluate(
        _request(
            network=network,
            classification=classification,
            source_opt_in=consent,
            one_request_override=override,
        ),
        _descriptor(),
    )

    assert decision.allowed is allowed
    assert decision.reason_code == reason
    assert decision.allowed_fields == (
        frozenset({OutboundField.EXCERPTS}) if allowed else frozenset()
    )


def test_local_provider_is_allowed_under_offline_policy() -> None:
    decision = EgressPolicy().evaluate(
        _request(
            network=NetworkPolicy.OFFLINE,
            classification=ContentClassification.LOCAL_SENSITIVE,
            fields=frozenset(
                {
                    OutboundField.EXCERPTS,
                    OutboundField.FULL_CONTENT,
                }
            ),
        ),
        _descriptor(execution=ExecutionLocation.LOCAL),
    )

    assert decision.allowed is True
    assert decision.reason_code == "local_execution"
    assert decision.allowed_fields == frozenset(
        {
            OutboundField.EXCERPTS,
            OutboundField.FULL_CONTENT,
        }
    )


def test_local_provider_must_accept_content_classification() -> None:
    decision = EgressPolicy().evaluate(
        _request(
            network=NetworkPolicy.OFFLINE,
            classification=ContentClassification.LOCAL_SENSITIVE,
            fields=frozenset({OutboundField.FULL_CONTENT}),
        ),
        _descriptor(
            execution=ExecutionLocation.LOCAL,
            accepted=frozenset({ContentClassification.PUBLIC}),
        ),
    )

    assert decision.allowed is False
    assert decision.reason_code == "classification_not_supported"


def test_allowlisted_network_requires_named_provider() -> None:
    denied = EgressPolicy().evaluate(
        _request(
            network=NetworkPolicy.ALLOWLISTED,
            allowed_providers=frozenset({"another-provider"}),
        ),
        _descriptor(),
    )
    allowed = EgressPolicy().evaluate(
        _request(
            network=NetworkPolicy.ALLOWLISTED,
            allowed_providers=frozenset({"remote-test"}),
        ),
        _descriptor(),
    )

    assert denied.reason_code == "provider_not_allowlisted"
    assert allowed.allowed is True


def test_provider_must_accept_classification_and_capability() -> None:
    classification_denial = EgressPolicy().evaluate(
        _request(classification=ContentClassification.PRIVATE, source_opt_in=True),
        _descriptor(accepted=frozenset({ContentClassification.PUBLIC})),
    )
    capability_denial = EgressPolicy().evaluate(
        _request(capability=ProviderCapability.SEARCH),
        _descriptor(),
    )

    assert classification_denial.reason_code == "classification_not_supported"
    assert capability_denial.reason_code == "capability_not_supported"


def test_policy_rejects_provider_identity_mismatch() -> None:
    decision = EgressPolicy().evaluate(
        _request(provider="different"),
        _descriptor(name="remote-test"),
    )

    assert decision.allowed is False
    assert decision.reason_code == "provider_mismatch"


def test_credentials_are_never_an_allowed_payload_field() -> None:
    decision = EgressPolicy().evaluate(
        _request(
            fields=frozenset(
                {
                    OutboundField.EXCERPTS,
                    OutboundField.CREDENTIALS,
                }
            ),
            source_opt_in=True,
            one_request_override=True,
        ),
        _descriptor(),
    )

    assert decision.allowed is False
    assert decision.reason_code == "forbidden_field"
    assert decision.allowed_fields == frozenset()


def test_policy_decision_serializes_without_source_content() -> None:
    decision = EgressPolicy().evaluate(_request(), _descriptor())

    assert decision.to_dict() == {
        "allowed": True,
        "allowed_fields": ["excerpts"],
        "reason_code": "public_content",
        "policy_basis": "public content is permitted by online policy",
    }


@pytest.mark.parametrize(
    "values",
    [
        {"provider": ""},
        {"purpose": ""},
        {"fields": frozenset()},
    ],
)
def test_request_rejects_missing_audit_fields(values: dict[str, object]) -> None:
    defaults: dict[str, object] = {
        "network": NetworkPolicy.ONLINE,
        "classification": ContentClassification.PUBLIC,
        "provider": "remote-test",
        "capability": ProviderCapability.SYNTHESIS,
        "purpose": "answer",
        "fields": frozenset({OutboundField.EXCERPTS}),
    }
    defaults.update(values)

    with pytest.raises(ValueError):
        EgressRequest(**defaults)  # type: ignore[arg-type]
