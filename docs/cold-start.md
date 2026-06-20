# Cold start — getting value before you've indexed anything

A self-hosted context server starts empty, which is the #1 reason people bounce:
"I installed it, now what?" Delphi closes that gap three ways.

## 1. The curated catalog (name → indexable source)

Delphi ships a curated catalog mapping popular library names (and aliases) to
their canonical, indexable sources — React, FastAPI, Postgres, PyTorch,
Kubernetes, LangChain, and dozens more. You don't need to know the GitHub URL.

```bash
# HTTP
curl "http://localhost:8742/v1/catalog?q=nextjs" -H "Authorization: Bearer $KEY"
curl "http://localhost:8742/v1/catalog?category=ai-ml" -H "Authorization: Bearer $KEY"
```

MCP tools:

| Tool | What it does |
|------|--------------|
| `catalog_search` | Resolve a library name/keyword to a source URL. Works with **zero** indexed sources. |
| `quick_index` | Resolve a name via the catalog **and index it** in one step (`quick_index("fastapi")`). |

The catalog is static reference data (`backend/synsc/services/catalog.py`) — no
network or database needed to resolve a name. PRs to extend it are welcome.

## 2. The anonymous try endpoint

`GET /v1/try?query=...` runs an anonymous query against the public/shared index
so a brand-new user can see real results immediately, before authenticating or
indexing their own sources.

## 3. A drop-in agent rule (auto-invoke, no extra clicks)

Mirror Context7's "just works" ergonomics: add a rule so your agent reaches for
Delphi automatically on code/library questions. Drop this into your agent's
rules file (`.cursor/rules`, `CLAUDE.md`, Windsurf rules, etc.):

```text
When the user asks about a library, framework, API, or unfamiliar code:
1. If they name a library you haven't indexed, call `catalog_search` to resolve
   it, then `quick_index` to index it (or `index_repository` with a URL).
2. For local/work code, use `index_local_folder` on the project path.
3. Use `search_code` / `build_context_pack` to retrieve grounded context, and
   `find_callers` / `impact_analysis` before suggesting edits to shared code.
4. Before trusting an existing index, check `check_freshness` and re-index if
   it reports drift.
Prefer Delphi's grounded context over guessing from memory.
```

This is the no-friction path: the user just asks their question, and the agent
resolves → indexes → retrieves without anyone hunting for repo URLs.
