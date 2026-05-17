"""Async research session lifecycle — Oracle-class research jobs.

POST /v2/research returns a session_id immediately; the iteration loop runs
in a background asyncio task and emits events through a per-session queue
that the SSE endpoint consumes. After the run completes the session stays
around for follow-up messages (chat-on-completed-research).

Session state lives in-process — restart loses sessions. Persisted final
answer + citations are fine to retrieve via the regular session_id once
this is wired to a Postgres table; for v1 the in-memory store keeps the
contract clean while staying testable.

The DISCOVER->INDEX->SEARCH pattern (Nia Oracle) is implemented by
iteration_callback: when the loop produces a REFINE: directive that names
an unindexed library (github URL / owner/repo / hf:id / arxiv:ID),
auto_index_if_unknown indexes it and continues. Budget-guarded by
max_auto_index_per_session so a runaway agent can't blow indexing costs.
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

logger = structlog.get_logger(__name__)


SessionStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


@dataclass
class ResearchEvent:
    seq: int
    type: str  # 'iteration' | 'retrieval' | 'discover' | 'index' | 'answer' | 'error' | 'done'
    timestamp: float
    payload: dict[str, Any]


@dataclass
class ResearchSession:
    session_id: str
    user_id: str | None
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
    queues: list[asyncio.Queue] = field(default_factory=list)
    task: asyncio.Task | None = None

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


_SESSIONS: dict[str, ResearchSession] = {}
_LOCK = asyncio.Lock()

_MAX_SESSIONS = 256  # FIFO eviction past this
_MAX_AUTO_INDEX_PER_SESSION = 3


def _gc_sessions():
    if len(_SESSIONS) <= _MAX_SESSIONS:
        return
    # Drop oldest completed/failed first.
    excess = len(_SESSIONS) - _MAX_SESSIONS
    by_age = sorted(
        _SESSIONS.values(),
        key=lambda s: (s.status in ("running", "pending"), s.created_at),
    )
    for s in by_age[:excess]:
        _SESSIONS.pop(s.session_id, None)


def get_session(session_id: str) -> ResearchSession | None:
    return _SESSIONS.get(session_id)


def list_sessions(user_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    out = []
    for s in sorted(_SESSIONS.values(), key=lambda x: x.created_at, reverse=True):
        if user_id and s.user_id != user_id:
            continue
        out.append(s.to_public())
        if len(out) >= limit:
            break
    return out


def _emit(session: ResearchSession, ev_type: str, **payload: Any) -> None:
    ev = ResearchEvent(
        seq=len(session.events),
        type=ev_type,
        timestamp=time.time(),
        payload=payload,
    )
    session.events.append(ev)
    for q in session.queues:
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            logger.warning("research_sessions: subscriber queue full, dropping")


# ---------------------------------------------------------------------------
# Auto-index helper — DISCOVER -> INDEX -> SEARCH
# ---------------------------------------------------------------------------

_DISCOVER_PATTERNS = [
    re.compile(r"https?://github\.com/[\w\-]+/[\w\-.]+", re.IGNORECASE),
    re.compile(r"\barxiv:\d{4}\.\d{4,5}(?:v\d+)?\b", re.IGNORECASE),
    re.compile(r"\bhf:[\w\-./]+\b", re.IGNORECASE),
]


def _extract_discoverable_refs(text: str) -> list[tuple[str, str]]:
    """Return ``[(source_type, ref), ...]`` references parsed from text."""
    refs: list[tuple[str, str]] = []
    for pat in _DISCOVER_PATTERNS:
        for m in pat.finditer(text or ""):
            tok = m.group(0)
            if tok.lower().startswith("arxiv:"):
                refs.append(("paper", tok))
            elif tok.lower().startswith("hf:"):
                refs.append(("dataset", tok))
            else:
                refs.append(("repo", tok))
    # De-dupe
    seen = set()
    out = []
    for r in refs:
        if r in seen:
            continue
        seen.add(r)
        out.append(r)
    return out


def _auto_index_if_unknown(
    refs: list[tuple[str, str]],
    user_id: str | None,
    session: ResearchSession,
    *,
    budget: int = _MAX_AUTO_INDEX_PER_SESSION,
) -> list[dict[str, Any]]:
    """Try to resolve each ref; index it if unresolved. Budget-guarded."""
    from synsc.services.source_service import (
        index_source,
        resolve_source_id,
    )

    indexed: list[dict[str, Any]] = []
    remaining = budget - len(session.auto_indexed)
    if remaining <= 0:
        return indexed

    for source_type, ref in refs:
        if remaining <= 0:
            break
        try:
            uid, stype = resolve_source_id(ref, user_id=user_id)
            _emit(session, "discover", ref=ref, status="already_indexed", source_id=uid)
            continue
        except ValueError:
            pass

        _emit(session, "discover", ref=ref, status="indexing")
        try:
            # Normalize the ref for indexing — index_source expects URL-shaped
            # inputs. arxiv:ID -> bare arxiv ID; hf:id -> bare hf id.
            url = ref
            if source_type == "paper" and ref.lower().startswith("arxiv:"):
                url = ref.split(":", 1)[1]
            if source_type == "dataset" and ref.lower().startswith("hf:"):
                url = ref.split(":", 1)[1]

            result = index_source(
                source_type=source_type, url=url, user_id=user_id
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
                "research_sessions: auto-index failed",
                ref=ref,
                error=str(exc),
            )
            _emit(
                session,
                "index",
                ref=ref,
                status="error",
                error=str(exc),
            )
    return indexed


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def create_session(
    query: str,
    mode: str = "quick",
    source_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    user_id: str | None = None,
) -> ResearchSession:
    sid = str(uuid.uuid4())
    session = ResearchSession(
        session_id=sid,
        user_id=user_id,
        query=query,
        mode=mode,
        source_ids=source_ids,
        source_types=source_types,
    )
    _SESSIONS[sid] = session
    _gc_sessions()
    return session


async def start_session(
    query: str,
    mode: str = "quick",
    source_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    user_id: str | None = None,
    *,
    auto_index: bool = True,
    runner: Callable[[ResearchSession], Awaitable[None]] | None = None,
) -> ResearchSession:
    """Create a session and kick off the background research task."""
    session = create_session(
        query=query,
        mode=mode,
        source_ids=source_ids,
        source_types=source_types,
        user_id=user_id,
    )

    if runner is None:
        runner = lambda s: _default_runner(s, auto_index=auto_index)  # noqa: E731

    async def _wrap():
        try:
            session.status = "running"
            _emit(session, "iteration", phase="start", query=session.query)
            await runner(session)
        except asyncio.CancelledError:
            session.status = "cancelled"
            _emit(session, "error", message="cancelled")
            raise
        except Exception as exc:
            session.status = "failed"
            session.error = str(exc)
            logger.exception("research_sessions: run failed")
            _emit(session, "error", message=str(exc))
        finally:
            session.completed_at = time.time()
            if session.status == "running":
                session.status = "completed"
            _emit(session, "done", status=session.status)
            # Signal SSE consumers.
            for q in session.queues:
                try:
                    q.put_nowait(None)
                except asyncio.QueueFull:
                    pass

    session.task = asyncio.create_task(_wrap())
    return session


async def _default_runner(
    session: ResearchSession,
    *,
    auto_index: bool,
) -> None:
    """In-process orchestrator that:
      1. Optionally auto-indexes references found in the query.
      2. Runs the synchronous ResearchService.run() in a thread.
      3. Emits retrieval + answer events.
    """
    from synsc.services.research_service import ResearchService

    if auto_index:
        refs = _extract_discoverable_refs(session.query)
        if refs:
            await asyncio.to_thread(
                _auto_index_if_unknown, refs, session.user_id, session
            )

    _emit(session, "iteration", phase="retrieve", hop=0)

    service = ResearchService()
    result = await asyncio.to_thread(
        service.run,
        query=session.query,
        mode=session.mode if session.mode in ("quick", "deep", "oracle") else "quick",
        source_ids=session.source_ids,
        source_types=session.source_types,
        user_id=session.user_id,
    )

    session.answer_markdown = result.get("answer_markdown", "")
    session.citations = result.get("citations", [])
    session.usage = result.get("usage", {})
    _emit(
        session,
        "answer",
        length=len(session.answer_markdown),
        citation_count=len(session.citations),
    )


async def subscribe(session_id: str) -> AsyncIterator[ResearchEvent]:
    """Subscribe to a session's events. Replays existing events, then streams new."""
    session = _SESSIONS.get(session_id)
    if not session:
        return
    # Replay history
    for ev in list(session.events):
        yield ev
    if session.status not in ("running", "pending"):
        return

    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    session.queues.append(q)
    try:
        while True:
            ev = await q.get()
            if ev is None:
                return
            yield ev
    finally:
        try:
            session.queues.remove(q)
        except ValueError:
            pass


