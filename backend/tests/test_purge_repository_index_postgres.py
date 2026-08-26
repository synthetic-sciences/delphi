"""Real-PostgreSQL contracts for repository index purge isolation."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from synsc.services.indexing_service import IndexingService


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
    reason="No real Postgres at DATABASE_URL — skipping purge contracts.",
)


@pytest.fixture
def paired_symbol_repositories():
    from synsc.database.connection import get_session

    target_repo_id = str(uuid.uuid4())
    other_repo_id = str(uuid.uuid4())
    target_file_id = str(uuid.uuid4())
    other_file_id = str(uuid.uuid4())
    parent_symbol_id = str(uuid.uuid4())
    child_symbol_id = str(uuid.uuid4())
    other_symbol_id = str(uuid.uuid4())

    with get_session() as session:
        for repo_id, url_suffix in (
            (target_repo_id, "target"),
            (other_repo_id, "other"),
        ):
            session.execute(
                text(
                    """
                    INSERT INTO repositories
                        (repo_id, url, owner, name, branch, commit_sha,
                         is_public, files_count, chunks_count)
                    VALUES
                        (:repo_id, :url, 'acme', :name, 'main', 'sha', TRUE, 1, 0)
                    """
                ),
                {
                    "repo_id": repo_id,
                    "url": f"https://github.com/acme/purge-{url_suffix}-{repo_id}",
                    "name": url_suffix,
                },
            )

        session.execute(
            text(
                """
                INSERT INTO repository_files
                    (file_id, repo_id, file_path, file_name, content_hash)
                VALUES
                    (:file_id, :repo_id, 'sample.py', 'sample.py', 'hash')
                """
            ),
            {"file_id": target_file_id, "repo_id": target_repo_id},
        )
        session.execute(
            text(
                """
                INSERT INTO repository_files
                    (file_id, repo_id, file_path, file_name, content_hash)
                VALUES
                    (:file_id, :repo_id, 'other.py', 'other.py', 'hash')
                """
            ),
            {"file_id": other_file_id, "repo_id": other_repo_id},
        )
        session.execute(
            text(
                """
                INSERT INTO symbols
                    (symbol_id, repo_id, file_id, name, qualified_name,
                     symbol_type, start_line, end_line)
                VALUES
                    (:symbol_id, :repo_id, :file_id, 'Parent', 'Parent', 'class', 1, 5)
                """
            ),
            {
                "symbol_id": parent_symbol_id,
                "repo_id": target_repo_id,
                "file_id": target_file_id,
            },
        )
        session.execute(
            text(
                """
                INSERT INTO symbols
                    (symbol_id, repo_id, file_id, name, qualified_name,
                     symbol_type, start_line, end_line, parent_symbol_id)
                VALUES
                    (:symbol_id, :repo_id, :file_id, 'child', 'Parent.child',
                     'method', 2, 4, :parent_symbol_id)
                """
            ),
            {
                "symbol_id": child_symbol_id,
                "repo_id": target_repo_id,
                "file_id": target_file_id,
                "parent_symbol_id": parent_symbol_id,
            },
        )
        session.execute(
            text(
                """
                INSERT INTO symbols
                    (symbol_id, repo_id, file_id, name, qualified_name,
                     symbol_type, start_line, end_line)
                VALUES
                    (:symbol_id, :repo_id, :file_id, 'keep_me', 'keep_me',
                     'function', 1, 1)
                """
            ),
            {
                "symbol_id": other_symbol_id,
                "repo_id": other_repo_id,
                "file_id": other_file_id,
            },
        )

    yield {
        "target_repo_id": target_repo_id,
        "other_repo_id": other_repo_id,
        "other_symbol_id": other_symbol_id,
    }

    with get_session() as session:
        session.execute(
            text("DELETE FROM repositories WHERE repo_id = :repo_id"),
            {"repo_id": target_repo_id},
        )
        session.execute(
            text("DELETE FROM repositories WHERE repo_id = :repo_id"),
            {"repo_id": other_repo_id},
        )


def test_purge_repository_index_removes_target_symbols_but_not_unrelated_repo(
    paired_symbol_repositories,
) -> None:
    from synsc.database.connection import get_session

    service = IndexingService()
    target_repo_id = paired_symbol_repositories["target_repo_id"]
    other_repo_id = paired_symbol_repositories["other_repo_id"]
    other_symbol_id = paired_symbol_repositories["other_symbol_id"]

    with get_session() as session:
        service._purge_repository_index(session, target_repo_id)

        target_symbols = session.execute(
            text("SELECT COUNT(*) FROM symbols WHERE repo_id = :repo_id"),
            {"repo_id": target_repo_id},
        ).scalar_one()
        target_files = session.execute(
            text("SELECT COUNT(*) FROM repository_files WHERE repo_id = :repo_id"),
            {"repo_id": target_repo_id},
        ).scalar_one()
        other_symbols = session.execute(
            text("SELECT COUNT(*) FROM symbols WHERE repo_id = :repo_id"),
            {"repo_id": other_repo_id},
        ).scalar_one()
        surviving_symbol = session.execute(
            text("SELECT symbol_id FROM symbols WHERE symbol_id = :symbol_id"),
            {"symbol_id": other_symbol_id},
        ).scalar_one_or_none()
        target_repo_row = session.execute(
            text("SELECT repo_id FROM repositories WHERE repo_id = :repo_id"),
            {"repo_id": target_repo_id},
        ).scalar_one_or_none()

    assert target_symbols == 0
    assert target_files == 0
    assert other_symbols == 1
    assert str(surviving_symbol) == other_symbol_id
    assert str(target_repo_row) == target_repo_id
