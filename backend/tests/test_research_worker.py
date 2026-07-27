"""Contracts for executing durable research jobs under a fenced lease."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

from synsc.services.research_service import ResearchCancelledError
from synsc.workers.research_worker import ResearchJobRunner


def _job(**overrides):
    values = {
        "job_id": "job-1",
        "user_id": "user-1",
        "query": "Original question",
        "mode": "deep",
        "source_ids": ["source-1"],
        "source_types": ["repo"],
        "auto_index": False,
        "auto_indexed": [],
        "status": "running",
        "answer_markdown": None,
        "citations": [],
        "usage": {},
        "error_message": None,
        "created_at": datetime.now(timezone.utc),
        "completed_at": None,
        "worker_id": "worker-1",
        "attempt_count": 2,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _event(event_type: str, seq: int = 1):
    return SimpleNamespace(
        seq=seq,
        event_type=event_type,
        created_at=datetime.now(timezone.utc),
        payload={},
    )


def _queue(**overrides):
    values = {
        "heartbeat_job": MagicMock(return_value="active"),
        "append_event": MagicMock(side_effect=lambda _id, kind, *_a, **_k: _event(kind)),
        "list_messages_for_worker": MagicMock(return_value=[]),
        "complete_job": MagicMock(return_value=True),
        "fail_job": MagicMock(return_value=True),
        "acknowledge_cancellation": MagicMock(return_value=True),
        "claim_next_job": MagicMock(return_value=None),
        "recover_stale_jobs": MagicMock(
            return_value={"cancelled": 0, "requeued": 0, "failed": 0}
        ),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_runner_completes_job_with_fenced_result_and_progress() -> None:
    queue = _queue()
    research = MagicMock()
    research.run.return_value = {
        "answer_markdown": "Answer",
        "citations": [{"source_id": "source-1"}],
        "usage": {"tokens_in": 5, "tokens_out": 2},
    }
    runner = ResearchJobRunner(
        service=queue,
        research_factory=lambda _user_id: research,
        heartbeat_interval=0.01,
    )

    assert runner.process_job(_job()) is True

    kwargs = research.run.call_args.kwargs
    assert kwargs["query"] == "Original question"
    assert kwargs["cancellation"].cancelled is False
    assert callable(kwargs["progress_callback"])
    queue.complete_job.assert_called_once_with(
        "job-1",
        answer_markdown="Answer",
        citations=[{"source_id": "source-1"}],
        usage={"tokens_in": 5, "tokens_out": 2},
        auto_indexed=[],
        worker_id="worker-1",
        attempt_count=2,
    )
    queue.fail_job.assert_not_called()


def test_runner_uses_durable_conversation_for_followup() -> None:
    queue = _queue(
        list_messages_for_worker=MagicMock(
            return_value=[
                SimpleNamespace(role="assistant", content="First answer"),
                SimpleNamespace(role="user", content="What about Linux?"),
            ]
        )
    )
    research = MagicMock()
    research.run.return_value = {
        "answer_markdown": "Follow-up answer",
        "citations": [],
        "usage": {},
    }

    ResearchJobRunner(
        service=queue,
        research_factory=lambda _user_id: research,
    ).process_job(_job())

    query = research.run.call_args.kwargs["query"]
    assert "Original question" in query
    assert "assistant: First answer" in query
    assert "user: What about Linux?" in query


def test_runner_acknowledges_cancellation_without_publishing_late_answer() -> None:
    queue = _queue(
        heartbeat_job=MagicMock(return_value="cancelling"),
    )
    research = MagicMock(side_effect=AssertionError("research must not start"))

    completed = ResearchJobRunner(
        service=queue,
        research_factory=lambda _user_id: research,
    ).process_job(_job(status="cancelling"))

    assert completed is False
    research.assert_not_called()
    queue.complete_job.assert_not_called()
    queue.acknowledge_cancellation.assert_called_once_with(
        "job-1",
        worker_id="worker-1",
        attempt_count=2,
    )


def test_runner_persists_only_safe_failure_text() -> None:
    queue = _queue()
    research = MagicMock()
    research.run.side_effect = RuntimeError("sk-live-secret-material")

    completed = ResearchJobRunner(
        service=queue,
        research_factory=lambda _user_id: research,
    ).process_job(_job())

    assert completed is False
    failure = queue.fail_job.call_args.kwargs["error_message"]
    assert failure == "Research job failed"
    assert "secret" not in failure


def test_runner_treats_cooperative_cancel_as_cancellation() -> None:
    queue = _queue()
    research = MagicMock()
    research.run.side_effect = ResearchCancelledError("cancelled")

    completed = ResearchJobRunner(
        service=queue,
        research_factory=lambda _user_id: research,
    ).process_job(_job())

    assert completed is False
    queue.complete_job.assert_not_called()
    queue.fail_job.assert_not_called()
    queue.acknowledge_cancellation.assert_called_once()


def test_runner_times_out_blocked_provider_without_blocking_queue() -> None:
    queue = _queue()
    research = MagicMock()

    def blocked_run(**_kwargs):
        time.sleep(0.2)
        return {
            "answer_markdown": "too late",
            "citations": [],
            "usage": {},
        }

    research.run.side_effect = blocked_run
    runner = ResearchJobRunner(
        service=queue,
        research_factory=lambda _user_id: research,
        heartbeat_interval=0.005,
        job_timeout_seconds=0.02,
    )

    started = time.monotonic()
    completed = runner.process_job(_job())
    elapsed = time.monotonic() - started

    assert completed is False
    assert elapsed < 0.15
    queue.complete_job.assert_not_called()
    queue.fail_job.assert_called_once_with(
        "job-1",
        error_message="Research job timed out",
        worker_id="worker-1",
        attempt_count=2,
    )


def test_runner_acknowledges_cancel_race_when_timeout_transition_loses() -> None:
    queue = _queue(fail_job=MagicMock(return_value=False))
    research = MagicMock()
    research.run.side_effect = lambda **_kwargs: time.sleep(0.2)

    completed = ResearchJobRunner(
        service=queue,
        research_factory=lambda _user_id: research,
        heartbeat_interval=0.1,
        job_timeout_seconds=0.01,
    ).process_job(_job())

    assert completed is False
    queue.acknowledge_cancellation.assert_called_once_with(
        "job-1",
        worker_id="worker-1",
        attempt_count=2,
    )


def test_runner_bounds_orphaned_execution_threads_before_claiming_more() -> None:
    release = Event()
    queue = _queue()
    research = MagicMock()
    research.run.side_effect = lambda **_kwargs: release.wait(1.0)
    runner = ResearchJobRunner(
        service=queue,
        research_factory=lambda _user_id: research,
        heartbeat_interval=0.1,
        job_timeout_seconds=0.01,
        max_execution_threads=2,
    )

    try:
        assert runner.process_job(_job(job_id="job-1")) is False
        assert runner.process_job(_job(job_id="job-2")) is False
        assert runner.run_once("worker-next") is False
        queue.claim_next_job.assert_not_called()
    finally:
        release.set()

    for _ in range(100):
        runner.run_once("worker-after-quarantine")
        if queue.claim_next_job.called:
            break
        time.sleep(0.005)
    queue.claim_next_job.assert_called_once_with("worker-after-quarantine")


def test_runner_discovers_references_from_latest_followup(monkeypatch) -> None:
    from synsc.workers import research_worker

    followup = "Use https://github.com/acme/new-source"
    queue = _queue(
        list_messages_for_worker=MagicMock(
            return_value=[
                SimpleNamespace(role="assistant", content="First answer"),
                SimpleNamespace(role="user", content=followup),
            ]
        )
    )
    research = MagicMock()
    research.run.return_value = {
        "answer_markdown": "Follow-up answer",
        "citations": [],
        "usage": {},
    }
    extract = MagicMock(return_value=[])
    monkeypatch.setattr(research_worker, "_extract_discoverable_refs", extract)

    ResearchJobRunner(
        service=queue,
        research_factory=lambda _user_id: research,
    ).process_job(_job(auto_index=True))

    extract.assert_called_once_with(followup)


def test_run_once_returns_false_when_queue_is_empty() -> None:
    queue = _queue()
    runner = ResearchJobRunner(service=queue)

    assert runner.run_once("worker-1") is False
