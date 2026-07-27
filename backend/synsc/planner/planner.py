"""Deterministic construction of policy-admitted retrieval plans."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from synsc.planner.contracts import (
    PlanSkip,
    PlanStep,
    QueryIntent,
    QueryPlan,
    QueryRequest,
    RetrievalStepKind,
    compute_query_plan_id,
)
from synsc.providers.contracts import (
    ExecutionLocation,
    ProviderCapability,
)
from synsc.providers.policy import (
    EgressPolicy,
    EgressRequest,
    OutboundField,
)
from synsc.providers.registry import ProviderRegistration, ProviderRegistry

_IMPLEMENT_STARTERS = frozenset(
    {
        "add",
        "build",
        "create",
        "debug",
        "design",
        "fix",
        "implement",
        "migrate",
        "patch",
        "refactor",
        "rewrite",
        "write",
    }
)
_EXPLAIN_STARTERS = frozenset({"explain", "how", "what", "why"})
_RESEARCH_TERMS = frozenset(
    {"compare", "evidence", "literature", "paper", "papers", "research", "survey"}
)
_DISCOVER_TERMS = frozenset(
    {"current", "latest", "online", "release", "releases", "documentation"}
)


def classify_query_intent(query: str) -> QueryIntent:
    """Classify a query with stable, dependency-free lexical rules."""

    words = re.findall(r"[a-z0-9_]+", query.lower())
    if not words:
        return QueryIntent.LOOKUP
    word_set = set(words)
    if words[0] in _IMPLEMENT_STARTERS or word_set.intersection(
        {"implement", "migrate", "refactor", "debug"}
    ):
        return QueryIntent.IMPLEMENT
    if word_set.intersection(_RESEARCH_TERMS):
        return QueryIntent.RESEARCH
    if word_set.intersection(_DISCOVER_TERMS):
        return QueryIntent.DISCOVER
    if words[0] in _EXPLAIN_STARTERS:
        return QueryIntent.EXPLAIN
    return QueryIntent.LOOKUP


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _request_payload(request: QueryRequest) -> dict[str, Any]:
    return {
        "query": request.query,
        "user_scope": (
            hashlib.sha256(request.user_id.encode("utf-8")).hexdigest()
            if request.user_id
            else None
        ),
        "scopes": sorted(
            (scope.to_dict() for scope in request.scopes),
            key=lambda scope: (
                scope["source_type"],
                scope["source_id"],
                scope["snapshot_id"] or "",
            ),
        ),
        "source_types": sorted(request.source_types),
        "include_web": request.include_web,
        "query_classification": request.query_classification.value,
        "network": request.network.value,
        "allowed_providers": sorted(request.allowed_providers),
        "preferred_search_provider": request.preferred_search_provider,
        "source_opt_in": request.source_opt_in,
        "one_request_override": request.one_request_override,
        "budget": request.budget.to_dict(),
    }


class QueryPlanner:
    """Build the smallest useful plan allowed by policy and hard budgets."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        policy: EgressPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy or EgressPolicy()

    @staticmethod
    def _remote_candidates(
        request: QueryRequest,
        registrations: list[ProviderRegistration],
    ) -> list[ProviderRegistration]:
        if request.preferred_search_provider is not None:
            return [
                registration
                for registration in registrations
                if registration.descriptor.name == request.preferred_search_provider
            ]
        return registrations

    def plan(self, request: QueryRequest) -> QueryPlan:
        """Return a deterministic plan without constructing any provider."""

        steps: list[PlanStep] = []
        skips: list[PlanSkip] = []
        calls_planned = 0
        remote_calls_planned = 0

        def add_local_step(
            *,
            kind: RetrievalStepKind,
            source_ids: tuple[str, ...] = (),
            source_types: tuple[str, ...] = (),
            snapshot_ids: tuple[str, ...] = (),
            reason: str,
        ) -> None:
            nonlocal calls_planned
            if calls_planned >= request.budget.max_calls:
                skips.append(
                    PlanSkip(
                        kind=kind,
                        provider="local-index",
                        reason_code="call_budget_exhausted",
                        reason="the total provider call budget is exhausted",
                    )
                )
                return
            calls_planned += 1
            steps.append(
                PlanStep(
                    step_id=f"{len(steps) + 1:02d}-{kind.value}",
                    kind=kind,
                    provider="local-index",
                    capability=ProviderCapability.SEARCH,
                    execution=ExecutionLocation.LOCAL,
                    query=request.query,
                    limit=request.budget.max_results,
                    source_ids=source_ids,
                    source_types=source_types,
                    snapshot_ids=snapshot_ids,
                    reason=reason,
                )
            )

        pinned = sorted(
            (scope for scope in request.scopes if scope.snapshot_id is not None),
            key=lambda scope: (scope.source_type, scope.source_id, scope.snapshot_id or ""),
        )
        current = sorted(
            (scope for scope in request.scopes if scope.snapshot_id is None),
            key=lambda scope: (scope.source_type, scope.source_id),
        )

        if pinned:
            add_local_step(
                kind=RetrievalStepKind.LOCAL_SNAPSHOT,
                source_ids=tuple(scope.source_id for scope in pinned),
                source_types=tuple(scope.source_type for scope in pinned),
                snapshot_ids=tuple(scope.snapshot_id or "" for scope in pinned),
                reason="search the exact immutable source versions requested",
            )
        if current or (not request.scopes and request.source_types):
            add_local_step(
                kind=RetrievalStepKind.LOCAL_CURRENT,
                source_ids=tuple(scope.source_id for scope in current),
                source_types=(
                    tuple(scope.source_type for scope in current)
                    if current
                    else tuple(sorted(request.source_types))
                ),
                reason="search the local index within the requested current-source scope",
            )

        if request.include_web:
            registrations = self.registry.list_registrations(
                capability=ProviderCapability.SEARCH,
                execution=ExecutionLocation.REMOTE,
            )
            candidates = self._remote_candidates(request, registrations)
            if not candidates:
                skips.append(
                    PlanSkip(
                        kind=RetrievalStepKind.PROVIDER_SEARCH,
                        provider=request.preferred_search_provider,
                        reason_code="provider_unavailable",
                        reason="no available remote search provider matches the request",
                    )
                )

            for registration in candidates:
                descriptor = registration.descriptor
                egress_request = EgressRequest(
                    network=request.network,
                    classification=request.query_classification,
                    provider=descriptor.name,
                    capability=ProviderCapability.SEARCH,
                    purpose="retrieve public external context for the query",
                    fields=frozenset({OutboundField.QUERY}),
                    source_opt_in=request.source_opt_in,
                    one_request_override=request.one_request_override,
                    allowed_providers=request.allowed_providers,
                )
                decision = self.policy.evaluate(egress_request, descriptor)
                if not decision.allowed:
                    skips.append(
                        PlanSkip(
                            kind=RetrievalStepKind.PROVIDER_SEARCH,
                            provider=descriptor.name,
                            reason_code=decision.reason_code,
                            reason=decision.policy_basis,
                            decision=decision,
                        )
                    )
                    continue
                if calls_planned >= request.budget.max_calls:
                    skips.append(
                        PlanSkip(
                            kind=RetrievalStepKind.PROVIDER_SEARCH,
                            provider=descriptor.name,
                            reason_code="call_budget_exhausted",
                            reason="the total provider call budget is exhausted",
                        )
                    )
                    break
                if remote_calls_planned >= request.budget.max_remote_calls:
                    skips.append(
                        PlanSkip(
                            kind=RetrievalStepKind.PROVIDER_SEARCH,
                            provider=descriptor.name,
                            reason_code="remote_call_budget_exhausted",
                            reason="the remote provider call budget is exhausted",
                        )
                    )
                    break
                calls_planned += 1
                remote_calls_planned += 1
                steps.append(
                    PlanStep(
                        step_id=f"{len(steps) + 1:02d}-provider-search",
                        kind=RetrievalStepKind.PROVIDER_SEARCH,
                        provider=descriptor.name,
                        capability=ProviderCapability.SEARCH,
                        execution=ExecutionLocation.REMOTE,
                        query=request.query,
                        limit=request.budget.max_results,
                        reason="supplement the local index with policy-approved external search",
                        egress_request=egress_request,
                        egress_decision=decision,
                    )
                )
                break

        request_fingerprint = _canonical_hash(_request_payload(request))
        intent = classify_query_intent(request.query)
        user_scope_hash = (
            hashlib.sha256(request.user_id.encode("utf-8")).hexdigest()
            if request.user_id
            else None
        )
        frozen_steps = tuple(steps)
        frozen_skips = tuple(skips)
        return QueryPlan(
            plan_id=compute_query_plan_id(
                version=1,
                request_fingerprint=request_fingerprint,
                user_scope_hash=user_scope_hash,
                query=request.query,
                intent=intent,
                network=request.network,
                query_classification=request.query_classification,
                allowed_providers=request.allowed_providers,
                source_opt_in=request.source_opt_in,
                one_request_override=request.one_request_override,
                budget=request.budget,
                steps=frozen_steps,
                skips=frozen_skips,
            ),
            request_fingerprint=request_fingerprint,
            query=request.query,
            user_id=request.user_id,
            user_scope_hash=user_scope_hash,
            intent=intent,
            network=request.network,
            query_classification=request.query_classification,
            allowed_providers=request.allowed_providers,
            source_opt_in=request.source_opt_in,
            one_request_override=request.one_request_override,
            budget=request.budget,
            steps=frozen_steps,
            skips=frozen_skips,
        )
