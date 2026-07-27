"""Local index provider behavior for current and pinned sources."""

from __future__ import annotations

from typing import Any

import pytest

from synsc.planner.providers import LocalIndexSearchProvider
from synsc.providers.contracts import CancellationToken, ProviderSearchRequest


class FakeSnapshotService:
    def __init__(self) -> None:
        self.calls: list[
            tuple[
                tuple[str, ...],
                str,
                str | None,
                int,
                tuple[tuple[str, str], ...] | None,
                int,
                CancellationToken | None,
            ]
        ] = []

    def search(
        self,
        snapshot_ids: tuple[str, ...],
        query: str,
        *,
        user_id: str | None,
        limit: int,
        expected_sources: tuple[tuple[str, str], ...] | None = None,
        timeout_ms: int = 10_000,
        cancellation: CancellationToken | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            (
                snapshot_ids,
                query,
                user_id,
                limit,
                expected_sources,
                timeout_ms,
                cancellation,
            )
        )
        return [
            {
                "snapshot_id": snapshot_ids[0],
                "source_id": "repo-1",
                "source_type": "repo",
                "origin_item_id": "chunk-1",
                "locator": "src/auth.py:1-4",
                "content": "def validate_token(): pass",
                "score": 0.8,
                "metadata": {"language": "python"},
            }
        ]


def test_local_provider_searches_current_index_with_exact_scope() -> None:
    calls: list[dict[str, Any]] = []

    def retrieve(**kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs)
        return [
            {
                "source_type": "repo",
                "source_id": "repo-1",
                "chunk_id": "chunk-1",
                "text": "content",
                "score": 1.2,
                "path": "src/app.py",
                "line_no": 4,
                "metadata": {"repo_name": "repo"},
            },
            {
                "source_type": "paper",
                "source_id": "paper-out-of-scope",
                "chunk_id": "chunk-2",
                "text": "must be filtered",
                "score": 0.9,
                "metadata": {"paper_title": "other"},
            },
            {
                "source_type": "paper",
                "source_id": "repo-1",
                "chunk_id": "chunk-3",
                "text": "wrong source type",
                "score": 0.9,
                "metadata": {"paper_title": "other"},
            },
        ]

    provider = LocalIndexSearchProvider(
        user_id="u1",
        current_retrieve_fn=retrieve,
        snapshot_service=FakeSnapshotService(),  # type: ignore[arg-type]
    )
    response = provider.search(
        ProviderSearchRequest(
            query="content",
            limit=5,
            timeout_ms=1000,
            source_ids=("repo-1",),
            source_types=("repo",),
        )
    )

    assert len(calls) == 1
    call = calls[0]
    cancellation = call.pop("cancellation")
    assert cancellation.cancelled is False
    assert call == {
        "query": "content",
        "source_bindings": [("repo", "repo-1")],
        "source_types": ["repo"],
        "k": 5,
        "user_id": "u1",
        "timeout_ms": 1000,
    }
    assert len(response.hits) == 1
    assert response.hits[0].source_id == "repo-1"
    assert response.hits[0].score == 1.0
    assert response.hits[0].locator == "src/app.py:4"


def test_local_provider_routes_pinned_scope_only_to_snapshot_service() -> None:
    snapshot_service = FakeSnapshotService()

    def fail_current(**_: Any) -> list[dict[str, Any]]:
        raise AssertionError("current index must not run for pinned snapshots")

    provider = LocalIndexSearchProvider(
        user_id="u1",
        current_retrieve_fn=fail_current,
        snapshot_service=snapshot_service,  # type: ignore[arg-type]
    )
    response_request = ProviderSearchRequest(
        query="validate",
        limit=3,
        timeout_ms=1000,
        source_ids=("repo-1",),
        source_types=("repo",),
        snapshot_ids=("snapshot-1",),
    )
    response = provider.search(response_request)

    assert snapshot_service.calls == [
        (
            ("snapshot-1",),
            "validate",
            "u1",
            3,
            (("repo", "repo-1"),),
            1000,
            response_request.cancellation,
        )
    ]
    assert response.hits[0].snapshot_id == "snapshot-1"


def test_local_provider_does_not_broaden_empty_source_types() -> None:
    calls: list[dict[str, Any]] = []
    provider = LocalIndexSearchProvider(
        user_id="u1",
        current_retrieve_fn=lambda **kwargs: (
            calls.append(kwargs) or []
        ),
        snapshot_service=FakeSnapshotService(),  # type: ignore[arg-type]
    )

    response = provider.search(
        ProviderSearchRequest(query="no local sources", source_types=())
    )

    assert response.hits == ()
    assert calls == []


def test_search_request_rejects_incomplete_snapshot_source_binding() -> None:
    provider = LocalIndexSearchProvider(
        user_id="u1",
        current_retrieve_fn=lambda **_: [],
        snapshot_service=FakeSnapshotService(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="parallel source"):
        provider.search(
            ProviderSearchRequest(
                query="query",
                snapshot_ids=("snapshot-1",),
            )
        )


def test_local_provider_enforces_response_byte_limit_before_returning() -> None:
    def retrieve(**_: Any) -> list[dict[str, Any]]:
        return [
            {
                "source_type": "repo",
                "source_id": "repo-1",
                "chunk_id": f"chunk-{index}",
                "text": "x" * 400,
                "score": 1.0,
            }
            for index in range(5)
        ]

    provider = LocalIndexSearchProvider(
        user_id="u1",
        current_retrieve_fn=retrieve,
        snapshot_service=FakeSnapshotService(),  # type: ignore[arg-type]
    )
    response = provider.search(
        ProviderSearchRequest(
            query="content",
            limit=5,
            timeout_ms=1000,
            max_response_bytes=256,
            source_ids=("repo-1",),
            source_types=("repo",),
        )
    )

    assert response.hits == ()
    assert response.consumed_bytes <= 256


def test_local_provider_accepts_unscoped_type_only_filter() -> None:
    calls: list[dict[str, Any]] = []

    provider = LocalIndexSearchProvider(
        user_id="u1",
        current_retrieve_fn=lambda **kwargs: (
            calls.append(kwargs) or []
        ),
        snapshot_service=FakeSnapshotService(),  # type: ignore[arg-type]
    )

    response = provider.search(
        ProviderSearchRequest(
            query="all local sources",
            source_types=("dataset", "docs", "paper", "repo"),
        )
    )

    assert response.hits == ()
    assert calls[0]["source_bindings"] is None
    assert calls[0]["source_types"] == [
        "dataset",
        "docs",
        "paper",
        "repo",
    ]
