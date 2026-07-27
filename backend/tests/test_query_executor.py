"""Query-plan execution, revalidation, budgets, and provenance."""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import replace

from synsc.planner.contracts import (
    QueryBudget,
    QueryRequest,
    compute_query_plan_id,
)
from synsc.planner.executor import QueryExecutor
from synsc.planner.planner import QueryPlanner
from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
    ProviderDescriptor,
    ProviderHealth,
    ProviderSearchHit,
    ProviderSearchRequest,
    ProviderSearchResponse,
)
from synsc.providers.policy import NetworkPolicy
from synsc.providers.registry import ProviderRegistry


class FakeSearchProvider:
    def __init__(self, response: ProviderSearchResponse) -> None:
        self.response = response
        self.requests: list[object] = []

    def search(self, request: object) -> ProviderSearchResponse:
        self.requests.append(request)
        return self.response


class BlockingSearchProvider:
    def search(self, request: object) -> ProviderSearchResponse:
        time.sleep(0.2)
        return ProviderSearchResponse()


def _descriptor(
    name: str,
    execution: ExecutionLocation,
    *,
    accepted: frozenset[ContentClassification] | None = None,
    health: ProviderHealth = ProviderHealth.READY,
    max_request_bytes: int | None = None,
    max_response_bytes: int | None = None,
) -> ProviderDescriptor:
    return ProviderDescriptor(
        name=name,
        version="1",
        capabilities=frozenset({ProviderCapability.SEARCH}),
        execution=execution,
        accepted_classifications=accepted or frozenset(ContentClassification),
        health=health,
        max_request_bytes=max_request_bytes,
        max_response_bytes=max_response_bytes,
    )


def _hit(
    hit_id: str,
    *,
    text: str,
    score: float,
    source_id: str | None = None,
    url: str | None = None,
) -> ProviderSearchHit:
    return ProviderSearchHit(
        hit_id=hit_id,
        text=text,
        score=score,
        title=hit_id,
        url=url,
        source_type="repo" if source_id else None,
        source_id=source_id,
        locator=f"src/{hit_id}.py" if source_id else url,
    )


def test_executor_lazily_runs_steps_deduplicates_and_records_provenance() -> None:
    local = FakeSearchProvider(
        ProviderSearchResponse(
            hits=(
                _hit("shared", text="same answer", score=0.9, url="https://example.test/a"),
                _hit("local", text="local only", score=0.7, source_id="repo-1"),
            )
        )
    )
    remote = FakeSearchProvider(
        ProviderSearchResponse(
            hits=(
                _hit("shared-web", text="same answer", score=0.95, url="https://example.test/a"),
                _hit("remote", text="remote only", score=0.8, url="https://example.test/b"),
            )
        )
    )
    registry = ProviderRegistry()
    registry.register(_descriptor("local-index", ExecutionLocation.LOCAL), lambda **_: local)
    registry.register(_descriptor("remote-search", ExecutionLocation.REMOTE), lambda **_: remote)
    request = QueryRequest(
        query="public API",
        user_id="u1",
        include_web=True,
        query_classification=ContentClassification.PUBLIC,
        network=NetworkPolicy.ONLINE,
        budget=QueryBudget(max_calls=3, max_remote_calls=1, max_results=10),
    )
    plan = QueryPlanner(registry=registry).plan(request)

    result = QueryExecutor(registry=registry).execute(
        plan,
        authenticated_user_id="u1",
    )

    assert result.calls_used == 2
    assert result.remote_calls_used == 1
    assert len(result.hits) == 3
    shared = next(hit for hit in result.hits if hit.url == "https://example.test/a")
    assert [item.provider for item in shared.provenance] == [
        "local-index",
        "remote-search",
    ]
    assert len(local.requests) == 1
    assert len(remote.requests) == 1
    assert all(record.status == "success" for record in result.records)


