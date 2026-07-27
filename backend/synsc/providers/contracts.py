"""Stable domain contracts shared by optional provider implementations."""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable


class ProviderCapability(str, Enum):
    """A discrete operation that a provider can perform."""

    EMBEDDING = "embedding"
    RERANK = "rerank"
    SEARCH = "search"
    CRAWL = "crawl"
    CONNECTOR = "connector"
    SYNTHESIS = "synthesis"
    RESEARCH = "research"
    SYNC = "sync"


class ExecutionLocation(str, Enum):
    """Whether a provider runs in-process or sends data off-machine."""

    LOCAL = "local"
    REMOTE = "remote"


class ContentClassification(str, Enum):
    """Privacy classification attached to a source or outbound payload."""

    PUBLIC = "public"
    UNLISTED = "unlisted"
    PRIVATE = "private"
    LOCAL_SENSITIVE = "local_sensitive"


class ProviderHealth(str, Enum):
    """Adapter availability, independent of per-request credentials."""

    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ProviderFailureCode(str, Enum):
    """Normalized failures independent of provider SDKs."""

    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN_BY_POLICY = "forbidden_by_policy"
    RATE_LIMITED = "rate_limited"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"
    CONTENT_REJECTED = "content_rejected"
    CANCELLED = "cancelled"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class ProviderDescriptor:
    """Serializable adapter metadata that never validates runtime credentials."""

    name: str
    version: str
    capabilities: frozenset[ProviderCapability]
    execution: ExecutionLocation
    accepted_classifications: frozenset[ContentClassification]
    health: ProviderHealth = ProviderHealth.READY
    supports_streaming: bool = False
    supports_cancellation: bool = False
    supports_retry: bool = False
    supports_cost_estimation: bool = False
    max_request_bytes: int | None = None
    max_response_bytes: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("provider name must not be empty")
        if not self.version.strip():
            raise ValueError("provider version must not be empty")
        if not self.capabilities:
            raise ValueError("provider must declare at least one capability")
        if not self.accepted_classifications:
            raise ValueError("provider must accept at least one content classification")
        for label, limit in (
            ("max_request_bytes", self.max_request_bytes),
            ("max_response_bytes", self.max_response_bytes),
        ):
            if limit is not None and limit <= 0:
                raise ValueError(f"{label} must be greater than zero")

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic, JSON-compatible public metadata."""

        return {
            "name": self.name,
            "version": self.version,
            "capabilities": sorted(item.value for item in self.capabilities),
            "execution": self.execution.value,
            "accepted_classifications": sorted(
                item.value for item in self.accepted_classifications
            ),
            "health": self.health.value,
            "supports_streaming": self.supports_streaming,
            "supports_cancellation": self.supports_cancellation,
            "supports_retry": self.supports_retry,
            "supports_cost_estimation": self.supports_cost_estimation,
            "max_request_bytes": self.max_request_bytes,
            "max_response_bytes": self.max_response_bytes,
        }


@dataclass(frozen=True)
class ProviderFailure:
    """Safe provider failure details plus an optional private cause."""

    code: ProviderFailureCode
    message: str
    retryable: bool
    provider: str
    retry_after_seconds: float | None = None
    cause: BaseException | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Return public fields without leaking the underlying exception."""

        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "provider": self.provider,
            "retry_after_seconds": self.retry_after_seconds,
        }


class ProviderUnavailableError(RuntimeError):
    """Raised when a provider cannot be created or selected safely."""

    def __init__(self, failure: ProviderFailure):
        self.failure = failure
        super().__init__(f"{failure.provider}: {failure.message}")


class CancellationToken:
    """Thread-safe cooperative cancellation shared with provider adapters."""

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()


def _copy_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("provider metadata cannot contain non-finite numbers")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"provider metadata is not JSON-compatible: {type(value).__name__}")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("provider metadata cannot contain non-finite numbers")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"provider metadata is not JSON-compatible: {type(value).__name__}")


