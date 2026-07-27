"""Schema contracts for immutable context sessions and revisions."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from synsc.database.connection import EXPECTED_ALEMBIC_REVISION
from synsc.database.models import ContextRevision, ContextSession

BACKEND_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
MIGRATION = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "018_context_sessions.py"
)
SETUP_SQL = PROJECT_ROOT / "database" / "supabase" / "setup_local.sql"


def _load_migration(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_context_session_models_are_registered() -> None:
    assert ContextSession.__tablename__ == "context_sessions"
    assert ContextRevision.__tablename__ == "context_revisions"
    for column in (
        "sharing_policy",
        "expires_at",
        "parent_session_id",
        "parent_revision_id",
        "current_revision_id",
        "current_revision",
    ):
        assert column in ContextSession.__table__.columns
    for column in (
        "revision_number",
        "token_budget",
        "tokens_used",
        "state",
        "pinned_snapshots",
        "context_manifest",
        "content_hash",
    ):
        assert column in ContextRevision.__table__.columns


def test_context_session_migration_is_current_head() -> None:
    migration = _load_migration(MIGRATION, "context_session_migration")
    assert migration.revision == "018_context_sessions"
    assert migration.down_revision == "017_connector_sync"
    assert migration.revision == EXPECTED_ALEMBIC_REVISION

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    assert ScriptDirectory.from_config(config).get_current_head() == (
        migration.revision
    )


def test_context_migration_builds_revision_and_immutability_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration(
        MIGRATION,
        "context_session_migration_sql",
    )
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    sql = " ".join("\n".join(statements).split())
    assert "CREATE TABLE IF NOT EXISTS context_sessions" in sql
    assert "CREATE TABLE IF NOT EXISTS context_revisions" in sql
    assert "UNIQUE (session_id, revision_number)" in sql
    assert "prevent_context_revision_update" in sql
    assert "current_revision_id" in sql
    assert "sharing_policy IN ('private', 'shared')" in sql


def test_bootstrap_sql_contains_context_session_schema() -> None:
    sql = " ".join(SETUP_SQL.read_text().split())
    assert "CREATE TABLE IF NOT EXISTS context_sessions" in sql
    assert "CREATE TABLE IF NOT EXISTS context_revisions" in sql
    assert "prevent_context_revision_update" in sql
    assert "idx_context_sessions_user" in sql
