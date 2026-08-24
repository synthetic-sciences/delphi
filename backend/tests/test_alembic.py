"""Tests for Alembic migration setup."""

import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from synsc.database.connection import EXPECTED_ALEMBIC_REVISION

PROJECT_ROOT = Path(__file__).parent.parent


def test_alembic_ini_exists():
    """alembic.ini should exist at project root."""
    assert (PROJECT_ROOT / "alembic.ini").is_file()


def test_alembic_env_exists():
    """alembic/env.py should exist."""
    assert (PROJECT_ROOT / "alembic" / "env.py").is_file()


def test_alembic_versions_dir_exists():
    """alembic/versions/ directory should exist."""
    assert (PROJECT_ROOT / "alembic" / "versions").is_dir()


def test_initial_migration_exists():
    """Initial migration script should exist."""
    versions_dir = PROJECT_ROOT / "alembic" / "versions"
    migration_files = list(versions_dir.glob("001_*.py"))
    assert len(migration_files) == 1, f"Expected 1 initial migration, found {len(migration_files)}"


def test_alembic_env_imports_base():
    """alembic/env.py should import Base from synsc models."""
    env_py = (PROJECT_ROOT / "alembic" / "env.py").read_text()
    assert "from synsc.database.models import Base" in env_py


def test_alembic_env_uses_application_database_config():
    """Alembic should honor both DATABASE_URL and POSTGRES_* configuration."""
    env_py = (PROJECT_ROOT / "alembic" / "env.py").read_text()
    assert "SynscConfig.from_env().get_database_url()" in env_py


def test_database_url_takes_precedence_for_migrations(monkeypatch):
    """The shared config should preserve an explicit DATABASE_URL."""
    from synsc.config import SynscConfig

    monkeypatch.setenv("DATABASE_URL", "postgresql://explicit.example/delphi")
    monkeypatch.setenv("POSTGRES_HOST", "ignored.example")

    assert SynscConfig.from_env().get_database_url() == "postgresql://explicit.example/delphi"


def test_database_url_can_be_derived_for_migrations(monkeypatch):
    """POSTGRES_* remains a supported alternative to DATABASE_URL."""
    from synsc.config import SynscConfig

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_USER", "delphi")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("POSTGRES_DB", "context")

    assert (
        SynscConfig.from_env().get_database_url()
        == "postgresql://delphi:secret@db.internal:6543/context"
    )


def test_initial_migration_is_idempotent():
    """Initial migration should check for existing tables before creating."""
    migration_file = next((PROJECT_ROOT / "alembic" / "versions").glob("001_*.py"))
    content = migration_file.read_text()
    # Should check if tables already exist
    assert "repositories" in content
    assert "already_exists" in content or "EXISTS" in content


def test_initial_migration_revision_id():
    """Initial migration should have a valid revision ID."""
    migration_file = next((PROJECT_ROOT / "alembic" / "versions").glob("001_*.py"))
    content = migration_file.read_text()
    assert "revision" in content
    assert "down_revision" in content


def test_script_mako_template_exists():
    """Alembic template for new migrations should exist."""
    assert (PROJECT_ROOT / "alembic" / "script.py.mako").is_file()


def test_research_jobs_migration_exists():
    """research_jobs migration script should exist and chain off 001_initial."""
    migration_file = next((PROJECT_ROOT / "alembic" / "versions").glob("002_research_jobs.py"))
    content = migration_file.read_text()
    assert 'revision: str = "002_research_jobs"' in content
    assert 'down_revision: Union[str, None] = "001_initial"' in content
    assert "create_table" in content
    assert "research_jobs" in content
    assert "drop_table" in content  # downgrade is wired


def test_file_okapi_compact_migration_chains_after_symbol_parent_index():
    compact_path = PROJECT_ROOT / "alembic" / "versions" / "021_file_okapi_compact.py"
    assert compact_path.is_file()
    compact_content = compact_path.read_text()
    assert 'revision: str = "021_file_okapi_compact"' in compact_content
    assert 'down_revision: Union[str, None] = "020_symbol_parent_index"' in compact_content

    head_path = PROJECT_ROOT / "alembic" / "versions" / "020_symbol_parent_index.py"
    head_content = head_path.read_text()
    assert 'revision: str = "020_symbol_parent_index"' in head_content
    assert 'down_revision: Union[str, None] = "019_file_okapi"' in head_content
    assert EXPECTED_ALEMBIC_REVISION == "022_file_okapi_repo_scope_index"


def test_file_okapi_migration_defines_persistent_schema():
    path = PROJECT_ROOT / "alembic" / "versions" / "019_file_okapi.py"
    content = " ".join(path.read_text().split())

    assert "ADD COLUMN IF NOT EXISTS file_okapi_index_version VARCHAR(32)" in content
    assert (
        "ADD COLUMN IF NOT EXISTS file_okapi_documents_count "
        "INTEGER NOT NULL DEFAULT 0"
    ) in content
    assert "CREATE TABLE IF NOT EXISTS repository_file_lexical_documents" in content
    assert "CREATE TABLE IF NOT EXISTS repository_file_lexical_terms" in content
    assert (
        "file_id UUID PRIMARY KEY REFERENCES repository_files(file_id) "
        "ON DELETE CASCADE"
    ) in content
    assert content.count(
        "repo_id UUID NOT NULL REFERENCES repositories(repo_id) "
        "ON DELETE CASCADE"
    ) == 2
    assert (
        "file_id UUID NOT NULL REFERENCES repository_files(file_id) "
        "ON DELETE CASCADE"
    ) in content
    assert (
        "CREATE INDEX IF NOT EXISTS idx_file_lexical_terms_scope "
        "ON repository_file_lexical_terms (repo_id, term, file_id)"
    ) in content


def test_alembic_config_importable():
    """Alembic configuration should be loadable."""
    from alembic.config import Config

    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    assert alembic_cfg.get_main_option("script_location") == "alembic"


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
def test_file_okapi_migration_applies_uuid_foreign_keys() -> None:
    """Regression: 019 must apply on UUID repository_files/repos schemas."""
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

    try:
        command.downgrade(cfg, "018_context_sessions")
        command.upgrade(cfg, "019_file_okapi")

        engine = create_engine(os.environ["DATABASE_URL"])
        with engine.connect() as conn:
            file_id_type = conn.execute(
                text(
                    """
                    SELECT data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'repository_file_lexical_documents'
                      AND column_name = 'file_id'
                    """
                )
            ).scalar_one()
            assert file_id_type == "uuid"
    finally:
        command.upgrade(cfg, "head")
