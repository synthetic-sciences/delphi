# Delphi (synsc-context)

> **Open-source MCP Server for AI Agents** — Index code repositories, research papers, and HuggingFace datasets. Runs fully local.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## What is this?

Delphi is an open-source [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that provides semantic search across:

- **GitHub Repositories** — Index code, understand patterns, find symbols
- **Research Papers** — Index arXiv papers, extract citations, equations, code
- **HuggingFace Datasets** — Index dataset cards for semantic search

Everything runs locally — PostgreSQL for storage, sentence-transformers for embeddings. No API keys required.

## Quick Start

### Docker Compose (recommended)

```bash
git clone https://github.com/InkVell/synsc-delphi.git
cd synsc-delphi
cp env.example .env  # edit .env and set SYSTEM_PASSWORD
docker compose up
```

This starts PostgreSQL (with pgvector), the API server, and the frontend.
Open `http://localhost:3000`, log in with your system password, and create an API key for your AI tools.

### Manual Setup

```bash
# 1. Start PostgreSQL with pgvector
docker compose up -d postgres

# 2. Install Python dependencies
uv sync

# 3. Set your password and start the API server
export SYSTEM_PASSWORD=your-secure-password
uv run synsc-context-http

# 4. (Optional) Start the frontend
cd frontend && npm install && npm run dev
```

### MCP Configuration

Add to your Claude Desktop / Cursor / Claude Code config:

```json
{
  "mcpServers": {
    "synsc-context": {
      "command": "uv",
      "args": ["--directory", "/path/to/synsc-delphi", "run", "synsc-context-mcp"]
    }
  }
}
```

## Architecture

```
┌─────────────────────────────────────────────┐
│  AI Agent (Claude, Cursor, etc.)            │
│  Uses MCP tools to index & search           │
└──────────────┬──────────────────────────────┘
               │ MCP (stdio) or HTTP API
┌──────────────▼──────────────────────────────┐
│  Delphi Server                              │
│  FastAPI + MCP Server                       │
│  ┌──────────┐  ┌────────────┐  ┌─────────┐ │
│  │ Indexing  │  │   Search   │  │ Papers  │ │
│  │ Service   │  │  Service   │  │ Service │ │
│  └──────────┘  └────────────┘  └─────────┘ │
│       │              │              │       │
│  ┌────▼──────────────▼──────────────▼─────┐ │
│  │  sentence-transformers (local)         │ │
│  │  Embeddings — no API keys needed       │ │
│  └────────────────────────────────────────┘ │
└──────────────┬──────────────────────────────┘
               │
┌──────────────▼──────────────────────────────┐
│  PostgreSQL + pgvector                      │
│  Local database — all data stays on disk    │
└─────────────────────────────────────────────┘
```

## Available MCP Tools

### Code Repository Tools
| Tool | Description |
|------|-------------|
| `index_repository` | Index a GitHub repository |
| `list_repositories` | List indexed repositories |
| `search_code` | Semantic code search |
| `get_file` | Get file content |
| `search_symbols` | Find functions, classes, methods |
| `analyze_repository` | Deep code analysis |
| `get_directory_structure` | Browse repo structure |

### Research Paper Tools
| Tool | Description |
|------|-------------|
| `index_paper` | Index from arXiv or PDF |
| `list_papers` | List indexed papers |
| `search_papers` | Semantic paper search |
| `get_citations` | Extract citations |
| `get_equations` | Extract equations |
| `generate_report` | Generate markdown report |

### Dataset Tools
| Tool | Description |
|------|-------------|
| `index_dataset` | Index HuggingFace dataset card |
| `list_datasets` | List indexed datasets |
| `search_datasets` | Semantic dataset search |

## Configuration

All configuration is via environment variables. See [env.example](env.example) for the full list.

Key variables:
- `DATABASE_URL` — PostgreSQL connection string (default: `postgresql://synsc:synsc@localhost:5432/synsc`)
- `EMBEDDING_MODEL` — sentence-transformers model (default: `all-mpnet-base-v2`)
- `SYSTEM_PASSWORD` — admin password for the dashboard (required)
- `HF_TOKEN` — Optional HuggingFace token for dataset indexing

## Development

```bash
# Run tests
uv run pytest

# Lint & format
uv run ruff check synsc/ tests/
uv run ruff format synsc/ tests/

# Type check
uv run mypy synsc/
```

## License

MIT
