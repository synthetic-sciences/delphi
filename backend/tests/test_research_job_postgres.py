"""Durable research queue contracts against a real PostgreSQL database."""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command


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
    reason="No real Postgres at DATABASE_URL — skipping research queue tests.",
)


@pytest.fixture
def research_user_id():
    from synsc.database.connection import get_session

    user_id = str(uuid.uuid4())
    yield user_id
    with get_session() as session:
        session.execute(
            text("DELETE FROM research_jobs WHERE user_id = :user_id"),
            {"user_id": user_id},
        )


def test_job_and_event_log_survive_service_recreation(research_user_id) -> None:
    from synsc.services.research_job_service import ResearchJobService

    created = ResearchJobService().create_job(
        user_id=research_user_id,
        query="survive restart",
    )

    loaded = ResearchJobService().get_job(
        created.job_id,
        user_id=research_user_id,
    )
    events = ResearchJobService().list_events(
        created.job_id,
        user_id=research_user_id,
    )

    assert loaded.query == "survive restart"
    assert loaded.status == "pending"
    assert [(event.seq, event.event_type) for event in events] == [(0, "queued")]


def test_concurrent_workers_claim_a_job_once(research_user_id) -> None:
    from synsc.services.research_job_service import ResearchJobService

    created = ResearchJobService().create_job(
        user_id=research_user_id,
        query="claim once",
    )
    workers = 8
    barrier = threading.Barrier(workers)

    def claim(index: int):
        barrier.wait()
        return ResearchJobService().claim_next_job(f"worker-{index}")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        claimed = list(executor.map(claim, range(workers)))

    winners = [job for job in claimed if job is not None]
    assert len(winners) == 1
    assert winners[0].job_id == created.job_id
    assert winners[0].attempt_count == 1


def test_concurrent_event_writers_allocate_contiguous_sequences(
    research_user_id,
) -> None:
    from synsc.services.research_job_service import ResearchJobService

    created = ResearchJobService().create_job(
        user_id=research_user_id,
        query="ordered events",
    )
    writers = 12
    barrier = threading.Barrier(writers)

    def append(index: int):
        barrier.wait()
        return ResearchJobService().append_event(
            created.job_id,
            "iteration",
            {"index": index},
        )

    with ThreadPoolExecutor(max_workers=writers) as executor:
        records = list(executor.map(append, range(writers)))

    assert all(record is not None for record in records)
    events = ResearchJobService().list_events(
        created.job_id,
        user_id=research_user_id,
    )
    assert [event.seq for event in events] == list(range(writers + 1))


