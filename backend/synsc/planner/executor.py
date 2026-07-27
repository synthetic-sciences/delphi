"""Bounded execution of policy-aware query plans."""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, replace
from threading import Lock, Thread
from typing import Any
from urllib.parse import urldefrag
from weakref import WeakKeyDictionary

from synsc.planner.contracts import (
    ExecutionRecord,
    PlanStep,
    QueryExecution,
    QueryPlan,
    RetrievalHit,
    RetrievalProvenance,
)
from synsc.providers.contracts import (
    ExecutionLocation,
    ProviderFailure,
    ProviderFailureCode,
    ProviderHealth,
    ProviderSearchHit,
    ProviderSearchRequest,
    ProviderSearchResponse,
    ProviderUnavailableError,
    SearchProvider,
)
from synsc.providers.policy import EgressPolicy
from synsc.providers.registry import ProviderRegistry, ProviderRegistryError

_MAX_PROVIDER_CONCURRENCY = 8


@dataclass
class _ProviderRuntimeState:
    active: int = 0
    quarantined: bool = False


class _ProviderCallIsolation:
    """Bound work per registry/provider and quarantine timed-out adapters."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._states: WeakKeyDictionary[
            ProviderRegistry,
            dict[str, _ProviderRuntimeState],
        ] = WeakKeyDictionary()

    @staticmethod
    def _unavailable(provider: str) -> ProviderUnavailableError:
        return ProviderUnavailableError(
            ProviderFailure(
                code=ProviderFailureCode.UNAVAILABLE,
                message="Provider is temporarily unavailable.",
                retryable=True,
                provider=provider,
            )
        )

    def reserve(
        self,
        registry: ProviderRegistry,
        provider: str,
    ) -> _ProviderRuntimeState:
        with self._lock:
            providers = self._states.setdefault(registry, {})
            state = providers.setdefault(provider, _ProviderRuntimeState())
            if (
                state.quarantined
                or state.active >= _MAX_PROVIDER_CONCURRENCY
            ):
                raise self._unavailable(provider)
            state.active += 1
            return state

    def quarantine(self, state: _ProviderRuntimeState) -> None:
        with self._lock:
            if state.active > 0:
                state.quarantined = True

    def release(self, state: _ProviderRuntimeState) -> None:
        with self._lock:
            state.active -= 1
            if state.active == 0:
                state.quarantined = False


_PROVIDER_CALLS = _ProviderCallIsolation()


class _ProviderLimitError(RuntimeError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


class _ProviderWorkerError(RuntimeError):
    """Safe marker for provider-originated process-control exceptions."""


@dataclass
class _FusedHit:
    hit: ProviderSearchHit
    score: float
    provenance: list[RetrievalProvenance]


def _serialized_size(hit: ProviderSearchHit) -> int:
    return len(
        json.dumps(
            hit.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )


def _dedupe_key(hit: ProviderSearchHit) -> str:
    if hit.url:
        url, _ = urldefrag(hit.url)
        return f"url:{url.rstrip('/')}"
    if hit.source_id and hit.locator:
        return (
            f"source:{hit.snapshot_id or 'current'}:"
            f"{hit.source_type or ''}:{hit.source_id}:{hit.locator}"
        )
    normalized_text = " ".join(hit.text.split())
    return "content:" + hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


class QueryExecutor:
    """Execute admitted steps while rechecking every runtime boundary."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        policy: EgressPolicy | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.registry = registry
        self.policy = policy or EgressPolicy()
        self.clock = clock

    def _runtime_decision(self, step: PlanStep) -> tuple[bool, str]:
        try:
            registration = self.registry.get(step.provider)
        except ProviderRegistryError:
            return False, "provider_unavailable"
        descriptor = registration.descriptor
        if descriptor.health is ProviderHealth.UNAVAILABLE:
            return False, "provider_unavailable"
        if descriptor.execution is not step.execution:
            return False, "provider_descriptor_changed"
        if step.capability not in descriptor.capabilities:
            return False, "capability_not_supported"
        if step.execution is ExecutionLocation.LOCAL:
            return True, "local_execution"
        if step.egress_request is None or step.egress_decision is None:
            return False, "missing_egress_context"
        if not step.egress_decision.allowed:
            return False, "plan_policy_denied"
        decision = self.policy.evaluate(step.egress_request, descriptor)
        return decision.allowed, decision.reason_code

    def _invoke(
        self,
        step: PlanStep,
        request: ProviderSearchRequest,
        *,
        user_id: str | None,
    ) -> ProviderSearchResponse:
        """Run construction and search behind the plan's wall-clock timeout."""

        descriptor = self.registry.get(step.provider).descriptor
        response_limit = request.max_response_bytes
        if descriptor.max_response_bytes is not None:
            response_limit = min(
                response_limit,
                descriptor.max_response_bytes,
            )
        if response_limit < 256:
            raise _ProviderLimitError("provider_response_cap_too_small")
        effective_request = replace(
            request,
            max_response_bytes=response_limit,
        )
        request_bytes = len(
            json.dumps(
                effective_request.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        )
        if (
            descriptor.max_request_bytes is not None
            and request_bytes > descriptor.max_request_bytes
        ):
            raise _ProviderLimitError("request_too_large")

        def call() -> ProviderSearchResponse:
            provider = self.registry.create(step.provider, user_id=user_id)
            if not isinstance(provider, SearchProvider):
                raise TypeError("provider does not implement search")
            response = provider.search(effective_request)
            if not isinstance(response, ProviderSearchResponse):
                raise TypeError("provider returned an invalid search response")
            if response.consumed_bytes > effective_request.max_response_bytes:
                raise TypeError("provider response exceeded its byte ceiling")
            return response

        state = _PROVIDER_CALLS.reserve(
            self.registry,
            step.provider,
        )
        future: Future[ProviderSearchResponse] = Future()

        def run() -> None:
            try:
                future.set_result(call())
            except BaseException as exc:
                future.set_exception(
                    exc
                    if isinstance(exc, Exception)
                    else _ProviderWorkerError(
                        "Provider execution failed."
                    )
                )
            finally:
                _PROVIDER_CALLS.release(state)

        thread = Thread(
            target=run,
            name=f"query-provider-{step.provider}",
            daemon=True,
        )
        try:
            thread.start()
        except BaseException:
            _PROVIDER_CALLS.release(state)
            raise
        try:
            return future.result(
                timeout=effective_request.timeout_ms / 1000
            )
        except FutureTimeoutError:
            effective_request.cancellation.cancel()
            _PROVIDER_CALLS.quarantine(state)
            raise TimeoutError from None

    @staticmethod
    def _record(
        step: PlanStep,
        *,
        status: str,
        reason_code: str,
        hit_count: int = 0,
        consumed_bytes: int = 0,
        elapsed_ms: int = 0,
    ) -> ExecutionRecord:
        return ExecutionRecord(
            step_id=step.step_id,
            provider=step.provider,
            execution=step.execution,
            status=status,
            reason_code=reason_code,
            hit_count=hit_count,
            consumed_bytes=consumed_bytes,
            elapsed_ms=elapsed_ms,
        )

    def execute(
        self,
        plan: QueryPlan,
        *,
        authenticated_user_id: str | None,
    ) -> QueryExecution:
        started = self.clock()
        if not plan.verify_integrity():
            return QueryExecution(
                plan_id=plan.plan_id,
                hits=(),
                records=tuple(
                    self._record(
                        step,
                        status="skipped",
                        reason_code="invalid_plan_integrity",
                    )
                    for step in plan.steps
                ),
                stop_reason="invalid_plan_integrity",
                calls_used=0,
                remote_calls_used=0,
                bytes_used=0,
                elapsed_ms=int((self.clock() - started) * 1000),
            )
        if not plan.verify_user_scope():
            return QueryExecution(
                plan_id=plan.plan_id,
                hits=(),
                records=tuple(
                    self._record(
                        step,
                        status="skipped",
                        reason_code="invalid_user_scope",
                    )
                    for step in plan.steps
                ),
                stop_reason="invalid_user_scope",
                calls_used=0,
                remote_calls_used=0,
                bytes_used=0,
                elapsed_ms=int((self.clock() - started) * 1000),
            )
        if plan.user_id != authenticated_user_id:
            return QueryExecution(
                plan_id=plan.plan_id,
                hits=(),
                records=tuple(
                    self._record(
                        step,
                        status="skipped",
                        reason_code="authenticated_user_mismatch",
                    )
                    for step in plan.steps
                ),
                stop_reason="authenticated_user_mismatch",
                calls_used=0,
                remote_calls_used=0,
                bytes_used=0,
                elapsed_ms=int((self.clock() - started) * 1000),
            )
        deadline = started + plan.budget.deadline_ms / 1000
        calls_used = 0
        remote_calls_used = 0
        bytes_used = 0
        admitted_hit_count = 0
        records: list[ExecutionRecord] = []
        fused: dict[str, _FusedHit] = {}
        stop_reason = "completed"

        for step in plan.steps:
            if self.clock() >= deadline:
                records.append(
                    self._record(
                        step,
                        status="skipped",
                        reason_code="deadline_exhausted",
                    )
                )
                stop_reason = "deadline_exhausted"
                break
            if calls_used >= plan.budget.max_calls:
                records.append(
                    self._record(
                        step,
                        status="skipped",
                        reason_code="call_budget_exhausted",
                    )
                )
                stop_reason = "call_budget_exhausted"
                break
            if (
                step.execution is ExecutionLocation.REMOTE
                and remote_calls_used >= plan.budget.max_remote_calls
            ):
                records.append(
                    self._record(
                        step,
                        status="skipped",
                        reason_code="remote_call_budget_exhausted",
                    )
                )
                continue
            remaining_bytes = plan.budget.max_response_bytes - bytes_used
            if remaining_bytes < 256:
                records.append(
                    self._record(
                        step,
                        status="skipped",
                        reason_code="response_budget_exhausted",
                    )
                )
                stop_reason = "response_budget_exhausted"
                break

            allowed, reason_code = self._runtime_decision(step)
            if not allowed:
                records.append(
                    self._record(
                        step,
                        status="skipped",
                        reason_code=reason_code,
                    )
                )
                continue

            step_started = self.clock()
            remaining_ms = max(1, int((deadline - step_started) * 1000))
            search_request = ProviderSearchRequest(
                query=step.query,
                limit=min(step.limit, plan.budget.max_results),
                timeout_ms=remaining_ms,
                max_response_bytes=remaining_bytes,
                source_ids=step.source_ids,
                source_types=step.source_types,
                snapshot_ids=step.snapshot_ids,
            )
            calls_used += 1
            if step.execution is ExecutionLocation.REMOTE:
                remote_calls_used += 1
            try:
                response = self._invoke(
                    step,
                    search_request,
                    user_id=authenticated_user_id,
                )
            except _ProviderLimitError as exc:
                records.append(
                    self._record(
                        step,
                        status="skipped",
                        reason_code=exc.reason_code,
                        elapsed_ms=int(
                            (self.clock() - step_started) * 1000
                        ),
                    )
                )
                continue
            except ProviderUnavailableError as exc:
                records.append(
                    self._record(
                        step,
                        status="failure",
                        reason_code=exc.failure.code.value,
                        elapsed_ms=int((self.clock() - step_started) * 1000),
                    )
                )
                continue
            except TimeoutError:
                if self.clock() >= deadline:
                    stop_reason = "deadline_exhausted"
                records.append(
                    self._record(
                        step,
                        status="failure",
                        reason_code="timeout",
                        elapsed_ms=int((self.clock() - step_started) * 1000),
                    )
                )
                continue
            except Exception:
                records.append(
                    self._record(
                        step,
                        status="failure",
                        reason_code="invalid_response",
                        elapsed_ms=int((self.clock() - step_started) * 1000),
                    )
                )
                continue

            accepted_count = 0
            accepted_bytes = 0
            for rank, hit in enumerate(response.hits, start=1):
                hit_bytes = _serialized_size(hit) + (
                    2 if admitted_hit_count == 0 else 1
                )
                if bytes_used + hit_bytes > plan.budget.max_response_bytes:
                    stop_reason = "response_budget_exhausted"
                    break
                bytes_used += hit_bytes
                admitted_hit_count += 1
                accepted_bytes += hit_bytes
                accepted_count += 1
                key = _dedupe_key(hit)
                provenance = RetrievalProvenance(
                    step_id=step.step_id,
                    provider=step.provider,
                    execution=step.execution,
                    rank=rank,
                    provider_score=hit.score,
                )
                contribution = 1.0 / (60.0 + rank)
                existing = fused.get(key)
                if existing is None:
                    fused[key] = _FusedHit(
                        hit=hit,
                        score=contribution,
                        provenance=[provenance],
                    )
                else:
                    existing.score += contribution
                    existing.provenance.append(provenance)
                    if len(hit.text) > len(existing.hit.text):
                        existing.hit = hit

            records.append(
                self._record(
                    step,
                    status="success",
                    reason_code=(
                        "response_budget_exhausted"
                        if stop_reason == "response_budget_exhausted"
                        else "completed"
                    ),
                    hit_count=accepted_count,
                    consumed_bytes=accepted_bytes,
                    elapsed_ms=int((self.clock() - step_started) * 1000),
                )
            )
            if stop_reason == "response_budget_exhausted":
                break

        if stop_reason == "completed" and any(
            record.status == "failure" for record in records
        ):
            stop_reason = "completed_with_failures"

        ranked = sorted(
            fused.items(),
            key=lambda item: (
                item[1].score,
                max(p.provider_score for p in item[1].provenance),
                item[0],
            ),
            reverse=True,
        )[: plan.budget.max_results]
        hits = tuple(
            RetrievalHit(
                result_id=hashlib.sha256(key.encode("utf-8")).hexdigest(),
                text=value.hit.text,
                score=value.score,
                title=value.hit.title,
                url=value.hit.url,
                source_type=value.hit.source_type,
                source_id=value.hit.source_id,
                snapshot_id=value.hit.snapshot_id,
                locator=value.hit.locator,
                metadata=value.hit.metadata,
                provenance=tuple(value.provenance),
            )
            for key, value in ranked
        )
        return QueryExecution(
            plan_id=plan.plan_id,
            hits=hits,
            records=tuple(records),
            stop_reason=stop_reason,
            calls_used=calls_used,
            remote_calls_used=remote_calls_used,
            bytes_used=bytes_used,
            elapsed_ms=int((self.clock() - started) * 1000),
        )
