"""Immutable contracts for policy-aware query plans and executions."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
)
from synsc.providers.policy import (
    EgressDecision,
    EgressRequest,
    NetworkPolicy,
)

_SOURCE_TYPES = frozenset({"repo", "paper", "dataset", "docs"})


def _copy_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("planner metadata cannot contain non-finite numbers")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"planner metadata is not JSON-compatible: {type(value).__name__}")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("planner metadata cannot contain non-finite numbers")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"planner metadata is not JSON-compatible: {type(value).__name__}")


class QueryIntent(str, Enum):
    """Stable high-level query intent used for explainable planning."""

    LOOKUP = "lookup"
    EXPLAIN = "explain"
    IMPLEMENT = "implement"
    RESEARCH = "research"
    DISCOVER = "discover"


class RetrievalStepKind(str, Enum):
    """Discrete retrieval operations understood by the executor."""

    LOCAL_CURRENT = "local_current"
    LOCAL_SNAPSHOT = "local_snapshot"
    PROVIDER_SEARCH = "provider_search"


@dataclass(frozen=True)
class QueryBudget:
    """Hard ceilings shared by planning and runtime execution.

    ``max_response_bytes`` bounds serialized provider-hit payload admitted
    into fusion. The small execution envelope and audit records are accounted
    separately and are not part of this content-ingress ceiling.
    """

    max_calls: int = 3
    max_remote_calls: int = 1
    max_results: int = 20
    max_response_bytes: int = 2_000_000
    deadline_ms: int = 15_000

    def __post_init__(self) -> None:
        if not 0 <= self.max_calls <= 100:
            raise ValueError("max_calls must be between 0 and 100")
        if not 0 <= self.max_remote_calls <= self.max_calls:
            raise ValueError("max_remote_calls must be between 0 and max_calls")
        if not 1 <= self.max_results <= 100:
            raise ValueError("max_results must be between 1 and 100")
        if not 256 <= self.max_response_bytes <= 100_000_000:
            raise ValueError("max_response_bytes must be between 256 and 100000000")
        if not 1 <= self.deadline_ms <= 300_000:
            raise ValueError("deadline_ms must be between 1 and 300000")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_calls": self.max_calls,
            "max_remote_calls": self.max_remote_calls,
            "max_results": self.max_results,
            "max_response_bytes": self.max_response_bytes,
            "deadline_ms": self.deadline_ms,
        }


@dataclass(frozen=True)
class SourceScope:
    """One current logical source or one exact immutable snapshot."""

    source_type: str
    source_id: str
    snapshot_id: str | None = None
    classification: ContentClassification = ContentClassification.PRIVATE

    def __post_init__(self) -> None:
        if self.source_type not in _SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {self.source_type}")
        if not self.source_id.strip():
            raise ValueError("source_id must not be empty")
        if self.snapshot_id is not None and not self.snapshot_id.strip():
            raise ValueError("snapshot_id must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "snapshot_id": self.snapshot_id,
            "classification": self.classification.value,
        }


@dataclass(frozen=True)
class QueryRequest:
    """All facts that may influence one query plan."""

    query: str
    user_id: str | None = field(default=None, repr=False)
    scopes: tuple[SourceScope, ...] = ()
    source_types: tuple[str, ...] = ("repo", "paper", "dataset", "docs")
    include_web: bool = False
    query_classification: ContentClassification = ContentClassification.PRIVATE
    network: NetworkPolicy = NetworkPolicy.LOCAL_ONLY
    allowed_providers: frozenset[str] = frozenset()
    preferred_search_provider: str | None = None
    source_opt_in: bool = False
    one_request_override: bool = False
    budget: QueryBudget = field(default_factory=QueryBudget)

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("query must not be empty")
        if len(self.query) > 4000:
            raise ValueError("query must not exceed 4000 characters")
        if self.user_id is not None and not self.user_id.strip():
            raise ValueError("user_id must not be empty")
        if any(source_type not in _SOURCE_TYPES for source_type in self.source_types):
            raise ValueError("source_types contains an unsupported source type")
        if len(self.source_types) != len(set(self.source_types)):
            raise ValueError("source_types cannot contain duplicates")
        if len(self.scopes) > 100:
            raise ValueError("scopes can contain at most 100 entries")
        scope_keys = [
            (scope.source_type, scope.source_id, scope.snapshot_id)
            for scope in self.scopes
        ]
        if len(scope_keys) != len(set(scope_keys)):
            raise ValueError("scopes cannot contain duplicates")
        if any(not provider.strip() for provider in self.allowed_providers):
            raise ValueError("allowed_providers cannot contain empty values")
        if (
            self.preferred_search_provider is not None
            and not self.preferred_search_provider.strip()
        ):
            raise ValueError("preferred_search_provider must not be empty")


@dataclass(frozen=True)
class PlanStep:
    """One admitted provider operation in deterministic execution order."""

    step_id: str
    kind: RetrievalStepKind
    provider: str
    capability: ProviderCapability
    execution: ExecutionLocation
    query: str = field(repr=False)
    limit: int = 10
    source_ids: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    snapshot_ids: tuple[str, ...] = ()
    reason: str = ""
    egress_request: EgressRequest | None = field(default=None, repr=False)
    egress_decision: EgressDecision | None = None

    def __post_init__(self) -> None:
        if not self.step_id.strip() or not self.provider.strip():
            raise ValueError("plan step identity must not be empty")
        if not self.query.strip():
            raise ValueError("plan step query must not be empty")
        if not 1 <= self.limit <= 100:
            raise ValueError("plan step limit must be between 1 and 100")
        if not self.reason.strip():
            raise ValueError("plan step reason must not be empty")
        if self.kind is RetrievalStepKind.LOCAL_SNAPSHOT:
            if not self.snapshot_ids:
                raise ValueError("local snapshot step requires snapshot_ids")
            if not (
                len(self.snapshot_ids)
                == len(self.source_ids)
                == len(self.source_types)
            ):
                raise ValueError(
                    "local snapshot step requires parallel snapshot/source bindings"
                )
        if self.kind is RetrievalStepKind.LOCAL_CURRENT and self.snapshot_ids:
            raise ValueError("local current step cannot include snapshot_ids")
        if (
            self.kind is RetrievalStepKind.LOCAL_CURRENT
            and self.source_ids
            and len(self.source_ids) != len(self.source_types)
        ):
            raise ValueError(
                "local current step requires parallel source bindings"
            )

    @staticmethod
    def _egress_request_dict(request: EgressRequest) -> dict[str, Any]:
        return {
            "network": request.network.value,
            "classification": request.classification.value,
            "provider": request.provider,
            "capability": request.capability.value,
            "purpose": request.purpose,
            "fields": sorted(field.value for field in request.fields),
            "source_opt_in": request.source_opt_in,
            "one_request_override": request.one_request_override,
            "allowed_providers": sorted(request.allowed_providers),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "kind": self.kind.value,
            "provider": self.provider,
            "capability": self.capability.value,
            "execution": self.execution.value,
            "query": self.query,
            "limit": self.limit,
            "source_ids": list(self.source_ids),
            "source_types": list(self.source_types),
            "snapshot_ids": list(self.snapshot_ids),
            "reason": self.reason,
            "egress_request": (
                self._egress_request_dict(self.egress_request)
                if self.egress_request is not None
                else None
            ),
            "egress_decision": (
                self.egress_decision.to_dict()
                if self.egress_decision is not None
                else None
            ),
        }


@dataclass(frozen=True)
class PlanSkip:
    """An operation considered but not admitted to the plan."""

    kind: RetrievalStepKind
    reason_code: str
    reason: str
    provider: str | None = None
    decision: EgressDecision | None = None

    def __post_init__(self) -> None:
        if not self.reason_code.strip() or not self.reason.strip():
            raise ValueError("plan skip reason must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "provider": self.provider,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "decision": self.decision.to_dict() if self.decision else None,
        }


def compute_query_plan_id(
    *,
    version: int,
    request_fingerprint: str,
    user_scope_hash: str | None,
    query: str,
    intent: QueryIntent,
    network: NetworkPolicy,
    query_classification: ContentClassification,
    allowed_providers: frozenset[str],
    source_opt_in: bool,
    one_request_override: bool,
    budget: QueryBudget,
    steps: tuple[PlanStep, ...],
    skips: tuple[PlanSkip, ...],
) -> str:
    """Hash every executable and explanatory part of a plan."""

    payload = {
        "version": version,
        "request_fingerprint": request_fingerprint,
        "user_scope_hash": user_scope_hash,
        "query": query,
        "intent": intent.value,
        "network": network.value,
        "query_classification": query_classification.value,
        "allowed_providers": sorted(allowed_providers),
        "source_opt_in": source_opt_in,
        "one_request_override": one_request_override,
        "budget": budget.to_dict(),
        "steps": [step.to_dict() for step in steps],
        "skips": [skip.to_dict() for skip in skips],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class QueryPlan:
    """Deterministic plan plus the policy context needed for runtime checks."""

    plan_id: str
    request_fingerprint: str
    query: str = field(repr=False)
    user_id: str | None = field(default=None, repr=False)
    user_scope_hash: str | None = field(default=None, repr=False)
    intent: QueryIntent = QueryIntent.LOOKUP
    network: NetworkPolicy = NetworkPolicy.LOCAL_ONLY
    query_classification: ContentClassification = ContentClassification.PRIVATE
    allowed_providers: frozenset[str] = frozenset()
    source_opt_in: bool = False
    one_request_override: bool = False
    budget: QueryBudget = field(default_factory=QueryBudget)
    steps: tuple[PlanStep, ...] = ()
    skips: tuple[PlanSkip, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        for label, digest in (
            ("plan_id", self.plan_id),
            ("request_fingerprint", self.request_fingerprint),
        ):
            if len(digest) != 64:
                raise ValueError(f"{label} must be a SHA-256 digest")
            try:
                bytes.fromhex(digest)
            except ValueError as exc:
                raise ValueError(f"{label} must be a SHA-256 digest") from exc
        if self.user_scope_hash is not None:
            if len(self.user_scope_hash) != 64:
                raise ValueError("user_scope_hash must be a SHA-256 digest")
            try:
                bytes.fromhex(self.user_scope_hash)
            except ValueError as exc:
                raise ValueError("user_scope_hash must be a SHA-256 digest") from exc

    def verify_integrity(self) -> bool:
        expected = compute_query_plan_id(
            version=self.version,
            request_fingerprint=self.request_fingerprint,
            user_scope_hash=self.user_scope_hash,
            query=self.query,
            intent=self.intent,
            network=self.network,
            query_classification=self.query_classification,
            allowed_providers=self.allowed_providers,
            source_opt_in=self.source_opt_in,
            one_request_override=self.one_request_override,
            budget=self.budget,
            steps=self.steps,
            skips=self.skips,
        )
        return hmac.compare_digest(self.plan_id, expected)

    def verify_user_scope(self) -> bool:
        actual = (
            hashlib.sha256(self.user_id.encode("utf-8")).hexdigest()
            if self.user_id
            else None
        )
        if self.user_scope_hash is None or actual is None:
            return self.user_scope_hash is actual
        return hmac.compare_digest(self.user_scope_hash, actual)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "plan_id": self.plan_id,
            "request_fingerprint": self.request_fingerprint,
            "query": self.query,
            "intent": self.intent.value,
            "network": self.network.value,
            "query_classification": self.query_classification.value,
            "allowed_providers": sorted(self.allowed_providers),
            "source_opt_in": self.source_opt_in,
            "one_request_override": self.one_request_override,
            "budget": self.budget.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "skips": [skip.to_dict() for skip in self.skips],
        }


@dataclass(frozen=True)
class RetrievalProvenance:
    """One provider's contribution to a fused result."""

    step_id: str
    provider: str
    execution: ExecutionLocation
    rank: int
    provider_score: float

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError("provenance rank must be positive")
        if (
            not math.isfinite(self.provider_score)
            or not 0.0 <= self.provider_score <= 1.0
        ):
            raise ValueError("provider_score must be finite and between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "provider": self.provider,
            "execution": self.execution.value,
            "rank": self.rank,
            "provider_score": self.provider_score,
        }


