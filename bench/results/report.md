# Delphi Retrieval Benchmark

Corpus: **12 files** · Tasks: **12** · k = **5**

| Retriever | recall@5 | precision@5 | success@5 | ndcg@5 | mrr | avg tokens read |
|---|---|---|---|---|---|---|
| naive_grep | 0.917 | 0.431 | 0.917 | 0.633 | 0.540 | 364 (1.0× leaner) |
| smart_grep | 0.917 | 0.403 | 0.917 | 0.763 | 0.720 | 300 (1.2× leaner) |
| bm25 | 0.917 | 0.431 | 0.917 | 0.844 | 0.819 | 280 (1.3× leaner) |
| symbol | 0.833 | 0.549 | 0.833 | 0.772 | 0.750 | 166 (2.2× leaner) |
| hybrid | 0.917 | 0.403 | 0.917 | 0.844 | 0.831 | 302 (1.2× leaner) |

> Token economy is measured against `naive_grep` (dump every file with a token match), which is what an agent does without a retrieval layer.

