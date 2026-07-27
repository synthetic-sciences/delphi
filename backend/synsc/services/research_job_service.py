"""PostgreSQL-backed queue and replay log for asynchronous research."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, cast

import structlog
from sqlalchemy import func, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from synsc.database.connection import get_session
from synsc.database.models import (
    ResearchEventRecord,
    ResearchJob,
    ResearchMessage,
    generate_uuid,
)

logger = structlog.get_logger(__name__)

ResearchMode = Literal["quick", "deep", "oracle"]
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
ACTIVE_STATUSES = frozenset({"pending", "running", "cancelling"})


class ResearchJobNotFoundError(LookupError):
    """The caller cannot access the requested research job."""


class ResearchJobStateError(ValueError):
    """A transition is invalid for the job's current state."""


def public_error_for_exception(exc: BaseException) -> str:
    """Map internal failures to a stable message safe to persist and return."""
    from synsc.services.research_service import ResearchProviderNotConfiguredError

    if isinstance(exc, ResearchProviderNotConfiguredError):
        return "Research provider is not configured"
    if isinstance(exc, TimeoutError):
        return "Research job timed out"
    return "Research job failed"


class ResearchJobService:
    """Owns all durable research queue state transitions."""

    @staticmethod
    def _owned_job(
        session: Session,
        job_id: str,
        user_id: str,
        *,
        for_update: bool = False,
    ) -> ResearchJob:
        query = session.query(ResearchJob).filter(
            ResearchJob.job_id == job_id,
            ResearchJob.user_id == user_id,
        )
        if for_update:
            query = query.with_for_update()
        job = query.first()
        if job is None:
            raise ResearchJobNotFoundError("research session not found")
        return job

    @staticmethod
    def _append_event_locked(
        session: Session,
        job_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> ResearchEventRecord:
        latest = (
            session.query(func.max(ResearchEventRecord.seq))
            .filter(ResearchEventRecord.job_id == job_id)
            .scalar()
        )
        event = ResearchEventRecord(
            event_id=generate_uuid(),
            job_id=job_id,
            seq=0 if latest is None else int(latest) + 1,
            event_type=event_type,
            payload=dict(payload),
        )
        session.add(event)
        # Later events in the same transaction must observe this sequence.
        session.flush()
        return event

    def create_job(
        self,
        *,
        user_id: str,
        query: str,
        mode: str = "quick",
        source_ids: list[str] | None = None,
        source_types: list[str] | None = None,
        auto_index: bool = True,
    ) -> ResearchJob:
        if not user_id.strip():
            raise ValueError("user_id is required")
        if not query.strip():
            raise ValueError("query is required")
        if mode not in {"quick", "deep", "oracle"}:
            raise ValueError("mode must be quick, deep, or oracle")

        job = ResearchJob(
            job_id=generate_uuid(),
            user_id=user_id,
            query=query,
            mode=mode,
            source_ids=list(source_ids) if source_ids else None,
            source_types=list(source_types) if source_types else None,
            auto_index=auto_index,
            status="pending",
            citations=[],
            usage={},
            auto_indexed=[],
            attempt_count=0,
            max_attempts=3,
        )
        event = ResearchEventRecord(
            event_id=generate_uuid(),
            job_id=job.job_id,
            seq=0,
            event_type="queued",
            payload={"status": "pending"},
        )
        with get_session() as session:
            session.add(job)
            # The models intentionally avoid loading large event relationships.
            # Flush the parent explicitly so the database FK determines order.
            session.flush()
            session.add(event)
            session.flush()
        return job

    def get_job(self, job_id: str, *, user_id: str) -> ResearchJob:
        with get_session() as session:
            return self._owned_job(session, job_id, user_id)

    def list_jobs(
        self,
        *,
        user_id: str,
        limit: int = 50,
        status: str | None = None,
    ) -> list[ResearchJob]:
        bounded_limit = max(1, min(limit, 100))
        if status is not None and status not in ACTIVE_STATUSES | TERMINAL_STATUSES:
            raise ValueError("invalid research status")
        with get_session() as session:
            query = session.query(ResearchJob).filter(
                ResearchJob.user_id == user_id
            )
            if status:
                query = query.filter(ResearchJob.status == status)
            return list(
                query.order_by(ResearchJob.created_at.desc())
                .limit(bounded_limit)
                .all()
            )

    def append_event(
        self,
        job_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        worker_id: str | None = None,
        attempt_count: int | None = None,
    ) -> ResearchEventRecord | None:
        with get_session() as session:
            query = session.query(ResearchJob).filter(
                ResearchJob.job_id == job_id
            )
            job = query.with_for_update().first()
            if job is None:
                return None
            if worker_id is not None and (
                job.worker_id != worker_id
                or job.attempt_count != attempt_count
                or job.status not in {"running", "cancelling"}
            ):
                return None
            return self._append_event_locked(session, job_id, event_type, payload)

    def list_events(
        self,
        job_id: str,
        *,
        user_id: str,
        since_seq: int = -1,
        limit: int = 500,
    ) -> list[ResearchEventRecord]:
        bounded_limit = max(1, min(limit, 1000))
        with get_session() as session:
            self._owned_job(session, job_id, user_id)
            return list(
                session.query(ResearchEventRecord)
                .filter(
                    ResearchEventRecord.job_id == job_id,
                    ResearchEventRecord.seq > since_seq,
                )
                .order_by(ResearchEventRecord.seq.asc())
                .limit(bounded_limit)
                .all()
            )

    def claim_next_job(self, worker_id: str) -> ResearchJob | None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        with get_session() as session:
            row = (
                session.execute(
                    text(
                        """
                        UPDATE research_jobs
                        SET status = 'running',
                            worker_id = :worker_id,
                            started_at = NOW(),
                            updated_at = NOW(),
                            completed_at = NULL,
                            attempt_count = attempt_count + 1
                        WHERE job_id = (
                            SELECT job_id
                            FROM research_jobs
                            WHERE status = 'pending'
                              AND attempt_count < max_attempts
                            ORDER BY created_at ASC
                            LIMIT 1
                            FOR UPDATE SKIP LOCKED
                        )
                        RETURNING job_id
                        """
                    ),
                    {"worker_id": worker_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            job = session.get(ResearchJob, row["job_id"])
            if job is None:
                return None
            self._append_event_locked(
                session,
                job.job_id,
                "iteration",
                {"phase": "start", "attempt": job.attempt_count},
            )
            return job

    def heartbeat_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        attempt_count: int,
    ) -> Literal["active", "cancelling", "lost"]:
        with get_session() as session:
            job = (
                session.query(ResearchJob)
                .filter(
                    ResearchJob.job_id == job_id,
                    ResearchJob.worker_id == worker_id,
                    ResearchJob.attempt_count == attempt_count,
                )
                .with_for_update()
                .first()
            )
            if job is None or job.status not in {"running", "cancelling"}:
                return "lost"
            if job.status == "cancelling":
                return "cancelling"
            job.updated_at = datetime.now(timezone.utc)
            return "active"

    def complete_job(
        self,
        job_id: str,
        *,
        answer_markdown: str,
        citations: list[dict[str, Any]],
        usage: dict[str, Any],
        auto_indexed: list[dict[str, Any]],
        worker_id: str,
        attempt_count: int,
    ) -> bool:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            updated = (
                session.query(ResearchJob)
                .filter(
                    ResearchJob.job_id == job_id,
                    ResearchJob.status == "running",
                    ResearchJob.worker_id == worker_id,
                    ResearchJob.attempt_count == attempt_count,
                )
                .update(
                    {
                        ResearchJob.status: "completed",
                        ResearchJob.answer_markdown: answer_markdown,
                        ResearchJob.citations: citations,
                        ResearchJob.usage: usage,
                        ResearchJob.auto_indexed: auto_indexed,
                        ResearchJob.tokens_in: int(usage.get("tokens_in") or 0),
                        ResearchJob.tokens_out: int(usage.get("tokens_out") or 0),
                        ResearchJob.latency_ms: int(usage.get("latency_ms") or 0),
                        ResearchJob.error_message: None,
                        ResearchJob.completed_at: now,
                        ResearchJob.updated_at: now,
                    },
                    synchronize_session=False,
                )
            )
            if not updated:
                return False
            job = (
                session.query(ResearchJob)
                .filter(ResearchJob.job_id == job_id)
                .with_for_update()
                .first()
            )
            if job is None:
                return False
            session.add(
                ResearchMessage(
                    message_id=generate_uuid(),
                    job_id=job_id,
                    role="assistant",
                    content=answer_markdown,
                    citations=citations,
                )
            )
            self._append_event_locked(
                session,
                job_id,
                "answer",
                {
                    "length": len(answer_markdown),
                    "citation_count": len(citations),
                },
            )
            self._append_event_locked(
                session, job_id, "done", {"status": "completed"}
            )
            return True

    def fail_job(
        self,
        job_id: str,
        *,
        error_message: str,
        worker_id: str,
        attempt_count: int,
    ) -> bool:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            updated = (
                session.query(ResearchJob)
                .filter(
                    ResearchJob.job_id == job_id,
                    ResearchJob.status == "running",
                    ResearchJob.worker_id == worker_id,
                    ResearchJob.attempt_count == attempt_count,
                )
                .update(
                    {
                        ResearchJob.status: "failed",
                        ResearchJob.error_message: error_message,
                        ResearchJob.completed_at: now,
                        ResearchJob.updated_at: now,
                    },
                    synchronize_session=False,
                )
            )
            if not updated:
                return False
            job = (
                session.query(ResearchJob)
                .filter(ResearchJob.job_id == job_id)
                .with_for_update()
                .first()
            )
            if job is None:
                return False
            self._append_event_locked(
                session, job_id, "error", {"message": error_message}
            )
            self._append_event_locked(
                session, job_id, "done", {"status": "failed"}
            )
            return True

    def cancel_job(self, job_id: str, *, user_id: str) -> ResearchJob:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            job = self._owned_job(session, job_id, user_id, for_update=True)
            if job.status == "pending":
                job.status = "cancelled"
                job.completed_at = now
                job.updated_at = now
                self._append_event_locked(
                    session, job_id, "cancelled", {"status": "cancelled"}
                )
                self._append_event_locked(
                    session, job_id, "done", {"status": "cancelled"}
                )
                return job
            if job.status == "running":
                job.status = "cancelling"
                job.updated_at = now
                self._append_event_locked(
                    session,
                    job_id,
                    "cancellation_requested",
                    {"status": "cancelling"},
                )
                return job
            if job.status == "cancelling":
                return job
            raise ResearchJobStateError(
                f"cannot cancel research session in status {job.status}"
            )

    def acknowledge_cancellation(
        self,
        job_id: str,
        *,
        worker_id: str,
        attempt_count: int,
    ) -> bool:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            updated = (
                session.query(ResearchJob)
                .filter(
                    ResearchJob.job_id == job_id,
                    ResearchJob.status == "cancelling",
                    ResearchJob.worker_id == worker_id,
                    ResearchJob.attempt_count == attempt_count,
                )
                .update(
                    {
                        ResearchJob.status: "cancelled",
                        ResearchJob.completed_at: now,
                        ResearchJob.updated_at: now,
                    },
                    synchronize_session=False,
                )
            )
            if not updated:
                return False
            job = (
                session.query(ResearchJob)
                .filter(ResearchJob.job_id == job_id)
                .with_for_update()
                .first()
            )
            if job is None:
                return False
            self._append_event_locked(
                session, job_id, "cancelled", {"status": "cancelled"}
            )
            self._append_event_locked(
                session, job_id, "done", {"status": "cancelled"}
            )
            return True

    def enqueue_followup(
        self,
        job_id: str,
        *,
        message: str,
        user_id: str,
    ) -> ResearchJob:
        if not message.strip():
            raise ValueError("message is required")
        with get_session() as session:
            job = self._owned_job(session, job_id, user_id, for_update=True)
            if job.status not in TERMINAL_STATUSES:
                raise ResearchJobStateError("research session is still running")
            session.add(
                ResearchMessage(
                    message_id=generate_uuid(),
                    job_id=job_id,
                    role="user",
                    content=message,
                )
            )
            job.status = "pending"
            job.worker_id = None
            # Retry budgets apply to one queued turn, not the lifetime of the
            # conversation. A completed session may accept many follow-ups.
            job.attempt_count = 0
            job.started_at = None
            job.completed_at = None
            job.error_message = None
            job.updated_at = datetime.now(timezone.utc)
            self._append_event_locked(
                session,
                job_id,
                "queued",
                {"status": "pending", "followup": True},
            )
            return job

    def list_messages_for_worker(
        self,
        job_id: str,
        *,
        worker_id: str,
        attempt_count: int,
    ) -> list[ResearchMessage]:
        with get_session() as session:
            job = (
                session.query(ResearchJob)
                .filter(
                    ResearchJob.job_id == job_id,
                    ResearchJob.status.in_(["running", "cancelling"]),
                    ResearchJob.worker_id == worker_id,
                    ResearchJob.attempt_count == attempt_count,
                )
                .first()
            )
            if job is None:
                return []
            return list(
                session.query(ResearchMessage)
                .filter(ResearchMessage.job_id == job_id)
                .order_by(ResearchMessage.created_at.asc())
                .all()
            )

    @staticmethod
    def _returned_job_ids(result: Any) -> list[str]:
        """Read RETURNING rows while keeping mocked rowcount tests lightweight."""
        try:
            return [
                str(row["job_id"])
                for row in result.mappings().all()
            ]
        except (AttributeError, TypeError):
            return []

    def recover_stale_jobs(
        self, stale_after_seconds: int = 900
    ) -> dict[str, int]:
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        params = {"stale_after_seconds": stale_after_seconds}
        with get_session() as session:
            cancelled_result = cast(
                CursorResult[Any],
                session.execute(
                    text(
                        """
                        UPDATE research_jobs
                        SET status = 'cancelled',
                            completed_at = NOW(),
                            updated_at = NOW(),
                            error_message = NULL
                        WHERE status = 'cancelling'
                          AND updated_at < NOW() - (
                              :stale_after_seconds * INTERVAL '1 second'
                          )
                        RETURNING job_id
                        """
                    ),
                    params,
                ),
            )
            cancelled_ids = self._returned_job_ids(cancelled_result)
            for job_id in cancelled_ids:
                self._append_event_locked(
                    session,
                    job_id,
                    "cancelled",
                    {"status": "cancelled", "recovered": True},
                )
                self._append_event_locked(
                    session,
                    job_id,
                    "done",
                    {"status": "cancelled"},
                )

            requeued_result = cast(
                CursorResult[Any],
                session.execute(
                    text(
                        """
                        UPDATE research_jobs
                        SET status = 'pending',
                            worker_id = NULL,
                            started_at = NULL,
                            updated_at = NOW(),
                            error_message = NULL
                        WHERE status = 'running'
                          AND updated_at < NOW() - (
                              :stale_after_seconds * INTERVAL '1 second'
                          )
                          AND attempt_count < max_attempts
                        RETURNING job_id
                        """
                    ),
                    params,
                ),
            )
            requeued_ids = self._returned_job_ids(requeued_result)
            for job_id in requeued_ids:
                self._append_event_locked(
                    session,
                    job_id,
                    "recovered",
                    {"status": "pending"},
                )

            failed_result = cast(
                CursorResult[Any],
                session.execute(
                    text(
                        """
                        UPDATE research_jobs
                        SET status = 'failed',
                            worker_id = NULL,
                            completed_at = NOW(),
                            updated_at = NOW(),
                            error_message = 'Research worker interrupted and retry budget exhausted'
                        WHERE status = 'running'
                          AND updated_at < NOW() - (
                              :stale_after_seconds * INTERVAL '1 second'
                          )
                          AND attempt_count >= max_attempts
                        RETURNING job_id
                        """
                    ),
                    params,
                ),
            )
            failed_ids = self._returned_job_ids(failed_result)
            for job_id in failed_ids:
                self._append_event_locked(
                    session,
                    job_id,
                    "error",
                    {
                        "message": (
                            "Research worker interrupted and retry budget exhausted"
                        )
                    },
                )
                self._append_event_locked(
                    session,
                    job_id,
                    "done",
                    {"status": "failed"},
                )
            cancelled = cancelled_result.rowcount
            requeued = requeued_result.rowcount
            failed = failed_result.rowcount
        result = {
            "cancelled": int(cancelled or 0),
            "requeued": int(requeued or 0),
            "failed": int(failed or 0),
        }
        if any(result.values()):
            logger.warning(
                "Recovered stale research jobs",
                stale_after_seconds=stale_after_seconds,
                **result,
            )
        return result


_research_job_service: ResearchJobService | None = None


def get_research_job_service() -> ResearchJobService:
    global _research_job_service
    if _research_job_service is None:
        _research_job_service = ResearchJobService()
    return _research_job_service
