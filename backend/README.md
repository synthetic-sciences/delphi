# Delphi — Backend

Python backend for Delphi (synsc-context). This directory is the Python project root — all `uv` commands run here.

See the main [README](../README.md) for user-facing docs and [docs/architecture.md](../docs/architecture.md) for the full architecture walkthrough.

## Quick commands

```bash
uv sync                               # install deps
uv run synsc-context-http             # run API server (port 8742)
uv run synsc-context-worker           # run background indexer
uv run pytest                         # run tests
uv run alembic upgrade head           # apply migrations
uv run ruff check synsc/ tests/       # lint
uv run mypy synsc/                    # type-check
```

## Entry points

| Command | Target |
|---|---|
| `synsc-context` | `synsc.cli:main` |
| `synsc-context-http` | `synsc.api.http_server:run_http_server` |
| `synsc-context-mcp` | `synsc.api.mcp_server:run_server` |
| `synsc-context-proxy` | `synsc.mcp_stdio_proxy:main` |
| `synsc-context-worker` | `synsc.workers.indexing_worker:run_worker` |
