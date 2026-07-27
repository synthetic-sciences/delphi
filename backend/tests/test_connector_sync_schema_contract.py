"""Schema contracts for durable incremental connector synchronization."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from synsc.database.connection import EXPECTED_ALEMBIC_REVISION
from synsc.database.models import (
    ConnectorRecordAccess,
    ConnectorSource,
    ConnectorSyncJob,
    UserConnectorSource,
)
from synsc.snapshots.contracts import SnapshotSourceType

BACKEND_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
MIGRATION = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "017_connector_sync.py"
)
SETUP_SQL = PROJECT_ROOT / "database" / "supabase" / "setup_local.sql"


def _load_migration(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_connector_models_and_snapshot_type_are_registered() -> None:
    assert ConnectorSource.__tablename__ == "connector_sources"
    assert ConnectorRecordAccess.__tablename__ == "connector_record_access"
    assert UserConnectorSource.__tablename__ == "user_connector_sources"
    assert ConnectorSyncJob.__tablename__ == "connector_sync_jobs"
    assert SnapshotSourceType.CONNECTOR.value == "connector"
    for column in (
        "encrypted_config",
        "encrypted_cursor",
        "schedule_seconds",
        "next_sync_at",
        "last_snapshot_id",
    ):
        assert column in ConnectorSource.__table__.columns
    for column in (
        "worker_id",
        "attempt_count",
        "max_attempts",
        "lease_expires_at",
    ):
        assert column in ConnectorSyncJob.__table__.columns


def test_connector_migration_is_current_head() -> None:
    migration = _load_migration(MIGRATION, "connector_sync_migration")
    assert migration.revision == "017_connector_sync"
    assert migration.down_revision == "016_durable_research_jobs"
    assert migration.revision == EXPECTED_ALEMBIC_REVISION

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    assert ScriptDirectory.from_config(config).get_current_head() == migration.revision


def test_connector_migration_builds_queue_and_expands_snapshot_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration(MIGRATION, "connector_sync_migration_sql")
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    sql = " ".join("\n".join(statements).split())
    assert "CREATE TABLE IF NOT EXISTS connector_sources" in sql
    assert "CREATE TABLE IF NOT EXISTS connector_record_access" in sql
    assert "CREATE TABLE IF NOT EXISTS connector_sync_jobs" in sql
    assert "CREATE TABLE IF NOT EXISTS user_connector_sources" in sql
    assert "encrypted_config" in sql
    assert "encrypted_cursor" in sql
    assert "FOR UPDATE" not in sql
    assert "WHERE status IN ('pending', 'running')" in sql
    assert "source_type IN ('repo', 'paper', 'dataset', 'docs', 'connector')" in sql


def test_bootstrap_sql_contains_connector_sync_schema() -> None:
    sql = " ".join(SETUP_SQL.read_text().split())
    assert "CREATE TABLE IF NOT EXISTS connector_sources" in sql
    assert "CREATE TABLE IF NOT EXISTS connector_record_access" in sql
    assert "CREATE TABLE IF NOT EXISTS connector_sync_jobs" in sql
    assert "CREATE TABLE IF NOT EXISTS user_connector_sources" in sql
    assert "idx_connector_sources_due" in sql
    assert "uq_connector_sync_jobs_active_source" in sql
    assert (
        "source_type IN ('repo', 'paper', 'dataset', 'docs', 'connector')"
        in sql
    )
