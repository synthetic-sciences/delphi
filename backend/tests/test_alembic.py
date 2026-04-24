"""Tests for Alembic migration setup."""

import os
from pathlib import Path


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


def test_alembic_env_reads_database_url():
    """alembic/env.py should read DATABASE_URL from environment."""
    env_py = (PROJECT_ROOT / "alembic" / "env.py").read_text()
    assert 'os.getenv("DATABASE_URL")' in env_py


def test_initial_migration_is_idempotent():
    """Initial migration should check for existing tables before creating."""
    migration_file = next(
        (PROJECT_ROOT / "alembic" / "versions").glob("001_*.py")
    )
    content = migration_file.read_text()
    # Should check if tables already exist
    assert "repositories" in content
    assert "already_exists" in content or "EXISTS" in content


def test_initial_migration_revision_id():
    """Initial migration should have a valid revision ID."""
    migration_file = next(
        (PROJECT_ROOT / "alembic" / "versions").glob("001_*.py")
    )
    content = migration_file.read_text()
    assert 'revision' in content
    assert 'down_revision' in content


def test_script_mako_template_exists():
    """Alembic template for new migrations should exist."""
    assert (PROJECT_ROOT / "alembic" / "script.py.mako").is_file()


def test_alembic_config_importable():
    """Alembic configuration should be loadable."""
    from alembic.config import Config

    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    assert alembic_cfg.get_main_option("script_location") == "alembic"
