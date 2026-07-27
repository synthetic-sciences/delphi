"""Exact immutable-snapshot retrieval service contracts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import pytest

from synsc.providers.contracts import (
    CancellationToken,
    ContentClassification,
)
from synsc.snapshots.contracts import SnapshotSourceType, SourceSnapshot
from synsc.snapshots.service import (
    PostgresSnapshotStore,
    SnapshotAccessDeniedError,
    SnapshotNotFoundError,
    SnapshotService,
)


def _snapshot(snapshot_id: str, source_id: str) -> SourceSnapshot:
    return SourceSnapshot(
        snapshot_id=snapshot_id,
        source_id=source_id,
        source_type=SnapshotSourceType.REPOSITORY,
        version="v1",
        content_hash="a" * 64,
        external_ref="org/repo",
        display_name="repo",
        classification=ContentClassification.PRIVATE,
        item_count=1,
        total_tokens=3,
        embedding_model="local-model",
        embedding_fingerprint="b" * 64,
        vector_count=1,
        vectors_complete=True,
        created_by="u1",
        sealed_at=datetime.now(timezone.utc),
    )


class FakeSnapshotSearchStore:
    def __init__(self) -> None:
        self.snapshots = {
            "snapshot-1": _snapshot("snapshot-1", "repo-1"),
            "snapshot-2": _snapshot("snapshot-2", "repo-2"),
        }
        self.allowed = {"snapshot-1", "snapshot-2"}
        self.search_calls: list[tuple[tuple[str, ...], str, int]] = []
        self.preflight_timeouts: list[int] = []
        self.search_timeouts: list[int] = []
        self.now: list[float] | None = None

    def get_search_snapshots(
        self,
        session: object,
        snapshot_ids: tuple[str, ...],
        user_id: str | None,
        *,
        timeout_ms: int,
        cancellation: CancellationToken,
    ) -> list[tuple[SourceSnapshot, bool]]:
        assert cancellation.cancelled is False
        self.preflight_timeouts.append(timeout_ms)
        if self.now is not None:
            self.now[0] += 0.4
        return [
            (
                self.snapshots[snapshot_id],
                snapshot_id in self.allowed and user_id == "u1",
            )
            for snapshot_id in snapshot_ids
            if snapshot_id in self.snapshots
        ]

    def search_items(
        self,
        session: object,
        snapshot_ids: tuple[str, ...],
        query: str,
        limit: int,
        user_id: str | None,
        *,
        timeout_ms: int,
        source_types: tuple[SnapshotSourceType, ...],
    ) -> list[dict[str, Any]]:
        assert user_id == "u1"
        self.search_timeouts.append(timeout_ms)
        assert source_types == (SnapshotSourceType.REPOSITORY,)
        self.search_calls.append((snapshot_ids, query, limit))
        return [
            {
                "snapshot_id": snapshot_ids[0],
                "source_id": "repo-1",
                "source_type": "repo",
                "origin_item_id": "chunk-1",
                "locator": "src/auth.py:10-20",
                "content": "def validate_token(): pass",
                "score": 0.8,
                "metadata": {"language": "python"},
            }
        ]


@contextmanager
def _session() -> Iterator[object]:
    yield object()


def test_snapshot_search_uses_only_explicit_snapshot_ids() -> None:
    store = FakeSnapshotSearchStore()
    service = SnapshotService(store=store, session_factory=_session)  # type: ignore[arg-type]

    hits = service.search(
        ("snapshot-1",),
        "validate token",
        user_id="u1",
        limit=5,
        expected_sources=(("repo", "repo-1"),),
    )

    assert store.search_calls == [(("snapshot-1",), "validate token", 5)]
    assert 1 <= store.preflight_timeouts[0] <= 10_000
    assert 1 <= store.search_timeouts[0] <= store.preflight_timeouts[0]
    assert hits[0]["snapshot_id"] == "snapshot-1"
    assert hits[0]["source_id"] == "repo-1"


def test_snapshot_search_rejects_scope_binding_mismatch_before_query() -> None:
    store = FakeSnapshotSearchStore()
    service = SnapshotService(store=store, session_factory=_session)  # type: ignore[arg-type]

    with pytest.raises(SnapshotNotFoundError, match="Snapshot not found"):
        service.search(
            ("snapshot-1",),
            "validate token",
            user_id="u1",
            expected_sources=(("paper", "repo-1"),),
        )

    assert store.search_calls == []


def test_snapshot_search_rejects_missing_or_inaccessible_snapshot_before_query() -> None:
    store = FakeSnapshotSearchStore()
    service = SnapshotService(store=store, session_factory=_session)  # type: ignore[arg-type]

    with pytest.raises(SnapshotNotFoundError, match="Snapshot not found"):
        service.search(("missing",), "query", user_id="u1")

    store.allowed.remove("snapshot-2")
    with pytest.raises(SnapshotAccessDeniedError, match="Snapshot not found"):
        service.search(("snapshot-1", "snapshot-2"), "query", user_id="u1")

    assert store.search_calls == []


@pytest.mark.parametrize(
    ("snapshot_ids", "query", "limit"),
    [
        ((), "query", 10),
        (("snapshot-1",), "", 10),
        (("snapshot-1",), "query", 0),
        (("snapshot-1",), "query", 101),
    ],
)
def test_snapshot_search_validates_bounds(
    snapshot_ids: tuple[str, ...],
    query: str,
    limit: int,
) -> None:
    service = SnapshotService(
        store=FakeSnapshotSearchStore(),  # type: ignore[arg-type]
        session_factory=_session,
    )

    with pytest.raises(ValueError):
        service.search(snapshot_ids, query, user_id="u1", limit=limit)


def test_snapshot_search_passes_only_remaining_timeout_after_preflight() -> None:
    store = FakeSnapshotSearchStore()
    now = [10.0]
    store.now = now
    service = SnapshotService(
        store=store,  # type: ignore[arg-type]
        session_factory=_session,
        clock=lambda: now[0],
    )

    service.search(
        ("snapshot-1",),
        "bounded",
        user_id="u1",
        timeout_ms=1000,
        expected_sources=(("repo", "repo-1"),),
    )

    assert store.preflight_timeouts == [1000]
    assert store.search_timeouts == [599]


def test_snapshot_search_stops_when_cancelled_after_preflight() -> None:
    store = FakeSnapshotSearchStore()
    token = CancellationToken()

    original = store.get_search_snapshots

    def cancel_after_preflight(*args, **kwargs):
        snapshots = original(*args, **kwargs)
        token.cancel()
        return snapshots

    store.get_search_snapshots = cancel_after_preflight  # type: ignore[method-assign]
    service = SnapshotService(
        store=store,  # type: ignore[arg-type]
        session_factory=_session,
    )

    with pytest.raises(TimeoutError, match="cancelled"):
        service.search(
            ("snapshot-1",),
            "bounded",
            user_id="u1",
            cancellation=token,
        )

    assert store.search_calls == []


def test_postgres_snapshot_search_rechecks_acl_in_the_search_statement() -> None:
    class EmptyRows:
        def mappings(self) -> EmptyRows:
            return self

        def all(self) -> list[dict[str, Any]]:
            return []

    class CapturingSession:
        def __init__(self) -> None:
            self.statements: list[str] = []
            self.parameters: list[dict[str, Any]] = []

        def execute(
            self,
            statement: object,
            parameters: dict[str, Any],
        ) -> EmptyRows:
            self.statements.append(str(statement))
            self.parameters.append(parameters)
            return EmptyRows()

    session = CapturingSession()

    hits = PostgresSnapshotStore().search_items(
        session,  # type: ignore[arg-type]
        ("snapshot-1",),
        "token",
        5,
        "u1",
        timeout_ms=800,
        source_types=(SnapshotSourceType.REPOSITORY,),
    )

    assert hits == []
    search_sql = session.statements[-1]
    assert "repositories current_source" in search_sql
    assert "user_repositories access" in search_sql
    assert "documentation_sources" not in search_sql
    assert ":user_id" in search_sql
    assert session.parameters[-1]["user_id"] == "u1"
