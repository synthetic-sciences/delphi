"""Contracts that prevent services from starting on a stale schema."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import ProgrammingError

from synsc.database.connection import (
    EXPECTED_ALEMBIC_REVISION,
    _verify_migration_revision,
)

BACKEND_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent


def test_expected_revision_matches_alembic_head() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(BACKEND_ROOT / "alembic"),
    )

    assert ScriptDirectory.from_config(config).get_current_head() == (EXPECTED_ALEMBIC_REVISION)


def test_migration_guard_accepts_current_revision() -> None:
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [(EXPECTED_ALEMBIC_REVISION,)]

    _verify_migration_revision(connection)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [("012_user_research_credentials",)],
        [(EXPECTED_ALEMBIC_REVISION,), ("unexpected_parallel_head",)],
    ],
)
def test_migration_guard_rejects_missing_stale_or_multiple_revisions(
    rows: list[tuple[str]],
) -> None:
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = rows

    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        _verify_migration_revision(connection)


def test_migration_guard_rejects_missing_version_table() -> None:
    connection = Mock()
    connection.execute.side_effect = ProgrammingError(
        "SELECT version_num FROM alembic_version",
        {},
        Exception("relation does not exist"),
    )

    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        _verify_migration_revision(connection)


def test_local_launcher_fails_closed_on_database_setup() -> None:
    launcher = (PROJECT_ROOT / "scripts" / "launch_app.sh").read_text()

    assert "trap cleanup EXIT INT TERM" not in launcher
    assert "trap cleanup EXIT" in launcher
    assert "Migrations failed or skipped. Continuing" not in launcher
    assert '(cd "$BACKEND_DIR" && uv run alembic upgrade head)' in launcher
    assert "DATABASE_URL_WAS_SET" in launcher
    assert 'make_url(os.environ["DATABASE_URL"])' in launcher
    assert 'pg_isready -h "$DATABASE_READY_HOST" -p "$DATABASE_READY_PORT"' in launcher
    assert '[ "$DATABASE_URL_WAS_SET" = false ]' in launcher
    assert "PostgreSQL did not become ready" in launcher


def test_example_env_derives_a_context_appropriate_database_url() -> None:
    env_example = (PROJECT_ROOT / "env.example").read_text()

    assert "DATABASE_URL=\n" in env_example
    assert "<auto>" not in env_example


def test_worker_waits_for_migrated_healthy_api() -> None:
    compose = yaml.load(
        (PROJECT_ROOT / "docker-compose.yml").read_text(),
        Loader=yaml.BaseLoader,
    )

    assert compose["services"]["worker"]["depends_on"]["api"] == {"condition": "service_healthy"}

    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text()
    worker_stage = dockerfile.split("FROM runtime AS worker", maxsplit=1)[1]
    assert "alembic upgrade head && synsc-context worker" in worker_stage