def test_executor_rechecks_remote_policy_against_runtime_descriptor() -> None:
    planning_registry = ProviderRegistry()
    planning_registry.register(
        _descriptor("local-index", ExecutionLocation.LOCAL),
        lambda **_: FakeSearchProvider(ProviderSearchResponse()),
    )
    planning_registry.register(
        _descriptor("remote-search", ExecutionLocation.REMOTE),
        lambda **_: FakeSearchProvider(ProviderSearchResponse()),
    )
    plan = QueryPlanner(registry=planning_registry).plan(
        QueryRequest(
            query="private terms",
            user_id="u1",
            include_web=True,
            query_classification=ContentClassification.PRIVATE,
            source_opt_in=True,
            network=NetworkPolicy.ONLINE,
        )
    )

    remote = FakeSearchProvider(
        ProviderSearchResponse(hits=(_hit("remote", text="should not run", score=1.0),))
    )
    runtime_registry = ProviderRegistry()
    runtime_registry.register(
        _descriptor("local-index", ExecutionLocation.LOCAL),
        lambda **_: FakeSearchProvider(ProviderSearchResponse()),
    )
    runtime_registry.register(
        _descriptor(
            "remote-search",
            ExecutionLocation.REMOTE,
            accepted=frozenset({ContentClassification.PUBLIC}),
        ),
        lambda **_: remote,
    )

    result = QueryExecutor(registry=runtime_registry).execute(
        plan,
        authenticated_user_id="u1",
    )

    assert remote.requests == []
    remote_record = next(record for record in result.records if record.provider == "remote-search")
    assert remote_record.status == "skipped"
    assert remote_record.reason_code == "classification_not_supported"


def test_executor_enforces_runtime_result_and_byte_budgets() -> None:
    provider = FakeSearchProvider(
        ProviderSearchResponse(
            hits=tuple(
                _hit(f"h-{index}", text="x" * 20, score=1.0 - index / 100)
                for index in range(5)
            )
        )
    )
    registry = ProviderRegistry()
    registry.register(_descriptor("local-index", ExecutionLocation.LOCAL), lambda **_: provider)
    request = QueryRequest(
        query="bounded",
        user_id="u1",
        budget=QueryBudget(
            max_calls=1,
            max_remote_calls=0,
            max_results=3,
            max_response_bytes=2_000,
        ),
    )
    plan = QueryPlanner(registry=registry).plan(request)

    result = QueryExecutor(registry=registry).execute(
        plan,
        authenticated_user_id="u1",
    )

    assert len(result.hits) <= 3
    assert result.bytes_used <= 2_000
    assert result.stop_reason in {"completed", "response_budget_exhausted"}


def test_executor_does_not_execute_a_tampered_remote_step() -> None:
    provider = FakeSearchProvider(ProviderSearchResponse())
    registry = ProviderRegistry()
    registry.register(_descriptor("local-index", ExecutionLocation.LOCAL), lambda **_: provider)
    registry.register(_descriptor("remote-search", ExecutionLocation.REMOTE), lambda **_: provider)
    plan = QueryPlanner(registry=registry).plan(
        QueryRequest(
            query="public",
            user_id="u1",
            include_web=True,
            query_classification=ContentClassification.PUBLIC,
            network=NetworkPolicy.ONLINE,
        )
    )
    remote_index = next(
        index for index, step in enumerate(plan.steps) if step.provider == "remote-search"
    )
    tampered_step = replace(plan.steps[remote_index], egress_request=None)
    tampered_plan = replace(
        plan,
        steps=plan.steps[:remote_index] + (tampered_step,) + plan.steps[remote_index + 1 :],
    )

    result = QueryExecutor(registry=registry).execute(
        tampered_plan,
        authenticated_user_id="u1",
    )

    record = next(item for item in result.records if item.provider == "remote-search")
    assert record.status == "skipped"
    assert record.reason_code == "invalid_plan_integrity"
    assert provider.requests == []


