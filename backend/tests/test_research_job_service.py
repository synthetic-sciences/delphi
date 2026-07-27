"""Behavior contracts for the durable research queue."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from synsc.services import research_job_service


def _job(**overrides):
    values = {
        "job_id": "job-1",
        "user_id": "user-1",
        "query": "What changed?",
        "mode": "deep",
        "source_ids": ["source-1"],
        "source_types": ["repo"],
        "auto_index": True,
        "status": "pending",
        "answer_markdown": None,
        "citations": [],
        "usage": {},
        "auto_indexed": [],
        "error_message": None,
        "worker_id": None,
        "attempt_count": 0,
        "max_attempts": 3,
        "created_at": datetime.now(timezone.utc),
        "started_at": None,
        "updated_at": datetime.now(timezone.utc),
        "completed_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_create_job_persists_complete_payload_and_initial_event(monkeypatch) -> None:
    session = MagicMock()

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(research_job_service, "get_session", fake_session)

    created = research_job_service.ResearchJobService().create_job(
        user_id="user-1",
        query="What changed?",
        mode="deep",
        source_ids=["source-1"],
        source_types=["repo"],
        auto_index=False,
    )

    persisted_job = session.add.call_args_list[0].args[0]
    persisted_event = session.add.call_args_list[1].args[0]
    assert persisted_job.user_id == "user-1"
    assert persisted_job.query == "What changed?"
    assert persisted_job.mode == "deep"
    assert persisted_job.source_ids == ["source-1"]
    assert persisted_job.source_types == ["repo"]
    assert persisted_job.auto_index is False
    assert persisted_event.job_id == persisted_job.job_id
    assert persisted_event.seq == 0
    assert persisted_event.event_type == "queued"
    assert created is persisted_job


@pytest.mark.parametrize("mode", ["", "slow", "QUICK"])
def test_create_job_rejects_invalid_modes(monkeypatch, mode: str) -> None:
    with pytest.raises(ValueError, match="mode"):
        research_job_service.ResearchJobService().create_job(
            user_id="user-1",
            query="query",
            mode=mode,
        )


def test_create_job_requires_an_owner() -> None:
    with pytest.raises(ValueError, match="user_id"):
        research_job_service.ResearchJobService().create_job(
            user_id="",
            query="query",
        )


def test_public_error_never_exposes_exception_text() -> None:
    secret = "sk-live-secret-material"
    assert secret not in research_job_service.public_error_for_exception(
        RuntimeError(secret)
    )


def test_claim_uses_skip_locked_and_increments_lease_generation(monkeypatch) -> None:
    claimed = _job(status="running", worker_id="worker-1", attempt_count=2)
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = {
        "job_id": claimed.job_id
    }
    session.get.return_value = claimed

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(research_job_service, "get_session", fake_session)

    result = research_job_service.ResearchJobService().claim_next_job("worker-1")

    sql = str(session.execute.call_args_list[0].args[0])
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "attempt_count = attempt_count + 1" in sql
    assert result is claimed


def test_stale_worker_cannot_complete_reassigned_job(monkeypatch) -> None:
    session = MagicMock()
    session.query.return_value.filter.return_value.update.return_value = 0

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(research_job_service, "get_session", fake_session)

    completed = research_job_service.ResearchJobService().complete_job(
        "job-1",
        answer_markdown="stale answer",
        citations=[],
        usage={},
        auto_indexed=[],
        worker_id="worker-old",
        attempt_count=1,
    )

    assert completed is False


def test_recover_stale_jobs_requeues_retryable_and_fails_exhausted(monkeypatch) -> None:
    session = MagicMock()
    session.execute.side_effect = [
        SimpleNamespace(rowcount=1),
        SimpleNamespace(rowcount=2),
        SimpleNamespace(rowcount=1),
    ]

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(research_job_service, "get_session", fake_session)

    result = research_job_service.ResearchJobService().recover_stale_jobs(
        stale_after_seconds=900
    )

    assert result == {"cancelled": 1, "requeued": 2, "failed": 1}
    assert session.execute.call_count == 3


def test_append_event_locks_job_before_allocating_sequence(monkeypatch) -> None:
    session = MagicMock()
    session.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = (
        _job()
    )
    session.query.return_value.filter.return_value.scalar.return_value = 7

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(research_job_service, "get_session", fake_session)

    event = research_job_service.ResearchJobService().append_event(
        "job-1",
        "iteration",
        {"phase": "retrieve"},
    )

    assert event is not None
    assert event.seq == 8
    session.query.return_value.filter.return_value.with_for_update.assert_called_once_with()


def test_cancel_pending_job_is_terminal_and_records_done(monkeypatch) -> None:
    job = _job()
    session = MagicMock()
    session.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = (
        job
    )
    session.query.return_value.filter.return_value.scalar.side_effect = [None, 0]

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(research_job_service, "get_session", fake_session)

    result = research_job_service.ResearchJobService().cancel_job(
        "job-1", user_id="user-1"
    )

    assert result.status == "cancelled"
    assert result.completed_at is not None
    event_types = [
        call.args[0].event_type
        for call in session.add.call_args_list
        if hasattr(call.args[0], "event_type")
    ]
    assert event_types == ["cancelled", "done"]


def test_followup_is_durable_and_requeues_terminal_job(monkeypatch) -> None:
    job = _job(status="completed", answer_markdown="old", attempt_count=3)
    session = MagicMock()
    session.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = (
        job
    )
    session.query.return_value.filter.return_value.scalar.return_value = 3

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(research_job_service, "get_session", fake_session)

    result = research_job_service.ResearchJobService().enqueue_followup(
        "job-1",
        message="What about Linux?",
        user_id="user-1",
    )

    assert result.status == "pending"
    assert result.completed_at is None
    assert result.attempt_count == 0
    messages = [
        call.args[0]
        for call in session.add.call_args_list
        if hasattr(call.args[0], "role")
    ]
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "What about Linux?"
