"""Schema contracts for durable asynchronous research jobs."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from synsc.database.connection import EXPECTED_ALEMBIC_REVISION
from synsc.database.models import ResearchEventRecord, ResearchJob, ResearchMessage

BACKEND_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
MIGRATION = BACKEND_ROOT / "alembic" / "versions" / "016_durable_research_jobs.py"
SETUP_SQL = PROJECT_ROOT / "database" / "supabase" / "setup_local.sql"


def _load_migration(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_durable_research_models_use_distinct_tables() -> None:
    assert ResearchJob.__tablename__ == "research_jobs"
    assert ResearchEventRecord.__tablename__ == "research_events"
    assert ResearchMessage.__tablename__ == "research_messages"

    for column in (
        "auto_index",
        "auto_indexed",
        "usage",
        "worker_id",
        "attempt_count",
        "max_attempts",
        "started_at",
        "updated_at",
    ):
        assert column in ResearchJob.__table__.columns


def test_durable_research_migration_is_current_head() -> None:
    migration = _load_migration(MIGRATION, "durable_research_jobs_migration")

    assert migration.revision == "016_durable_research_jobs"
    assert migration.down_revision == "015_snapshot_search"
    assert migration.revision == EXPECTED_ALEMBIC_REVISION

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    assert ScriptDirectory.from_config(config).get_current_head() == migration.revision


def test_durable_research_migration_builds_queue_and_event_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration(MIGRATION, "durable_research_jobs_migration_sql")
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    sql = " ".join("\n".join(statements).split())
    assert "ALTER TABLE research_jobs" in sql
    assert "CREATE TABLE IF NOT EXISTS research_events" in sql
    assert "CREATE TABLE IF NOT EXISTS research_messages" in sql
    assert "UNIQUE (job_id, seq)" in sql
    assert "ON DELETE CASCADE" in sql
    assert "cancelling" in sql
    assert "cancelled" in sql
    assert "attempt_count" in sql
    assert "max_attempts" in sql
    assert "worker_id" in sql
    assert "FOR UPDATE" not in sql


def test_durable_research_downgrade_normalizes_cancellation_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration(
        MIGRATION,
        "durable_research_jobs_downgrade_sql",
    )
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.downgrade()

    sql = " ".join("\n".join(statements).split())
    normalize = sql.index("UPDATE research_jobs")
    old_constraint = sql.index("status IN ('pending', 'running', 'completed', 'failed')")
    assert "status IN ('cancelling', 'cancelled')" in sql
    assert normalize < old_constraint


def test_bootstrap_sql_contains_durable_research_schema() -> None:
    sql = SETUP_SQL.read_text()

    assert "CREATE TABLE IF NOT EXISTS research_jobs" in sql
    assert "CREATE TABLE IF NOT EXISTS research_events" in sql
    assert "CREATE TABLE IF NOT EXISTS research_messages" in sql
    assert "UNIQUE (job_id, seq)" in sql
    assert "idx_research_jobs_claim" in sql
    assert "idx_research_events_job_seq" in sql
    assert "idx_research_messages_job_created" in sql
