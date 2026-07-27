"""Schema contracts for immutable source snapshots."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from synsc.database.connection import EXPECTED_ALEMBIC_REVISION
from synsc.database.models import (
    DocumentationSource,
    Paper,
    SourceSnapshot,
    SourceSnapshotHead,
    SourceSnapshotItem,
    SourceSnapshotItemEmbedding,
)

BACKEND_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
MIGRATION = BACKEND_ROOT / "alembic" / "versions" / "014_source_snapshots.py"
SEARCH_MIGRATION = BACKEND_ROOT / "alembic" / "versions" / "015_snapshot_search.py"
SETUP_SQL = PROJECT_ROOT / "database" / "supabase" / "setup_local.sql"


def _load_migration(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_models_use_distinct_tables() -> None:
    assert SourceSnapshot.__tablename__ == "source_snapshots"
    assert SourceSnapshotHead.__tablename__ == "source_snapshot_heads"
    assert SourceSnapshotItem.__tablename__ == "source_snapshot_items"
    assert (
        SourceSnapshotItemEmbedding.__tablename__
        == "source_snapshot_item_embeddings"
    )
    assert "embedding_model" in Paper.__table__.columns
    assert "embedding_model" in DocumentationSource.__table__.columns


def test_snapshot_search_migration_is_current_head() -> None:
    migration = _load_migration(MIGRATION, "source_snapshot_migration")
    search_migration = _load_migration(
        SEARCH_MIGRATION,
        "source_snapshot_search_migration",
    )

    assert migration.revision == "014_source_snapshots"
    assert migration.down_revision == "013_visibility_contracts"
    assert search_migration.revision == "015_snapshot_search"
    assert search_migration.down_revision == migration.revision

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    assert (
        ScriptDirectory.from_config(config).get_current_head()
        == EXPECTED_ALEMBIC_REVISION
    )


def test_snapshot_migration_builds_append_only_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration(MIGRATION, "source_snapshot_migration_sql")
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    sql = "\n".join(statements)
    for table in (
        "source_snapshots",
        "source_snapshot_heads",
        "source_snapshot_items",
        "source_snapshot_item_embeddings",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "vector(768)" in sql
    assert "embedding_fingerprint" in sql
    assert "vectors_complete" in sql
    assert "sealed_at" in sql
    assert "prevent_source_snapshot_update" in sql
    assert "prevent_sealed_snapshot_item_change" in sql
    assert "BEFORE INSERT OR UPDATE OR DELETE" in sql
    for table in ("papers", "datasets", "documentation_sources"):
        assert f"ALTER TABLE {table}" in sql


def test_bootstrap_sql_contains_snapshot_schema() -> None:
    sql = SETUP_SQL.read_text()

    for table in (
        "source_snapshots",
        "source_snapshot_heads",
        "source_snapshot_items",
        "source_snapshot_item_embeddings",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "prevent_source_snapshot_update" in sql
    assert "prevent_sealed_snapshot_item_change" in sql
    assert "sealed_at" in sql
    assert "idx_source_snapshot_items_content_fts" in sql


def test_snapshot_search_migration_builds_matching_fts_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration(
        SEARCH_MIGRATION,
        "source_snapshot_search_migration_sql",
    )
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    sql = " ".join("\n".join(statements).split())
    bootstrap_sql = " ".join(SETUP_SQL.read_text().split())
    definition = (
        "CREATE INDEX IF NOT EXISTS idx_source_snapshot_items_content_fts "
        "ON source_snapshot_items USING GIN (to_tsvector('simple', content))"
    )
    assert definition in sql
    assert definition in bootstrap_sql


def test_snapshot_identity_constraint_matches_bootstrap() -> None:
    migration = _load_migration(
        MIGRATION,
        "source_snapshot_identity_migration",
    )
    statements: list[str] = []
    original_execute = migration.op.execute
    try:
        migration.op.execute = statements.append
        migration.upgrade()
    finally:
        migration.op.execute = original_execute

    identity = (
        "UNIQUE ( source_type, source_id, version, content_hash, "
        "embedding_model, embedding_fingerprint )"
    )
    migration_sql = " ".join("\n".join(statements).split())
    bootstrap_sql = " ".join(SETUP_SQL.read_text().split())

    assert identity in migration_sql
    assert identity in bootstrap_sql
