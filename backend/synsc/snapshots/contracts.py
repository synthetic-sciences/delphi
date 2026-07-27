"""Stable, transport-neutral contracts for immutable source snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any

from synsc.providers.contracts import ContentClassification


class SnapshotSourceType(str, Enum):
    """Core indexed source families that support durable snapshots."""

    REPOSITORY = "repo"
    PAPER = "paper"
    DATASET = "dataset"
    DOCUMENTATION = "docs"


def _copy_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"snapshot metadata is not JSON-compatible: {type(value).__name__}")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _freeze_json(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"snapshot metadata is not JSON-compatible: {type(value).__name__}")


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen = _freeze_json(value)
    assert isinstance(frozen, Mapping)
    return frozen


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _copy_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True)
class SnapshotItem:
    """One normalized chunk copied into an immutable source snapshot."""

    ordinal: int
    origin_item_id: str
    locator: str
    content: str = field(repr=False)
    token_count: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("snapshot item ordinal must be non-negative")
        if not self.origin_item_id.strip():
            raise ValueError("snapshot item origin_item_id must not be empty")
        if not self.locator.strip():
            raise ValueError("snapshot item locator must not be empty")
        if self.token_count is not None and self.token_count < 0:
            raise ValueError("snapshot item token_count must be non-negative")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        object.__setattr__(
            self,
            "content_hash",
            hashlib.sha256(self.content.encode("utf-8")).hexdigest(),
        )

    def to_dict(self, *, include_content: bool = False) -> dict[str, Any]:
        result = {
            "ordinal": self.ordinal,
            "origin_item_id": self.origin_item_id,
            "locator": self.locator,
            "content_hash": self.content_hash,
            "token_count": self.token_count,
            "metadata": _copy_json(self.metadata),
        }
        if include_content:
            result["content"] = self.content
        return result


def compute_snapshot_content_hash(items: Sequence[SnapshotItem]) -> str:
    """Hash ordered, stable item content without database-generated identities."""

    hasher = hashlib.sha256()
    for item in items:
        payload = {
            "ordinal": item.ordinal,
            "locator": item.locator,
            "content_hash": item.content_hash,
            "token_count": item.token_count,
            "metadata": item.metadata,
        }
        encoded = _canonical_json(payload).encode("utf-8")
        hasher.update(len(encoded).to_bytes(8, "big"))
        hasher.update(encoded)
    return hasher.hexdigest()


@dataclass(frozen=True)
class SourceSnapshot:
    """Public metadata for one published, immutable source version."""

    snapshot_id: str
    source_id: str
    source_type: SnapshotSourceType
    version: str
    content_hash: str
    external_ref: str
    display_name: str
    classification: ContentClassification
    item_count: int
    total_tokens: int
    embedding_model: str
    embedding_fingerprint: str
    vector_count: int
    vectors_complete: bool
    created_by: str | None
    manifest: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    sealed_at: datetime | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("snapshot_id", self.snapshot_id),
            ("source_id", self.source_id),
            ("version", self.version),
            ("external_ref", self.external_ref),
            ("display_name", self.display_name),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        for label, digest in (
            ("content_hash", self.content_hash),
            ("embedding_fingerprint", self.embedding_fingerprint),
        ):
            if len(digest) != 64:
                raise ValueError(
                    f"{label} must be a SHA-256 hexadecimal digest"
                )
            try:
                bytes.fromhex(digest)
            except ValueError as exc:
                raise ValueError(
                    f"{label} must be a SHA-256 hexadecimal digest"
                ) from exc
        if not self.embedding_model.strip():
            raise ValueError("embedding_model must not be empty")
        if (
            self.item_count < 0
            or self.total_tokens < 0
            or self.vector_count < 0
        ):
            raise ValueError("snapshot counts must be non-negative")
        if self.vector_count > self.item_count:
            raise ValueError("vector_count cannot exceed item_count")
        if self.vectors_complete != (self.vector_count == self.item_count):
            raise ValueError(
                "vectors_complete must match vector and item counts"
            )
        object.__setattr__(self, "manifest", _freeze_mapping(self.manifest))

    def to_dict(self, *, include_owner: bool = False) -> dict[str, Any]:
        result = {
            "snapshot_id": self.snapshot_id,
            "source_id": self.source_id,
            "source_type": self.source_type.value,
            "version": self.version,
            "content_hash": self.content_hash,
            "external_ref": self.external_ref,
            "display_name": self.display_name,
            "classification": self.classification.value,
            "item_count": self.item_count,
            "total_tokens": self.total_tokens,
            "embedding_model": self.embedding_model,
            "embedding_fingerprint": self.embedding_fingerprint,
            "vector_count": self.vector_count,
            "vectors_complete": self.vectors_complete,
            "manifest": _copy_json(self.manifest),
            "created_at": (
                self.created_at.isoformat()
                if self.created_at is not None
                else None
            ),
            "sealed_at": (
                self.sealed_at.isoformat()
                if self.sealed_at is not None
                else None
            ),
        }
        if include_owner:
            result["created_by"] = self.created_by
        return result
