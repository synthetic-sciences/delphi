```
 ███████╗██╗   ██╗███╗   ██╗███████╗ ██████╗██╗  ██████╗ ███████╗██╗     ██████╗ ██╗  ██╗██╗
 ██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝██╔════╝██║  ██╔══██╗██╔════╝██║     ██╔══██╗██║  ██║██║
 ███████╗ ╚████╔╝ ██╔██╗ ██║███████╗██║     ██║  ██║  ██║█████╗  ██║     ██████╔╝███████║██║
 ╚════██║  ╚██╔╝  ██║╚██╗██║╚════██║██║     ██║  ██║  ██║██╔══╝  ██║     ██╔═══╝ ██╔══██║██║
 ███████║   ██║   ██║ ╚████║███████║╚██████╗██║  ██████╔╝███████╗███████╗██║     ██║  ██║██║
 ╚══════╝   ╚═╝   ╚═╝  ╚═══╝╚══════╝ ╚═════╝╚═╝  ╚═════╝ ╚══════╝╚══════╝╚═╝     ╚═╝  ╚═╝╚═╝
```

<h3 align="center">open-source MCP server for AI agents</h3>
<p align="center">Index code repositories, research papers, and HuggingFace datasets. Runs fully local.</p>

<p align="center">
  <a href="https://www.apache.org/licenses/LICENSE-2.0"><img src="https://img.shields.io/badge/License-Apache_2.0-orange.svg" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10+-orange.svg" alt="Python"></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-compatible-orange.svg" alt="MCP"></a>
</p>

---

## What is Delphi?

