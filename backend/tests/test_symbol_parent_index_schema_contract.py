"""Schema contracts for symbols.parent_symbol_id lookup index."""

from __future__ import annotations

import importlib.util
import os
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
MIGRATION = BACKEND_ROOT / "alembic" / "versions" / "020_symbol_parent_index.py"
SETUP_SQL = PROJECT_ROOT / "database" / "supabase" / "setup_local.sql"


def _load_migration(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_symbol_parent_index_migration_chains_after_file_okapi() -> None:
    migration = _load_migration(MIGRATION, "symbol_parent_index_migration")
    assert migration.revision == "020_symbol_parent_index"
    assert migration.down_revision == "019_file_okapi"

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    assert ScriptDirectory.from_config(config).get_current_head() == (
        EXPECTED_ALEMBIC_REVISION
    )


def test_symbol_parent_index_migration_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration(
        MIGRATION,
        "symbol_parent_index_migration_sql",
    )
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    sql = " ".join("\n".join(statements).split())
    assert (
        "CREATE INDEX IF NOT EXISTS idx_symbols_parent "
        "ON symbols (parent_symbol_id)"
    ) in sql

    downgrade_statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", downgrade_statements.append)
    migration.downgrade()
    assert "DROP INDEX IF EXISTS idx_symbols_parent" in downgrade_statements[0]


def test_bootstrap_sql_contains_symbol_parent_index() -> None:
    sql = SETUP_SQL.read_text()
    assert (
        "CREATE INDEX IF NOT EXISTS idx_symbols_parent ON symbols(parent_symbol_id)"
    ) in sql


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


@pytest.mark.skipif(
    not _postgres_reachable(),
    reason="No real Postgres at DATABASE_URL — skipping migration apply test.",
)
def test_symbol_parent_index_migration_applies_on_real_postgres() -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

    try:
        command.downgrade(cfg, "019_file_okapi")
        command.upgrade(cfg, "020_symbol_parent_index")

        engine = create_engine(os.environ["DATABASE_URL"])
        with engine.connect() as conn:
            index_names = {
                row[0]
                for row in conn.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND tablename = 'symbols'
                        """
                    )
                )
            }
            assert "idx_symbols_parent" in index_names
    finally:
        command.upgrade(cfg, "head")
