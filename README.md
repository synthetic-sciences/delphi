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

Everything runs on your machine — PostgreSQL for storage. Pick **local sentence-transformers** (no API keys) or wire up **Gemini** / **OpenAI** for hosted embeddings.

---

## Quick Start

```bash
npx @synsci/delphi
```

That's it. The installer asks two questions:

1. **Add Delphi to your coding agent** (Claude Code, Cursor, Windsurf, Claude Desktop) — or **run your own index** with a Gemini / OpenAI / local-model key and a dashboard.
2. Which embeddings provider to use.

Then it pulls the source, spins up the Docker stack, mints an API key, and (if you picked the agent path) writes the MCP config for the tools you have installed.

When it finishes, restart your AI tool — Delphi shows up as an MCP server. After install, just type `delphi` in any terminal to open the dashboard.

```bash
delphi              # open the dashboard (boots the stack if it's down)
delphi status       # check health + container state
delphi logs -f      # tail logs
delphi stop         # tear it down
delphi uninstall    # remove containers + data volume
```

> Requires Docker Desktop (or `docker compose` v2) and `git`.
> **Dashboard:** [localhost:3000](http://localhost:3000) &nbsp;&middot;&nbsp; **API:** [localhost:8742](http://localhost:8742)

<details>
<summary><strong>Manual install (from source)</strong></summary>

For contributors or anyone who wants to run a fork:

```bash
git clone https://github.com/synthetic-sciences/delhpi.git
cd delhpi
cp env.example .env       # set SERVER_SECRET and SYSTEM_PASSWORD
./scripts/launch_app.sh   # or: docker compose up --build
```
</details>

<details>
<summary><strong>Manual MCP config (for any client the installer doesn't cover)</strong></summary>

Once you have an API key (from the dashboard at `/api-keys` or via `npx @synsci/delphi init`), add this to your client's MCP config:

```json
{
  "mcpServers": {
    "synsci-delphi": {
      "command": "uvx",
      "args": ["synsci-delphi-proxy"],
      "env": {
        "SYNSC_API_KEY": "your-api-key",
        "SYNSC_API_URL": "http://localhost:8742"
      }
    }
  }
}
```

**Config file paths:** Cursor `~/.cursor/mcp.json` · Windsurf `~/.codeium/windsurf/mcp_config.json` · Claude Desktop `~/Library/Application Support/Claude/claude_desktop_config.json` · Claude Code use `claude mcp add --scope user synsci-delphi -- uvx synsci-delphi-proxy`.
</details>

<details>
<summary><strong>HTTP API (any client)</strong></summary>

```bash
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

> **MCP defaults to `quality_mode='agent'`.** Indexing includes tests, docs, examples, configs, manifests, and dotfiles. Search runs hybrid retrieval (vector + BM25 + exact symbol + exact path + trigram) with a cross-encoder rerank. Each result carries `candidate_sources` so the agent can see which branches surfaced it. Pass `quality_mode='fast'` for the legacy pure-vector path.

### Code
| Tool | Description |
|------|-------------|
| `index_repository` | Index a GitHub repository. Accepts `quality_mode`, `include_tests`, `include_docs`, `include_examples`, `deep_index`, `force_reindex`. Branch is optional — the default branch is auto-detected. |
| `index_local_folder` | Index a **local directory** straight from disk (no GitHub needed) — private/work code and work-in-progress. |
| `quick_index` | Resolve a library name via the curated catalog and index it in one step (`quick_index("fastapi")`). |
| `catalog_search` | Resolve a library/framework name to an indexable source — works with **zero** indexed sources (cold start). |
| `search_code` | Hybrid code search (vector + BM25 + symbol + path + trigram, fused). |
| `search_symbols` | Find functions, classes, methods by name. Structural extraction for **16 languages** (Python, JS/TS, Go, Rust, Java, C, C++, C#, Ruby, PHP + Kotlin/Swift/Scala/Lua/Elixir/shell via regex). |
| `get_symbol` | Full symbol details *plus the reconstructed source body* (no separate `get_file` call needed). |
| `find_callers` | Who calls this symbol? (code-dependency graph) |
| `find_callees` | What does this symbol call — internal symbols + external names. |
| `impact_analysis` | Blast radius — transitive callers: "what breaks if I change this function?" |
| `build_code_graph` | (Re)build the call graph for a repo (built automatically after indexing). |
| `check_freshness` | Is this index stale? Compares against remote HEAD (git) or re-hashes files (local). |
| `list_stale_sources` | List indexed repos whose index has drifted from its source. |
| `get_file` | Retrieve file content from an indexed repo. |
| `get_context` | Fetch a chunk plus adjacent chunks, enclosing function/class body, and same-class siblings. |
| `build_context_pack` | Agent-ready pack: primary hits + enclosing bodies + adjacent chunks + same-class siblings + imports + linked tests/docs/examples/configs + symbol details + architecture summary, with a token budgeter and a re-query planner. |
| `get_directory_structure` | Browse repository file tree. |
| `analyze_repository` | Deep code analysis and architecture overview. |
| `classify_failure` | Tag a "Delphi failed because" event with a stable failure-mode code. |

> **Code intelligence:** after indexing, Delphi builds a symbol-level call graph so agents can reason about structure (`find_callers`, `impact_analysis`), not just retrieve text. **Cold start:** a curated catalog maps popular library names to sources so `catalog_search`/`quick_index` work before you've indexed anything. **Freshness:** `check_freshness` flags stale indexes. See [`docs/cold-start.md`](docs/cold-start.md).

### Papers
| Tool | Description |
|------|-------------|
| `index_paper` | Index from arXiv URL/ID or PDF upload. |
| `search_papers` | Hybrid paper search with section-aware (Methods > Related Work) and citation-aware ranking, cross-encoder rerank. |
| `extract_quoted_evidence` | Pull literal sentences from a paper that ground a claim. |
| `joint_retrieval` | One call → paper + code + Atlas-graph hits, fused. |
| `get_citations` | Extract citation graph. |
| `get_equations` | Extract equations with context. |
| `generate_report` | Generate a markdown summary report. |
| `compare_papers` | Side-by-side paper comparison. |

### Datasets
| Tool | Description |
|------|-------------|
| `index_dataset` | Index a HuggingFace dataset card. |
| `search_datasets` | Semantic dataset search with cross-encoder rerank. |

### Atlas integration (optional)

Delphi can ingest and retrieve over an [Atlas](https://github.com/synthetic-sciences/atlas) research graph (nodes, edges, artifacts, executions, tool contracts), with graph-aware context packs and "what was tried / don't-repeat / decision recall" surfaces. **Off by default** — these tools only make sense if you're pushing graph data into Delphi from an Atlas workspace, and they cost MCP-handshake tokens when exposed. Set `SYNSC_MCP_PROFILE=atlas` (or `all`) to turn them on. Full tool list and ingestion contracts in [`docs/atlas-integration.md`](docs/atlas-integration.md).

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
│  ┌──────────┐ ┌───────────┐ ┌─────────────┐  │
│  │ Indexing │ │  Search   │ │   Papers    │  │
│  │ Service  │ │  Service  │ │   Service   │  │
│  └─────┬────┘ └─────┬─────┘ └──────┬──────┘  │
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
packages/cli/             `npx @synsci/delphi` installer (one-command setup)
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

## Lite deployment

For a laptop, CI, or air-gapped box, the **lite stack** (Postgres + API only)
skips the ~1.2 GB embedding-model download via `EMBEDDING_PROVIDER=hash` and
boots in seconds — hybrid retrieval's lexical + symbol branches still carry most
of the quality. See [`docs/deployment-lite.md`](docs/deployment-lite.md).

```bash
docker compose -f docker-compose.lite.yml up --build
```

## Benchmark

Retrieval quality and token economy are measured, not asserted. The reproducible,
database-free harness in [`bench/`](bench/) scores recall@k, precision@k, nDCG,
MRR, and token cost across naive grep, smart grep, BM25, symbol lookup, and
Delphi's hybrid fusion:

```bash
uv run --project backend python bench/run.py
```

Point it at your own corpus with `--corpus` / `--tasks`. Methodology and sample
numbers are in [`bench/README.md`](bench/README.md).

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
