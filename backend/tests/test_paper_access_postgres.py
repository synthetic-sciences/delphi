"""PostgreSQL concurrency regression for shared paper deletion."""

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
    reason="No real Postgres at DATABASE_URL — skipping paper concurrency test.",
)


def test_concurrent_final_user_deletes_do_not_leave_orphaned_paper():
    from synsc.database.connection import get_session
    from synsc.services.paper_service import PaperService

    paper_id = str(uuid.uuid4())
    user_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    barrier = threading.Barrier(2)

    with get_session() as session:
        session.execute(
            text(
                "INSERT INTO papers (paper_id, title, pdf_hash) "
                "VALUES (:pid, 'Concurrent delete', :pdf_hash)"
            ),
            {"pid": paper_id, "pdf_hash": uuid.uuid4().hex},
        )
        for user_id in user_ids:
            session.execute(
                text(
                    "INSERT INTO user_papers (user_id, paper_id) "
                    "VALUES (:uid, :pid)"
                ),
                {"uid": user_id, "pid": paper_id},
            )

    def remove(user_id: str):
        barrier.wait()
        return PaperService(user_id=user_id).delete_paper(paper_id)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(remove, user_ids))

        assert all(result["success"] for result in results)
        with get_session() as session:
            assert (
                session.execute(
                    text("SELECT COUNT(*) FROM user_papers WHERE paper_id = :pid"),
                    {"pid": paper_id},
                ).scalar_one()
                == 0
            )
            assert (
                session.execute(
                    text("SELECT COUNT(*) FROM papers WHERE paper_id = :pid"),
                    {"pid": paper_id},
                ).scalar_one()
                == 0
            )
    finally:
        with get_session() as session:
            session.execute(
                text("DELETE FROM user_papers WHERE paper_id = :pid"),
                {"pid": paper_id},
            )
            session.execute(
                text("DELETE FROM papers WHERE paper_id = :pid"),
                {"pid": paper_id},
            )
