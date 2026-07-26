"""Contracts for the repository's required GitHub Actions checks."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
PINNED_ACTION = re.compile(r"^[^@]+@[0-9a-f]{40}$")


def _workflow() -> dict:
    assert WORKFLOW_PATH.is_file(), "missing .github/workflows/ci.yml"
    return yaml.load(WORKFLOW_PATH.read_text(), Loader=yaml.BaseLoader)


def _run_commands(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"] if "run" in step)


def test_ci_has_safe_triggers_permissions_and_concurrency() -> None:
    workflow = _workflow()

    assert set(workflow["on"]) == {"pull_request", "push"}
    assert workflow["on"]["push"]["branches"] == ["master"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] == "true"


def test_ci_covers_every_shippable_surface() -> None:
    jobs = _workflow()["jobs"]

    assert set(jobs) == {
        "backend",
        "postgres",
        "mcp-proxy",
        "cli",
        "frontend",
        "landing",
    }
    for job in jobs.values():
        assert int(job["timeout-minutes"]) <= 30


def test_ci_pins_third_party_actions_by_commit() -> None:
    for job in _workflow()["jobs"].values():
        for step in job["steps"]:
            if action := step.get("uses"):
                assert PINNED_ACTION.fullmatch(action), action


def test_backend_and_postgres_jobs_enforce_locked_migrations_and_tests() -> None:
    jobs = _workflow()["jobs"]
    backend = _run_commands(jobs["backend"])
    postgres = _run_commands(jobs["postgres"])

    assert "uv sync --locked --extra dev" in backend
    assert "uv run pytest -q" in backend
    assert re.fullmatch(
        r"pgvector/pgvector:0\.8\.2-pg16-bookworm@sha256:[0-9a-f]{64}",
        jobs["postgres"]["services"]["postgres"]["image"],
    )
    assert "psql -v ON_ERROR_STOP=1" in postgres
    assert "database/supabase/setup_local.sql" in postgres
    assert "uv run alembic upgrade head" in postgres
    assert "test_atomic_reindex_postgres.py" in postgres
    assert "test_job_queue_postgres.py" in postgres


def test_package_and_frontend_jobs_use_reproducible_checks() -> None:
    jobs = _workflow()["jobs"]
    proxy = _run_commands(jobs["mcp-proxy"])
    cli = _run_commands(jobs["cli"])
    frontend = _run_commands(jobs["frontend"])
    landing = _run_commands(jobs["landing"])

    assert "uv sync --locked --group dev" in proxy
    assert "uv run pytest -q" in proxy
    assert "uv build" in proxy

    assert "npm ci" in cli
    assert "npm test" in cli
    assert "npm audit --audit-level=low" in cli
    assert "npm pack --dry-run" in cli

    assert "npm ci" in frontend
    assert "npm run lint" in frontend
    assert "npm audit --audit-level=low" in frontend
    assert "npm run build" in frontend

    assert "pnpm install --frozen-lockfile" in landing
    assert "pnpm audit --prod" in landing
    assert "pnpm build" in landing
    assert "/_next/image" in landing
