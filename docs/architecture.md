# Delphi — Architecture & Repository Guide

This document is a map of the repository for humans and LLMs. Read this before making changes: it tells you **what lives where**, **how the pieces connect**, and **the minimum set of files you need to touch for a given task**.

---

## Top-level layout

```
.
├── backend/              Python backend (FastAPI + MCP + Alembic + pytest)
├── frontend/             Next.js 14 dashboard (App Router, TypeScript, Tailwind)
├── packages/
│   └── mcp-proxy/        Thin stdio-to-HTTP MCP proxy (published to PyPI separately)
├── database/
│   └── supabase/         Local PostgreSQL init SQL (pgvector extension + schema)
├── scripts/              Developer scripts (launch_app.sh orchestrates the stack)
├── docs/                 Engineering docs (this file lives here)
├── docker-compose.yml    Local dev stack: postgres + api + worker + frontend
├── env.example           Environment variable template
├── .mcp.json             Local MCP client config (points at http://localhost:8742/mcp)
├── README.md             User-facing readme
├── LICENSE               Apache 2.0
└── UPSTREAM.txt          Upstream lineage notes
```

---

## Backend (`backend/`)

The backend is a single Python package named `synsc` (module name kept short on purpose — all imports are `from synsc.*`). The project root is `backend/`, i.e. `pyproject.toml` lives there.

```
backend/
├── pyproject.toml        Python deps + entry points (synsc-context, synsc-context-http, …)
├── uv.lock               Locked dependencies (uv)
├── alembic.ini           Alembic config (script_location = alembic)
├── alembic/
│   ├── env.py            Reads DATABASE_URL from env, imports Base from synsc.database.models
│   └── versions/001_initial_schema.py
├── Dockerfile            Two build targets: `api` (uvicorn) and `worker` (background indexer)
├── tests/                Pytest suite (conftest.py mocks DB + model load)
└── synsc/
    ├── __init__.py
    ├── main.py           Small entry helper
    ├── cli.py            Click CLI — `synsc-context` entrypoint
    ├── config.py         Central SynscConfig (reads env vars, singleton)
    ├── logging.py        Structlog setup
    ├── mcp_stdio_proxy.py Stdio MCP proxy that forwards to the HTTP server
    │
    ├── api/              HTTP + MCP servers
    │   ├── http_server.py  FastAPI app factory `create_app()` — main surface
    │   ├── mcp_server.py   MCP tool registry (tools call into services/)
    │   └── rate_limit.py   slowapi limiter config
    │
    ├── auth/
    │   ├── oauth.py        GitHub OAuth flow
    │   └── sessions.py     JWT session issuance / verification
    │
    ├── database/
    │   ├── connection.py   Engine/Session helpers, init_db()
    │   └── models.py       SQLAlchemy 2.0 declarative models (the single source of truth for the schema)
    │
    ├── embeddings/
    │   └── generator.py    sentence-transformers singleton (all-mpnet-base-v2 by default)
    │
    ├── core/               Domain-agnostic helpers
    │   ├── arxiv_client.py
    │   ├── chunker.py          Code chunker
    │   ├── paper_chunker.py    PDF chunker
    │   ├── context_enrichment.py
    │   ├── deduplicator.py
    │   ├── git_client.py       Dulwich-based clone/diff
    │   ├── huggingface_client.py
    │   ├── language_detector.py
    │   ├── pdf_processor.py    pymupdf wrappers
    │   └── text_processing.py
    │
    ├── extractors/         Pull structure out of source files (citations, equations, symbols)
    │   ├── base.py
    │   ├── citations.py
    │   ├── code_snippets.py
    │   └── equations.py
    │
    ├── parsing/            Tree-sitter AST walkers
    │   ├── registry.py     Language → parser map
    │   ├── python_parser.py
    │   └── typescript_parser.py
    │
    ├── indexing/           Vector store backends
    │   ├── faiss_manager.py      Optional FAISS local store
    │   ├── pgvector_manager.py   Default: pgvector in Postgres
    │   └── vector_store.py       Interface + selection
    │
    ├── services/           Business logic — the bulk of the code
    │   ├── indexing_service.py   Repo/paper/dataset ingestion orchestrator
    │   ├── analysis_service.py   Repository analysis, architecture summaries
    │   ├── search_service.py     Semantic search across all entity types
    │   ├── symbol_service.py     Function/class lookup
    │   ├── paper_service.py      Papers ingest + reports + comparison
    │   ├── dataset_service.py    HuggingFace dataset indexing
    │   ├── job_queue_service.py  Enqueue/claim jobs against indexing_jobs table
    │   ├── reranker.py           Optional cross-encoder reranker
    │   └── token_encryption.py   Fernet for OAuth tokens at rest
    │
    └── workers/
        └── indexing_worker.py    Background worker — pulls jobs from job_queue_service
```

### Entry points (declared in `backend/pyproject.toml`)

| Command | Target | Purpose |
|---|---|---|
| `synsc-context` | `synsc.cli:main` | CLI (index / search / worker subcommands) |
| `synsc-context-http` | `synsc.api.http_server:run_http_server` | FastAPI server (default port 8742) |
| `synsc-context-mcp` | `synsc.api.mcp_server:run_server` | Standalone MCP server (stdio) |
| `synsc-context-proxy` | `synsc.mcp_stdio_proxy:main` | Stdio-to-HTTP proxy for `uvx` users |
| `synsc-context-worker` | `synsc.workers.indexing_worker:run_worker` | Background job runner |

### Backend-internal dependency flow

