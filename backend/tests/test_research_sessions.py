"""Tests for the async research session lifecycle + auto-index."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _clear_sessions():
    from synsc.services import research_sessions

    research_sessions._SESSIONS.clear()
    yield
    research_sessions._SESSIONS.clear()


def test_extract_discoverable_refs_github_arxiv_hf():
    from synsc.services.research_sessions import _extract_discoverable_refs

    text = (
        "see https://github.com/tiangolo/fastapi and arxiv:2301.12345 "
        "plus the hf:squad dataset"
    )
    refs = _extract_discoverable_refs(text)
    kinds = sorted({k for k, _ in refs})
    tokens = sorted({tok.lower() for _, tok in refs})
    assert "repo" in kinds and "paper" in kinds and "dataset" in kinds
    assert "https://github.com/tiangolo/fastapi" in tokens
    assert any("arxiv:2301.12345" in t for t in tokens)
    assert any(t.startswith("hf:") for t in tokens)


def test_extract_discoverable_refs_dedupes():
    from synsc.services.research_sessions import _extract_discoverable_refs

    refs = _extract_discoverable_refs(
        "arxiv:2301.12345 arxiv:2301.12345 hf:foo hf:foo"
    )
    assert len(refs) == 2


def test_auto_index_skips_already_resolved(monkeypatch):
    """A ref that resolve_source_id can handle is NOT re-indexed."""
    from synsc.services import research_sessions, source_service

    monkeypatch.setattr(
        source_service,
        "resolve_source_id",
        lambda raw, user_id=None: ("uuid-1", "repo"),
    )
    indexed_calls = []

    def fake_index_source(**kwargs):
        indexed_calls.append(kwargs)
        return {"source_id": "x", "status": "indexed"}

    monkeypatch.setattr(source_service, "index_source", fake_index_source)
    session = research_sessions.create_session("q", user_id="u1")
    out = research_sessions._auto_index_if_unknown(
        [("repo", "https://github.com/x/y")], "u1", session
    )
    assert out == []
    assert indexed_calls == []
    # discover event recorded
    types = [e.type for e in session.events]
    assert "discover" in types


def test_auto_index_indexes_unknown(monkeypatch):
    from synsc.services import research_sessions, source_service

    def raise_unresolved(raw, user_id=None):
        raise ValueError("not indexed")

    monkeypatch.setattr(source_service, "resolve_source_id", raise_unresolved)

    indexed_calls = []

    def fake_index_source(**kwargs):
        indexed_calls.append(kwargs)
        return {"source_id": "new-uuid", "status": "indexed"}

    monkeypatch.setattr(source_service, "index_source", fake_index_source)

    session = research_sessions.create_session("q", user_id="u1")
    out = research_sessions._auto_index_if_unknown(
        [("repo", "https://github.com/x/y")], "u1", session
    )
    assert len(out) == 1
    assert out[0]["source_id"] == "new-uuid"
    assert len(indexed_calls) == 1
    assert any(e.type == "index" for e in session.events)


def test_auto_index_respects_budget(monkeypatch):
    from synsc.services import research_sessions, source_service

    monkeypatch.setattr(
        source_service,
        "resolve_source_id",
        lambda raw, user_id=None: (_ for _ in ()).throw(ValueError("nope")),
    )
    monkeypatch.setattr(
        source_service,
        "index_source",
        lambda **kw: {"source_id": "x", "status": "indexed"},
    )

    session = research_sessions.create_session("q", user_id="u1")
    out = research_sessions._auto_index_if_unknown(
        [
            ("repo", "https://github.com/a/b"),
            ("repo", "https://github.com/c/d"),
            ("repo", "https://github.com/e/f"),
            ("repo", "https://github.com/g/h"),
            ("repo", "https://github.com/i/j"),
        ],
        "u1",
        session,
        budget=3,
    )
    assert len(out) == 3
    assert len(session.auto_indexed) == 3


def test_start_session_runs_to_completion(monkeypatch):
    """Run a session with a fake runner — should reach status=completed."""
    from synsc.services import research_sessions

    async def fake_runner(session):
        session.answer_markdown = "the answer"
        session.citations = [{"source_id": "x", "chunk_id": "y", "text": "z"}]
        research_sessions._emit(session, "answer", length=10)

    async def go():
        s = await research_sessions.start_session(
            query="anything",
            mode="quick",
            user_id="u1",
            runner=fake_runner,
        )
        # Wait for completion
        await s.task
        return s

    s = asyncio.run(go())
    assert s.status == "completed"
    assert s.answer_markdown == "the answer"
    assert len(s.citations) == 1
    types = [e.type for e in s.events]
    assert "done" in types
    assert "answer" in types


def test_subscribe_replays_history_then_streams(monkeypatch):
    from synsc.services import research_sessions

    async def fake_runner(session):
        research_sessions._emit(session, "iteration", phase="r1")
        # Yield to allow subscribe loop to attach
        await asyncio.sleep(0)
        research_sessions._emit(session, "iteration", phase="r2")

    async def go():
        s = await research_sessions.start_session(
            query="q",
            user_id="u1",
            runner=fake_runner,
        )
        seen = []
        async for ev in research_sessions.subscribe(s.session_id):
            seen.append(ev.type)
            if len(seen) >= 4:
                break
        await s.task
        return seen, s

    seen, s = asyncio.run(go())
    assert "iteration" in seen
    assert "done" in seen
    assert s.status == "completed"


def test_post_followup_requires_completed(monkeypatch):
    from synsc.services import research_sessions

    async def slow_runner(session):
        await asyncio.sleep(10)  # never completes during test

    async def go():
        s = await research_sessions.start_session(
            query="q",
            user_id="u1",
            runner=slow_runner,
        )
        # session is still 'running'
        with pytest.raises(ValueError):
            await research_sessions.post_followup(
                s.session_id, "follow-up", user_id="u1"
            )
        s.task.cancel()
        return s

    asyncio.run(go())


def test_post_followup_runs_followup(monkeypatch):
    from synsc.services import research_sessions, research_service

    async def fake_runner(session):
        session.answer_markdown = "first answer"

    async def go():
        s = await research_sessions.start_session(
            query="q1",
            user_id="u1",
            runner=fake_runner,
        )
        await s.task

        class FakeService:
            def run(self, **kw):
                return {
                    "answer_markdown": "follow-up answer",
                    "citations": [],
                    "usage": {},
                }

        monkeypatch.setattr(
            research_service, "ResearchService", lambda: FakeService()
        )
        result = await research_sessions.post_followup(
            s.session_id, "what about X?", user_id="u1"
        )
        return result, s

    result, s = asyncio.run(go())
    assert result["answer_markdown"] == "follow-up answer"
    assert s.answer_markdown == "follow-up answer"
