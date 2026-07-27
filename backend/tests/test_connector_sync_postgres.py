"""Durability, leasing, ACL, and checkpoint contracts against PostgreSQL."""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import text

from alembic import command
from synsc.connectors.contracts import (
    ConnectorRecord,
    ConnectorSyncResponse,
)
from synsc.providers.contracts import ContentClassification


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
    reason="No real Postgres at DATABASE_URL — skipping connector contracts.",
)


@pytest.fixture
def connector_runtime(monkeypatch: pytest.MonkeyPatch):
    from synsc.database.connection import get_session
    from synsc.services import token_encryption

    user_id = str(uuid.uuid4())
    monkeypatch.setenv(
        "TOKEN_ENCRYPTION_KEY",
        Fernet.generate_key().decode(),
    )
    token_encryption._fernet = None
    yield user_id
    with get_session() as session:
        session.execute(
            text("DELETE FROM connector_sources WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
    token_encryption._fernet = None


def _create(store, user_id: str) -> dict[str, object]:
    return store.create_source(
        user_id=user_id,
        provider="local-folder",
        display_name="Local notes",
        external_ref="file:///private/notes",
        configuration={"path": "/private/notes", "api_token": "secret"},
        classification=ContentClassification.LOCAL_SENSITIVE,
        schedule_seconds=300,
        enabled=True,
    )


def test_configuration_and_cursor_are_encrypted_and_owner_scoped(
    connector_runtime: str,
) -> None:
    from synsc.connectors.postgres import (
        ConnectorSourceNotFoundError,
        PostgresConnectorSyncStore,
    )
    from synsc.database.connection import get_session

    store = PostgresConnectorSyncStore()
    created = _create(store, connector_runtime)
    source_id = str(created["source_id"])

    with get_session() as session:
        row = session.execute(
            text(
                """
                SELECT encrypted_config, encrypted_cursor
                FROM connector_sources
                WHERE source_id = :source_id
                """
            ),
            {"source_id": source_id},
        ).mappings().one()
    assert "/private/notes" not in row["encrypted_config"]
    assert "secret" not in row["encrypted_config"]
    assert row["encrypted_cursor"] is None
    assert "configuration" not in created

    with pytest.raises(ConnectorSourceNotFoundError):
        store.get_source(source_id, user_id=str(uuid.uuid4()))


def test_concurrent_enqueue_and_claim_have_single_winners(
    connector_runtime: str,
) -> None:
    from synsc.connectors.postgres import PostgresConnectorSyncStore

    store = PostgresConnectorSyncStore()
    source_id = str(_create(store, connector_runtime)["source_id"])
    workers = 8
    barrier = threading.Barrier(workers)

    def enqueue(_: int) -> str:
        barrier.wait()
        return str(
            PostgresConnectorSyncStore().enqueue_sync(
                source_id,
                user_id=connector_runtime,
                priority=0,
            )["job_id"]
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        job_ids = list(executor.map(enqueue, range(workers)))
    assert len(set(job_ids)) == 1

    claim_barrier = threading.Barrier(workers)

    def claim(index: int):
        claim_barrier.wait()
        return PostgresConnectorSyncStore().claim_next_job(
            worker_id=f"worker-{index}"
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        claims = list(executor.map(claim, range(workers)))
    assert len([claim for claim in claims if claim is not None]) == 1


def test_page_apply_activates_snapshot_then_advances_cursor(
    connector_runtime: str,
) -> None:
    from synsc.connectors.postgres import PostgresConnectorSyncStore
    from synsc.database.connection import get_session

    store = PostgresConnectorSyncStore()
    source_id = str(_create(store, connector_runtime)["source_id"])
    job_id = str(
        store.enqueue_sync(
            source_id,
            user_id=connector_runtime,
            priority=0,
        )["job_id"]
    )
    claimed = store.claim_next_job(worker_id="worker-current")
    assert claimed is not None
    job, source = claimed
    result = store.apply_sync_page(
        job,
        source,
        ConnectorSyncResponse(
            records=(
                ConnectorRecord(
                    external_id="doc-1",
                    locator="notes/one.md",
                    content="first version",
                    accessible_principals=(connector_runtime,),
                ),
                ConnectorRecord(
                    external_id="doc-2",
                    locator="notes/two.md",
                    content="second record",
                    accessible_principals=(connector_runtime,),
                ),
            ),
            next_cursor={"generation": 1},
        ),
    )

    assert result["job_id"] == job_id
    assert result["status"] == "completed"
    snapshot_id = str(result["snapshot_id"])
    with get_session() as session:
        row = session.execute(
            text(
                """
                SELECT source.encrypted_cursor, source.last_snapshot_id,
                       job.status, snapshot.sealed_at,
                       head.snapshot_id
                FROM connector_sources source
                JOIN connector_sync_jobs job
                  ON job.source_id = source.source_id
                JOIN source_snapshots snapshot
                  ON snapshot.snapshot_id = source.last_snapshot_id
                JOIN source_snapshot_heads head
                  ON head.source_type = 'connector'
                 AND head.source_id = source.source_id
                WHERE source.source_id = :source_id
                """
            ),
            {"source_id": source_id},
        ).mappings().one()
    assert "generation" not in row["encrypted_cursor"]
    assert row["last_snapshot_id"] == snapshot_id
    assert row["snapshot_id"] == snapshot_id
    assert row["status"] == "completed"
    assert row["sealed_at"] is not None

    store.enqueue_sync(
        source_id,
        user_id=connector_runtime,
        priority=0,
    )
    next_claim = store.claim_next_job(worker_id="worker-next")
    assert next_claim is not None
    next_state, next_source = next_claim
    assert next_source.cursor == {"generation": 1}
    tombstoned = store.apply_sync_page(
        next_state,
        next_source,
        ConnectorSyncResponse(
            records=(
                ConnectorRecord(
                    external_id="doc-2",
                    locator="notes/two.md",
                    deleted=True,
                ),
            ),
            next_cursor={"generation": 2},
        ),
    )
    with get_session() as session:
        locators = session.execute(
            text(
                """
                SELECT item.locator
                FROM source_snapshot_items item
                WHERE item.snapshot_id = :snapshot_id
                ORDER BY item.locator
                """
            ),
            {"snapshot_id": tombstoned["snapshot_id"]},
        ).scalars().all()
    assert locators == ["notes/one.md"]


def test_failure_does_not_advance_checkpoint(
    connector_runtime: str,
) -> None:
    from synsc.connectors.postgres import PostgresConnectorSyncStore
    from synsc.database.connection import get_session

    store = PostgresConnectorSyncStore()
    source_id = str(_create(store, connector_runtime)["source_id"])
    store.enqueue_sync(source_id, user_id=connector_runtime, priority=0)
    claimed = store.claim_next_job(worker_id="worker-failing")
    assert claimed is not None
    job, _ = claimed
    assert store.fail_job(job, error_message="network failed")

    with get_session() as session:
        row = session.execute(
            text(
                """
                SELECT source.encrypted_cursor, source.last_snapshot_id,
                       job.status
                FROM connector_sources source
                JOIN connector_sync_jobs job
                  ON job.source_id = source.source_id
                WHERE source.source_id = :source_id
                """
            ),
            {"source_id": source_id},
        ).mappings().one()
    assert row["encrypted_cursor"] is None
    assert row["last_snapshot_id"] is None
    assert row["status"] == "failed"


def test_permission_revocation_is_materialized_as_tombstone(
    connector_runtime: str,
) -> None:
    from synsc.connectors.postgres import PostgresConnectorSyncStore
    from synsc.database.connection import get_session

    store = PostgresConnectorSyncStore()
    source_id = str(_create(store, connector_runtime)["source_id"])
    store.enqueue_sync(source_id, user_id=connector_runtime, priority=0)
    first = store.claim_next_job(worker_id="worker-one")
    assert first is not None
    first_job, first_source = first
    store.apply_sync_page(
        first_job,
        first_source,
        ConnectorSyncResponse(
            records=(
                ConnectorRecord(
                    external_id="private-doc",
                    locator="private.md",
                    content="visible now",
                    accessible_principals=(connector_runtime,),
                ),
            ),
            next_cursor={"generation": 1},
        ),
    )

    store.enqueue_sync(source_id, user_id=connector_runtime, priority=0)
    second = store.claim_next_job(worker_id="worker-two")
    assert second is not None
    second_job, second_source = second
    result = store.apply_sync_page(
        second_job,
        second_source,
        ConnectorSyncResponse(
            records=(
                ConnectorRecord(
                    external_id="private-doc",
                    locator="private.md",
                    content="must not remain",
                    accessible_principals=("different-user",),
                ),
            ),
            next_cursor={"generation": 2},
        ),
    )

    with get_session() as session:
        item_count = session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM source_snapshot_items
                WHERE snapshot_id = :snapshot_id
                """
            ),
            {"snapshot_id": result["snapshot_id"]},
        ).scalar_one()
    assert item_count == 0


def test_snapshot_failure_rolls_back_checkpoint_and_head(
    connector_runtime: str,
) -> None:
    from synsc.connectors.postgres import PostgresConnectorSyncStore
    from synsc.database.connection import get_session
    from synsc.snapshots.service import PostgresSnapshotStore

    class FailingSnapshotStore(PostgresSnapshotStore):
        def seal_snapshot(self, session, snapshot_id):
            raise RuntimeError("snapshot validation failed")

    store = PostgresConnectorSyncStore(
        snapshot_store=FailingSnapshotStore()
    )
    source_id = str(_create(store, connector_runtime)["source_id"])
    store.enqueue_sync(source_id, user_id=connector_runtime, priority=0)
    claimed = store.claim_next_job(worker_id="worker-failing-snapshot")
    assert claimed is not None
    job, source = claimed

    with pytest.raises(RuntimeError, match="snapshot validation"):
        store.apply_sync_page(
            job,
            source,
            ConnectorSyncResponse(
                records=(
                    ConnectorRecord(
                        external_id="doc-1",
                        locator="one.md",
                        content="must roll back",
                    ),
                ),
                next_cursor={"generation": 1},
            ),
        )

    with get_session() as session:
        source_row = session.execute(
            text(
                """
                SELECT encrypted_cursor, last_snapshot_id
                FROM connector_sources
                WHERE source_id = :source_id
                """
            ),
            {"source_id": source_id},
        ).mappings().one()
        snapshot_count = session.execute(
            text(
                """
                SELECT COUNT(*) FROM source_snapshots
                WHERE source_type = 'connector'
                  AND source_id = :source_id
                """
            ),
            {"source_id": source_id},
        ).scalar_one()
    assert source_row["encrypted_cursor"] is None
    assert source_row["last_snapshot_id"] is None
    assert snapshot_count == 0


def test_local_folder_service_runs_end_to_end(
    connector_runtime: str,
    tmp_path: Path,
) -> None:
    from synsc.connectors.postgres import PostgresConnectorSyncStore
    from synsc.connectors.service import ConnectorSyncService
    from synsc.services.source_service import (
        resolve_source_id,
        unified_search,
    )
    from synsc.snapshots.service import (
        SnapshotAccessDeniedError,
        SnapshotService,
    )

    (tmp_path / "notes.md").write_text(
        "durable local context",
        encoding="utf-8",
    )
    service = ConnectorSyncService(store=PostgresConnectorSyncStore())
    source = service.create_source(
        user_id=connector_runtime,
        provider="local-folder",
        display_name="Local notes",
        external_ref=tmp_path.as_uri(),
        configuration={"path": str(tmp_path)},
        classification=ContentClassification.LOCAL_SENSITIVE,
    )
    queued = service.enqueue_sync(
        str(source["source_id"]),
        user_id=connector_runtime,
    )

    completed = service.run_once(worker_id="connector-e2e")

    assert completed is not None
    assert completed["job_id"] == queued["job_id"]
    assert completed["status"] == "completed"
    snapshot_id = str(completed["snapshot_id"])
    visible = SnapshotService().get(
        snapshot_id,
        user_id=connector_runtime,
        include_items=True,
    )
    assert visible["items"][0]["content"] == "durable local context"
    assert resolve_source_id(
        str(source["source_id"]),
        user_id=connector_runtime,
    ) == (str(source["source_id"]), "connector")
    search = unified_search(
        query="durable local",
        source_ids=[str(source["source_id"])],
        source_types=["connector"],
        user_id=connector_runtime,
    )
    assert search["results"][0]["text"] == "durable local context"
    with pytest.raises(SnapshotAccessDeniedError):
        SnapshotService().get(
            snapshot_id,
            user_id=str(uuid.uuid4()),
        )


def test_migration_downgrade_removes_connector_snapshots_before_constraint(
    connector_runtime: str,
) -> None:
    import psycopg2

    from synsc.connectors.postgres import PostgresConnectorSyncStore

    store = PostgresConnectorSyncStore()
    source_id = str(_create(store, connector_runtime)["source_id"])
    store.enqueue_sync(source_id, user_id=connector_runtime, priority=0)
    claimed = store.claim_next_job(worker_id="worker-downgrade")
    assert claimed is not None
    job, source = claimed
    store.apply_sync_page(
        job,
        source,
        ConnectorSyncResponse(
            records=(
                ConnectorRecord(
                    external_id="doc",
                    locator="doc.md",
                    content="downgrade safely",
                ),
            ),
            next_cursor={"generation": 1},
        ),
    )

    backend_root = os.path.dirname(os.path.dirname(__file__))
    config = Config(os.path.join(backend_root, "alembic.ini"))
    config.set_main_option(
        "script_location",
        os.path.join(backend_root, "alembic"),
    )
    database_url = os.environ["DATABASE_URL"]
    try:
        command.downgrade(config, "016_durable_research_jobs")
        connection = psycopg2.connect(database_url)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM source_snapshots
                    WHERE source_type = 'connector'
                    """
                )
                assert cursor.fetchone() == (0,)
                cursor.execute(
                    "SELECT to_regclass('public.connector_sources')"
                )
                assert cursor.fetchone() == (None,)
        finally:
            connection.close()
    finally:
        command.upgrade(config, "head")


def test_many_bounded_pages_do_not_exhaust_retry_budget(
    connector_runtime: str,
    tmp_path: Path,
) -> None:
    from synsc.connectors.postgres import PostgresConnectorSyncStore
    from synsc.connectors.service import ConnectorSyncService

    for index in range(5):
        (tmp_path / f"{index}.md").write_text(
            f"record {index}",
            encoding="utf-8",
        )
    service = ConnectorSyncService(
        store=PostgresConnectorSyncStore(),
        page_limit=1,
    )
    source = service.create_source(
        user_id=connector_runtime,
        provider="local-folder",
        display_name="Paged notes",
        external_ref=tmp_path.as_uri(),
        configuration={"path": str(tmp_path)},
        classification=ContentClassification.LOCAL_SENSITIVE,
    )
    queued = service.enqueue_sync(
        str(source["source_id"]),
        user_id=connector_runtime,
    )

    results = [
        service.run_once(worker_id=f"worker-page-{index}")
        for index in range(5)
    ]

    assert [result["status"] for result in results if result] == [
        "pending",
        "pending",
        "pending",
        "pending",
        "completed",
    ]
    job = service.get_job(
        str(queued["job_id"]),
        user_id=connector_runtime,
    )
    assert job["records_changed"] == 5
