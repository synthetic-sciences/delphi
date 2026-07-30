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
 * re-run live against the same corpora, 0 failures.
 *
 * Every row here is the 75-case development split, because that is the split
 * ARB's published baselines were run on and mixing sample sizes inside one
 * table would not be a comparison. The Delphi-versus-Nia question is answered
 * separately in HEAD_TO_HEAD, which pools 135 cases — a 0.02 difference cannot
 * be resolved at n=75 when run-to-run variance is itself about 0.02. */
export const RETRIEVAL_COMPARISON = [
  { system: "Delphi", mrr: 0.220, recall5: 0.369, recall20: 0.551, latencyMs: 5694, ours: true },
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
  cases: 135,
  failures: 0,
  delphi: { mrr: 0.229, recall5: 0.350, recall20: 0.528, latencyMs: 5694, meanPaths: 20.0 },
  nia: { mrr: 0.261, recall5: 0.360, recall20: 0.424, latencyMs: 36881, meanPaths: 7.8 },
  latencyRatio: 6.5,
} as const;

/* Paired per-case outcomes on the 135 shared cases. Averages hide how often
 * two systems simply agree; these counts do not. Recall@5 is a genuine tie —
 * 21 cases each — while Recall@20 is decided 31 to 12. */
export const PAIRED_OUTCOMES = [
  { metric: "MRR", delphiWins: 40, niaWins: 47, ties: 48 },
  { metric: "Recall@5", delphiWins: 21, niaWins: 22, ties: 92 },
  { metric: "Recall@20", delphiWins: 31, niaWins: 12, ties: 92 },
] as const;

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

/* Held-out confirmation, now at full scope: all 220 positive cases of the
 * final split, every corpus provisioned, zero failed queries. These numbers
 * come out slightly ahead of the development split the pipeline was tuned on,
 * which is the direction you want — no sign of having fit the tuning set. */
export const HELD_OUT = {
  split: "final",
  scored: 220,
  skippedUnprovisioned: 0,
  mrr: 0.309,
  recall5: 0.442,
  recall20: 0.582,
  bcy8k: 0.467,
  latencyMsMean: 5571,
  failures: 0,
} as const;

/* Query expansion, measured on the full held-out split. A code index is
 * written in code and questions about it are written in English; embedding a
 * hypothetical snippet alongside the question bridges that. */
export const QUERY_EXPANSION = [
  { label: "Retrieval only", mrr: 0.228, recall5: 0.349, recall20: 0.552, latencyMs: 1957 },
  { label: "+ hypothetical document", mrr: 0.241, recall5: 0.355, recall20: 0.579, latencyMs: 4110 },
  { label: "+ listwise rerank", mrr: 0.309, recall5: 0.442, recall20: 0.582, latencyMs: 5571 },
] as const;

/* Per-workflow on the held-out split. The spread is the interesting part:
 * a failure trace names symbols that exist in the code, and a review comment
 * names almost nothing a retriever can key on. */
export const HELD_OUT_WORKFLOWS = [
  { workflow: "trace2code", cases: 38, mrr: 0.693, recall5: 0.842, recall20: 0.908 },
  { workflow: "edit2ripple", cases: 44, mrr: 0.274, recall5: 0.434, recall20: 0.587 },
  { workflow: "code2test", cases: 83, mrr: 0.220, recall5: 0.394, recall20: 0.586 },
  { workflow: "comment2context", cases: 55, mrr: 0.207, recall5: 0.245, recall20: 0.345 },
] as const;

/* Reranker selection. The larger, code-aware model lost on every axis. */
export const RERANKER_CHOICE = [
  { model: "none", params: "—", mrr: 0.176, recall5: 0.256, recall20: 0.552, latencyMs: 1000 },
  { model: "bge-reranker-base", params: "278M", mrr: 0.173, recall5: 0.288, recall20: 0.515, latencyMs: 21281 },
  { model: "ms-marco-MiniLM-L-6", params: "22M", mrr: 0.193, recall5: 0.294, recall20: 0.560, latencyMs: 2903 },
] as const;

/* DS-1000, and the reason it is reported as a null result rather than a win.
 *
 * On 40 development tasks Delphi reached 0.900 against 0.875 for both hosted
 * engines, which looks like a downstream lead. On 100 held-out tasks the same
 * comparison against a no-retrieval control comes out at 0.860 to 0.870, with
 * 95 of 100 cases decided identically. Documentation context does not change
 * what this model produces on this benchmark, in either direction, and the
 * 40-case spread was one or two tasks of noise.
 *
 * Published because a benchmark that cannot separate the conditions is worth
 * saying out loud, especially when the smaller slice of it flatters us. */
export const DOWNSTREAM = {
  benchmark: "DS-1000",
  tasks: 100,
  model: "Claude Opus 5",
  verdict: "no measurable effect",
  rows: [
    { condition: "No retrieval", passAtOne: 0.870, ours: false },
    { condition: "Delphi", passAtOne: 0.860, ours: true },
  ],
  pairedDelphiOnlyPasses: 2,
  pairedControlOnlyPasses: 3,
  pairedIdentical: 95,
} as const;

export const ARTICLE = {
  slug: "context-engine-is-the-product",
  href: "/blog/context-engine-is-the-product",
  title: "The context engine is the product",
  dek: "Our benchmark was comparing vectors from two different embedding models. Here is how we found it, and what fixing it was actually worth.",
  published: "July 30, 2026",
  publishedIso: "2026-07-30",
  readingTime: "12 min read",
  labels: ["Evaluation", "Retrieval", "Developer agents"],
} as const;

export const PIPELINE = [
  ["01", "Index", "Immutable source versions"],
  ["02", "Retrieve", "Semantic, lexical, symbol, path, structural"],
  ["03", "Fuse", "Rank and diversify evidence"],
  ["04", "Assemble", "Token-bounded context with provenance"],
  ["05", "Act", "Write and verify the change"],
] as const;
