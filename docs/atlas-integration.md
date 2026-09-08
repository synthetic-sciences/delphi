# Atlas integration

This document covers the optional [Atlas](https://github.com/synthetic-sciences/atlas) integration in Delphi. If you don't run an Atlas workspace, you can stop reading — none of this applies, and the tools described here are off by default.

## What it is

Delphi can be the retrieval substrate for an Atlas research graph. An Atlas workspace pushes its **nodes** (claims / hypotheses / plans / decisions / insights), **edges** (typed relationships between nodes), **artifacts** (tables, plots, logs, diffs, metrics attached to a node), **executions** (runs / tool calls against a node), and **tool contracts** (signature + when-to-use + examples) into Delphi as embeddings. Delphi then exposes graph-aware retrieval and context packs over that state, so an agent picking up a long-running research workflow can ask:

- *"What's been tried for X?"*
- *"What did we decide about Y, and why?"*
- *"Don't repeat anything that previously failed."*
- *"Which tools apply to this task, with their contracts?"*

These are very different surfaces from plain code retrieval, and they're useful only when there's an Atlas (or Atlas-shaped) workspace upstream of Delphi.

## Turning it on

The Atlas tools sit behind the `atlas` MCP profile group. The default profile is `code`, which excludes them entirely.

```bash
# Expose only the Atlas tools (+ sources/minimal)
SYNSC_MCP_PROFILE=atlas

# Expose everything (Atlas + code + papers + docs + datasets + research)
SYNSC_MCP_PROFILE=all
```

Why off by default: every tool definition costs tokens on every MCP handshake. An OSS install pointed at a code repo should ship a clean, code-focused tool list — adding 16 graph-ingestion tools that an unconnected user can't drive is pure overhead.

## MCP tools (when `SYNSC_MCP_PROFILE=atlas` or `all`)

### Ingestion — push from Atlas

| Tool | Description |
|------|-------------|
| `atlas_register_workspace` | Register (create or update) an Atlas workspace and link it to the calling user. |
| `atlas_ingest_node` | Index a node (claim / hypothesis / plan / decision / insight). Embeds the node's summary, content, rationale, and outcome as four separate chunks so each participates in retrieval independently. |
| `atlas_ingest_edge` | Add a directed, typed edge between two nodes. |
| `atlas_ingest_artifact` | Attach a table / plot / log / diff / metric to a node, with a preview string for retrieval. |
| `atlas_ingest_execution` | Record a run or tool call against a node, including outcome + duration + linked artifact ids. |
| `atlas_ingest_tool_contract` | Register tool docs (signature, when-to-use, examples). |

### Retrieval — read for agents

| Tool | Description |
|------|-------------|
| `atlas_search_nodes` | Hybrid graph search with artifact-aware and committed-decision boosts (nodes that produced artifacts or carry a committed decision rank higher than nodes that only stated intent). |
| `find_related_nodes` | BFS the graph from a node or a natural-language question. |
| `find_relevant_artifacts` | Search artifacts by preview text plus linked-node text. |
| `atlas_retrieve_tool_contract` | Find tool docs applicable to a task. |
| `summarize_relevant_subgraph` | Compact subgraph summary (shape + size + edges) for a query, useful when an agent wants a layout before drilling in. |
| `build_atlas_context` | Full Atlas-aware context pack: matched nodes + 2-hop subgraph + artifacts + tool contracts + what-was-tried + don't-repeat. Designed to be the single call an agent makes when picking up a workflow. |
| `atlas_what_was_tried` | "What's already been tried for X?" — matched nodes + their executions + outcomes. |
| `atlas_what_not_to_repeat` | "What should I not repeat?" — failed-outcome nodes and failed executions. |
| `atlas_active_work_context` | Recent in-progress nodes — "what was I doing?" |
| `atlas_find_decisions` | Surface committed decisions related to a question, so the agent doesn't contradict prior commitments. |

## How the ingestion is shaped

Each `atlas_ingest_node` call lands four embeddings (summary / content / rationale / outcome) so a vector hit against the *rationale* can independently surface the node even when the summary doesn't match. Combined with BM25, exact-symbol, and graph adjacency in the hybrid retriever, this gives Atlas a meaningfully richer retrieval surface than a pure-content vector index would.

Artifacts ship with a `preview` string (typically the first few rows of a table or the caption of a plot) which is indexed as ordinary text. The artifact itself stays on the Atlas side — Delphi only stores enough to find it.

## Reference

- Service module: `backend/synsc/services/atlas_connector.py` — push API, embedding pipeline, hybrid graph search, context pack builder.
- Schema: `backend/alembic/versions/005_thesis_connector.py` (file name retained as a historical marker; the migration creates the `atlas_*` tables).
- Tests: `backend/tests/test_atlas_connector_surface.py`, `backend/tests/test_mcp_profiles.py`.