def test_cancel_and_complete_have_one_terminal_winner(research_user_id) -> None:
    from synsc.services.research_job_service import (
        ResearchJobService,
        ResearchJobStateError,
    )

    queue = ResearchJobService()
    created = queue.create_job(user_id=research_user_id, query="race")
    claimed = queue.claim_next_job("worker-current")
    assert claimed is not None
    barrier = threading.Barrier(2)

    def cancel():
        barrier.wait()
        try:
            return ResearchJobService().cancel_job(
                created.job_id,
                user_id=research_user_id,
            )
        except ResearchJobStateError:
            return None

    def complete():
        barrier.wait()
        return ResearchJobService().complete_job(
            created.job_id,
            answer_markdown="answer",
            citations=[],
            usage={},
            auto_indexed=[],
            worker_id=claimed.worker_id,
            attempt_count=claimed.attempt_count,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        cancelled_future = executor.submit(cancel)
        completed_future = executor.submit(complete)
        cancelled = cancelled_future.result()
        completed = completed_future.result()

    assert int(cancelled is not None) + int(completed) == 1
    if cancelled is not None and cancelled.status == "cancelling":
        assert queue.acknowledge_cancellation(
            created.job_id,
            worker_id=claimed.worker_id,
            attempt_count=claimed.attempt_count,
        )
    final = queue.get_job(created.job_id, user_id=research_user_id)
    assert final.status in {"completed", "cancelled"}


def test_owner_scope_hides_job_and_events(research_user_id) -> None:
    from synsc.services.research_job_service import (
        ResearchJobNotFoundError,
        ResearchJobService,
    )

    created = ResearchJobService().create_job(
        user_id=research_user_id,
        query="private",
    )
    stranger = str(uuid.uuid4())

    with pytest.raises(ResearchJobNotFoundError):
        ResearchJobService().get_job(created.job_id, user_id=stranger)
    with pytest.raises(ResearchJobNotFoundError):
        ResearchJobService().list_events(created.job_id, user_id=stranger)


def test_stale_worker_is_fenced_after_recovery(research_user_id) -> None:
    from synsc.database.connection import get_session
    from synsc.services.research_job_service import ResearchJobService

    queue = ResearchJobService()
    created = queue.create_job(user_id=research_user_id, query="recover")
    first = queue.claim_next_job("worker-old")
    assert first is not None

    with get_session() as session:
        session.execute(
            text(
                "UPDATE research_jobs "
                "SET updated_at = NOW() - INTERVAL '2 hours' "
                "WHERE job_id = :job_id"
            ),
            {"job_id": created.job_id},
        )

    assert queue.recover_stale_jobs(stale_after_seconds=60)["requeued"] == 1
    recovered_events = queue.list_events(
        created.job_id,
        user_id=research_user_id,
    )
    assert recovered_events[-1].event_type == "recovered"
    second = queue.claim_next_job("worker-new")
    assert second is not None
    assert second.attempt_count == first.attempt_count + 1

    assert queue.complete_job(
        created.job_id,
        answer_markdown="stale",
        citations=[],
        usage={},
        auto_indexed=[],
        worker_id=first.worker_id,
        attempt_count=first.attempt_count,
    ) is False
    assert queue.complete_job(
        created.job_id,
        answer_markdown="current",
        citations=[],
        usage={},
        auto_indexed=[],
        worker_id=second.worker_id,
        attempt_count=second.attempt_count,
    ) is True


def test_followup_message_survives_requeue_and_claim(research_user_id) -> None:
    from synsc.services.research_job_service import ResearchJobService

    queue = ResearchJobService()
    created = queue.create_job(user_id=research_user_id, query="initial")
    first = queue.claim_next_job("worker-first")
    assert first is not None
    assert queue.complete_job(
        created.job_id,
        answer_markdown="first answer",
        citations=[],
        usage={},
        auto_indexed=[],
        worker_id=first.worker_id,
        attempt_count=first.attempt_count,
    )

    queued = queue.enqueue_followup(
        created.job_id,
        message="follow up",
        user_id=research_user_id,
    )
    assert queued.status == "pending"
    second = queue.claim_next_job("worker-second")
    assert second is not None
    messages = queue.list_messages_for_worker(
        created.job_id,
        worker_id=second.worker_id,
        attempt_count=second.attempt_count,
    )

    assert [(message.role, message.content) for message in messages] == [
        ("assistant", "first answer"),
        ("user", "follow up"),
    ]


def test_runner_persists_answer_usage_and_replay_events(research_user_id) -> None:
    from synsc.services.research_job_service import ResearchJobService
    from synsc.workers.research_worker import ResearchJobRunner

    queue = ResearchJobService()
    created = queue.create_job(
        user_id=research_user_id,
        query="run end to end",
        auto_index=False,
    )
    claimed = queue.claim_next_job("worker-integration")
    assert claimed is not None

    class FakeResearch:
        def run(self, **kwargs):
            kwargs["progress_callback"](
                "retrieval",
                {"hop": 0, "query": kwargs["query"]},
            )
            return {
                "answer_markdown": "persisted answer",
                "citations": [{"source_id": "source-1"}],
                "usage": {
                    "tokens_in": 7,
                    "tokens_out": 3,
                    "latency_ms": 11,
                },
            }

    assert ResearchJobRunner(
        service=queue,
        research_factory=lambda _user_id: FakeResearch(),
    ).process_job(claimed)

    completed = queue.get_job(created.job_id, user_id=research_user_id)
    events = queue.list_events(created.job_id, user_id=research_user_id)
    assert completed.status == "completed"
    assert completed.answer_markdown == "persisted answer"
    assert completed.tokens_in == 7
    assert completed.tokens_out == 3
    assert completed.latency_ms == 11
    assert [event.event_type for event in events] == [
        "queued",
        "iteration",
        "retrieval",
        "answer",
        "done",
    ]


def test_migration_downgrade_normalizes_cancelled_jobs(research_user_id) -> None:
    import psycopg2

    job_id = str(uuid.uuid4())
    database_url = os.environ["DATABASE_URL"]
    connection = psycopg2.connect(database_url)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                """
                    INSERT INTO research_jobs (
                        job_id, user_id, mode, query, status
                    ) VALUES (%s, %s, 'quick', 'downgrade', 'cancelled')
                    """,
                (job_id, research_user_id),
            )
    finally:
        connection.close()

    backend_root = os.path.dirname(os.path.dirname(__file__))
    config = Config(os.path.join(backend_root, "alembic.ini"))
    config.set_main_option(
        "script_location",
        os.path.join(backend_root, "alembic"),
    )

    try:
        command.downgrade(config, "015_snapshot_search")

        connection = psycopg2.connect(database_url)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT status FROM research_jobs WHERE job_id = %s",
                    (job_id,),
                )
                assert cursor.fetchone() == ("failed",)
        finally:
            connection.close()
    finally:
        command.upgrade(config, "head")
