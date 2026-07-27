"""Provider-domain contract tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
    ProviderDescriptor,
    ProviderFailure,
    ProviderFailureCode,
    ProviderHealth,
    ProviderUnavailableError,
)


def test_descriptor_is_immutable_and_serializes_deterministically() -> None:
    descriptor = ProviderDescriptor(
        name="local-test",
        version="1",
        capabilities=frozenset(
            {
                ProviderCapability.SYNTHESIS,
                ProviderCapability.EMBEDDING,
            }
        ),
        execution=ExecutionLocation.LOCAL,
        accepted_classifications=frozenset(ContentClassification),
        health=ProviderHealth.READY,
        supports_retry=True,
        max_request_bytes=1024,
    )

    assert descriptor.to_dict() == {
        "name": "local-test",
        "version": "1",
        "capabilities": ["embedding", "synthesis"],
        "execution": "local",
        "accepted_classifications": [
            "local_sensitive",
            "private",
            "public",
            "unlisted",
        ],
        "health": "ready",
        "supports_streaming": False,
        "supports_cancellation": False,
        "supports_retry": True,
        "supports_cost_estimation": False,
        "max_request_bytes": 1024,
        "max_response_bytes": None,
    }
    with pytest.raises(FrozenInstanceError):
        descriptor.name = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", ""),
        ("version", ""),
        ("capabilities", frozenset()),
        ("accepted_classifications", frozenset()),
        ("max_request_bytes", 0),
        ("max_response_bytes", -1),
    ],
)
def test_descriptor_rejects_invalid_identity_or_limits(
    field: str,
    value: object,
) -> None:
    values: dict[str, object] = {
        "name": "valid",
        "version": "1",
        "capabilities": frozenset({ProviderCapability.EMBEDDING}),
        "execution": ExecutionLocation.LOCAL,
        "accepted_classifications": frozenset({ContentClassification.PUBLIC}),
        "max_request_bytes": None,
        "max_response_bytes": None,
    }
    values[field] = value

    with pytest.raises(ValueError):
        ProviderDescriptor(**values)  # type: ignore[arg-type]


def test_provider_failure_omits_cause_from_safe_serialization() -> None:
    failure = ProviderFailure(
        code=ProviderFailureCode.UNAUTHORIZED,
        message="Credential rejected.",
        retryable=False,
        provider="remote-test",
        cause=RuntimeError("Bearer secret-value"),
    )

    assert failure.to_dict() == {
        "code": "unauthorized",
        "message": "Credential rejected.",
        "retryable": False,
        "provider": "remote-test",
        "retry_after_seconds": None,
    }
    assert "secret-value" not in repr(failure)


def test_provider_unavailable_error_exposes_only_safe_failure_message() -> None:
    failure = ProviderFailure(
        code=ProviderFailureCode.INTERNAL_ERROR,
        message="Provider construction failed.",
        retryable=False,
        provider="remote-test",
        cause=RuntimeError("api-key=secret-value"),
    )

    error = ProviderUnavailableError(failure)

    assert error.failure is failure
    assert str(error) == "remote-test: Provider construction failed."
    assert "secret-value" not in str(error)