async def post_followup(
    session_id: str,
    message: str,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Post a follow-up message on a completed session.

    Re-runs the research loop with the new message scoped to the same
    source_ids/source_types but starts from scratch on retrieval. The
    follow-up answer is appended to the session and returned synchronously.
    """
    session = _SESSIONS.get(session_id)
    if not session:
        raise ValueError(f"session not found: {session_id}")
    if session.user_id and user_id and session.user_id != user_id:
        raise PermissionError("not your session")
    if session.status not in ("completed", "failed", "cancelled"):
        raise ValueError("session is still running")

    _emit(session, "iteration", phase="followup", message=message)

    from synsc.services.research_service import ResearchService

    service = ResearchService()
    # Stitch the prior answer + new question into a single combined query so
    # the follow-up has the context of what was already said.
    combined = (
        f"Prior question: {session.query}\n"
        f"Prior answer (markdown):\n{session.answer_markdown}\n\n"
        f"Follow-up: {message}"
    )
    result = await asyncio.to_thread(
        service.run,
        query=combined,
        mode="quick",
        source_ids=session.source_ids,
        source_types=session.source_types,
        user_id=session.user_id,
    )
    session.answer_markdown = result.get("answer_markdown", "")
    session.citations = result.get("citations", []) or session.citations
    _emit(session, "answer", length=len(session.answer_markdown))
    return {
        "session_id": session_id,
        "answer_markdown": session.answer_markdown,
        "citations": session.citations,
    }
