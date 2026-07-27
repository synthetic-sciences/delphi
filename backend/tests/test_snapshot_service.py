"""Snapshot publication orchestration tests."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime
from typing import Any

import pytest

from synsc.providers.contracts import ContentClassification
from synsc.snapshots.contracts import SnapshotItem, SnapshotSourceType
from synsc.snapshots.service import (
    SnapshotAccessDeniedError,
    SnapshotMaterial,
    SnapshotService,
)


def _material(
    *,
    version: str | None = "commit-a",
    content: str = "alpha",
) -> SnapshotMaterial:
    return SnapshotMaterial(
        source_id="source-1",
        source_type=SnapshotSourceType.REPOSITORY,
        version=version,
        external_ref="https://example.invalid/repo",
        display_name="example/repo",
        classification=ContentClassification.PRIVATE,
        embedding_model="local-model",
        embedding_fingerprint="b" * 64,
        vector_count=1,
        created_by="user-1",
        manifest={"branch": "main"},
        items=(
            SnapshotItem(
                ordinal=0,
                origin_item_id="chunk-1",
                locator="app.py:1-2",
                content=content,
                token_count=1,
                metadata={"language": "python"},
            ),
        ),
    )


class FakeSnapshotStore:
    def __init__(self, material: SnapshotMaterial):
        self.material = material
        self.snapshots: dict[
            tuple[str, str, str, str, str, str],
            Any,
        ] = {}
        self.items: dict[str, tuple[SnapshotItem, ...]] = {}
        self.heads: dict[tuple[str, str], str] = {}
        self.copy_calls: list[tuple[str, SnapshotSourceType]] = []
        self.seal_calls: list[str] = []
        self.list_user_ids: list[str | None] = []
        self.access = True

    def prepare_capture(self, _session: object) -> None:
        return None

    def load_material(
        self,
        _session: object,
        source_type: SnapshotSourceType,
        source_id: str,
        user_id: str | None,
    ) -> SnapshotMaterial:
        assert source_type is self.material.source_type
        assert source_id == self.material.source_id
        assert user_id == "user-1"
        return self.material

    def put_snapshot(
        self,
        _session: object,
        snapshot,
        items: tuple[SnapshotItem, ...],
    ):
        key = (
            snapshot.source_type.value,
            snapshot.source_id,
            snapshot.version,
            snapshot.content_hash,
            snapshot.embedding_model,
            snapshot.embedding_fingerprint,
        )
        existing = self.snapshots.get(key)
        if existing is not None:
            return existing, False
        self.snapshots[key] = snapshot
        self.items[snapshot.snapshot_id] = items
        return snapshot, True

    def copy_embeddings(
        self,
        _session: object,
        snapshot_id: str,
        source_type: SnapshotSourceType,
    ) -> None:
        self.copy_calls.append((snapshot_id, source_type))

    def set_head(
        self,
        _session: object,
        source_type: SnapshotSourceType,
        source_id: str,
        snapshot_id: str,
    ) -> None:
        self.heads[(source_type.value, source_id)] = snapshot_id

    def seal_snapshot(
        self,
        _session: object,
        snapshot_id: str,
    ):
        self.seal_calls.append(snapshot_id)
        snapshot = self.get_snapshot(_session, snapshot_id)
        assert snapshot is not None
        return replace(snapshot, sealed_at=datetime(2026, 7, 27))

    def get_snapshot(
        self,
        _session: object,
        snapshot_id: str,
    ):
        return next(
            (
                snapshot
                for snapshot in self.snapshots.values()
                if snapshot.snapshot_id == snapshot_id
            ),
            None,
        )

    def can_access_snapshot(
        self,
        _session: object,
        _snapshot,
        _user_id: str | None,
    ) -> bool:
        return self.access

    def list_snapshots(
        self,
        _session: object,
        *,
        user_id: str | None,
        source_type: SnapshotSourceType | None,
        source_id: str | None,
        limit: int,
    ):
        self.list_user_ids.append(user_id)
        snapshots = list(self.snapshots.values())
        if not self.access:
            snapshots = []
        if source_type is not None:
            snapshots = [
                item for item in snapshots
                if item.source_type is source_type
            ]
        if source_id is not None:
            snapshots = [
                item for item in snapshots
                if item.source_id == source_id
            ]
        return snapshots[:limit]

    def list_items(
        self,
        _session: object,
        snapshot_id: str,
        *,
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        return [
            item.to_dict(include_content=True)
            for item in self.items[snapshot_id][offset : offset + limit]
        ]


def _service(store: FakeSnapshotStore) -> SnapshotService:
    return SnapshotService(
        store=store,
        session_factory=lambda: nullcontext(object()),
    )


def test_publish_copies_items_vectors_then_sets_head() -> None:
    store = FakeSnapshotStore(_material())

    snapshot = _service(store).publish(
        SnapshotSourceType.REPOSITORY,
        "source-1",
        user_id="user-1",
    )

    assert snapshot.version == "commit-a"
    assert snapshot.item_count == 1
    assert snapshot.total_tokens == 1
    assert store.copy_calls == [
        (snapshot.snapshot_id, SnapshotSourceType.REPOSITORY)
    ]
    assert store.seal_calls == [snapshot.snapshot_id]
    assert snapshot.sealed_at is not None
    assert store.heads[("repo", "source-1")] == snapshot.snapshot_id


def test_publish_is_idempotent_for_same_version_and_content() -> None:
    store = FakeSnapshotStore(_material())
    service = _service(store)

    first = service.publish(
        SnapshotSourceType.REPOSITORY,
        "source-1",
        user_id="user-1",
    )
    second = service.publish(
        SnapshotSourceType.REPOSITORY,
        "source-1",
        user_id="user-1",
    )

    assert second.snapshot_id == first.snapshot_id
    assert len(store.snapshots) == 1
    assert store.copy_calls == [
        (first.snapshot_id, SnapshotSourceType.REPOSITORY)
    ]
    assert store.seal_calls == [first.snapshot_id]


def test_vector_fingerprint_change_publishes_new_snapshot() -> None:
    store = FakeSnapshotStore(_material())
    service = _service(store)
    first = service.publish(
        SnapshotSourceType.REPOSITORY,
        "source-1",
        user_id="user-1",
    )

    store.material = replace(
        _material(),
        embedding_fingerprint="c" * 64,
        embedding_model="replacement-model",
    )
    second = service.publish(
        SnapshotSourceType.REPOSITORY,
        "source-1",
        user_id="user-1",
    )

    assert second.snapshot_id != first.snapshot_id
    assert second.embedding_model == "replacement-model"
    assert second.embedding_fingerprint == "c" * 64


def test_embedding_model_change_publishes_new_snapshot() -> None:
    store = FakeSnapshotStore(_material())
    service = _service(store)
    first = service.publish(
        SnapshotSourceType.REPOSITORY,
        "source-1",
        user_id="user-1",
    )

    store.material = replace(
        _material(),
        embedding_model="replacement-model",
    )
    second = service.publish(
        SnapshotSourceType.REPOSITORY,
        "source-1",
        user_id="user-1",
    )

    assert second.snapshot_id != first.snapshot_id
    assert second.embedding_fingerprint == first.embedding_fingerprint
    assert second.embedding_model == "replacement-model"


def test_incomplete_vectors_are_explicit_in_snapshot_metadata() -> None:
    store = FakeSnapshotStore(
        replace(
            _material(),
            vector_count=0,
            embedding_fingerprint=(
                "e3b0c44298fc1c149afbf4c8996fb924"
                "27ae41e4649b934ca495991b7852b855"
            ),
        )
    )

    snapshot = _service(store).publish(
        SnapshotSourceType.REPOSITORY,
        "source-1",
        user_id="user-1",
    )

    assert snapshot.vector_count == 0
    assert snapshot.item_count == 1
    assert snapshot.vectors_complete is False


def test_content_change_publishes_new_snapshot_without_mutating_old() -> None:
    store = FakeSnapshotStore(_material())
    service = _service(store)
    first = service.publish(
        SnapshotSourceType.REPOSITORY,
        "source-1",
        user_id="user-1",
    )

    store.material = replace(
        _material(content="beta"),
        version="commit-b",
    )
    second = service.publish(
        SnapshotSourceType.REPOSITORY,
        "source-1",
        user_id="user-1",
    )

    assert second.snapshot_id != first.snapshot_id
    assert first.content_hash != second.content_hash
    assert store.items[first.snapshot_id][0].content == "alpha"
    assert store.items[second.snapshot_id][0].content == "beta"
    assert store.heads[("repo", "source-1")] == second.snapshot_id


def test_missing_provider_version_uses_content_address() -> None:
    store = FakeSnapshotStore(_material(version=None))

    snapshot = _service(store).publish(
        SnapshotSourceType.REPOSITORY,
        "source-1",
        user_id="user-1",
    )

    assert snapshot.version == f"content:{snapshot.content_hash[:16]}"


def test_get_and_list_enforce_snapshot_access() -> None:
    store = FakeSnapshotStore(_material())
    service = _service(store)
    snapshot = service.publish(
        SnapshotSourceType.REPOSITORY,
        "source-1",
        user_id="user-1",
    )
    store.access = False

    with pytest.raises(SnapshotAccessDeniedError):
        service.get(snapshot.snapshot_id, user_id="other-user")

    assert service.list(user_id="other-user") == []
    assert store.list_user_ids == ["other-user"]


def test_get_can_page_items_without_exposing_them_in_catalog() -> None:
    store = FakeSnapshotStore(_material())
    service = _service(store)
    snapshot = service.publish(
        SnapshotSourceType.REPOSITORY,
        "source-1",
        user_id="user-1",
    )

    catalog = service.list(user_id="user-1")
    detail = service.get(
        snapshot.snapshot_id,
        user_id="user-1",
        include_items=True,
        item_limit=10,
    )

    assert "items" not in catalog[0]
    assert detail["items"][0]["content"] == "alpha"