def test_executor_rejects_changed_user_scope_before_provider_construction() -> None:
    provider = FakeSearchProvider(ProviderSearchResponse())
    registry = ProviderRegistry()
    registry.register(_descriptor("local-index", ExecutionLocation.LOCAL), lambda **_: provider)
    plan = QueryPlanner(registry=registry).plan(
        QueryRequest(query="private lookup", user_id="u1")
    )

    result = QueryExecutor(registry=registry).execute(
        replace(plan, user_id="different-user"),
        authenticated_user_id="u1",
    )

    assert result.calls_used == 0
    assert provider.requests == []
    assert result.records[0].reason_code == "invalid_user_scope"


def test_executor_rejects_budget_mutation_before_provider_construction() -> None:
    provider = FakeSearchProvider(ProviderSearchResponse())
    registry = ProviderRegistry()
    registry.register(_descriptor("local-index", ExecutionLocation.LOCAL), lambda **_: provider)
    plan = QueryPlanner(registry=registry).plan(
        QueryRequest(
            query="bounded",
            user_id="u1",
            budget=QueryBudget(max_calls=1, max_remote_calls=0, deadline_ms=100),
        )
    )
    broadened = replace(
        plan,
        budget=replace(plan.budget, max_calls=10, deadline_ms=300_000),
    )

    result = QueryExecutor(registry=registry).execute(
        broadened,
        authenticated_user_id="u1",
    )

    assert result.calls_used == 0
    assert provider.requests == []
    assert result.records[0].reason_code == "invalid_plan_integrity"


