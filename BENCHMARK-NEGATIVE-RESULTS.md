# Measured and rejected

Every idea below was implemented, measured on the Agent Retrieval Bench v2
development split, and rejected. They are recorded so nobody spends the
afternoon rediscovering them.

The pattern worth internalising: **four** of these looked like wins on the
75-case development split and lost on the 220-case held-out split. Development
differences under about 0.03 are not trustworthy at that sample size, and where
a language model is in the loop the run-to-run variance alone is about 0.02 —
the same configuration scored Recall@5 0.367 and 0.391 on two different runs.
Every candidate change here was confirmed on the held-out split before shipping,
and four did not survive it.

| Idea | Result |
| --- | --- |
| **File-evidence aggregation** — score a file by its best chunk plus damped support from its other chunks, since ARB scores files while Delphi ranks chunks | Rejected at every weight. Recall@20 0.544 → 0.467 at w=0.5. Many gold files match on exactly one chunk, so rewarding breadth pushes them down. |
| **Deeper candidate pools** — 50 → 100 → 150 per branch | No gain. MRR 0.197 / 0.195 / 0.194. Candidate supply was never the constraint. |
| **Deeper rerank window** — k=30 → 60 → 100 | Monotonically worse. R@20 0.560 → 0.552 → 0.444. The cross-encoder promotes plausible-looking files from the tail. |
| **Pure cross-encoder ordering** — blend_alpha 1.0 | Worst configuration tested. MRR 0.193 → 0.154. Blending over the fused score is what makes reranking useful. |
| **Larger code-aware reranker** — bge-reranker-base (278M) vs ms-marco-MiniLM (22M) | The 12x larger model lost on every metric and ran 7x slower. MRR 0.173 vs 0.193, latency 21.3s vs 2.9s. |
| **Fusion weight rebalancing** — 5 configurations including lexical-heavy and vector-heavy | Existing defaults already at or near optimum; spread across the top three inside noise. Lexical-heavy was clearly worse once embeddings were aligned. |
| **Reverse-dependency branch at a global weight** | Real capability, wrong mechanism. edit2ripple R@5 0.238 → 0.381 at w=0.3, but overall MRR 0.193 → 0.163: the three workflows whose answer is not a dependent pay for it. Kept, defaulted off, needs query-intent gating. See PR #77. |
| **File path prepended to rerank passages** | Looked like a win on development (R@5 0.327 → 0.333) and lost on held-out (0.355 → 0.346, trace2code 0.763 → 0.697). Discarded. |
| **Cascade listwise: second pass over the top 6 with 1200-char excerpts** | Aimed squarely at MRR, which is decided by rank 1. Bought +0.001 MRR on held-out and cost 0.036 Recall@5, 0.017 Recall@20, and a second per query. Re-reading a head the model has already ordered shuffles it without improving the first decision. |
| **Listwise rerank tuning: shallower window, longer excerpts** | k=12 with 700-char excerpts looked best on development (R@5 0.411 vs 0.391) and lost on held-out (0.378 vs 0.419, MRR 0.260 vs 0.285). Shipped defaults k=20 / 280 chars unchanged. Longer excerpts at k=20 were clearly worse on both splits. |

## What did work

| Change | Effect |
| --- | --- |
| Aligning the query-time embedding model to the index | The whole result. Workflow-macro MRR 0.055 → 0.173. |
| Reciprocal-rank fusion instead of max-normalized scores | Removed the manufactured 1.0 that let a weak branch's top hit outrank multi-branch agreement. |
| Path-affinity branch | File paths were not searchable text at all. |
| ms-marco-MiniLM rerank at k=30, alpha=0.4 | MRR 0.176 → 0.193 for ~1.9s. |
| Hypothetical-document query expansion | Held-out MRR 0.228 → 0.241, R@20 0.552 → 0.579. |
| Listwise reranking of the retrieved head | Held-out MRR 0.241 → 0.285, R@5 0.355 → 0.419, BCY@8k 0.376 → 0.446. Worth more than everything else combined. |
