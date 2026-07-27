"""Durable asynchronous research sessions.

PostgreSQL is the source of truth for jobs, results, events, and conversation
turns. API and MCP processes only project that state; the shared background
worker claims pending jobs with a fenced lease.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import structlog

from synsc.database.models import ResearchEventRecord, ResearchJob
from synsc.services.research_job_service import (
    ResearchJobService,
    get_research_job_service,
)

logger = structlog.get_logger(__name__)

SessionStatus = Literal[
    "pending",
    "running",
    "cancelling",
    "completed",
    "failed",
    "cancelled",
]
_MAX_AUTO_INDEX_PER_SESSION = 3
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _timestamp(value: datetime | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.timestamp()
    return float(value)


@dataclass
class ResearchEvent:
    seq: int
    type: str
    timestamp: float
    payload: dict[str, Any]


@dataclass
class ResearchSession:
    session_id: str
    user_id: str
    query: str
    mode: str
    source_ids: list[str] | None
    source_types: list[str] | None
    status: SessionStatus = "pending"
    answer_markdown: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    auto_indexed: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    events: list[ResearchEvent] = field(default_factory=list)
    worker_id: str | None = field(default=None, repr=False)
    attempt_count: int | None = field(default=None, repr=False)
    event_sink: Callable[[str, dict[str, Any]], ResearchEvent | None] | None = field(
        default=None,
        repr=False,
    )

    @classmethod
    def from_job(cls, job: ResearchJob) -> ResearchSession:
        return cls(
            session_id=str(job.job_id),
            user_id=str(job.user_id),
            query=job.query,
            mode=job.mode,
            source_ids=list(job.source_ids) if job.source_ids else None,
            source_types=list(job.source_types) if job.source_types else None,
            status=job.status,  # type: ignore[arg-type]
            answer_markdown=job.answer_markdown or "",
            citations=list(job.citations or []),
            usage=dict(job.usage or {}),
            error=job.error_message,
            auto_indexed=list(job.auto_indexed or []),
            created_at=_timestamp(job.created_at) or time.time(),
            completed_at=_timestamp(job.completed_at),
            worker_id=job.worker_id,
            attempt_count=job.attempt_count,
        )

    def to_public(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "query": self.query,
            "mode": self.mode,
            "status": self.status,
            "answer_markdown": self.answer_markdown,
            "citations": self.citations,
            "usage": self.usage,
            "error": self.error,
            "auto_indexed": self.auto_indexed,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


def _event_from_record(record: ResearchEventRecord) -> ResearchEvent:
    return ResearchEvent(
        seq=record.seq,
        type=record.event_type,
        timestamp=_timestamp(record.created_at) or time.time(),
        payload=dict(record.payload or {}),
    )


def get_session(
    session_id: str,
    *,
    user_id: str,
    service: ResearchJobService | None = None,
) -> ResearchSession:
    job = (service or get_research_job_service()).get_job(
        session_id,
        user_id=user_id,
    )
    return ResearchSession.from_job(job)


def list_sessions(
    *,
    user_id: str,
    limit: int = 50,
    status: str | None = None,
    service: ResearchJobService | None = None,
) -> list[dict[str, Any]]:
    jobs = (service or get_research_job_service()).list_jobs(
        user_id=user_id,
        limit=limit,
        status=status,
    )
    return [ResearchSession.from_job(job).to_public() for job in jobs]


def _emit(session: ResearchSession, ev_type: str, **payload: Any) -> None:
    """Emit through the worker's fenced sink and mirror locally for helpers."""
    if session.event_sink is not None:
        persisted = session.event_sink(ev_type, payload)
        if persisted is not None:
            session.events.append(persisted)
        return
    session.events.append(
        ResearchEvent(
            seq=len(session.events),
            type=ev_type,
            timestamp=time.time(),
            payload=dict(payload),
        )
    )


_DISCOVER_PATTERNS = [
    re.compile(r"https?://github\.com/[\w\-]+/[\w\-.]+", re.IGNORECASE),
    re.compile(r"\barxiv:\d{4}\.\d{4,5}(?:v\d+)?\b", re.IGNORECASE),
    re.compile(r"\bhf:[\w\-./]+\b", re.IGNORECASE),
]


def _extract_discoverable_refs(text: str) -> list[tuple[str, str]]:
    """Return unique ``(source_type, reference)`` values parsed from text."""
    refs: list[tuple[str, str]] = []
    for pattern in _DISCOVER_PATTERNS:
        for match in pattern.finditer(text or ""):
            token = match.group(0)
            if token.lower().startswith("arxiv:"):
                refs.append(("paper", token))
            elif token.lower().startswith("hf:"):
                refs.append(("dataset", token))
            else:
                refs.append(("repo", token))
    return list(dict.fromkeys(refs))


