"""Deployment-bounded entry points for query planning and execution."""

from __future__ import annotations

from dataclasses import replace

from synsc.config import get_provider_policy_config
from synsc.planner.contracts import QueryExecution, QueryPlan, QueryRequest
from synsc.planner.executor import QueryExecutor
from synsc.planner.planner import QueryPlanner
from synsc.providers.policy import EgressPolicy, NetworkPolicy
from synsc.providers.registry import ProviderRegistry, get_provider_registry

_NETWORK_RANK = {
    NetworkPolicy.OFFLINE: 0,
    NetworkPolicy.LOCAL_ONLY: 1,
    NetworkPolicy.ALLOWLISTED: 2,
    NetworkPolicy.ONLINE: 3,
}


def _effective_request(request: QueryRequest) -> QueryRequest:
    config = get_provider_policy_config()
    network = min(
        (request.network, config.network_policy),
        key=_NETWORK_RANK.__getitem__,
    )
    allowed_providers = request.allowed_providers
    if network is NetworkPolicy.ALLOWLISTED:
        configured = frozenset(config.allowed_remote_providers)
        if config.network_policy is NetworkPolicy.ALLOWLISTED:
            allowed_providers = (
                configured & request.allowed_providers
                if request.allowed_providers
                else configured
            )
    return replace(
        request,
        network=network,
        allowed_providers=allowed_providers,
    )


def plan_query(
    request: QueryRequest,
    *,
    registry: ProviderRegistry | None = None,
    policy: EgressPolicy | None = None,
) -> QueryPlan:
    """Plan a query without exceeding the deployment's network ceiling."""

    selected_registry = registry or get_provider_registry()
    selected_policy = policy or EgressPolicy()
    return QueryPlanner(
        registry=selected_registry,
        policy=selected_policy,
    ).plan(_effective_request(request))


def execute_query(
    request: QueryRequest,
    *,
    authenticated_user_id: str | None,
    registry: ProviderRegistry | None = None,
    policy: EgressPolicy | None = None,
) -> QueryExecution:
    """Plan and execute using identity supplied by the authentication layer."""

    selected_registry = registry or get_provider_registry()
    selected_policy = policy or EgressPolicy()
    authenticated_request = replace(
        request,
        user_id=authenticated_user_id,
    )
    plan = plan_query(
        authenticated_request,
        registry=selected_registry,
        policy=selected_policy,
    )
    return QueryExecutor(
        registry=selected_registry,
        policy=selected_policy,
    ).execute(
        plan,
        authenticated_user_id=authenticated_user_id,
    )
