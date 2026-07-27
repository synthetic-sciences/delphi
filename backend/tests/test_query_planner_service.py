"""Deployment policy ceilings around query planning and execution."""

from __future__ import annotations

from types import SimpleNamespace

from synsc.planner.contracts import QueryRequest, RetrievalStepKind
from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
    ProviderDescriptor,
    ProviderSearchRequest,
    ProviderSearchResponse,
)
from synsc.providers.policy import NetworkPolicy
from synsc.providers.registry import ProviderRegistry
from synsc.services import query_planner_service


def _registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(
        ProviderDescriptor(
            name="remote-search",
            version="1",
            capabilities=frozenset({ProviderCapability.SEARCH}),
            execution=ExecutionLocation.REMOTE,
            accepted_classifications=frozenset(ContentClassification),
        ),
        lambda: object(),
    )
    return registry


def test_service_never_exceeds_deployment_network_ceiling(monkeypatch) -> None:
    monkeypatch.setattr(
        query_planner_service,
        "get_provider_policy_config",
        lambda: SimpleNamespace(
            network_policy=NetworkPolicy.LOCAL_ONLY,
            allowed_remote_providers=[],
        ),
    )

    plan = query_planner_service.plan_query(
        QueryRequest(
            query="public current information",
            user_id="u1",
            include_web=True,
            query_classification=ContentClassification.PUBLIC,
            network=NetworkPolicy.ONLINE,
        ),
        registry=_registry(),
    )

    assert plan.network is NetworkPolicy.LOCAL_ONLY
    assert [step.kind for step in plan.steps] == [RetrievalStepKind.LOCAL_CURRENT]


def test_service_intersects_request_and_deployment_allowlists(monkeypatch) -> None:
    monkeypatch.setattr(
        query_planner_service,
        "get_provider_policy_config",
        lambda: SimpleNamespace(
            network_policy=NetworkPolicy.ALLOWLISTED,
            allowed_remote_providers=["remote-search", "another"],
        ),
    )

    plan = query_planner_service.plan_query(
        QueryRequest(
            query="public current information",
            user_id="u1",
            include_web=True,
            query_classification=ContentClassification.PUBLIC,
            network=NetworkPolicy.ALLOWLISTED,
            allowed_providers=frozenset({"remote-search", "not-configured"}),
        ),
        registry=_registry(),
    )

    assert plan.allowed_providers == frozenset({"remote-search"})
    assert any(step.provider == "remote-search" for step in plan.steps)


def test_execute_service_uses_independent_authenticated_identity(
    monkeypatch,
) -> None:
    created_for: list[str | None] = []

    class EmptySearchProvider:
        def search(
            self,
            request: ProviderSearchRequest,
        ) -> ProviderSearchResponse:
            return ProviderSearchResponse()

    registry = ProviderRegistry()
    registry.register(
        ProviderDescriptor(
            name="local-index",
            version="1",
            capabilities=frozenset({ProviderCapability.SEARCH}),
            execution=ExecutionLocation.LOCAL,
            accepted_classifications=frozenset(ContentClassification),
        ),
        lambda **kwargs: (
            created_for.append(kwargs.get("user_id"))
            or EmptySearchProvider()
        ),
    )
    monkeypatch.setattr(
        query_planner_service,
        "get_provider_policy_config",
        lambda: SimpleNamespace(
            network_policy=NetworkPolicy.LOCAL_ONLY,
            allowed_remote_providers=[],
        ),
    )

    result = query_planner_service.execute_query(
        QueryRequest(
            query="private lookup",
            user_id="request-controlled-victim",
        ),
        authenticated_user_id="authenticated-caller",
        registry=registry,
    )

    assert result.calls_used == 1
    assert created_for == ["authenticated-caller"]