def _auto_index_if_unknown(
    refs: list[tuple[str, str]],
    user_id: str | None,
    session: ResearchSession,
    *,
    budget: int = _MAX_AUTO_INDEX_PER_SESSION,
) -> list[dict[str, Any]]:
    """Resolve references and index unknown ones within a strict job budget."""
    from synsc.services.source_service import index_source, resolve_source_id

    indexed: list[dict[str, Any]] = []
    remaining = budget - len(session.auto_indexed)
    if remaining <= 0:
        return indexed

    for source_type, ref in refs:
        if remaining <= 0:
            break
        try:
            source_id, _ = resolve_source_id(ref, user_id=user_id)
            _emit(
                session,
                "discover",
                ref=ref,
                status="already_indexed",
                source_id=source_id,
            )
            continue
        except ValueError:
            pass

        _emit(session, "discover", ref=ref, status="indexing")
        try:
            url = ref
            if source_type in {"paper", "dataset"} and ":" in ref:
                url = ref.split(":", 1)[1]
            result = index_source(
                source_type=source_type,
                url=url,
                user_id=user_id,
            )
            entry = {
                "ref": ref,
                "source_type": source_type,
                "source_id": result.get("source_id"),
                "status": result.get("status"),
            }
            indexed.append(entry)
            session.auto_indexed.append(entry)
            _emit(
                session,
                "index",
                ref=ref,
                source_id=result.get("source_id"),
                status=result.get("status"),
            )
            remaining -= 1
        except Exception as exc:
            logger.warning(
                "Research auto-index failed",
                ref=ref,
                error_type=type(exc).__name__,
            )
            _emit(
                session,
                "index",
                ref=ref,
                status="error",
                error="Auto-indexing failed",
            )
    return indexed


def create_session(
    query: str,
    mode: str = "quick",
    source_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    user_id: str | None = None,
    *,
    auto_index: bool = True,
    service: ResearchJobService | None = None,
) -> ResearchSession:
    if not user_id:
        raise ValueError("user_id is required for durable research")
    job = (service or get_research_job_service()).create_job(
        user_id=user_id,
        query=query,
        mode=mode,
        source_ids=source_ids,
        source_types=source_types,
        auto_index=auto_index,
    )
    return ResearchSession.from_job(job)


async def start_session(
    query: str,
    mode: str = "quick",
    source_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    user_id: str | None = None,
    *,
    auto_index: bool = True,
    service: ResearchJobService | None = None,
) -> ResearchSession:
    """Persist a pending session for a worker to claim."""
    return create_session(
        query=query,
        mode=mode,
        source_ids=source_ids,
        source_types=source_types,
        user_id=user_id,
        auto_index=auto_index,
        service=service,
    )


async def subscribe(
    session_id: str,
    *,
    user_id: str,
    since_seq: int = -1,
    poll_interval: float = 0.25,
    service: ResearchJobService | None = None,
) -> AsyncIterator[ResearchEvent]:
    """Replay persisted events, then poll for new rows until terminal."""
    queue = service or get_research_job_service()
    cursor = since_seq
    while True:
        # Read status before events. If a completion commits between these
        # queries, the subsequent event read sees that same or newer commit;
        # this prevents a terminal status from making us skip final rows.
        current = await asyncio.to_thread(
            queue.get_job,
            session_id,
            user_id=user_id,
        )
        records = await asyncio.to_thread(
            queue.list_events,
            session_id,
            user_id=user_id,
            since_seq=cursor,
        )
        for record in records:
            event = _event_from_record(record)
            cursor = max(cursor, event.seq)
            yield event

        if current.status in _TERMINAL_STATUSES and not records:
            return
        await asyncio.sleep(poll_interval)


async def post_followup(
    session_id: str,
    message: str,
    *,
    user_id: str | None = None,
    service: ResearchJobService | None = None,
) -> dict[str, Any]:
    """Persist a user turn and requeue the existing research session."""
    if not user_id:
        raise ValueError("user_id is required for durable research")
    job = await asyncio.to_thread(
        (service or get_research_job_service()).enqueue_followup,
        session_id,
        message=message,
        user_id=user_id,
    )
    return {
        "session_id": job.job_id,
        "status": job.status,
        "accepted": True,
    }


def cancel_session(
    session_id: str,
    *,
    user_id: str,
    service: ResearchJobService | None = None,
) -> ResearchSession:
    job = (service or get_research_job_service()).cancel_job(
        session_id,
        user_id=user_id,
    )
    return ResearchSession.from_job(job)
