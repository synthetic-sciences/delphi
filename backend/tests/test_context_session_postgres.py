"""PostgreSQL concurrency and immutability contracts for contexts."""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from synsc.connectors.contracts import ConnectorRecord, ConnectorSyncResponse
from synsc.contexts.postgres import PostgresContextSessionStore
from synsc.contexts.service import (
    ContextRevisionConflictError,
    ContextSessionService,
)
from synsc.database.connection import get_session
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
    reason="No real Postgres at DATABASE_URL — skipping context contracts.",
)


@pytest.fixture
def context_user_id(monkeypatch: pytest.MonkeyPatch):
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
            text("DELETE FROM context_sessions WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        session.execute(
            text("DELETE FROM connector_sources WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
    token_encryption._fernet = None


def _session(user_id: str) -> dict[str, object]:
    return {
        "session_id": str(uuid.uuid4()),
        "user_id": user_id,
        "name": f"context-{uuid.uuid4()}",
        "objective": "Preserve exact evidence",
        "status": "active",
        "sharing_policy": "private",
        "expires_at": None,
        "parent_session_id": None,
        "parent_revision_id": None,
        "handoff_note": None,
    }


def _revision(
    session_id: str,
    number: int,
    *,
    parent_revision_id: str | None = None,
) -> dict[str, object]:
    return {
        "revision_id": str(uuid.uuid4()),
        "session_id": session_id,
        "revision_number": number,
        "parent_revision_id": parent_revision_id,
        "token_budget": 100,
        "tokens_used": 2,
        "state": {
            "task_state": {},
            "accepted_evidence": [],
            "rejected_evidence": [],
            "decisions": [],
            "unresolved_questions": [],
            "summary": None,
        },
        "pinned_snapshots": [],
        "context_manifest": {
            "schema_version": 1,
            "items": [],
            "tokens_used": 2,
        },
        "content_hash": f"{number:064x}",
        "summary_model": None,
        "summary_version": None,
    }


def test_create_get_list_and_owner_scope(context_user_id: str) -> None:
    store = PostgresContextSessionStore()
    session = _session(context_user_id)
    revision = _revision(str(session["session_id"]), 1)

    created = store.create(session=session, revision=revision)

    assert created["session"]["current_revision"] == 1
    assert created["session"]["write_version"] == 1
    assert created["revision"]["revision_id"] == revision["revision_id"]
    assert store.list(
        user_id=context_user_id,
        limit=10,
        include_expired=False,
    )[0]["session_id"] == session["session_id"]
    with pytest.raises(LookupError):
        store.get(
            str(session["session_id"]),
            user_id=str(uuid.uuid4()),
        )


def test_concurrent_append_has_one_revision_winner(
    context_user_id: str,
) -> None:
    store = PostgresContextSessionStore()
    session = _session(context_user_id)
    first = _revision(str(session["session_id"]), 1)
    store.create(session=session, revision=first)
    barrier = threading.Barrier(2)

    def append() -> str:
        barrier.wait()
        try:
            result = PostgresContextSessionStore().append(
                str(session["session_id"]),
                user_id=context_user_id,
                expected_version=1,
                revision=_revision(
                    str(session["session_id"]),
                    2,
                    parent_revision_id=str(first["revision_id"]),
                ),
            )
            return str(result["revision"]["revision_id"])
        except ContextRevisionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: append(), range(2)))

    assert results.count("conflict") == 1
    assert len([result for result in results if result != "conflict"]) == 1
    loaded = store.get(
        str(session["session_id"]),
        user_id=context_user_id,
    )
    assert loaded["session"]["current_revision"] == 2
    assert loaded["session"]["write_version"] == 2


def test_revision_rows_cannot_be_updated(context_user_id: str) -> None:
    store = PostgresContextSessionStore()
    session = _session(context_user_id)
    revision = _revision(str(session["session_id"]), 1)
    store.create(session=session, revision=revision)

    with pytest.raises(DBAPIError), get_session() as database:
        database.execute(
            text(
                """
                UPDATE context_revisions
                SET token_budget = token_budget + 1
                WHERE revision_id = :revision_id
                """
            ),
            {"revision_id": revision["revision_id"]},
        )


def test_policy_update_advances_shared_write_fence(
    context_user_id: str,
) -> None:
    store = PostgresContextSessionStore()
    session = _session(context_user_id)
    revision = _revision(str(session["session_id"]), 1)
    store.create(session=session, revision=revision)

    updated = store.update_policy(
        str(session["session_id"]),
        user_id=context_user_id,
        expected_version=1,
        sharing_policy="shared",
        expires_at=None,
        status="completed",
    )
    assert updated["sharing_policy"] == "shared"
    assert updated["status"] == "completed"
    assert updated["write_version"] == 2

    with pytest.raises(ContextRevisionConflictError):
        store.update_policy(
            str(session["session_id"]),
            user_id=context_user_id,
            expected_version=1,
            sharing_policy="private",
            expires_at=None,
            status="active",
        )


