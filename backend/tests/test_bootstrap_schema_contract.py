"""Contract tests for the SQL bootstrap and visibility migration."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

BACKEND_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
SETUP_SQL = PROJECT_ROOT / "database" / "supabase" / "setup_local.sql"
VISIBILITY_MIGRATION = BACKEND_ROOT / "alembic" / "versions" / "008_source_visibility.py"
VISIBILITY_RECONCILIATION = BACKEND_ROOT / "alembic" / "versions" / "013_visibility_contracts.py"


def _create_table_body(sql: str, table: str) -> str:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\n\);",
        sql,
        flags=re.DOTALL,
    )
    assert match is not None, f"missing CREATE TABLE statement for {table}"
    return match.group(1)


@pytest.mark.parametrize(
    ("table", "default"),
    [
        ("repositories", "public"),
        ("papers", "private"),
        ("datasets", "public"),
    ],
)
def test_bootstrap_source_visibility_defaults(table: str, default: str) -> None:
    sql = SETUP_SQL.read_text()
    body = _create_table_body(sql, table)

    assert re.search(
        rf"visibility\s+VARCHAR\(16\)\s+NOT NULL\s+DEFAULT\s+'{default}'",
        body,
        flags=re.IGNORECASE,
    )
    assert (f"CREATE INDEX IF NOT EXISTS idx_{table}_visibility ON {table}(visibility);") in sql
    assert (f"ALTER TABLE {table}\n    ADD COLUMN IF NOT EXISTS visibility VARCHAR(16);") in sql
    assert (
        f"UPDATE {table}\n"
        "SET visibility = CASE WHEN is_public THEN 'public' ELSE 'private' END\n"
        "WHERE visibility IS NULL;"
    ) in sql
    assert (
        f"ALTER TABLE {table}\n"
        f"    ALTER COLUMN visibility SET DEFAULT '{default}',\n"
        "    ALTER COLUMN visibility SET NOT NULL;"
    ) in sql


def _load_migration(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_visibility_upgrade_uses_source_specific_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration(
        VISIBILITY_MIGRATION,
        "source_visibility_migration",
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        migration,
        "_add_visibility",
        lambda table, default: calls.append((table, default)),
    )

    migration.upgrade()

    assert calls == [
        ("repositories", "public"),
        ("papers", "private"),
        ("documentation_sources", "public"),
        ("datasets", "public"),
    ]


def test_visibility_migration_is_idempotent_and_preserves_existing_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration(
        VISIBILITY_MIGRATION,
        "source_visibility_migration",
    )
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration._add_visibility("papers", "private")

    sql = "\n".join(statements)
    assert "ADD COLUMN IF NOT EXISTS visibility VARCHAR(16)" in sql
    assert "WHERE visibility IS NULL" in sql
    assert "ALTER COLUMN visibility SET DEFAULT 'private'" in sql
    assert "ALTER COLUMN visibility SET NOT NULL" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_papers_visibility" in sql


def test_visibility_reconciliation_follows_current_head() -> None:
    migration = _load_migration(
        VISIBILITY_RECONCILIATION,
        "visibility_contracts_migration",
    )

    assert migration.revision == "013_visibility_contracts"
    assert migration.down_revision == "012_user_research_credentials"


def test_bootstrap_reconciles_released_paper_default() -> None:
    sql = SETUP_SQL.read_text()

    assert (
        "UPDATE papers\n"
        "SET visibility = 'private'\n"
        "WHERE visibility = 'public' AND is_public IS NOT TRUE;"
    ) in sql


def test_visibility_reconciliation_repairs_old_paper_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration(
        VISIBILITY_RECONCILIATION,
        "visibility_contracts_migration",
    )
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration.upgrade()

    sql = "\n".join(statements)
    assert (
        "UPDATE papers SET visibility = 'private' "
        "WHERE visibility = 'public' AND is_public IS NOT TRUE"
    ) in sql
    assert ("ALTER TABLE papers ALTER COLUMN visibility SET DEFAULT 'private'") in sql
    for table in (
        "repositories",
        "papers",
        "documentation_sources",
        "datasets",
    ):
        assert (f"CREATE INDEX IF NOT EXISTS idx_{table}_visibility ON {table}(visibility)") in sql
