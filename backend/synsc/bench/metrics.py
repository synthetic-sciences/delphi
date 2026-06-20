"""Retrieval metrics: recall@k, precision@k, MRR, success@k, nDCG@k."""

from __future__ import annotations

import math
from statistics import mean


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = retrieved[:k]
    hits = sum(1 for r in top if r in relevant)
    return hits / len(relevant)


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top = retrieved[:k]
    if not top:
        return 0.0
    hits = sum(1 for r in top if r in relevant)
    return hits / len(top)


def success_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """1.0 if any relevant doc is in the top-k, else 0.0."""
    return 1.0 if any(r in relevant for r in retrieved[:k]) else 0.0


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for i, doc_id in enumerate(retrieved, start=1):
        if doc_id in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    dcg = 0.0
    for i, doc_id in enumerate(retrieved[:k], start=1):
        if doc_id in relevant:
            dcg += 1.0 / math.log2(i + 1)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def task_metrics(retrieved: list[str], relevant: set[str], k: int) -> dict[str, float]:
    """Compute all per-task metrics for one ranked result list."""
    return {
        f"recall@{k}": recall_at_k(retrieved, relevant, k),
        f"precision@{k}": precision_at_k(retrieved, relevant, k),
        f"success@{k}": success_at_k(retrieved, relevant, k),
        f"ndcg@{k}": ndcg_at_k(retrieved, relevant, k),
        "mrr": reciprocal_rank(retrieved, relevant),
    }


def aggregate_metrics(per_task: list[dict[str, float]]) -> dict[str, float]:
    """Mean each metric across tasks."""
    if not per_task:
        return {}
    keys = per_task[0].keys()
    return {key: mean(t[key] for t in per_task) for key in keys}
