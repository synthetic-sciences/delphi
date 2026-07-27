"""Immutable source snapshot domain-contract tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from synsc.providers.contracts import ContentClassification
from synsc.snapshots.contracts import (
    SnapshotItem,
    SnapshotSourceType,
    SourceSnapshot,
    compute_snapshot_content_hash,
)


def _item(
    ordinal: int,
    *,
    content: str,
    locator: str,
) -> SnapshotItem:
    return SnapshotItem(
        ordinal=ordinal,
        origin_item_id=f"origin-{ordinal}",
        locator=locator,
        content=content,
        token_count=len(content.split()),
        metadata={"kind": "code", "language": "python"},
    )


def test_snapshot_item_is_immutable_and_hashes_its_content() -> None:
    item = _item(0, content="def hello(): pass", locator="app.py:1-1")

    assert len(item.content_hash) == 64
    assert item.to_dict(include_content=False) == {
        "ordinal": 0,
        "origin_item_id": "origin-0",
        "locator": "app.py:1-1",
        "content_hash": item.content_hash,
        "token_count": 3,
        "metadata": {"kind": "code", "language": "python"},
    }
    with pytest.raises(FrozenInstanceError):
        item.locator = "changed"  # type: ignore[misc]


def test_snapshot_item_deep_freezes_nested_metadata() -> None:
    item = SnapshotItem(
        ordinal=0,
        origin_item_id="origin-0",
        locator="app.py:1",
        content="alpha",
        metadata={"nested": {"kind": "code"}, "tags": ["python"]},
    )

    nested = item.metadata["nested"]
    tags = item.metadata["tags"]
    assert isinstance(nested, dict) is False
    assert isinstance(tags, tuple)
    with pytest.raises(TypeError):
        nested["kind"] = "changed"  # type: ignore[index]


def test_snapshot_content_hash_is_deterministic_and_order_sensitive() -> None:
    first = _item(0, content="alpha", locator="a.py:1")
    second = _item(1, content="beta", locator="b.py:1")

    digest = compute_snapshot_content_hash([first, second])

    assert digest == compute_snapshot_content_hash([first, second])
    assert digest != compute_snapshot_content_hash([second, first])
    assert digest != compute_snapshot_content_hash(
        [_item(0, content="changed", locator="a.py:1"), second]
    )


def test_source_snapshot_serialization_contains_no_item_content() -> None:
    snapshot = SourceSnapshot(
        snapshot_id="snapshot-1",
        source_id="source-1",
        source_type=SnapshotSourceType.REPOSITORY,
        version="abc123",
        content_hash="a" * 64,
        external_ref="https://example.invalid/repo",
        display_name="example/repo",
        classification=ContentClassification.PRIVATE,
        item_count=2,
        total_tokens=10,
        embedding_model="local-model",
        embedding_fingerprint="b" * 64,
        vector_count=2,
        vectors_complete=True,
        created_by="user-1",
        manifest={"branch": "main"},
    )

    public = snapshot.to_dict()

    assert public == {
        "snapshot_id": "snapshot-1",
        "source_id": "source-1",
        "source_type": "repo",
        "version": "abc123",
        "content_hash": "a" * 64,
        "external_ref": "https://example.invalid/repo",
        "display_name": "example/repo",
        "classification": "private",
        "item_count": 2,
        "total_tokens": 10,
        "embedding_model": "local-model",
        "embedding_fingerprint": "b" * 64,
        "vector_count": 2,
        "vectors_complete": True,
        "manifest": {"branch": "main"},
        "created_at": None,
        "sealed_at": None,
    }
    assert "created_by" not in public
    assert snapshot.to_dict(include_owner=True)["created_by"] == "user-1"


@pytest.mark.parametrize(
    ("ordinal", "origin_item_id", "locator"),
    [
        (-1, "origin", "path"),
        (0, "", "path"),
        (0, "origin", ""),
    ],
)
def test_snapshot_item_rejects_invalid_identity_fields(
    ordinal: int,
    origin_item_id: str,
    locator: str,
) -> None:
    with pytest.raises(ValueError):
        SnapshotItem(
            ordinal=ordinal,
            origin_item_id=origin_item_id,
            locator=locator,
            content="content",
            token_count=1,
        )
