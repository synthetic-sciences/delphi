"""Durability contracts for generic source indexing jobs."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

from synsc.services import job_queue_service


def test_create_source_job_persists_the_complete_payload(monkeypatch):
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(job_queue_service, "get_session", fake_session)

    service = job_queue_service.JobQueueService()
    result = service.create_source_job(
        user_id="user-1",
        source_type="dataset",
        url="acme/corpus",
        display_name="Corpus",
        options={"split": "train"},
    )

    persisted = session.add.call_args.args[0]
    assert persisted.job_type == "dataset"
    assert persisted.source_url == "acme/corpus"
    assert persisted.display_name == "Corpus"
    assert persisted.options == {"split": "train"}
    assert result["success"] is True
    assert result["status"] == "pending"


def test_recover_stale_jobs_requeues_retryable_and_fails_exhausted(monkeypatch):
    session = MagicMock()
    session.execute.side_effect = [
        SimpleNamespace(rowcount=1),
        SimpleNamespace(rowcount=2),
        SimpleNamespace(rowcount=1),
    ]

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(job_queue_service, "get_session", fake_session)

    result = job_queue_service.JobQueueService().recover_stale_jobs(stale_after_seconds=900)

    assert result == {"cancelled": 1, "requeued": 2, "failed": 1}
    assert session.execute.call_count == 3
    assert all(
        call.args[1] == {"stale_after_seconds": 900} for call in session.execute.call_args_list
    )


def test_terminal_job_cannot_be_overwritten_by_late_worker_completion(monkeypatch):
    session = MagicMock()
    session.query.return_value.filter.return_value.update.return_value = 0

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(job_queue_service, "get_session", fake_session)

    completed = job_queue_service.JobQueueService().complete_source_job(
        "job-cancelled",
        source_type="docs",
        source_id="docs-1",
        worker_id="stale-worker",
        attempt_count=1,
    )

    assert completed is False