@dataclass(frozen=True)
class RetrievalHit:
    """A deduplicated, fused result with all contributing provenance."""

    result_id: str
    text: str = field(repr=False)
    score: float
    title: str | None = None
    url: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    snapshot_id: str | None = None
    locator: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    provenance: tuple[RetrievalProvenance, ...] = ()

    def __post_init__(self) -> None:
        if not self.result_id.strip():
            raise ValueError("result_id must not be empty")
        if not math.isfinite(self.score) or self.score < 0.0:
            raise ValueError("result score must be finite and non-negative")
        frozen = _freeze_json(self.metadata)
        assert isinstance(frozen, Mapping)
        object.__setattr__(self, "metadata", frozen)

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "text": self.text,
            "score": self.score,
            "title": self.title,
            "url": self.url,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "snapshot_id": self.snapshot_id,
            "locator": self.locator,
            "metadata": _copy_json(self.metadata),
            "provenance": [item.to_dict() for item in self.provenance],
        }


@dataclass(frozen=True)
class ExecutionRecord:
    """Safe outcome of attempting one plan step."""

    step_id: str
    provider: str
    execution: ExecutionLocation
    status: str
    reason_code: str
    hit_count: int = 0
    consumed_bytes: int = 0
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "provider": self.provider,
            "execution": self.execution.value,
            "status": self.status,
            "reason_code": self.reason_code,
            "hit_count": self.hit_count,
            "consumed_bytes": self.consumed_bytes,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True)
class QueryExecution:
    """Final bounded execution result.

    ``bytes_used`` is the serialized provider-hit payload admitted by the
    executor, matching :class:`QueryBudget.max_response_bytes`.
    """

    plan_id: str
    hits: tuple[RetrievalHit, ...]
    records: tuple[ExecutionRecord, ...]
    stop_reason: str
    calls_used: int
    remote_calls_used: int
    bytes_used: int
    elapsed_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "hits": [hit.to_dict() for hit in self.hits],
            "records": [record.to_dict() for record in self.records],
            "stop_reason": self.stop_reason,
            "calls_used": self.calls_used,
            "remote_calls_used": self.remote_calls_used,
            "bytes_used": self.bytes_used,
            "elapsed_ms": self.elapsed_ms,
        }
