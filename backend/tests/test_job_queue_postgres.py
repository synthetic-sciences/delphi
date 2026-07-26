"""Concurrent job-queue contracts against a real PostgreSQL database.

Run with a migrated test database:

    DATABASE_URL=postgresql://... pytest tests/test_job_queue_postgres.py -q
"""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text


def _postgres_reachable() -> bool:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        return False
    try:
        import psycopg2

        connection = psycopg2.connect(url, connect_timeout=2)
        connection.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="No real Postgres at DATABASE_URL — skipping queue concurrency tests.",
)


@pytest.fixture
def queue_user_id():
    from synsc.database.connection import get_session

    user_id = str(uuid.uuid4())
    yield user_id
    with get_session() as session:
        session.execute(
            text("DELETE FROM indexing_jobs WHERE user_id = :user_id"),
            {"user_id": user_id},
        )


def test_concurrent_source_enqueues_deduplicate(queue_user_id):
    from synsc.services.job_queue_service import JobQueueService

    workers = 8
    barrier = threading.Barrier(workers)

    def enqueue():
        barrier.wait()
        return JobQueueService().create_source_job(
            user_id=queue_user_id,
            source_type="docs",
            url="https://docs.example.com/concurrent",
            options={"max_pages": 10},
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(lambda _: enqueue(), range(workers)))

    assert len({str(result["job_id"]) for result in results}) == 1


def test_repository_enqueues_deduplicate_across_both_apis(queue_user_id):
    from synsc.services.job_queue_service import JobQueueService

    barrier = threading.Barrier(2)

    def legacy_enqueue():
        barrier.wait()
        return JobQueueService().create_job(
            user_id=queue_user_id,
            repo_url="https://github.com/acme/cross-api",
        )

    def unified_enqueue():
        barrier.wait()
        return JobQueueService().create_source_job(
            user_id=queue_user_id,
            source_type="repo",
            url="https://github.com/acme/cross-api",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        legacy_result = executor.submit(legacy_enqueue)
        unified_result = executor.submit(unified_enqueue)
        results = [legacy_result.result(), unified_result.result()]

    assert len({str(result["job_id"]) for result in results}) == 1


def test_behavior_changing_options_create_distinct_jobs(queue_user_id):
    from synsc.services.job_queue_service import JobQueueService

    barrier = threading.Barrier(2)

    def enqueue(max_pages):
        barrier.wait()
        return JobQueueService().create_source_job(
            user_id=queue_user_id,
            source_type="docs",
            url="https://docs.example.com/versioned",
            options={"max_pages": max_pages},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(enqueue, (10, 100)))

    assert len({str(result["job_id"]) for result in results}) == 2


def test_stale_worker_is_fenced_after_reassignment(queue_user_id):
    from synsc.database.connection import get_session
    from synsc.services.job_queue_service import JobQueueService

    queue = JobQueueService()
    created = queue.create_source_job(
        user_id=queue_user_id,
        source_type="dataset",
        url="acme/reassigned",
    )
    job_a = queue.claim_next_job("worker-a")
    assert job_a is not None
    assert str(job_a.job_id) == str(created["job_id"])

    with get_session() as session:
        session.execute(
            text(
                "UPDATE indexing_jobs "
                "SET updated_at = NOW() - INTERVAL '2 hours' "
                "WHERE job_id = :job_id"
            ),
            {"job_id": job_a.job_id},
        )

    assert queue.recover_stale_jobs(stale_after_seconds=60)["requeued"] == 1
    job_b = queue.claim_next_job("worker-b")
    assert job_b is not None
    assert job_b.attempt_count == job_a.attempt_count + 1

    assert queue.heartbeat_job(
        job_a.job_id,
        worker_id=job_a.worker_id,
        attempt_count=job_a.attempt_count,
    ) is False
    assert queue.complete_source_job(
        job_a.job_id,
        source_type="dataset",
        source_id="00000000-0000-0000-0000-000000000001",
        worker_id=job_a.worker_id,
        attempt_count=job_a.attempt_count,
    ) is False

    status = queue.get_job(job_a.job_id, user_id=queue_user_id)["job"]
    assert status["status"] == "processing"
    assert status["attempt_count"] == job_b.attempt_count

    assert queue.complete_source_job(
        job_b.job_id,
        source_type="dataset",
        source_id="00000000-0000-0000-0000-000000000002",
        worker_id=job_b.worker_id,
        attempt_count=job_b.attempt_count,
    ) is True


def test_cancel_and_complete_are_one_atomic_transition(queue_user_id):
    from synsc.services.job_queue_service import JobQueueService

    queue = JobQueueService()
    created = queue.create_source_job(
        user_id=queue_user_id,
        source_type="docs",
        url="https://docs.example.com/cancel-race",
    )
    job = queue.claim_next_job("worker-racing")
    assert job is not None
    barrier = threading.Barrier(2)

    def cancel():
        barrier.wait()
        return JobQueueService().cancel_job(created["job_id"], queue_user_id)

    def complete():
        barrier.wait()
        return JobQueueService().complete_source_job(
            created["job_id"],
            source_type="docs",
            source_id="00000000-0000-0000-0000-000000000003",
            worker_id=job.worker_id,
            attempt_count=job.attempt_count,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        cancel_result = executor.submit(cancel)
        complete_result = executor.submit(complete)
        cancelled = cancel_result.result()
        completed = complete_result.result()

    assert int(cancelled["success"]) + int(completed) == 1
    if cancelled["success"]:
        assert queue.acknowledge_cancellation(
            created["job_id"],
            worker_id=job.worker_id,
            attempt_count=job.attempt_count,
        )
    final = queue.get_job(created["job_id"], user_id=queue_user_id)["job"]
    assert final["status"] in {"cancelled", "completed"}


def test_processing_cancellation_is_not_reassigned_before_worker_ack(queue_user_id):
    from synsc.services.job_queue_service import JobQueueService

    queue = JobQueueService()
    created = queue.create_source_job(
        user_id=queue_user_id,
        source_type="dataset",
        url="acme/cooperative-cancel",
    )
    claimed = queue.claim_next_job("worker-current")
    assert claimed is not None

    result = queue.cancel_job(created["job_id"], queue_user_id)

    assert result["success"] is True
    assert result["job"]["status"] == "cancelling"
    assert queue.claim_next_job("worker-other") is None
    assert queue.update_progress(
        claimed.job_id,
        0.5,
        worker_id=claimed.worker_id,
        attempt_count=claimed.attempt_count,
    ) is False
    assert queue.acknowledge_cancellation(
        claimed.job_id,
        worker_id=claimed.worker_id,
        attempt_count=claimed.attempt_count,
    ) is True
    final = queue.get_job(created["job_id"], user_id=queue_user_id)["job"]
    assert final["status"] == "cancelled"
