export const DEVELOPER_PILOT = {
  tasks: 40,
  model: "Claude Opus 5",
  delphiPassAtOne: 95,
  nextBestPassAtOne: 90,
} as const;

export const RETRIEVAL_AUDIT = {
  attempted: 75,
  strictValid: 18,
  excludedTruncated: 57,
  delphiLatencySeconds: 1.25,
  comparatorLatencySeconds: 26.58,
  latencyRatio: 21.3,
  delphiMrr: 0.188,
  comparatorMrr: 0.329,
  delphiRecall5: 0.361,
  comparatorRecall5: 0.5,
  delphiRecall10: 0.472,
  comparatorRecall10: 0.639,
  delphiRecall20: 0.667,
  comparatorRecall20: 0.639,
  recall20Ci: "[-0.094, 0.139]",
} as const;

export const ARTICLE = {
  slug: "context-engine-is-the-product",
  href: "/blog/context-engine-is-the-product",
  title: "The context engine is the product",
  dek: "What a fixed-model developer benchmark taught us about retrieval, latency, corpus fidelity, and the difference between finding a file and helping an agent finish the work.",
  published: "July 29, 2026",
  publishedIso: "2026-07-29",
  readingTime: "11 min read",
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
    title: "The corpus gets audited",
    body: "We remove 57 truncated scored targets before comparing repository retrieval on the 18 strict-valid cases.",
  },
  {
    date: "July 2026",
    title: "The downstream result",
    body: "Delphi reaches 95.0% pass@1—the strongest result in our fixed-model, 40-task developer pilot.",
  },
] as const;

export const PIPELINE = [
  ["01", "Index", "Immutable source versions"],
  ["02", "Retrieve", "Semantic, lexical, symbol, path, structural"],
  ["03", "Fuse", "Rank and diversify evidence"],
  ["04", "Assemble", "Token-bounded context with provenance"],
  ["05", "Act", "Write and verify the change"],
] as const;
