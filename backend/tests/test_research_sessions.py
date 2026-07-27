"""Tests for durable research-session projections and auto-index helpers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from synsc.services import research_sessions


def _job(**overrides):
    values = {
        "job_id": "job-1",
        "user_id": "user-1",
        "query": "q",
        "mode": "quick",
        "source_ids": None,
        "source_types": None,
        "auto_index": True,
        "status": "pending",
        "answer_markdown": None,
        "citations": [],
        "usage": {},
        "auto_indexed": [],
        "error_message": None,
        "worker_id": None,
        "attempt_count": 0,
        "created_at": datetime.now(timezone.utc),
        "completed_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _session() -> research_sessions.ResearchSession:
    return research_sessions.ResearchSession(
        session_id="job-1",
        user_id="user-1",
        query="q",
        mode="quick",
        source_ids=None,
        source_types=None,
    )


def test_extract_discoverable_refs_github_arxiv_hf() -> None:
    text = (
        "see https://github.com/tiangolo/fastapi and arxiv:2301.12345 "
        "plus the hf:squad dataset"
    )
    refs = research_sessions._extract_discoverable_refs(text)
    kinds = sorted({kind for kind, _ in refs})
    tokens = sorted({token.lower() for _, token in refs})
    assert "repo" in kinds and "paper" in kinds and "dataset" in kinds
    assert "https://github.com/tiangolo/fastapi" in tokens
    assert any("arxiv:2301.12345" in token for token in tokens)
    assert any(token.startswith("hf:") for token in tokens)


def test_extract_discoverable_refs_dedupes() -> None:
    refs = research_sessions._extract_discoverable_refs(
        "arxiv:2301.12345 arxiv:2301.12345 hf:foo hf:foo"
    )
    assert len(refs) == 2


def test_auto_index_skips_already_resolved(monkeypatch) -> None:
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "resolve_source_id",
        lambda raw, user_id=None: ("uuid-1", "repo"),
    )
    indexed_calls = []
    monkeypatch.setattr(
        source_service,
        "index_source",
        lambda **kwargs: indexed_calls.append(kwargs),
    )
    session = _session()

    out = research_sessions._auto_index_if_unknown(
        [("repo", "https://github.com/x/y")],
        "user-1",
        session,
    )

    assert out == []
    assert indexed_calls == []
    assert "discover" in [event.type for event in session.events]


def test_auto_index_indexes_unknown(monkeypatch) -> None:
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "resolve_source_id",
        lambda raw, user_id=None: (_ for _ in ()).throw(ValueError("not indexed")),
    )
    monkeypatch.setattr(
        source_service,
        "index_source",
        lambda **kwargs: {"source_id": "new-uuid", "status": "indexed"},
    )
    session = _session()

    out = research_sessions._auto_index_if_unknown(
        [("repo", "https://github.com/x/y")],
        "user-1",
        session,
    )

    assert out[0]["source_id"] == "new-uuid"
    assert any(event.type == "index" for event in session.events)


def test_auto_index_respects_budget(monkeypatch) -> None:
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "resolve_source_id",
        lambda raw, user_id=None: (_ for _ in ()).throw(ValueError("not indexed")),
    )
    monkeypatch.setattr(
        source_service,
        "index_source",
        lambda **kwargs: {"source_id": "x", "status": "indexed"},
    )
    session = _session()

    out = research_sessions._auto_index_if_unknown(
        [
            ("repo", "https://github.com/a/b"),
            ("repo", "https://github.com/c/d"),
            ("repo", "https://github.com/e/f"),
            ("repo", "https://github.com/g/h"),
        ],
        "user-1",
        session,
        budget=3,
    )

    assert len(out) == 3
    assert len(session.auto_indexed) == 3


def test_auto_index_does_not_expose_exception_text(monkeypatch) -> None:
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "resolve_source_id",
        lambda raw, user_id=None: (_ for _ in ()).throw(ValueError("not indexed")),
    )
    monkeypatch.setattr(
        source_service,
        "index_source",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("sk-secret")),
    )
    session = _session()

    research_sessions._auto_index_if_unknown(
        [("repo", "https://github.com/x/y")],
        "user-1",
        session,
    )

    event = session.events[-1]
    assert event.payload["error"] == "Auto-indexing failed"
    assert "secret" not in str(event.payload)


def test_start_session_only_enqueues_durable_work() -> None:
    service = MagicMock()
    service.create_job.return_value = _job()

    session = asyncio.run(
        research_sessions.start_session(
            query="q",
            user_id="user-1",
            service=service,
        )
    )

    assert session.status == "pending"
    service.create_job.assert_called_once_with(
        user_id="user-1",
        query="q",
        mode="quick",
        source_ids=None,
        source_types=None,
        auto_index=True,
    )


def test_get_session_is_owner_scoped() -> None:
    service = MagicMock()
    service.get_job.return_value = _job(status="completed")

    session = research_sessions.get_session(
        "job-1",
        user_id="user-1",
        service=service,
    )

    assert session.status == "completed"
    service.get_job.assert_called_once_with("job-1", user_id="user-1")


def test_subscribe_replays_persisted_events_then_stops() -> None:
    service = MagicMock()
    service.list_events.side_effect = [
        [
            SimpleNamespace(
                seq=4,
                event_type="answer",
                created_at=datetime.now(timezone.utc),
                payload={"length": 4},
            ),
            SimpleNamespace(
                seq=5,
                event_type="done",
                created_at=datetime.now(timezone.utc),
                payload={"status": "completed"},
            ),
        ],
        [],
    ]
    service.get_job.return_value = _job(status="completed")

    async def collect():
        return [
            event
            async for event in research_sessions.subscribe(
                "job-1",
                user_id="user-1",
                since_seq=3,
                poll_interval=0,
                service=service,
            )
        ]

    events = asyncio.run(collect())
    assert [event.seq for event in events] == [4, 5]
    assert service.list_events.call_args_list[-1].kwargs["since_seq"] == 5


def test_subscribe_reads_final_events_after_observing_terminal_state() -> None:
    service = MagicMock()
    terminal_observed = False
    final_delivered = False

    def get_terminal_job(*_args, **_kwargs):
        nonlocal terminal_observed
        terminal_observed = True
        return _job(status="completed")

    def list_committed_events(*_args, **_kwargs):
        nonlocal final_delivered
        if terminal_observed and not final_delivered:
            final_delivered = True
            return [
                SimpleNamespace(
                    seq=5,
                    event_type="done",
                    created_at=datetime.now(timezone.utc),
                    payload={"status": "completed"},
                )
            ]
        return []

    service.get_job.side_effect = get_terminal_job
    service.list_events.side_effect = list_committed_events

    async def collect():
        return [
            event
            async for event in research_sessions.subscribe(
                "job-1",
                user_id="user-1",
                since_seq=4,
                poll_interval=0,
                service=service,
            )
        ]

    events = asyncio.run(collect())

    assert [event.seq for event in events] == [5]
    assert service.get_job.call_count == 2
    assert service.list_events.call_args_list[-1].kwargs["since_seq"] == 5


def test_post_followup_persists_and_requeues() -> None:
    service = MagicMock()
    service.enqueue_followup.return_value = _job(status="pending")

    result = asyncio.run(
        research_sessions.post_followup(
            "job-1",
            "What about Linux?",
            user_id="user-1",
            service=service,
        )
    )

    assert result == {
        "session_id": "job-1",
        "status": "pending",
        "accepted": True,
    }
    service.enqueue_followup.assert_called_once_with(
        "job-1",
        message="What about Linux?",
        user_id="user-1",
    )
