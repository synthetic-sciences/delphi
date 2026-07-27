"""Background connector scheduling and polling contracts."""

from __future__ import annotations

from unittest.mock import MagicMock

from synsc.workers.connector_worker import ConnectorSyncRunner


def test_runner_enqueues_due_sources_and_processes_claimed_work() -> None:
    service = MagicMock()
    service.schedule_due.return_value = 2
    service.run_once.side_effect = [
        {"job_id": "job-1", "status": "completed"},
        None,
    ]
    sleeps: list[float] = []
    checks = iter((True, True, False))

    ConnectorSyncRunner(
        service=service,
        sleeper=sleeps.append,
        scheduler_interval=60.0,
    ).run_forever(
        worker_id="worker-connectors",
        should_continue=lambda: next(checks),
        poll_interval=0.25,
    )

    service.schedule_due.assert_called_once_with(limit=100)
    assert service.run_once.call_count == 2
    service.run_once.assert_called_with(worker_id="worker-connectors")
    assert sleeps == [0.25]


def test_runner_isolates_one_poll_failure() -> None:
    service = MagicMock()
    service.schedule_due.return_value = 0
    service.run_once.side_effect = RuntimeError("database restarting")
    sleeps: list[float] = []
    checks = iter((True, False))

    ConnectorSyncRunner(
        service=service,
        sleeper=sleeps.append,
    ).run_forever(
        worker_id="worker-connectors",
        should_continue=lambda: next(checks),
        poll_interval=0.5,
    )

    assert sleeps == [0.5]
