# Delphi Retrieval Benchmark

A small, **reproducible** harness for measuring retrieval quality and token
economy. The whole point: claims like "better retrieval" are meaningless
without numbers you can reproduce. This benchmark produces them with one
command, no database and no network required.

```bash
# from the repo root
uv run --project backend python bench/run.py
```

It writes `results/report.md` (a leaderboard) and `results/report.json`.

## What it measures

Each **task** is a natural-language query plus the set of files/symbols that
answer it (`tasks.json`). Every **retriever** returns a ranked list of files;
we score it against the relevant set with standard IR metrics:

| Metric | Meaning |
|---|---|
| `recall@k` | fraction of relevant files found in the top-k |
| `precision@k` | fraction of the top-k that are relevant |
| `success@k` | did *any* relevant file land in the top-k |
| `ndcg@k` | rank-weighted relevance (earlier hits score higher) |
| `mrr` | mean reciprocal rank of the first relevant hit |
| `avg tokens read` | tokens an agent must read to consume the answer |

**Token economy** is the load-bearing axis for agents: a retriever that finds
the answer but forces the model to read 20k tokens of unranked grep output is
worse, in practice, than one that returns the right 200 tokens. We measure it
relative to `naive_grep` — what an agent does *without* a retrieval layer.

## Retrievers (baselines + Delphi's strategy)

- **naive_grep** — dump every file containing a query token, unranked. The
  "no retrieval layer" baseline.
- **smart_grep** — identifier/definition-aware ranking (ripgrep + def patterns).
- **bm25** — classic lexical ranking.
- **symbol** — exact symbol-name lookup via Delphi's tree-sitter parsers.
- **hybrid** — normalized fusion of BM25 + symbol + substring, mirroring the
  strategy Delphi ships in `backend/synsc/services/hybrid_retrieval.py`.

## Sample results

Run against the bundled 12-file, 12-task fixture corpus (`corpus/`):

<!-- numbers come from `bench/results/report.md`; regenerate with bench/run.py -->

| Retriever | recall@5 | precision@5 | ndcg@5 | mrr | avg tokens read |
|---|---|---|---|---|---|
| naive_grep | 0.917 | 0.431 | 0.633 | 0.540 | 364 (1.0×) |
| smart_grep | 0.917 | 0.403 | 0.763 | 0.720 | 300 (1.2×) |
| bm25 | 0.917 | 0.431 | 0.844 | 0.819 | 280 (1.3×) |
| symbol | 0.833 | 0.549 | 0.772 | 0.750 | 166 (2.2×) |
| **hybrid** | **0.917** | 0.403 | **0.844** | **0.831** | 302 (1.2×) |

Takeaways on this corpus: hybrid matches the best recall while topping MRR and
nDCG (it puts the right file first more often), and the symbol retriever is the
most precise and leanest. Naive grep matches on recall but ranks worst — the
agent pays for it in tokens and wrong-first results.

## Benchmark your own codebase

```bash
uv run --project backend python bench/run.py \
    --corpus /path/to/repo \
    --tasks  /path/to/tasks.json \
    --k 5 --out /tmp/delphi-bench
```

`tasks.json` is a list of objects:

```json
[
  {
    "id": "validate-tokens",
    "query": "where are session tokens validated",
    "relevant_files": ["auth/tokens.py"],
    "relevant_symbols": ["validate_token"],
    "category": "definition"
  }
]
```

## Scope & honesty

This harness measures the **retrieval strategy** (lexical + symbol fusion) on a
fixture corpus, in-process. It is intentionally database-free so it always
reproduces. It is *not* the same as the production pgvector + cross-encoder
pipeline — semantic/embedding recall is not exercised here. A `--live` mode that
drives a running Delphi server (`/v1/search/code`) and adds the vector + rerank
path is the natural next extension; the metrics and task format are designed to
carry straight over.

Limitations are explicit on purpose: a benchmark that only flatters the tool is
marketing, not measurement.