Delphi is a self-hosted [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that gives AI agents deep context through semantic search across three domains:

| Domain | What it does |
|--------|-------------|
| **Code Repositories** | Index GitHub repos, search code semantically, find symbols (functions, classes), analyze architecture |
| **Research Papers** | Index arXiv papers or PDFs, extract citations and equations, generate reports |
| **HuggingFace Datasets** | Index dataset cards, search metadata |

Everything runs on your machine — PostgreSQL for storage, sentence-transformers for embeddings. **No API keys required.**

---

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/synthetic-sciences/delhpi.git
cd delhpi
cp env.example .env
```

Edit `.env` and set at minimum:

```bash
SERVER_SECRET=<generate-a-random-secret>
SYSTEM_PASSWORD=<your-admin-password>
```

### 2. Launch

```bash
./scripts/launch_app.sh
```

That's it. The script handles everything — installs dependencies (via `uv` in `backend/` and `npm` in `frontend/`), starts PostgreSQL via Docker, launches the API server, background worker, and frontend dashboard.

> **Dashboard:** [localhost:3000](http://localhost:3000) &nbsp;&middot;&nbsp; **API:** [localhost:8742](http://localhost:8742) &nbsp;&middot;&nbsp; **Health:** [localhost:8742/health](http://localhost:8742/health)

### Alternative: Docker Compose (everything containerized)

```bash
cp env.example .env       # edit .env
docker compose up --build
```

---

## Connect Your AI Tools

Create an API key from the dashboard at `/api-keys`, then add Delphi to your AI tool:

<details>
<summary><strong>Claude Code</strong></summary>

```json
// ~/.claude/settings.json
{
  "mcpServers": {
    "synsc-delphi": {
      "command": "uv",
      "args": ["--directory", "/path/to/delhpi/backend", "run", "synsc-context-mcp"],
      "env": { "SYNSC_API_KEY": "your-api-key" }
    }
  }
}
```
</details>

<details>
<summary><strong>Claude Desktop / Cursor</strong></summary>

```json
{
  "mcpServers": {
    "synsc-delphi": {
      "command": "uv",
      "args": ["--directory", "/path/to/delhpi/backend", "run", "synsc-context-mcp"],
      "env": { "SYNSC_API_KEY": "your-api-key" }
    }
  }
}
```
</details>

<details>
<summary><strong>HTTP API (any client)</strong></summary>

```bash
# Health check
curl http://localhost:8742/health

# Index a repository
curl -X POST http://localhost:8742/api/repositories/index \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/owner/repo"}'

# Search code
curl "http://localhost:8742/api/search/code?query=authentication+middleware" \
  -H "Authorization: Bearer your-api-key"
```
</details>

---

## MCP Tools

### Code
| Tool | Description |
|------|-------------|
| `index_repository` | Index a GitHub repository |
| `search_code` | Semantic code search across indexed repos |
| `search_symbols` | Find functions, classes, methods by name |
| `get_file` | Retrieve file content from an indexed repo |
| `get_directory_structure` | Browse repository file tree |
| `analyze_repository` | Deep code analysis and architecture overview |

### Papers
| Tool | Description |
|------|-------------|
| `index_paper` | Index from arXiv URL/ID or PDF upload |
| `search_papers` | Semantic search across indexed papers |
| `get_citations` | Extract citation graph |
| `get_equations` | Extract equations with context |
| `generate_report` | Generate a markdown summary report |
| `compare_papers` | Side-by-side paper comparison |

### Datasets
| Tool | Description |
|------|-------------|
| `index_dataset` | Index a HuggingFace dataset card |
| `search_datasets` | Semantic dataset search |

---

## Architecture

```
┌──────────────────────────────────────────────┐
│  AI Agent (Claude, Cursor, etc.)             │
│  Calls MCP tools to index & search           │
└──────────────┬───────────────────────────────┘
               │ MCP (stdio) or HTTP
┌──────────────▼───────────────────────────────┐
│  Delphi Server (FastAPI)                     │
│  ┌──────────┐ ┌───────────┐ ┌─────────────┐ │
│  │ Indexing  │ │  Search   │ │   Papers    │ │
│  │ Service   │ │  Service  │ │   Service   │ │
│  └─────┬────┘ └─────┬─────┘ └──────┬──────┘ │
│  ┌─────▼─────────────▼──────────────▼──────┐ │
│  │  sentence-transformers (local)          │ │
│  │  No API keys needed                     │ │
│  └─────────────────────────────────────────┘ │
└──────────────┬───────────────────────────────┘
               │
┌──────────────▼───────────────────────────────┐
│  PostgreSQL + pgvector                       │
│  All data stays on your machine              │
└──────────────────────────────────────────────┘
```

---

## Project Structure

```
backend/                  Python backend (FastAPI + MCP)
  synsc/                  Application package
    api/                  HTTP + MCP server entry points
    services/             Business logic (search, indexing, papers, datasets)
    database/             SQLAlchemy models, session management
    embeddings/           sentence-transformers embedding provider
    extractors/           Symbol extraction (tree-sitter AST)
    indexing/             Repo/paper/dataset indexing pipelines
    parsing/              Language parsers
    workers/              Background indexing worker
  alembic/                DB migrations
  tests/                  Pytest suite
  pyproject.toml          Python deps & entry points
  Dockerfile              Image for api + worker targets
frontend/                 Next.js dashboard
packages/mcp-proxy/       MCP stdio-to-HTTP bridge (published separately)
database/supabase/        Local PostgreSQL init SQL
scripts/                  Developer scripts (launch_app.sh, etc.)
docs/                     Architecture + engineering docs
docker-compose.yml        Local dev stack (postgres + api + worker + frontend)
```

See [`docs/architecture.md`](docs/architecture.md) for a walk-through of how the pieces fit together.

## Configuration

All configuration is via environment variables. See [`env.example`](env.example) for the full list.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://synsc:synsc@localhost:5432/synsc` | PostgreSQL connection |
| `SERVER_SECRET` | — | JWT signing secret (required) |
| `SYSTEM_PASSWORD` | — | Admin login password |
| `EMBEDDING_MODEL` | `all-mpnet-base-v2` | sentence-transformers model |
| `EMBEDDING_DEVICE` | auto | `cpu`, `cuda`, or `mps` |
| `SYNSC_ENABLE_RERANKER` | `false` | Enable cross-encoder reranking |
| `HF_TOKEN` | — | HuggingFace token for dataset indexing |

## Development

All Python commands run from `backend/`:

```bash
cd backend
uv run pytest                         # tests
uv run ruff check synsc/ tests/       # lint
uv run ruff format synsc/ tests/      # format
uv run mypy synsc/                    # type check
```

---

## License

[Apache License 2.0](LICENSE)
