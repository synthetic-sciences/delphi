# Synsc Context 🧠

> **Unified MCP Server for AI Agents** - Index code repositories and research papers, giving your AI deep contextual understanding.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## What is this?

Synsc Context is a unified [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) service that provides semantic search across:
- **GitHub Repositories** - Index code, understand patterns, find symbols
- **Research Papers** - Index arXiv papers, extract citations, equations, code

Works directly with **Cursor**, **Claude**, and any MCP-compatible AI assistant.

## Features

### Code Context
- 🔍 **Semantic Code Search** - Find code by meaning, not just keywords
- 📦 **Repository Indexing** - Index any GitHub repository
- 🎯 **Symbol Extraction** - Find functions, classes, methods with tree-sitter
- 📊 **Code Analysis** - Detect frameworks, architecture, dependencies
- ⚡ **Job Queue** - Background indexing with progress tracking

### Paper Context
- 📄 **PDF Processing** - Index papers from arXiv or local PDFs
- 📝 **Citation Extraction** - Numbered, author-year, superscript citations
- ➗ **Equation Indexing** - LaTeX equations with type detection
- 💻 **Code Snippets** - Extract code blocks from papers
- 🔗 **Paper Comparison** - Compare multiple papers side-by-side

### Infrastructure
- 🔑 **Supabase Auth** - Secure API key authentication with GitHub OAuth
- 🐘 **PostgreSQL + pgvector** - Vector storage for semantic search
- 🚀 **Multi-threading** - Parallel file processing for fast indexing
- 📈 **Progress Tracking** - Real-time job progress with ETA

## Quick Start

### 1. Get an API Key

Sign in at [context.syntheticsciences.ai](https://context.syntheticsciences.ai) with GitHub.

### 2. Connect to Cursor

**Option A: Remote Server (recommended)**

Add to your `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "synsc-context": {
      "url": "https://context.syntheticsciences.ai/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

**Option B: Local Proxy via `uvx`**

```json
{
  "mcpServers": {
    "synsc-context": {
      "command": "uvx",
      "args": ["synsc-context-proxy"],
      "env": {
        "SYNSC_API_KEY": "YOUR_API_KEY"
      }
    }
  }
}
```

### 3. Use It!

```
# Index a GitHub repository
@synsc-context index_repository("facebook/react")

# Search code
@synsc-context search_code("how does useState work")

# Index a paper
@synsc-context index_paper("https://arxiv.org/abs/2301.07041")

# Search papers
@synsc-context search_papers("transformer attention mechanisms")
```

## MCP Tools

### Code Repository Tools
| Tool | Description |
|------|-------------|
| `index_repository(url, branch)` | Index a GitHub repository |
| `list_repositories()` | List your indexed repositories |
| `get_repository(repo_id)` | Get repository details |
| `delete_repository(repo_id)` | Delete a repository |
| `remove_from_collection(repo_id)` | Remove repo from your collection |
| `search_code(query, ...)` | Semantic code search |
| `get_file(repo_id, file_path)` | Get file content |
| `search_symbols(name, ...)` | Find functions, classes |
| `get_symbol(symbol_id)` | Get symbol details |
| `get_directory_structure(repo_id)` | Get repo directory tree |
| `analyze_repository(repo_id)` | Deep code analysis |

### Research Paper Tools
| Tool | Description |
|------|-------------|
| `index_paper(source)` | Index from arXiv URL/ID or PDF |
| `list_papers(limit, offset)` | List indexed papers |
| `get_paper(paper_id)` | Get full paper content |
| `search_papers(query, top_k)` | Semantic paper search |
| `get_citations(paper_id)` | Extract citations |
| `get_equations(paper_id)` | Extract LaTeX equations |
| `get_code_snippets(paper_id)` | Extract code blocks |
| `generate_report(paper_id)` | Generate markdown report |
| `compare_papers(paper_ids)` | Compare multiple papers |

## Embedding Strategy

- **Code**: Google Gemini API (`gemini-embedding-001`) - Fast, optimized for code
- **Papers**: HuggingFace sentence-transformers (`all-mpnet-base-v2`) - Better for academic text

## Project Structure

```
synsc-context/
├── synsc/                    # Python backend (FastAPI + MCP)
│   ├── api/                  # HTTP server (27 endpoints) & MCP server
│   ├── core/                 # Core utilities (chunker, git, pdf, arxiv)
│   ├── database/             # SQLAlchemy models & connection management
│   ├── embeddings/           # Gemini (code) & sentence-transformers (papers)
│   ├── extractors/           # Paper extractors (citations, equations, code)
│   ├── indexing/             # Vector storage (pgvector)
│   ├── parsing/              # AST parsers (tree-sitter: Python, TypeScript)
│   ├── services/             # Business logic (indexing, search, papers, jobs)
│   └── workers/              # Background indexing worker (ThreadPoolExecutor)
├── frontend/                 # Next.js dashboard (login, repos, papers, docs)
├── packages/wizard/          # CLI tools (API key management, MCP config)
├── docs/                     # Documentation (progress, audit, pricing)
├── supabase/                 # Supabase CLI config & migrations
└── pyproject.toml            # Python dependencies (uv)
```

## Development

### Quick Start (All Services)

```bash
# Start backend + frontend + worker
./launch_app.sh

# With local Supabase (Docker required)
./launch_app.sh --local

# Backend only
./launch_app.sh --no-frontend
```

| Service | URL |
|---------|-----|
| Backend API | http://localhost:8742 |
| API Docs (Swagger) | http://localhost:8742/docs |
| Frontend | http://localhost:3000 |

### Manual Setup

```bash
# Backend
cp env.example .env  # Edit with your credentials
uv sync
uv run python -m synsc.cli serve http

# Frontend
cd frontend && npm install && npm run dev

# Background worker
uv run python -m synsc.cli worker
```

### CLI Tools

```bash
# Install globally via npm
npm install -g synsc-context

# Manage API keys and configure MCP
synsc-context-keys
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SUPABASE_URL` | Supabase project URL | Yes |
| `SUPABASE_SECRET_KEY` | Supabase service role key | Yes |
| `SUPABASE_DATABASE_URL` | PostgreSQL connection string | Yes |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase anon/publishable key | Frontend |
| `GEMINI_API_KEY` | Google AI API key for code embeddings | Code indexing |
| `SYNSC_API_PORT` | Server port (default: 8742) | No |
| `SYNSC_REQUIRE_AUTH` | Require API key auth (default: true) | No |

See `env.example` for all available configuration options.

## License

MIT License - see [LICENSE](LICENSE) for details.

---

**Built with ❤️ by [InkVell](https://inkvell.ai) for AI-assisted development**