@dataclass(frozen=True)
class ProviderSearchRequest:
    """Bounded input accepted by local and optional search providers.

    Providers must honor ``timeout_ms``, cooperative ``cancellation``, and
    ``max_response_bytes`` before returning a materialized response.
    """

    query: str
    limit: int = 10
    timeout_ms: int = 10_000
    max_response_bytes: int = 2_000_000
    source_ids: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    snapshot_ids: tuple[str, ...] = ()
    cancellation: CancellationToken = field(
        default_factory=CancellationToken,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("search query must not be empty")
        if not 1 <= self.limit <= 100:
            raise ValueError("search limit must be between 1 and 100")
        if not 1 <= self.timeout_ms <= 300_000:
            raise ValueError("search timeout_ms must be between 1 and 300000")
        if not 256 <= self.max_response_bytes <= 100_000_000:
            raise ValueError(
                "search max_response_bytes must be between 256 and 100000000"
            )
        for label, values in (
            ("source_ids", self.source_ids),
            ("source_types", self.source_types),
            ("snapshot_ids", self.snapshot_ids),
        ):
            if len(values) > 100:
                raise ValueError(f"{label} can contain at most 100 entries")
            if any(not value.strip() for value in values):
                raise ValueError(f"{label} cannot contain empty values")
            if label == "snapshot_ids" and len(values) != len(set(values)):
                raise ValueError(f"{label} cannot contain duplicates")
        if self.snapshot_ids:
            if not (
                len(self.snapshot_ids)
                == len(self.source_ids)
                == len(self.source_types)
            ):
                raise ValueError(
                    "snapshot_ids require parallel source_ids and source_types"
                )
        elif self.source_ids:
            if len(self.source_ids) != len(self.source_types):
                raise ValueError(
                    "source_ids require parallel source_types"
                )
            bindings = tuple(
                zip(
                    self.source_types,
                    self.source_ids,
                    strict=True,
                )
            )
            if len(bindings) != len(set(bindings)):
                raise ValueError("source bindings cannot contain duplicates")
        elif len(self.source_types) != len(set(self.source_types)):
            raise ValueError("source_types cannot contain duplicates")
        if not isinstance(self.cancellation, CancellationToken):
            raise TypeError("cancellation must be a CancellationToken")

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "limit": self.limit,
            "timeout_ms": self.timeout_ms,
            "max_response_bytes": self.max_response_bytes,
            "source_ids": list(self.source_ids),
            "source_types": list(self.source_types),
            "snapshot_ids": list(self.snapshot_ids),
        }


@dataclass(frozen=True)
class ProviderSearchHit:
    """One normalized provider hit with stable provenance fields."""

    hit_id: str
    text: str = field(repr=False)
    score: float
    title: str | None = None
    url: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    snapshot_id: str | None = None
    locator: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.hit_id.strip():
            raise ValueError("search hit_id must not be empty")
        if not self.text and not self.title and not self.url:
            raise ValueError("search hit must include text, title, or url")
        if not math.isfinite(self.score) or not 0.0 <= self.score <= 1.0:
            raise ValueError("search hit score must be finite and between 0 and 1")
        for label, value in (
            ("title", self.title),
            ("url", self.url),
            ("source_type", self.source_type),
            ("source_id", self.source_id),
            ("snapshot_id", self.snapshot_id),
            ("locator", self.locator),
        ):
            if value is not None and not value.strip():
                raise ValueError(f"search hit {label} must not be empty")
        frozen = _freeze_json(self.metadata)
        assert isinstance(frozen, Mapping)
        object.__setattr__(self, "metadata", frozen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hit_id": self.hit_id,
            "text": self.text,
            "score": self.score,
            "title": self.title,
            "url": self.url,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "snapshot_id": self.snapshot_id,
            "locator": self.locator,
            "metadata": _copy_json(self.metadata),
        }


@dataclass(frozen=True)
class ProviderSearchResponse:
    """Validated provider output with a conservative serialized-byte count."""

    hits: tuple[ProviderSearchHit, ...] = ()
    next_cursor: str | None = None
    consumed_bytes: int = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.hits, tuple) or any(
            not isinstance(hit, ProviderSearchHit) for hit in self.hits
        ):
            raise TypeError("search response hits must be a tuple of ProviderSearchHit")
        if self.next_cursor is not None and not self.next_cursor.strip():
            raise ValueError("search next_cursor must not be empty")
        encoded = json.dumps(
            [hit.to_dict() for hit in self.hits],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        object.__setattr__(self, "consumed_bytes", len(encoded))

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": [hit.to_dict() for hit in self.hits],
            "next_cursor": self.next_cursor,
            "consumed_bytes": self.consumed_bytes,
        }


@runtime_checkable
class SearchProvider(Protocol):
    """Runtime-checkable boundary implemented by search adapters."""

    def search(self, request: ProviderSearchRequest) -> ProviderSearchResponse: ...