```
  api/http_server.py ── calls ──▶ services/*
         │                           │
         │                           ├── indexing/*  (vector store)
         │                           ├── embeddings/generator.py
         │                           ├── extractors/*  + parsing/*
         │                           └── core/*  (git, pdf, text helpers)
         │
         └── uses ──▶ database/connection.py ──▶ database/models.py  ◀── alembic imports Base
         └── uses ──▶ auth/*
         └── uses ──▶ api/rate_limit.py
```

---

## Frontend (`frontend/`)

Next.js 14 App Router, TypeScript, Tailwind. Talks to the backend exclusively over HTTP. **No Prisma, no direct DB.**

```
frontend/
├── next.config.mjs       Dev rewrites: /config, /mcp, /auth/*, /v1/* → ${NEXT_PUBLIC_API_URL}
├── package.json
├── src/
│   ├── app/              App Router pages: activity/, admin/, api-keys/, auth/, datasets/,
│   │                     docs/, overview/, papers/, repositories/
│   ├── components/
│   ├── contexts/         React context (auth state)
│   └── lib/              API client helpers
└── public/
```

### Frontend ↔ Backend connection

- Dev: Next.js dev-server rewrites `/config`, `/auth/*`, `/v1/*`, `/mcp` to `NEXT_PUBLIC_API_URL` (default `http://localhost:8742`).
- Prod: the frontend calls the backend directly via `NEXT_PUBLIC_API_URL`.
- Auth: httpOnly cookies set by the backend at `/auth/login` / `/auth/github/callback`.

---

## Database (`database/supabase/`)

`setup_local.sql` — the canonical bootstrap script for local Postgres. Creates the `vector` extension and all tables (so a fresh DB can start without running Alembic). Alembic's initial migration is **idempotent**: it checks for the `repositories` table and no-ops if the SQL has already created it.

Mounted into the `postgres` container by `docker-compose.yml`:
```yaml
./database/supabase/setup_local.sql:/docker-entrypoint-initdb.d/01-setup.sql
```

`synsc.database.models` is the single source of truth for production schemas; `setup_local.sql` mirrors it for local bootstrap. **When you change a model, also update the SQL (or add an Alembic migration).**

---

## Packages (`packages/mcp-proxy/`)

A standalone Python package (`synsc-context-proxy` on PyPI) that provides a tiny stdio→HTTP bridge so AI tools that only speak stdio MCP can connect to a Delphi HTTP server. **Does not depend on the main `synsc` package** — it ships as its own wheel with `mcp[cli]` + `httpx` as deps.

---

## Scripts (`scripts/`)

### `scripts/launch_app.sh`

One-command dev launcher. Resolves `PROJECT_ROOT` from the script's location, then:

1. Loads `.env` from project root.
2. Runs `uv sync` inside `backend/` if `.venv` is missing.
3. Runs `npm install` inside `frontend/` if `node_modules` is missing.
4. Starts Postgres via `docker compose up -d postgres` if not already running locally.
5. Starts:
   - API server — `cd backend && uv run synsc-context-http`
   - Worker — `cd backend && uv run synsc-context-worker` (unless `--no-worker`)
   - Frontend — `cd frontend && npm run dev` (unless `--no-frontend`)

Flags: `--no-worker`, `--no-frontend`, `--docker` (full compose), `--help`.

---

## Docker (`docker-compose.yml` at root)

| Service | Build context | Notes |
|---|---|---|
| `postgres` | pgvector/pgvector:pg16 | Mounts `./database/supabase/setup_local.sql` on init |
| `api` | `./backend` (target `api`) | FastAPI + alembic upgrade head on boot |
| `worker` | `./backend` (target `worker`) | Background indexer |
| `frontend` | `./frontend` | Next.js dev server |

`backend/Dockerfile` has two targets (`api`, `worker`). Both copy `synsc/`, `alembic/`, `alembic.ini`, `pyproject.toml`, `uv.lock`, `README.md` into the image and pre-download the sentence-transformers model during the build stage.

---

## How to do common tasks

**Add a new API endpoint.**
Touch `backend/synsc/api/http_server.py`. If it needs new business logic, add a method on the relevant `*_service.py` in `backend/synsc/services/`. If the endpoint should also be an MCP tool, register it in `backend/synsc/api/mcp_server.py`.

**Add a DB column.**
1. Edit the model in `backend/synsc/database/models.py`.
2. Update `database/supabase/setup_local.sql` so fresh local envs get it.
3. Create an Alembic migration: `cd backend && uv run alembic revision -m "add X column"` — make it idempotent if it also covers the setup-sql case.

**Add a new MCP tool.**
Register it in `backend/synsc/api/mcp_server.py` and implement the body in the right service file. The stdio and HTTP MCP surfaces both reuse the same registry.

**Change the frontend's call to the backend.**
Frontend always hits the backend through URL rewrites in `frontend/next.config.mjs` or via `NEXT_PUBLIC_API_URL`. If you add a new backend route under a new prefix, add a rewrite there so dev cookies/CORS stay correct.

**Run tests.**
```bash
cd backend && uv run pytest
```

**Run everything locally.**
```bash
./scripts/launch_app.sh
```

---

## Invariants (things to preserve when refactoring)

1. The Python module is named `synsc` — do not rename without updating entry points, Alembic's `from synsc.database.models import Base`, and `packages = ["synsc"]` in hatchling config.
2. `backend/` is the Python project root — `uv` commands must be run from there.
3. `setup_local.sql` and `synsc.database.models` must stay in sync.
4. Alembic migrations must be idempotent with respect to `setup_local.sql` (the initial migration is the reference pattern).
5. The frontend **never** touches the DB; it only speaks HTTP to the backend.
6. `packages/mcp-proxy/` is a separate distributable — keep its deps minimal (no imports from `synsc`).
