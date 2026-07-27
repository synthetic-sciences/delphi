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
    ProviderSearchHit,
    ProviderSearchRequest,
    ProviderSearchResponse,
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


def test_search_provider_contracts_are_bounded_and_json_safe() -> None:
    request = ProviderSearchRequest(
        query="validate token",
        limit=5,
        timeout_ms=1500,
        source_ids=("repo-1",),
        source_types=("repo",),
        snapshot_ids=(),
    )
    hit = ProviderSearchHit(
        hit_id="chunk-1",
        text="def validate_token(): ...",
        score=0.8,
        title="validate_token",
        source_type="repo",
        source_id="repo-1",
        locator="src/auth.py:10-20",
        metadata={"language": "python"},
    )
    response = ProviderSearchResponse(hits=(hit,))

    assert request.to_dict() == {
        "query": "validate token",
        "limit": 5,
        "timeout_ms": 1500,
        "max_response_bytes": 2_000_000,
        "source_ids": ["repo-1"],
        "source_types": ["repo"],
        "snapshot_ids": [],
    }
    assert response.to_dict()["hits"][0]["metadata"] == {"language": "python"}
    assert response.consumed_bytes > len(hit.text)


def test_snapshot_request_allows_two_versions_of_the_same_source() -> None:
    request = ProviderSearchRequest(
        query="historic behavior",
        source_ids=("repo-1", "repo-1"),
        source_types=("repo", "repo"),
        snapshot_ids=("snapshot-1", "snapshot-2"),
    )

    assert request.source_ids == ("repo-1", "repo-1")
    assert request.snapshot_ids == ("snapshot-1", "snapshot-2")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": ""},
        {"limit": 0},
        {"limit": 101},
        {"timeout_ms": 0},
        {"max_response_bytes": 255},
    ],
)
def test_search_provider_request_rejects_invalid_bounds(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "query": "query",
        "limit": 10,
        "timeout_ms": 1000,
        "max_response_bytes": 2_000_000,
    }
    values.update(kwargs)

    with pytest.raises(ValueError):
        ProviderSearchRequest(**values)  # type: ignore[arg-type]


def test_search_provider_request_caps_source_bindings() -> None:
    with pytest.raises(ValueError, match="at most 100"):
        ProviderSearchRequest(
            query="bounded",
            source_ids=tuple(f"repo-{index}" for index in range(101)),
            source_types=("repo",) * 101,
        )


def test_search_provider_hit_rejects_non_finite_or_out_of_range_scores() -> None:
    with pytest.raises(ValueError):
        ProviderSearchHit(hit_id="h", text="x", score=float("nan"))
    with pytest.raises(ValueError):
        ProviderSearchHit(hit_id="h", text="x", score=-0.1)
    with pytest.raises(ValueError):
        ProviderSearchHit(hit_id="h", text="x", score=1.1)
    with pytest.raises(TypeError):
        ProviderSearchHit(
            hit_id="h",
            text="x",
            score=0.5,
            metadata={"not_json": float("nan")},
        )
