<pre align="center">
██████╗ ███████╗██╗     ██████╗ ██╗  ██╗██╗
██╔══██╗██╔════╝██║     ██╔══██╗██║  ██║██║
██║  ██║█████╗  ██║     ██████╔╝███████║██║
██║  ██║██╔══╝  ██║     ██╔═══╝ ██╔══██║██║
██████╔╝███████╗███████╗██║     ██║  ██║██║
╚═════╝ ╚══════╝╚══════╝╚═╝     ╚═╝  ╚═╝╚═╝
</pre>

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

## Latest results

On [Agent Retrieval Bench v2](https://github.com/eyuansu62/agent-retrieval-bench)
(commit `d04953371d96`), Delphi leads every published baseline on MRR and
Recall@5 over the same 75 development cases, with the same `all_files`
candidate filter, scored by the benchmark's own code.

| System | MRR | Recall@5 | Recall@20 | Latency |
| --- | ---: | ---: | ---: | ---: |
| **Delphi** | 0.191 | 0.327 | **0.547** | **5.3 s** |
| Nia (hosted) | **0.228** | **0.391** | 0.449 | 36.9 s |
| grep | 0.180 | 0.302 | 0.578 | — |
| RepoMap | 0.169 | 0.240 | 0.551 | — |
| lexical | 0.127 | 0.198 | 0.451 | — |
| BM25 | 0.116 | 0.136 | 0.429 | — |

The hosted comparator was re-run live against the same corpora, 75 cases,
zero failures on either side. It is a split decision, and we print both
halves: Nia ranks the top of the list better (MRR, Recall@5); Delphi covers
more of the answer set (Recall@20) and returns it about 7x faster, on your
own hardware. grep still leads Recall@20 outright at 0.578.

The two shapes follow from different strategies rather than different amounts
of skill: Nia returns ~7.8 files per query, Delphi returns 20. A short
confident list wins precision at the top; a longer one wins coverage.

### What changed, and what each change was worth

The previous evaluation measured a corpus indexed with `text-embedding-3-small`
but queried with `gemini-embedding-001`. Both emit 768-dimensional vectors, so
pgvector computed cosines between unrelated spaces without raising anything.
Embedding a chunk's own exact content and comparing it against that chunk's
stored vector scored **cosine 0.0101** — orthogonal. Aligning the query-time
model to the index moved the same comparison to **0.9430**.

| Configuration | MRR | Recall@5 | Recall@20 | Latency |
| --- | ---: | ---: | ---: | ---: |
| As previously benchmarked | 0.055 | 0.056 | 0.161 | 1.0 s |
| Embedding space aligned | 0.173 | 0.259 | 0.549 | 0.9 s |
| + rank fusion, path affinity | 0.176 | 0.256 | 0.552 | 1.1 s |
| + cross-encoder rerank | **0.193** | **0.294** | **0.560** | 2.9 s |

Delphi now compares `repositories.embedding_model` against the model answering
queries on every search and on `/backend-health`, so a silent vector-space
mismatch is reported instead of absorbed.

### Held-out results, by workflow

All 220 positive cases of the final split, zero failed queries:

| Workflow | Cases | MRR | Recall@5 | Recall@20 |
| --- | ---: | ---: | ---: | ---: |
| trace2code | 38 | 0.468 | 0.763 | 0.908 |
| edit2ripple | 44 | 0.230 | 0.362 | 0.587 |
| code2test | 83 | 0.179 | 0.287 | 0.521 |
| comment2context | 55 | 0.134 | 0.170 | 0.324 |
| **overall** | **220** | **0.241** | **0.355** | **0.579** |

Queries about a code index are usually written in English while the index is
written in code, so Delphi can embed a hypothetical code snippet alongside the
question (`SYNSC_QUERY_EXPANSION=true`). On the held-out split that moves every
metric:

| Configuration | MRR | Recall@5 | Recall@20 | Latency |
| --- | ---: | ---: | ---: | ---: |
| Retrieval only | 0.228 | 0.349 | 0.552 | 1.96 s |
| + hypothetical document | **0.241** | **0.355** | **0.579** | 4.11 s |

The spread matters more than the average. A failure trace hands the retriever
real symbols and stack frames, and Delphi finds the root-cause file in the top
five 74% of the time. A review comment hands it English, and the same engine
manages 15%. That gap is the difference between a query that contains evidence
and one that does not.

### Scope and limits

- The held-out split is reported at full scope: all 220 positive cases, every
  corpus provisioned, zero failed queries. Delphi scores 0.241 MRR / 0.355
  Recall@5 / 0.579 Recall@20 with query expansion enabled — ahead of the
  development split the pipeline was tuned on.
- The hosted head-to-head is run on the development split, where both engines
  have every corpus indexed. Nia has 60 of the 220 final-split commits indexed
  on its side, so a full held-out head-to-head is not available.
- Delphi is not state of the art at the top of the list. On this benchmark the
  hosted comparator leads MRR and Recall@5, and that is published alongside the
  metrics Delphi does lead rather than omitted.
- Earlier head-to-head figures are withdrawn rather than restated: the Delphi
  half of that run is now known to have been measuring a mismatched embedding
  space.

Full method, ablations, and expandable per-query retrieval traces:
[The context engine is the product](https://trydelphi.ai/blog/context-engine-is-the-product).

### Timeline

| When | Milestone |
| --- | --- |
| Open source | Released Delphi as a local-first MCP context engine under Apache 2.0. |
| Product foundation | Added versioned multi-source indexing, hybrid retrieval, code intelligence, and agent-ready context packs. |
| 2026-07-30 | Found and fixed a silent embedding-space mismatch that had made the vector branch return random results; added a permanent check for it. |
| 2026-07-30 | Rebuilt ranking on reciprocal-rank fusion, added a path-affinity branch, and set reranker defaults from measurement. |

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
git clone https://github.com/synthetic-sciences/delphi.git
cd delphi
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

### Reproducible source versions

Completed indexing runs publish immutable, content-addressed snapshots of
repositories, papers, datasets, and documentation. Each version keeps its own
normalized chunks and vectors, while a separate head identifies the current
version. This is fully local and does not require a hosted service.

```bash
# Authenticated HTTP
curl "http://localhost:8742/v2/sources/SOURCE_ID/snapshots?type=repo" \
  -H "Authorization: Bearer your-api-key"
curl "http://localhost:8742/v2/snapshots/SNAPSHOT_ID?include_items=true" \
  -H "Authorization: Bearer your-api-key"

# Local database CLI
synsc-context snapshots list --type repo --source-id SOURCE_ID --json
synsc-context snapshots show SNAPSHOT_ID --include-items --json
```

### Policy-aware retrieval

Retrieval is planned before providers run. The planner searches the local index
first, keeps pinned snapshot scopes exact, and only admits optional remote
search when both the deployment network ceiling and the request-level egress
policy allow it. Plans are deterministic and auditable: admitted steps, denied
alternatives, provider choices, privacy decisions, and hard call/result/
provider-hit-payload/deadline budgets are recorded without exposing user
identities.

Execution binds the plan to the independently authenticated user and revalidates
plan integrity, provider health and capabilities, and egress immediately before
each call. Providers receive the remaining deadline, a bounded response
contract, and cooperative cancellation. Provider failures remain isolated, and
results carry fused per-provider provenance. The default remains local-only;
remote providers are optional.

An optional hosted adapter supplies web search and bounded public-site crawling
without changing the local-first default. It is registered lazily, requires no
cloud credential at startup, and cannot run unless both deployment policy and
the individual request permit public egress. See
[`docs/env-advanced.md`](docs/env-advanced.md#optional-provider-network-policy).

### Incremental connectors

Connectors ingest changing sources through a durable, local-first sync queue.
Configuration and checkpoints are encrypted, changes are bounded and
idempotent, deletions and permission revocations become tombstones, and a
cursor advances only in the transaction that activates its validated immutable
snapshot. The built-in `local-folder` adapter never uses the network; hosted
adapters remain optional. Local-folder access is denied until the operator sets
`SYNSC_LOCAL_CONNECTOR_ALLOWED_ROOTS`. See
[`docs/connectors.md`](docs/connectors.md).

### Reproducible context sessions

Context sessions keep task state, pinned snapshot references, accepted and
rejected evidence, decisions, unresolved questions, and deterministic
token-budget manifests in append-only revisions. Parent/child handoffs preserve
the exact revision they continue from. Reads and exports re-check current source
authorization, so a later permission revocation does not leak content through a
saved context. See [`docs/context-sessions.md`](docs/context-sessions.md).

### One workspace, three interfaces

The dashboard's `/workspace` route brings provider health, connector sources,
durable research, and reproducible contexts into one local-first control plane.
The same safe surface is available to scripts through the Python client and CLI:

```bash
export SYNSC_API_URL=http://localhost:8742
export SYNSC_API_KEY=your-api-key

synsc-context workspace
synsc-context connectors list
synsc-context connectors sync SOURCE_ID
synsc-context contexts create release-review \
  --objective "Verify the release against pinned evidence" \
  --snapshot-id SNAPSHOT_ID
synsc-context contexts export SESSION_ID --json
```

```python
from synsc.client import SynscClient

with SynscClient() as client:
    workspace = client.workspace()
```

Authentication stays in environment variables; neither the dashboard nor these
commands returns connector configuration or provider credentials.

---

## MCP Tools

> **MCP defaults to `quality_mode='agent'`.** Indexing includes tests, docs, examples, configs, manifests, and dotfiles. Search runs hybrid retrieval (vector + BM25 + exact symbol + exact path + trigram) with stable file-level diversity. Structured developer requests with safe repository-relative file fields also probe related paths (for example, `core_model_loading.py` can surface `test_core_model_loading.py`). Deployments can opt into a cross-encoder rerank with `SYNSC_ENABLE_RERANKER=true`. Each result carries `candidate_sources` so the agent can see which branches surfaced it. Pass `quality_mode='fast'` for the legacy pure-vector path.

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

### Durable research

| Tool | Description |
|------|-------------|
| `research_start` | Queue a `quick`, `deep`, or `oracle` research session and return immediately. |
| `research_list` | List the caller's sessions, including work recovered after a restart. |
| `research_status` | Read the latest persisted answer, citations, usage, and status. |
| `research_events` | Replay the append-only progress log from a sequence cursor. |
| `research_followup` | Persist a follow-up turn and requeue the same conversation. |
| `research_cancel` | Cancel pending work or request cooperative cancellation of a running job. |

Async research is backed by PostgreSQL rather than API-process memory. The
worker uses leased claims, heartbeats, bounded retries, stale-job recovery, and
generation fencing so an interrupted or superseded worker cannot publish a
late answer. The HTTP equivalents are under `/v2/research`; SSE reconnects can
send `Last-Event-ID` and receive only later persisted events.

### Reproducible contexts

| Tool | Description |
|------|-------------|
| `context_session_create` | Create a private-by-default session from pinned snapshot references. |
| `context_session_list` | List the caller's current context-session metadata. |
| `context_session_get` | Rehydrate an authorized current or historical revision. |
| `context_session_revise` | Append an immutable revision behind an optimistic write fence. |
| `context_session_handoff` | Create an explicitly linked child from the current parent revision. |

These tools are included in the `all`, `code`, `papers`, `docs`, and `atlas`
profiles. The compact `minimal` profile omits them.

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
landing/                  Public Next.js site (deployed from this monorepo)
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
