"""Deterministic, policy-aware query planning contracts."""

from __future__ import annotations

import pytest

from synsc.planner.contracts import (
    QueryBudget,
    QueryIntent,
    QueryRequest,
    RetrievalStepKind,
    SourceScope,
)
from synsc.planner.planner import QueryPlanner, classify_query_intent
from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
    ProviderDescriptor,
)
from synsc.providers.policy import NetworkPolicy
from synsc.providers.registry import ProviderRegistry


def _registry(*, accepted: frozenset[ContentClassification] | None = None) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(
        ProviderDescriptor(
            name="remote-search",
            version="1",
            capabilities=frozenset({ProviderCapability.SEARCH}),
            execution=ExecutionLocation.REMOTE,
            accepted_classifications=accepted or frozenset(ContentClassification),
        ),
        lambda: object(),
        priority=20,
    )
    registry.register(
        ProviderDescriptor(
            name="remote-search-secondary",
            version="1",
            capabilities=frozenset({ProviderCapability.SEARCH}),
            execution=ExecutionLocation.REMOTE,
            accepted_classifications=frozenset(ContentClassification),
        ),
        lambda: object(),
        priority=30,
    )
    return registry


def test_query_contracts_are_immutable_validated_and_hide_user_identity() -> None:
    request = QueryRequest(
        query="Where is token validation implemented?",
        user_id="private-user-id",
        scopes=(
            SourceScope(
                source_type="repo",
                source_id="repo-1",
                classification=ContentClassification.PRIVATE,
            ),
        ),
        network=NetworkPolicy.LOCAL_ONLY,
        budget=QueryBudget(max_calls=2, max_results=8),
    )

    plan = QueryPlanner(registry=_registry()).plan(request)
    payload = plan.to_dict()

    assert payload["query"] == request.query
    assert payload["intent"] == "lookup"
    assert payload["network"] == "local_only"
    assert "private-user-id" not in str(payload)
    assert len(plan.plan_id) == 64
    assert plan == QueryPlanner(registry=_registry()).plan(request)


def test_intent_classification_is_stable_and_explainable() -> None:
    assert classify_query_intent("Where is validate_token defined?") is QueryIntent.LOOKUP
    assert classify_query_intent("How does the cache eviction policy work?") is QueryIntent.EXPLAIN
    assert classify_query_intent("Implement an async retry helper") is QueryIntent.IMPLEMENT
    assert classify_query_intent("Compare the evidence across these papers") is QueryIntent.RESEARCH
    assert classify_query_intent("Find current documentation on release signing") is QueryIntent.DISCOVER


def test_local_only_plan_keeps_local_step_and_records_remote_denial() -> None:
    request = QueryRequest(
        query="How does authentication work?",
        user_id="u1",
        include_web=True,
        query_classification=ContentClassification.PUBLIC,
        network=NetworkPolicy.LOCAL_ONLY,
    )

    plan = QueryPlanner(registry=_registry()).plan(request)

    assert [step.kind for step in plan.steps] == [RetrievalStepKind.LOCAL_CURRENT]
    assert plan.steps[0].provider == "local-index"
    assert {skip.reason_code for skip in plan.skips} == {"network_local_only"}


def test_public_online_plan_adds_one_deterministic_remote_search_step() -> None:
    request = QueryRequest(
        query="latest public release notes",
        user_id="u1",
        include_web=True,
        query_classification=ContentClassification.PUBLIC,
        network=NetworkPolicy.ONLINE,
        budget=QueryBudget(max_calls=3, max_remote_calls=1, max_results=12),
    )

    plan = QueryPlanner(registry=_registry()).plan(request)

    assert [step.kind for step in plan.steps] == [
        RetrievalStepKind.LOCAL_CURRENT,
        RetrievalStepKind.PROVIDER_SEARCH,
    ]
    assert plan.steps[1].provider == "remote-search"
    assert plan.steps[1].egress_request is not None
    assert plan.steps[1].egress_decision is not None
    assert plan.steps[1].egress_decision.allowed is True


def test_private_query_requires_opt_in_before_remote_step() -> None:
    denied_request = QueryRequest(
        query="internal incident details",
        user_id="u1",
        include_web=True,
        query_classification=ContentClassification.PRIVATE,
        network=NetworkPolicy.ONLINE,
    )
    allowed_request = QueryRequest(
        query=denied_request.query,
        user_id="u1",
        include_web=True,
        query_classification=ContentClassification.PRIVATE,
        source_opt_in=True,
        network=NetworkPolicy.ONLINE,
    )

    denied = QueryPlanner(registry=_registry()).plan(denied_request)
    allowed = QueryPlanner(registry=_registry()).plan(allowed_request)

    assert all(step.kind is not RetrievalStepKind.PROVIDER_SEARCH for step in denied.steps)
    assert {skip.reason_code for skip in denied.skips} == {"source_opt_in_required"}
    assert any(step.kind is RetrievalStepKind.PROVIDER_SEARCH for step in allowed.steps)


