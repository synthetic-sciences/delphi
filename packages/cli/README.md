# `@synsci/delphi`

One-command installer for [Delphi](https://github.com/synthetic-sciences/delhpi) — a self-hosted MCP server that gives AI coding agents semantic context across code repositories, research papers, and HuggingFace datasets.

## Install

```bash
npx @synsci/delphi
```

The installer asks two questions:

1. **Add to my coding agent** (Claude Code, Cursor, Windsurf, Claude Desktop) **or run my own index** (pick a provider, attach an API key, get a dashboard).
2. **Embeddings** — local sentence-transformers (default, no key) · Google Gemini · OpenAI · Anthropic / Qwen (coming v0.3).

Then it pre-flights Docker + git, clones the source into `~/.synsci/delphi/source`, generates secrets, brings up `docker compose`, mints an API key via `/api/bootstrap`, writes the MCP config for the tools you have installed, and drops a `delphi` shim onto your `PATH`.

After it finishes, restart your AI tool and Delphi appears as an MCP server.

## Lifecycle

After install, just type `delphi` in any terminal — it boots the stack (if needed) and opens the dashboard.

```bash
delphi              # open dashboard, booting the stack if down
delphi status       # health + container state
delphi logs -f      # tail logs
delphi stop         # docker compose down
delphi start        # bring it back up
delphi uninstall    # tear down + drop data volume
```

## Requirements

- Node 18.17+
- Docker Desktop (or `docker` + `docker compose` v2)
- `git`

## Environment overrides

| Var | Default | Purpose |
|---|---|---|
| `SYNSCI_DELPHI_HOME` | `~/.synsci/delphi` | Install dir for source + state |
| `SYNSCI_DELPHI_REPO` | `https://github.com/synthetic-sciences/delhpi.git` | Source repo |
| `SYNSCI_DELPHI_REF` | `main` | Branch / tag to pull |
| `SYNSCI_DELPHI_API_URL` | `http://localhost:8742` | API URL |

## License

Apache-2.0
