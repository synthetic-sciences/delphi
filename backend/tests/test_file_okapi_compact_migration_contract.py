"""Schema contracts and round-trip tests for compact file Okapi storage."""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from alembic import command
from synsc.database.connection import EXPECTED_ALEMBIC_REVISION

BACKEND_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
MIGRATION = BACKEND_ROOT / "alembic" / "versions" / "021_file_okapi_compact.py"
SETUP_SQL = PROJECT_ROOT / "database" / "supabase" / "setup_local.sql"


def _load_migration(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_file_okapi_compact_migration_chains_after_symbol_parent_index() -> None:
    migration = _load_migration(MIGRATION, "file_okapi_compact_migration")
    assert migration.revision == "021_file_okapi_compact"
    assert migration.down_revision == "020_symbol_parent_index"

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    assert ScriptDirectory.from_config(config).get_current_head() == (
        EXPECTED_ALEMBIC_REVISION
    )


def test_file_okapi_compact_migration_defines_jsonb_schema() -> None:
    content = " ".join(Path(MIGRATION).read_text().split())
    assert "term_frequencies JSONB" in content
    assert "jsonb_object_agg(term, term_frequency ORDER BY term)" in content
    assert "idx_file_lexical_term_keys" in content
    assert "USING GIN (term_frequencies)" in content
    assert "DROP TABLE IF EXISTS repository_file_lexical_terms" in content
    assert "jsonb_each_text" in content


def test_bootstrap_sql_uses_compact_lexical_documents_only() -> None:
    sql = SETUP_SQL.read_text()
    assert "term_frequencies JSONB NOT NULL" in sql
    assert "idx_file_lexical_term_keys" in sql
    assert "repository_file_lexical_terms" not in sql


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


def _seed_row_per_term_fixture(conn, *, repo_id: str, file_id: str) -> None:
    conn.execute(
        text(
            """
            INSERT INTO repositories
                (repo_id, url, owner, name, branch, commit_sha, is_public)
            VALUES
                (:repo_id, :url, 'acme', 'compact', 'main', 'sha-1', true)
            """
        ),
        {
            "repo_id": repo_id,
            "url": f"https://github.com/acme/compact-{repo_id[:8]}",
        },
    )
    conn.execute(
        text(
            """
            INSERT INTO repository_files
                (file_id, repo_id, file_path, file_name, content_hash)
            VALUES
                (:file_id, :repo_id, 'src/example.py', 'example.py', 'hash-1')
            """
        ),
        {"file_id": file_id, "repo_id": repo_id},
    )
    conn.execute(
        text(
            """
            INSERT INTO repository_file_lexical_documents
                (file_id, repo_id, document_length, content_hash, index_version)
            VALUES
                (:file_id, :repo_id, 6, 'hash-1', 'v1')
            """
        ),
        {"file_id": file_id, "repo_id": repo_id},
    )
    conn.execute(
        text(
            """
            INSERT INTO repository_file_lexical_terms
                (file_id, repo_id, term, term_frequency)
            VALUES
                (:file_id, :repo_id, 'alpha', 2),
                (:file_id, :repo_id, 'beta', 1),
                (:file_id, :repo_id, 'gamma', 3)
            """
        ),
        {"file_id": file_id, "repo_id": repo_id},
    )
    conn.commit()


def _fetch_term_tuples(conn) -> set[tuple[str, str, int]]:
    rows = conn.execute(
        text(
            """
            SELECT d.file_id::text, kv.key, (kv.value)::text::integer
            FROM repository_file_lexical_documents d,
                 jsonb_each_text(d.term_frequencies) AS kv(key, value)
            ORDER BY d.file_id, kv.key
            """
        )
    ).fetchall()
    return {(file_id, term, frequency) for file_id, term, frequency in rows}


@pytest.mark.skipif(
    not _postgres_reachable(),
    reason="No real Postgres at DATABASE_URL — skipping migration apply test.",
)
def test_file_okapi_compact_migration_round_trip_preserves_term_tuples() -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

    repo_id = str(uuid.uuid4())
    file_id = str(uuid.uuid4())
    engine = create_engine(os.environ["DATABASE_URL"])

    try:
        command.downgrade(cfg, "020_symbol_parent_index")
        with engine.begin() as conn:
            _seed_row_per_term_fixture(conn, repo_id=repo_id, file_id=file_id)

        command.upgrade(cfg, "021_file_okapi_compact")
        with engine.connect() as conn:
            assert conn.execute(
                text(
                    """
                    SELECT to_regclass('public.repository_file_lexical_terms')
                    """
                )
            ).scalar_one() is None
            compact_tuples = _fetch_term_tuples(conn)
            assert compact_tuples == {
                (file_id, "alpha", 2),
                (file_id, "beta", 1),
                (file_id, "gamma", 3),
            }
            index_names = {
                row[0]
                for row in conn.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND tablename = 'repository_file_lexical_documents'
                        """
                    )
                )
            }
            assert "idx_file_lexical_term_keys" in index_names

        command.downgrade(cfg, "020_symbol_parent_index")
        with engine.connect() as conn:
            assert conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM repository_file_lexical_terms
                    WHERE file_id = :file_id
                    """
                ),
                {"file_id": file_id},
            ).scalar_one() == 3
            restored = {
                (str(row.file_id), row.term, row.term_frequency)
                for row in conn.execute(
                    text(
                        """
                        SELECT file_id, term, term_frequency
                        FROM repository_file_lexical_terms
                        WHERE file_id = :file_id
                        ORDER BY term
                        """
                    ),
                    {"file_id": file_id},
                )
            }
            assert restored == {
                (file_id, "alpha", 2),
                (file_id, "beta", 1),
                (file_id, "gamma", 3),
            }
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM repositories WHERE repo_id = :repo_id"),
                {"repo_id": repo_id},
            )
        command.upgrade(cfg, "head")