def test_archive_and_append_cannot_both_win(context_user_id: str) -> None:
    store = PostgresContextSessionStore()
    session = _session(context_user_id)
    first = _revision(str(session["session_id"]), 1)
    store.create(session=session, revision=first)
    barrier = threading.Barrier(2)

    def append() -> str:
        barrier.wait()
        try:
            PostgresContextSessionStore().append(
                str(session["session_id"]),
                user_id=context_user_id,
                expected_version=1,
                revision=_revision(
                    str(session["session_id"]),
                    2,
                    parent_revision_id=str(first["revision_id"]),
                ),
            )
            return "append"
        except ContextRevisionConflictError:
            return "conflict"

    def archive() -> str:
        barrier.wait()
        try:
            PostgresContextSessionStore().update_policy(
                str(session["session_id"]),
                user_id=context_user_id,
                expected_version=1,
                sharing_policy="private",
                expires_at=None,
                status="archived",
            )
            return "archive"
        except ContextRevisionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        append_future = executor.submit(append)
        archive_future = executor.submit(archive)
        results = [append_future.result(), archive_future.result()]

    assert results.count("conflict") == 1
    assert len([result for result in results if result != "conflict"]) == 1
    loaded = store.get(
        str(session["session_id"]),
        user_id=context_user_id,
    )
    assert loaded["session"]["write_version"] == 2
    if "archive" in results:
        assert loaded["session"]["status"] == "archived"
        assert loaded["session"]["current_revision"] == 1
    else:
        assert loaded["session"]["status"] == "active"
        assert loaded["session"]["current_revision"] == 2


def test_handoff_rechecks_parent_version_and_lifecycle(
    context_user_id: str,
) -> None:
    store = PostgresContextSessionStore()
    parent_session = _session(context_user_id)
    parent_revision = _revision(
        str(parent_session["session_id"]),
        1,
    )
    parent = store.create(
        session=parent_session,
        revision=parent_revision,
    )
    store.update_policy(
        str(parent_session["session_id"]),
        user_id=context_user_id,
        expected_version=1,
        sharing_policy="private",
        expires_at=None,
        status="archived",
    )
    child_session = {
        **_session(context_user_id),
        "parent_session_id": parent_session["session_id"],
        "parent_revision_id": parent["revision"]["revision_id"],
    }
    child_revision = _revision(str(child_session["session_id"]), 1)

    with pytest.raises(ContextRevisionConflictError):
        store.create(
            session=child_session,
            revision=child_revision,
            parent_expected_version=1,
        )


def test_context_rehydration_respects_current_record_access(
    context_user_id: str,
) -> None:
    from synsc.connectors.postgres import PostgresConnectorSyncStore

    connectors = PostgresConnectorSyncStore()
    source = connectors.create_source(
        user_id=context_user_id,
        provider="fixture",
        display_name="Private records",
        external_ref="fixture://context",
        configuration={},
        classification=ContentClassification.PRIVATE,
        schedule_seconds=None,
        enabled=True,
    )
    source_id = str(source["source_id"])
    connectors.enqueue_sync(
        source_id,
        user_id=context_user_id,
        priority=0,
    )
    first = connectors.claim_next_job(worker_id="context-first")
    assert first is not None
    first_job, first_source = first
    first_result = connectors.apply_sync_page(
        first_job,
        first_source,
        ConnectorSyncResponse(
            records=(
                ConnectorRecord(
                    external_id="record-1",
                    locator="private.md",
                    content="authorized context",
                    accessible_principals=(context_user_id,),
                ),
            ),
            next_cursor={"generation": 1},
        ),
    )

    contexts = ContextSessionService(
        store=PostgresContextSessionStore(),
    )
    created = contexts.create_session(
        user_id=context_user_id,
        name=f"acl-{uuid.uuid4()}",
        objective="Retain only currently authorized evidence",
        snapshot_ids=[str(first_result["snapshot_id"])],
        token_budget=100,
    )
    assert created["context_items"][0]["content"] == "authorized context"

    connectors.enqueue_sync(
        source_id,
        user_id=context_user_id,
        priority=0,
    )
    second = connectors.claim_next_job(worker_id="context-second")
    assert second is not None
    second_job, second_source = second
    connectors.apply_sync_page(
        second_job,
        second_source,
        ConnectorSyncResponse(
            records=(
                ConnectorRecord(
                    external_id="record-1",
                    locator="private.md",
                    content="must be hidden",
                    accessible_principals=(str(uuid.uuid4()),),
                ),
            ),
            next_cursor={"generation": 2},
        ),
    )

    loaded = contexts.get_session(
        str(created["session"]["session_id"]),
        user_id=context_user_id,
    )
    assert loaded["context_items"] == []
    assert loaded["unavailable_items"][0]["locator"] == "private.md"