def test_executor_returns_at_deadline_when_provider_blocks() -> None:
    remote = FakeSearchProvider(ProviderSearchResponse())
    registry = ProviderRegistry()
    registry.register(
        _descriptor("local-index", ExecutionLocation.LOCAL),
        lambda **_: BlockingSearchProvider(),
    )
    registry.register(
        _descriptor("remote-search", ExecutionLocation.REMOTE),
        lambda **_: remote,
    )
    plan = QueryPlanner(registry=registry).plan(
        QueryRequest(
            query="bounded latency",
            user_id="u1",
            include_web=True,
            query_classification=ContentClassification.PUBLIC,
            network=NetworkPolicy.ONLINE,
            budget=QueryBudget(
                max_calls=2,
                max_remote_calls=1,
                deadline_ms=10,
            ),
        )
    )

    started = time.monotonic()
    result = QueryExecutor(
        registry=registry,
        clock=lambda: 0.0,
    ).execute(
        plan,
        authenticated_user_id="u1",
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.15
    assert result.records[0].status == "failure"
    assert result.records[0].reason_code == "timeout"
    assert result.stop_reason == "deadline_exhausted"
    assert result.calls_used == 1
    assert remote.requests == []


def test_provider_reported_timeout_does_not_exhaust_plan_deadline() -> None:
    class ProviderReportedTimeout:
        def search(
            self,
            request: ProviderSearchRequest,
        ) -> ProviderSearchResponse:
            raise TimeoutError("provider transport timeout")

    registry = ProviderRegistry()
    registry.register(
        _descriptor("local-index", ExecutionLocation.LOCAL),
        lambda **_: ProviderReportedTimeout(),
    )
    plan = QueryPlanner(registry=registry).plan(
        QueryRequest(query="provider timeout", user_id="u1")
    )

    result = QueryExecutor(
        registry=registry,
        clock=lambda: 0.0,
    ).execute(
        plan,
        authenticated_user_id="u1",
    )

    assert result.records[0].reason_code == "timeout"
    assert result.stop_reason == "completed_with_failures"


def test_executor_failure_record_never_leaks_provider_cause() -> None:
    def fail(**_: object) -> object:
        raise RuntimeError("authorization=private-value")

    registry = ProviderRegistry()
    registry.register(
        _descriptor("local-index", ExecutionLocation.LOCAL),
        fail,
    )
    plan = QueryPlanner(registry=registry).plan(
        QueryRequest(query="safe failure", user_id="u1")
    )

    result = QueryExecutor(registry=registry).execute(
        plan,
        authenticated_user_id="u1",
    )

    assert result.records[0].status == "failure"
    assert result.records[0].reason_code == "internal_error"
    assert result.stop_reason == "completed_with_failures"
    assert "private-value" not in str(result.to_dict())


def test_provider_process_control_exception_is_isolated() -> None:
    class ExitingProvider:
        def search(
            self,
            request: ProviderSearchRequest,
        ) -> ProviderSearchResponse:
            raise SystemExit("provider-controlled exit")

    registry = ProviderRegistry()
    registry.register(
        _descriptor("local-index", ExecutionLocation.LOCAL),
        lambda **_: ExitingProvider(),
    )
    plan = QueryPlanner(registry=registry).plan(
        QueryRequest(query="safe isolation", user_id="u1")
    )

    result = QueryExecutor(registry=registry).execute(
        plan,
        authenticated_user_id="u1",
    )

    assert result.records[0].status == "failure"
    assert result.records[0].reason_code == "invalid_response"
    assert "provider-controlled exit" not in str(result.to_dict())


def test_executor_rejects_publicly_rehashed_plan_for_another_user() -> None:
    factory_users: list[str | None] = []
    registry = ProviderRegistry()
    registry.register(
        _descriptor("local-index", ExecutionLocation.LOCAL),
        lambda **kwargs: (
            factory_users.append(kwargs.get("user_id"))
            or FakeSearchProvider(ProviderSearchResponse())
        ),
    )
    original = QueryPlanner(registry=registry).plan(
        QueryRequest(query="private lookup", user_id="attacker")
    )
    victim_hash = hashlib.sha256(b"victim").hexdigest()
    forged = replace(
        original,
        user_id="victim",
        user_scope_hash=victim_hash,
    )
    forged = replace(
        forged,
        plan_id=compute_query_plan_id(
            version=forged.version,
            request_fingerprint=forged.request_fingerprint,
            user_scope_hash=forged.user_scope_hash,
            query=forged.query,
            intent=forged.intent,
            network=forged.network,
            query_classification=forged.query_classification,
            allowed_providers=forged.allowed_providers,
            source_opt_in=forged.source_opt_in,
            one_request_override=forged.one_request_override,
            budget=forged.budget,
            steps=forged.steps,
            skips=forged.skips,
        ),
    )
    assert forged.verify_integrity()
    assert forged.verify_user_scope()

    result = QueryExecutor(registry=registry).execute(
        forged,
        authenticated_user_id="attacker",
    )

    assert result.calls_used == 0
    assert factory_users == []
    assert result.records[0].reason_code == "authenticated_user_mismatch"


def test_executor_rejects_provider_that_became_unavailable() -> None:
    provider = FakeSearchProvider(ProviderSearchResponse())
    planning_registry = ProviderRegistry()
    planning_registry.register(
        _descriptor("local-index", ExecutionLocation.LOCAL),
        lambda **_: provider,
    )
    plan = QueryPlanner(registry=planning_registry).plan(
        QueryRequest(query="private lookup", user_id="u1")
    )
    runtime_registry = ProviderRegistry()
    runtime_registry.register(
        _descriptor(
            "local-index",
            ExecutionLocation.LOCAL,
            health=ProviderHealth.UNAVAILABLE,
        ),
        lambda **_: provider,
    )

    result = QueryExecutor(registry=runtime_registry).execute(
        plan,
        authenticated_user_id="u1",
    )

    assert result.calls_used == 0
    assert provider.requests == []
    assert result.records[0].reason_code == "provider_unavailable"


def test_executor_signals_cooperative_cancellation_at_deadline() -> None:
    stopped = False

    class CooperativeProvider:
        def search(
            self,
            request: ProviderSearchRequest,
        ) -> ProviderSearchResponse:
            nonlocal stopped
            while not request.cancellation.cancelled:
                time.sleep(0.001)
            stopped = True
            return ProviderSearchResponse()

    registry = ProviderRegistry()
    registry.register(
        _descriptor("local-index", ExecutionLocation.LOCAL),
        lambda **_: CooperativeProvider(),
    )
    plan = QueryPlanner(registry=registry).plan(
        QueryRequest(
            query="bounded work",
            user_id="u1",
            budget=QueryBudget(
                max_calls=1,
                max_remote_calls=0,
                deadline_ms=10,
            ),
        )
    )

    result = QueryExecutor(registry=registry).execute(
        plan,
        authenticated_user_id="u1",
    )
    for _ in range(100):
        if stopped:
            break
        time.sleep(0.001)

    assert result.records[0].reason_code == "timeout"
    assert stopped is True


def test_executor_rejects_provider_response_over_declared_byte_limit() -> None:
    provider = FakeSearchProvider(
        ProviderSearchResponse(
            hits=(
                _hit(
                    "oversized",
                    text="x" * 2_000,
                    score=1.0,
                    source_id="repo-1",
                ),
            )
        )
    )
    registry = ProviderRegistry()
    registry.register(
        _descriptor("local-index", ExecutionLocation.LOCAL),
        lambda **_: provider,
    )
    plan = QueryPlanner(registry=registry).plan(
        QueryRequest(
            query="bounded response",
            user_id="u1",
            budget=QueryBudget(
                max_calls=1,
                max_remote_calls=0,
                max_response_bytes=256,
            ),
        )
    )

    result = QueryExecutor(registry=registry).execute(
        plan,
        authenticated_user_id="u1",
    )

    assert result.hits == ()
    assert result.bytes_used == 0
    assert result.records[0].status == "failure"
    assert result.records[0].reason_code == "invalid_response"


def test_executor_enforces_runtime_descriptor_request_cap() -> None:
    provider = FakeSearchProvider(ProviderSearchResponse())
    registry = ProviderRegistry()
    registry.register(
        _descriptor(
            "local-index",
            ExecutionLocation.LOCAL,
            max_request_bytes=32,
        ),
        lambda **_: provider,
    )
    plan = QueryPlanner(registry=registry).plan(
        QueryRequest(query="request exceeds descriptor cap", user_id="u1")
    )

    result = QueryExecutor(registry=registry).execute(
        plan,
        authenticated_user_id="u1",
    )

    assert provider.requests == []
    assert result.records[0].reason_code == "request_too_large"


def test_executor_clamps_runtime_descriptor_response_cap() -> None:
    observed_response_caps: list[int] = []

    class CapAwareProvider:
        def search(
            self,
            request: ProviderSearchRequest,
        ) -> ProviderSearchResponse:
            observed_response_caps.append(request.max_response_bytes)
            return ProviderSearchResponse()

    registry = ProviderRegistry()
    registry.register(
        _descriptor(
            "local-index",
            ExecutionLocation.LOCAL,
            max_response_bytes=512,
        ),
        lambda **_: CapAwareProvider(),
    )
    plan = QueryPlanner(registry=registry).plan(
        QueryRequest(
            query="bounded response",
            user_id="u1",
            budget=QueryBudget(max_response_bytes=4_096),
        )
    )

    result = QueryExecutor(registry=registry).execute(
        plan,
        authenticated_user_id="u1",
    )

    assert observed_response_caps == [512]
    assert result.records[0].status == "success"


def test_non_cooperative_provider_is_quarantined_without_starving_others() -> None:
    release = threading.Event()
    hung_starts = 0

    class HungProvider:
        def search(
            self,
            request: ProviderSearchRequest,
        ) -> ProviderSearchResponse:
            nonlocal hung_starts
            hung_starts += 1
            release.wait()
            return ProviderSearchResponse()

    quick = FakeSearchProvider(
        ProviderSearchResponse(
            hits=(
                _hit(
                    "quick",
                    text="available",
                    score=1.0,
                    url="https://example.test/quick",
                ),
            )
        )
    )
    registry = ProviderRegistry()
    registry.register(
        _descriptor("hung-search", ExecutionLocation.REMOTE),
        lambda **_: HungProvider(),
    )
    registry.register(
        _descriptor("quick-search", ExecutionLocation.REMOTE),
        lambda **_: quick,
    )

    def remote_plan(provider: str, deadline_ms: int):
        return QueryPlanner(registry=registry).plan(
            QueryRequest(
                query="public web query",
                user_id="u1",
                source_types=(),
                include_web=True,
                preferred_search_provider=provider,
                query_classification=ContentClassification.PUBLIC,
                network=NetworkPolicy.ONLINE,
                budget=QueryBudget(
                    max_calls=1,
                    max_remote_calls=1,
                    deadline_ms=deadline_ms,
                ),
            )
        )

    executor = QueryExecutor(registry=registry)
    try:
        first = executor.execute(
            remote_plan("hung-search", 10),
            authenticated_user_id="u1",
        )
        started = time.monotonic()
        quarantined = executor.execute(
            remote_plan("hung-search", 1000),
            authenticated_user_id="u1",
        )
        quarantine_elapsed = time.monotonic() - started
        available = executor.execute(
            remote_plan("quick-search", 1000),
            authenticated_user_id="u1",
        )
    finally:
        release.set()

    assert first.records[0].reason_code == "timeout"
    assert quarantined.records[0].reason_code == "unavailable"
    assert quarantine_elapsed < 0.1
    assert hung_starts == 1
    assert [hit.title for hit in available.hits] == ["quick"]


def test_executor_counts_canonical_hit_array_framing_across_steps() -> None:
    local_response = ProviderSearchResponse(
        hits=(
            _hit(
                "local-sized",
                text="l" * 260,
                score=1.0,
                source_id="repo-1",
            ),
        )
    )
    remote_response = ProviderSearchResponse(
        hits=(
            _hit(
                "remote-sized",
                text="r" * 260,
                score=1.0,
                url="https://example.test/remote-sized",
            ),
        )
    )
    byte_budget = (
        local_response.consumed_bytes
        + remote_response.consumed_bytes
        - 2
    )
    registry = ProviderRegistry()
    registry.register(
        _descriptor("local-index", ExecutionLocation.LOCAL),
        lambda **_: FakeSearchProvider(local_response),
    )
    registry.register(
        _descriptor("remote-search", ExecutionLocation.REMOTE),
        lambda **_: FakeSearchProvider(remote_response),
    )
    plan = QueryPlanner(registry=registry).plan(
        QueryRequest(
            query="public bounded response",
            user_id="u1",
            include_web=True,
            query_classification=ContentClassification.PUBLIC,
            network=NetworkPolicy.ONLINE,
            budget=QueryBudget(
                max_calls=2,
                max_remote_calls=1,
                max_response_bytes=byte_budget,
            ),
        )
    )

    result = QueryExecutor(registry=registry).execute(
        plan,
        authenticated_user_id="u1",
    )

    assert result.bytes_used <= byte_budget
    assert len(result.hits) == 1
    assert result.stop_reason != "completed"


def test_executor_closes_constructed_provider_after_success_and_failure() -> None:
    closed: list[str] = []

    class CloseableProvider:
        def __init__(self, *, fail: bool) -> None:
            self.fail = fail

        def search(
            self,
            request: ProviderSearchRequest,
        ) -> ProviderSearchResponse:
            if self.fail:
                raise RuntimeError("provider failure")
            return ProviderSearchResponse()

        def close(self) -> None:
            closed.append("closed")

    registry = ProviderRegistry()
    registry.register(
        _descriptor("local-index", ExecutionLocation.LOCAL),
        lambda **_: CloseableProvider(fail=False),
    )
    success_plan = QueryPlanner(registry=registry).plan(
        QueryRequest(query="success", user_id="u1")
    )

    success = QueryExecutor(registry=registry).execute(
        success_plan,
        authenticated_user_id="u1",
    )

    failing_registry = ProviderRegistry()
    failing_registry.register(
        _descriptor("local-index", ExecutionLocation.LOCAL),
        lambda **_: CloseableProvider(fail=True),
    )
    failure_plan = QueryPlanner(registry=failing_registry).plan(
        QueryRequest(query="failure", user_id="u1")
    )
    failure = QueryExecutor(registry=failing_registry).execute(
        failure_plan,
        authenticated_user_id="u1",
    )

    assert success.records[0].status == "success"
    assert failure.records[0].status == "failure"
    assert closed == ["closed", "closed"]
