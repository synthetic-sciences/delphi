<h1 align="center">
  <img src="frontend/public/icon.svg" width="44" alt="" align="absmiddle"> Delphi
</h1>

<p align="center">Local search for your agent's code, docs, and papers.</p>

<p align="center">
  <a href="https://www.apache.org/licenses/LICENSE-2.0"><img src="https://img.shields.io/badge/license-Apache%202.0-b56f3e" alt="Apache 2.0 license"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-b56f3e" alt="Python 3.10+"></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-compatible-b56f3e" alt="MCP compatible"></a>
</p>

## Install

```bash
npx @synsci/delphi
```

The installer starts the local stack and can add Delphi to Claude Code,
Cursor, Windsurf, or Claude Desktop. It needs Docker, Git, and one embeddings
provider. Local sentence-transformers work without an API key.

```bash
delphi              # open the dashboard
delphi status       # check the stack
delphi logs -f      # follow logs
delphi stop         # stop services
delphi uninstall    # remove Delphi and its data
```

The dashboard runs at [localhost:3000](http://localhost:3000). The API runs at
[localhost:8742](http://localhost:8742).

<details>
<summary>Install from source</summary>

```bash
git clone https://github.com/synthetic-sciences/delphi.git
cd delphi
cp env.example .env
./scripts/launch_app.sh
```

</details>

<details>
<summary>Add Delphi to another MCP client</summary>

Create an API key in the dashboard, then add:

```json
{
  "mcpServers": {
    "delphi": {
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

</details>

## What Delphi does

| Source | Available context |
| --- | --- |
| Repositories | Code search, symbols, call graphs, related tests and docs |
| Papers | Sections, citations, equations, and quoted evidence |
| Documentation | Versioned pages and full-text search |
| Datasets | Hugging Face dataset cards and metadata |
| Local folders | Private, in-progress work without a Git remote |

Every index lives in your PostgreSQL database. Completed indexing runs create
immutable source snapshots, so a saved context can point to the exact version
it used.

### Agent tools

Delphi exposes MCP tools for:

- indexing repositories, folders, papers, documentation, and datasets;
- searching code, symbols, files, papers, and saved sources;
- following callers and callees or checking the impact of a code change;
- building a context pack around a task and a token budget;
- saving reproducible context sessions for handoffs;
- running optional, policy-gated research jobs.

The default MCP profile is local-first. Hosted search and Atlas graph tools are
opt-in through environment settings.

## Architecture

```text
AI agent
   │  MCP
   ▼
Delphi API ───── dashboard
   │
   ├── indexing and search
   ├── code and paper parsers
   └── background workers
   │
   ▼
PostgreSQL + pgvector
```

```text
backend/              FastAPI, MCP server, workers, and tests
frontend/             Local dashboard
landing/              trydelphi.ai
packages/cli/         npx installer and lifecycle commands
packages/mcp-proxy/   stdio-to-HTTP MCP bridge
database/             Local PostgreSQL setup
docs/                 Deployment and configuration notes
```

## Configuration

Copy [`env.example`](env.example) to `.env`. Common settings:

| Variable | Purpose |
| --- | --- |
| `SERVER_SECRET` | JWT signing secret |
| `SYSTEM_PASSWORD` | Local dashboard password |
| `EMBEDDING_PROVIDER` | `local`, `openai`, `gemini`, or `hash` |
| `EMBEDDING_MODEL` | Embedding model name |
| `EMBEDDING_DEVICE` | `cpu`, `cuda`, or `mps` |
| `SYNSC_ENABLE_RERANKER` | Enable the optional cross-encoder reranker |
| `SYNSC_MCP_PROFILE` | Choose the exposed MCP tool set |

See [`docs/env-advanced.md`](docs/env-advanced.md) for provider and network
policy settings. For a small local deployment, see
[`docs/deployment-lite.md`](docs/deployment-lite.md).

## Development

Backend:

```bash
cd backend
uv sync --locked --extra dev
uv run pytest
uv run ruff check synsc tests
uv run mypy synsc
```

Dashboard:

```bash
cd frontend
npm ci
npm run lint
npm run build
```

Landing site:

```bash
cd landing
corepack pnpm install --frozen-lockfile
corepack pnpm build
```

## License

[Apache License 2.0](LICENSE)
