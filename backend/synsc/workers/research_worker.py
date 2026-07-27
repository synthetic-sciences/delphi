"""Execution loop for PostgreSQL-backed research jobs."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Literal, cast

import structlog

from synsc.config import get_config
from synsc.database.models import ResearchJob
from synsc.providers.contracts import CancellationToken
from synsc.services.research_job_service import (
    ResearchJobService,
    get_research_job_service,
    public_error_for_exception,
)
from synsc.services.research_service import (
    ResearchCancelledError,
    ResearchService,
)
from synsc.services.research_sessions import (
    ResearchEvent,
    ResearchSession,
    _auto_index_if_unknown,
    _event_from_record,
    _extract_discoverable_refs,
)

logger = structlog.get_logger(__name__)


class ResearchJobRunner:
    """Claim and execute research jobs while fencing stale workers."""

    def __init__(
        self,
        *,
        service: ResearchJobService | None = None,
        research_factory: Callable[[str], ResearchService] | None = None,
        heartbeat_interval: float = 30.0,
        job_timeout_seconds: float | None = None,
        max_execution_threads: int | None = None,
    ) -> None:
        if heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be positive")
        if job_timeout_seconds is not None and job_timeout_seconds <= 0:
            raise ValueError("job_timeout_seconds must be positive")
        configured_max = (
            max_execution_threads
            if max_execution_threads is not None
            else get_config().research.max_execution_threads
        )
        if configured_max <= 0:
            raise ValueError("max_execution_threads must be positive")
        self.service = service or get_research_job_service()
        self.research_factory = research_factory or (
            lambda user_id: ResearchService(user_id=user_id)
        )
        self.heartbeat_interval = heartbeat_interval
        self.job_timeout_seconds = job_timeout_seconds
        self.max_execution_threads = configured_max
        self._execution_slots = threading.BoundedSemaphore(configured_max)

    @staticmethod
    def _lease(job: ResearchJob) -> tuple[str, int]:
        if not job.worker_id:
            raise RuntimeError("claimed research job has no worker_id")
        return job.worker_id, job.attempt_count

    @staticmethod
    def _conversation_query(
        job: ResearchJob,
        messages: list[Any],
        *,
        max_chars: int = 24_000,
    ) -> str:
        if not messages:
            return job.query
        rendered = "\n".join(
            f"{message.role}: {message.content}" for message in messages
        )
        if len(rendered) > max_chars:
            rendered = rendered[-max_chars:]
        return (
            f"Original question: {job.query}\n\n"
            f"Conversation so far:\n{rendered}\n\n"
            "Answer the latest user message using the available sources."
        )

    def _event_sink(
        self,
        job: ResearchJob,
    ) -> Callable[[str, dict[str, Any]], ResearchEvent | None]:
        worker_id, attempt_count = self._lease(job)

        def emit(event_type: str, payload: dict[str, Any]) -> ResearchEvent | None:
            record = self.service.append_event(
                job.job_id,
                event_type,
                payload,
                worker_id=worker_id,
                attempt_count=attempt_count,
            )
            return _event_from_record(record) if record is not None else None

        return emit

    def _timeout_for_mode(self, mode: str) -> float:
        if self.job_timeout_seconds is not None:
            return self.job_timeout_seconds
        config = get_config().research
        return float(
            {
                "quick": config.quick_job_timeout_seconds,
                "deep": config.deep_job_timeout_seconds,
                "oracle": config.oracle_job_timeout_seconds,
            }.get(mode, config.deep_job_timeout_seconds)
        )

    def process_job(
        self,
        job: ResearchJob,
        *,
        _execution_slot_reserved: bool = False,
    ) -> bool:
        """Execute one claimed job and publish only under its lease."""
        try:
            worker_id, attempt_count = self._lease(job)
        except Exception:
            if _execution_slot_reserved:
                self._execution_slots.release()
            raise
        if not _execution_slot_reserved:
            self._execution_slots.acquire()
        release_slot_in_caller = True
        token = CancellationToken()
        heartbeat_stop = threading.Event()
        lease_lost = threading.Event()
        cancellation_requested = threading.Event()
        heartbeat_thread: threading.Thread | None = None

        def heartbeat() -> None:
            while not heartbeat_stop.wait(self.heartbeat_interval):
                try:
                    state = self.service.heartbeat_job(
                        job.job_id,
                        worker_id=worker_id,
                        attempt_count=attempt_count,
                    )
                except Exception:
                    state = "lost"
                if state == "active":
                    continue
                if state == "cancelling":
                    cancellation_requested.set()
                else:
                    lease_lost.set()
                token.cancel()
                return

        try:
            initial_state = self.service.heartbeat_job(
                job.job_id,
                worker_id=worker_id,
                attempt_count=attempt_count,
            )
            if initial_state != "active":
                if initial_state == "cancelling":
                    self.service.acknowledge_cancellation(
                        job.job_id,
                        worker_id=worker_id,
                        attempt_count=attempt_count,
                    )
                return False

            heartbeat_thread = threading.Thread(
                target=heartbeat,
                daemon=True,
                name=f"research-heartbeat-{job.job_id}",
            )
            heartbeat_thread.start()

            session = ResearchSession.from_job(job)
            session.event_sink = self._event_sink(job)

            def progress(event_type: str, payload: dict[str, Any]) -> None:
                if token.cancelled:
                    raise ResearchCancelledError("research cancelled")
                if session.event_sink is not None:
                    session.event_sink(event_type, payload)

            execution_done = threading.Event()
            result_box: dict[str, dict[str, Any]] = {}
            error_box: list[Exception] = []

            def execute() -> None:
                try:
                    messages = self.service.list_messages_for_worker(
                        job.job_id,
                        worker_id=worker_id,
                        attempt_count=attempt_count,
                    )
                    latest_user_message = next(
                        (
                            message.content
                            for message in reversed(messages)
                            if message.role == "user"
                        ),
                        job.query,
                    )
                    if job.auto_index:
                        refs = _extract_discoverable_refs(latest_user_message)
                        if refs:
                            _auto_index_if_unknown(
                                refs,
                                job.user_id,
                                session,
                            )
                    if token.cancelled:
                        raise ResearchCancelledError("research cancelled")

                    query = self._conversation_query(job, messages)
                    result_box["result"] = self.research_factory(job.user_id).run(
                        query=query,
                        mode=cast(
                            Literal["quick", "deep", "oracle"],
                            job.mode,
                        ),
                        source_ids=job.source_ids,
                        source_types=job.source_types,
                        user_id=job.user_id,
                        cancellation=token,
                        progress_callback=progress,
                    )
                except Exception as exc:
                    error_box.append(exc)
                finally:
                    self._execution_slots.release()
                    execution_done.set()

            execution_thread = threading.Thread(
                target=execute,
                daemon=True,
                name=f"research-execution-{job.job_id}",
            )
            execution_thread.start()
            release_slot_in_caller = False

            deadline = time.monotonic() + self._timeout_for_mode(job.mode)
            while not execution_done.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    token.cancel()
                    heartbeat_stop.set()
                    failed = self.service.fail_job(
                        job.job_id,
                        error_message="Research job timed out",
                        worker_id=worker_id,
                        attempt_count=attempt_count,
                    )
                    if not failed:
                        self.service.acknowledge_cancellation(
                            job.job_id,
                            worker_id=worker_id,
                            attempt_count=attempt_count,
                        )
                    return False
                execution_done.wait(min(0.05, remaining))
                if lease_lost.is_set() or cancellation_requested.is_set():
                    token.cancel()
                    raise ResearchCancelledError("research cancelled")

            if error_box:
                raise error_box[0]
            result = result_box.get("result")
            if result is None:
                raise RuntimeError("research execution returned no result")
            if token.cancelled or lease_lost.is_set() or cancellation_requested.is_set():
                raise ResearchCancelledError("research cancelled")

            completed = self.service.complete_job(
                job.job_id,
                answer_markdown=result.get("answer_markdown", ""),
                citations=list(result.get("citations", [])),
                usage=dict(result.get("usage", {})),
                auto_indexed=session.auto_indexed,
                worker_id=worker_id,
                attempt_count=attempt_count,
            )
            if not completed:
                self.service.acknowledge_cancellation(
                    job.job_id,
                    worker_id=worker_id,
                    attempt_count=attempt_count,
                )
            return completed
        except ResearchCancelledError:
            self.service.acknowledge_cancellation(
                job.job_id,
                worker_id=worker_id,
                attempt_count=attempt_count,
            )
            return False
        except Exception as exc:
            logger.error(
                "Research job failed",
                job_id=job.job_id,
                error_type=type(exc).__name__,
            )
            failed = self.service.fail_job(
                job.job_id,
                error_message=public_error_for_exception(exc),
                worker_id=worker_id,
                attempt_count=attempt_count,
            )
            if not failed:
                self.service.acknowledge_cancellation(
                    job.job_id,
                    worker_id=worker_id,
                    attempt_count=attempt_count,
                )
            return False
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1.0)
            if release_slot_in_caller:
                self._execution_slots.release()

    def run_once(self, worker_id: str) -> bool:
        if not self._execution_slots.acquire(blocking=False):
            return False
        try:
            job = self.service.claim_next_job(worker_id)
        except Exception:
            self._execution_slots.release()
            raise
        if job is None:
            self._execution_slots.release()
            return False
        self.process_job(job, _execution_slot_reserved=True)
        return True

    def run_forever(
        self,
        *,
        worker_id: str,
        should_continue: Callable[[], bool],
        poll_interval: float = 2.0,
    ) -> None:
        """Poll until the owning composite worker requests shutdown."""
        try:
            self.service.recover_stale_jobs()
        except Exception as exc:
            logger.warning(
                "Could not recover stale research jobs at worker startup",
                worker_id=worker_id,
                error_type=type(exc).__name__,
            )
        next_recovery_at = time.monotonic() + 60.0
        while should_continue():
            try:
                if time.monotonic() >= next_recovery_at:
                    self.service.recover_stale_jobs()
                    next_recovery_at = time.monotonic() + 60.0
                if not self.run_once(worker_id):
                    threading.Event().wait(poll_interval)
            except Exception as exc:
                logger.error(
                    "Research worker poll failed",
                    worker_id=worker_id,
                    error_type=type(exc).__name__,
                )
                threading.Event().wait(poll_interval)
