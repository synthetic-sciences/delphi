"""Tests for the retrieval benchmark harness (metrics + retrievers + runner)."""

from __future__ import annotations

from pathlib import Path

from synsc.bench import load_corpus, load_tasks, run_benchmark
from synsc.bench.corpus import Corpus, Document, Task
from synsc.bench.harness import render_markdown
from synsc.bench.metrics import (
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    success_at_k,
)
from synsc.bench.retrievers import BM25Retriever, HybridRetriever, NaiveGrepRetriever

_BENCH_DIR = Path(__file__).resolve().parents[2] / "bench"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_recall_and_precision() -> None:
    retrieved = ["a", "b", "c", "d"]
    relevant = {"a", "c"}
    assert recall_at_k(retrieved, relevant, 4) == 1.0
    assert recall_at_k(retrieved, relevant, 1) == 0.5
    assert precision_at_k(retrieved, relevant, 2) == 0.5
    assert success_at_k(retrieved, relevant, 1) == 1.0
    assert success_at_k(["x"], relevant, 1) == 0.0


def test_reciprocal_rank_and_ndcg() -> None:
    assert reciprocal_rank(["x", "a"], {"a"}) == 0.5
    assert reciprocal_rank(["a", "x"], {"a"}) == 1.0
    assert reciprocal_rank(["x", "y"], {"a"}) == 0.0
    # First-position hit yields perfect nDCG.
    assert ndcg_at_k(["a", "b"], {"a"}, 2) == 1.0
    assert ndcg_at_k(["b", "a"], {"a"}, 2) < 1.0


# ---------------------------------------------------------------------------
# Retrievers on a tiny inline corpus
# ---------------------------------------------------------------------------


def _toy_corpus() -> Corpus:
    return Corpus(
        documents=[
            Document("auth.py", "def validate_token(tok):\n    return verify(tok)", "python"),
            Document("db.py", "def get_connection(dsn):\n    return Pool(dsn)", "python"),
            Document("cache.py", "class Cache:\n    def evict(self):\n        pass", "python"),
        ]
    )


def test_bm25_ranks_relevant_first() -> None:
    corpus = _toy_corpus()
    ranked, cost = BM25Retriever().retrieve(corpus, "validate token", k=3)
    assert ranked[0] == "auth.py"
    assert cost > 0


def test_naive_grep_returns_matches_with_full_cost() -> None:
    corpus = _toy_corpus()
    ranked, cost = NaiveGrepRetriever().retrieve(corpus, "connection", k=3)
    assert "db.py" in ranked
    assert cost > 0


def test_hybrid_finds_symbol_target() -> None:
    corpus = _toy_corpus()
    ranked, _ = HybridRetriever().retrieve(corpus, "where is evict implemented", k=3)
    assert ranked[0] == "cache.py"


# ---------------------------------------------------------------------------
# End-to-end runner over the committed fixture corpus
# ---------------------------------------------------------------------------


def test_run_benchmark_over_fixture_corpus() -> None:
    corpus = load_corpus(_BENCH_DIR / "corpus")
    tasks = load_tasks(_BENCH_DIR / "tasks.json")
    assert len(corpus) >= 10
    assert len(tasks) >= 10

    report = run_benchmark(corpus, tasks, k=5)
    by_name = {r.name: r for r in report.results}

    # Hybrid should rank the right file first at least as often as naive grep,
    # and read far fewer tokens than dumping every grep match.
    assert by_name["hybrid"].metrics["mrr"] >= by_name["naive_grep"].metrics["mrr"]
    assert by_name["hybrid"].avg_token_cost <= by_name["naive_grep"].avg_token_cost
    # Symbol retrieval is the most token-economical strategy here.
    assert by_name["symbol"].avg_token_cost < by_name["naive_grep"].avg_token_cost

    md = render_markdown(report)
    assert "Delphi Retrieval Benchmark" in md
    assert "hybrid" in md


def test_relevant_symbols_resolve_to_files() -> None:
    corpus = load_corpus(_BENCH_DIR / "corpus")
    # A task referencing only a symbol should still resolve to its file.
    task = Task(task_id="t", query="validate token", relevant_symbols=["validate_token"])
    from synsc.bench.harness import _relevant_set

    relevant = _relevant_set(corpus, task)
    assert "auth/tokens.py" in relevant
