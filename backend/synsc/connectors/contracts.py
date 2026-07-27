"""Stable, transport-neutral contracts for incremental connector providers."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from synsc.providers.contracts import CancellationToken, ProviderDescriptor


def _copy_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("connector metadata cannot contain non-finite numbers")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(
        f"connector metadata is not JSON-compatible: {type(value).__name__}"
    )


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("connector metadata cannot contain non-finite numbers")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(
        f"connector metadata is not JSON-compatible: {type(value).__name__}"
    )


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen = _freeze_json(value)
    assert isinstance(frozen, Mapping)
    return frozen


@dataclass(frozen=True)
class ConnectorSyncRequest:
    """One bounded incremental read from a connector provider."""

    user_id: str
    configuration: Mapping[str, Any]
    cursor: Mapping[str, Any] | None = None
    limit: int = 100
    timeout_ms: int = 30_000
    cancellation: CancellationToken = field(
        default_factory=CancellationToken,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            raise ValueError("connector user_id must not be empty")
        if not 1 <= self.limit <= 1000:
            raise ValueError("connector limit must be between 1 and 1000")
        if not 1 <= self.timeout_ms <= 300_000:
            raise ValueError(
                "connector timeout_ms must be between 1 and 300000"
            )
        if not isinstance(self.cancellation, CancellationToken):
            raise TypeError("cancellation must be a CancellationToken")
        object.__setattr__(
            self,
            "configuration",
            _freeze_mapping(self.configuration),
        )
        if self.cursor is not None:
            object.__setattr__(self, "cursor", _freeze_mapping(self.cursor))

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "configuration": _copy_json(self.configuration),
            "cursor": (
                _copy_json(self.cursor) if self.cursor is not None else None
            ),
            "limit": self.limit,
            "timeout_ms": self.timeout_ms,
        }


@dataclass(frozen=True)
class ConnectorRecord:
    """One normalized external record or a tombstone for a prior record."""

    external_id: str
    locator: str
    content: str = field(default="", repr=False)
    deleted: bool = False
    accessible_principals: tuple[str, ...] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.external_id.strip():
            raise ValueError("connector record external_id must not be empty")
        if not self.locator.strip():
            raise ValueError("connector record locator must not be empty")
        if not self.deleted and not self.content:
            raise ValueError(
                "connector record content must not be empty unless deleted"
            )
        if self.accessible_principals is not None:
            if any(
                not principal.strip()
                for principal in self.accessible_principals
            ):
                raise ValueError(
                    "connector accessible_principals cannot contain empty values"
                )
            if len(self.accessible_principals) != len(
                set(self.accessible_principals)
            ):
                raise ValueError(
                    "connector accessible_principals cannot contain duplicates"
                )
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "external_id": self.external_id,
            "locator": self.locator,
            "content": self.content,
            "deleted": self.deleted,
            "accessible_principals": (
                list(self.accessible_principals)
                if self.accessible_principals is not None
                else None
            ),
            "metadata": _copy_json(self.metadata),
        }


@dataclass(frozen=True)
class ConnectorSyncResponse:
    """A bounded page of changes plus the checkpoint after that page."""

    records: tuple[ConnectorRecord, ...] = ()
    next_cursor: Mapping[str, Any] | None = None
    has_more: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.records, tuple) or any(
            not isinstance(record, ConnectorRecord)
            for record in self.records
        ):
            raise TypeError(
                "connector records must be a tuple of ConnectorRecord"
            )
        external_ids = [record.external_id for record in self.records]
        if len(external_ids) != len(set(external_ids)):
            raise ValueError(
                "connector response cannot contain duplicate record ids"
            )
        if self.has_more and self.next_cursor is None:
            raise ValueError(
                "connector response must include a cursor when more pages exist"
            )
        if self.next_cursor is not None:
            object.__setattr__(
                self,
                "next_cursor",
                _freeze_mapping(self.next_cursor),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [record.to_dict() for record in self.records],
            "next_cursor": (
                _copy_json(self.next_cursor)
                if self.next_cursor is not None
                else None
            ),
            "has_more": self.has_more,
        }


@runtime_checkable
class ConnectorProvider(Protocol):
    """Provider boundary; adapters return records and never mutate indexes."""

    descriptor: ProviderDescriptor

    def validate_configuration(
        self,
        configuration: Mapping[str, Any],
    ) -> None: ...

    def sync(self, request: ConnectorSyncRequest) -> ConnectorSyncResponse: ...