def test_preferred_provider_is_strict_and_allowlist_is_enforced() -> None:
    request = QueryRequest(
        query="public API changes",
        user_id="u1",
        include_web=True,
        query_classification=ContentClassification.PUBLIC,
        network=NetworkPolicy.ALLOWLISTED,
        allowed_providers=frozenset({"remote-search-secondary"}),
        preferred_search_provider="remote-search-secondary",
    )

    plan = QueryPlanner(registry=_registry()).plan(request)

    remote = [step for step in plan.steps if step.kind is RetrievalStepKind.PROVIDER_SEARCH]
    assert [step.provider for step in remote] == ["remote-search-secondary"]


def test_pinned_snapshot_scope_never_adds_a_current_source_fallback() -> None:
    request = QueryRequest(
        query="historic retry behavior",
        user_id="u1",
        scopes=(
            SourceScope(
                source_type="repo",
                source_id="repo-1",
                snapshot_id="snapshot-1",
                classification=ContentClassification.PRIVATE,
            ),
        ),
        network=NetworkPolicy.OFFLINE,
    )

    plan = QueryPlanner(registry=_registry()).plan(request)

    assert [step.kind for step in plan.steps] == [RetrievalStepKind.LOCAL_SNAPSHOT]
    assert plan.steps[0].snapshot_ids == ("snapshot-1",)
    assert plan.steps[0].source_ids == ("repo-1",)
    assert plan.steps[0].source_types == ("repo",)


def test_current_source_scope_preserves_each_type_and_id_binding() -> None:
    request = QueryRequest(
        query="compare exact sources",
        user_id="u1",
        scopes=(
            SourceScope(
                source_type="repo",
                source_id="repo-1",
                classification=ContentClassification.PRIVATE,
            ),
            SourceScope(
                source_type="repo",
                source_id="repo-2",
                classification=ContentClassification.PRIVATE,
            ),
            SourceScope(
                source_type="paper",
                source_id="paper-1",
                classification=ContentClassification.PRIVATE,
            ),
        ),
        network=NetworkPolicy.OFFLINE,
    )

    plan = QueryPlanner(registry=_registry()).plan(request)

    assert plan.steps[0].source_types == ("paper", "repo", "repo")
    assert plan.steps[0].source_ids == ("paper-1", "repo-1", "repo-2")


def test_call_budget_prioritizes_explicit_snapshots_and_records_skips() -> None:
    request = QueryRequest(
        query="retry behavior",
        user_id="u1",
        scopes=(
            SourceScope(
                source_type="repo",
                source_id="repo-current",
                classification=ContentClassification.PRIVATE,
            ),
            SourceScope(
                source_type="repo",
                source_id="repo-pinned",
                snapshot_id="snapshot-1",
                classification=ContentClassification.PRIVATE,
            ),
        ),
        include_web=True,
        query_classification=ContentClassification.PUBLIC,
        network=NetworkPolicy.ONLINE,
        budget=QueryBudget(max_calls=1, max_remote_calls=1),
    )

    plan = QueryPlanner(registry=_registry()).plan(request)

    assert [step.kind for step in plan.steps] == [RetrievalStepKind.LOCAL_SNAPSHOT]
    assert any(skip.reason_code == "call_budget_exhausted" for skip in plan.skips)


def test_unavailable_remote_search_is_an_auditable_skip() -> None:
    request = QueryRequest(
        query="public release notes",
        user_id="u1",
        include_web=True,
        query_classification=ContentClassification.PUBLIC,
        network=NetworkPolicy.ONLINE,
    )

    plan = QueryPlanner(registry=ProviderRegistry()).plan(request)

    assert [step.kind for step in plan.steps] == [RetrievalStepKind.LOCAL_CURRENT]
    assert [skip.reason_code for skip in plan.skips] == ["provider_unavailable"]


def test_planner_preserves_an_explicitly_empty_local_source_scope() -> None:
    plan = QueryPlanner(registry=_registry()).plan(
        QueryRequest(
            query="web only",
            source_types=(),
            include_web=True,
            query_classification=ContentClassification.PUBLIC,
            network=NetworkPolicy.ONLINE,
        )
    )

    assert all(
        step.kind is not RetrievalStepKind.LOCAL_CURRENT
        for step in plan.steps
    )
    assert any(
        step.kind is RetrievalStepKind.PROVIDER_SEARCH
        for step in plan.steps
    )


def test_query_request_caps_source_scopes() -> None:
    with pytest.raises(ValueError, match="at most 100"):
        QueryRequest(
            query="too broad",
            scopes=tuple(
                SourceScope(source_type="repo", source_id=f"repo-{index}")
                for index in range(101)
            ),
        )
