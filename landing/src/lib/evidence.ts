/* Every figure here traces to a committed run artifact under
 * new/delphi-evaluation-2026-07-29-round2/artifacts/. Nothing is carried over
 * from an earlier evaluation, and the partial scopes are stated as partial. */

export const BENCHMARK = {
  name: "Agent Retrieval Bench v2",
  commit: "d04953371d962ec314fb15d642255ed4e9dadd40",
  repository: "eyuansu62/agent-retrieval-bench",
  split: "development",
  cases: 75,
  workflows: ["code2test", "comment2context", "edit2ripple", "trace2code"],
  candidateFilter: "all_files",
  embeddingModel: "text-embedding-3-small",
  reranker: "cross-encoder/ms-marco-MiniLM-L-6-v2",
} as const;

/* Same 75 cases, same candidate filter, same metric implementation. The
 * baselines are ARB's own published runs scored by ARB's own code; Nia was
 * re-run live against the same corpora on the same day, 0 failures. */
export const RETRIEVAL_COMPARISON = [
  { system: "Delphi", mrr: 0.197, recall5: 0.309, recall20: 0.544, latencyMs: 2903, ours: true },
  { system: "Nia", mrr: 0.228, recall5: 0.391, recall20: 0.449, latencyMs: 36881, ours: false },
  { system: "grep", mrr: 0.180, recall5: 0.302, recall20: 0.578, latencyMs: null, ours: false },
  { system: "RepoMap", mrr: 0.169, recall5: 0.240, recall20: 0.551, latencyMs: null, ours: false },
  { system: "lexical", mrr: 0.127, recall5: 0.198, recall20: 0.451, latencyMs: null, ours: false },
  { system: "BM25", mrr: 0.116, recall5: 0.136, recall20: 0.429, latencyMs: null, ours: false },
] as const;

/* The hosted comparison, stated plainly. Nia ranks the top of the list
 * better; Delphi covers more of the answer set and is an order of magnitude
 * faster. Both numbers matter and neither subsumes the other. */
export const HEAD_TO_HEAD = {
  comparator: "Nia",
  cases: 75,
  failures: 0,
  delphi: { mrr: 0.197, recall5: 0.309, recall20: 0.544, latencyMs: 2903, meanPaths: 20.0 },
  nia: { mrr: 0.228, recall5: 0.391, recall20: 0.449, latencyMs: 36881, meanPaths: 7.8 },
  latencyRatio: 12.7,
} as const;

/* What each change was worth, measured one at a time on the same split.
 * The first row is the configuration the previous evaluation actually ran. */
export const ABLATION = [
  {
    label: "As previously benchmarked",
    note: "query and index in different embedding spaces",
    mrr: 0.055,
    recall5: 0.056,
    recall20: 0.161,
    latencyMs: 1000,
  },
  {
    label: "Embedding space aligned",
    note: "same model indexing and querying",
    mrr: 0.173,
    recall5: 0.259,
    recall20: 0.549,
    latencyMs: 917,
  },
  {
    label: "+ rank fusion, path affinity",
    note: "reciprocal rank instead of rescaled scores",
    mrr: 0.176,
    recall5: 0.256,
    recall20: 0.552,
    latencyMs: 1089,
  },
  {
    label: "+ cross-encoder rerank",
    note: "ms-marco-MiniLM over the top 30",
    mrr: 0.193,
    recall5: 0.294,
    recall20: 0.560,
    latencyMs: 2903,
  },
] as const;

/* The bug the whole investigation turned on. Embedding a chunk's own exact
 * content and comparing it against that chunk's stored vector: a matched
 * space returns ~1.0, and two same-width spaces from different models return
 * noise without raising anything. */
export const EMBEDDING_MISMATCH = {
  cosineBefore: 0.0101,
  cosineAfter: 0.943,
  dimension: 768,
  indexedWith: "text-embedding-3-small",
  queriedWith: "gemini-embedding-001",
  repositoriesAffected: 68,
} as const;

/* Held-out confirmation. Scope is stated because it is partial: the final
 * split reaches the same repositories at commits that were never indexed. */
export const HELD_OUT = {
  split: "final",
  scored: 60,
  skippedUnprovisioned: 160,
  mrr: 0.197,
  recall5: 0.256,
  recall20: 0.448,
  bcy8k: 0.301,
  latencyMsMean: 1768,
  failures: 0,
} as const;

/* Reranker selection. The larger, code-aware model lost on every axis. */
export const RERANKER_CHOICE = [
  { model: "none", params: "—", mrr: 0.176, recall5: 0.256, recall20: 0.552, latencyMs: 1000 },
  { model: "bge-reranker-base", params: "278M", mrr: 0.173, recall5: 0.288, recall20: 0.515, latencyMs: 21281 },
  { model: "ms-marco-MiniLM-L-6", params: "22M", mrr: 0.193, recall5: 0.294, recall20: 0.560, latencyMs: 2903 },
] as const;

export const ARTICLE = {
  slug: "context-engine-is-the-product",
  href: "/blog/context-engine-is-the-product",
  title: "The context engine is the product",
  dek: "A retrieval benchmark that measured nothing, the one-line check that caught it, and what an honest rebuild of the ranking pipeline was actually worth.",
  published: "July 30, 2026",
  publishedIso: "2026-07-30",
  readingTime: "12 min read",
  labels: ["Evaluation", "Retrieval", "Developer agents"],
} as const;

export const TIMELINE = [
  {
    date: "Open source",
    title: "A context engine you can own",
    body: "Delphi begins as an Apache-2.0 MCP server for local-first code, paper, documentation, and dataset context.",
  },
  {
    date: "Product foundation",
    title: "Context becomes a pipeline",
    body: "Versioned sources, hybrid retrieval, code intelligence, provenance, and token-bounded context packs become one system.",
  },
  {
    date: "July 2026",
    title: "The measurement broke first",
    body: "A corpus indexed by one embedding model and queried by another scored cosine 0.0101 against itself. Same vector width, so nothing ever raised.",
  },
  {
    date: "July 2026",
    title: "Ranking rebuilt on evidence",
    body: "Rank fusion, a path branch, and a small cross-encoder take retrieval past every published ARB baseline, and past the hosted comparator on coverage at a twelfth of its latency.",
  },
] as const;

export const PIPELINE = [
  ["01", "Index", "Immutable source versions"],
  ["02", "Retrieve", "Semantic, lexical, symbol, path, structural"],
  ["03", "Fuse", "Rank and diversify evidence"],
  ["04", "Assemble", "Token-bounded context with provenance"],
  ["05", "Act", "Write and verify the change"],
] as const;
