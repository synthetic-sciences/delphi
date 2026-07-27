"""Stable domain contracts shared by optional provider implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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
