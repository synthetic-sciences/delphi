"""Identical searches must return identical results within a process.

Three stages used to break that: hosted chat models resample at temperature 0
(query expansion, listwise rerank), hosted embedding APIs jitter, and fusion
ties fell back to insertion order. These tests pin the caching and total-order
behavior that closes each hole.
"""
from __future__ import annotations

import numpy as np

from synsc.core.llm_cache import BoundedCache, get_cache
from synsc.services.hybrid_retrieval import Candidate, fuse_candidates


def test_cache_key_is_stable_and_input_sensitive():
    assert BoundedCache.key("a", "b") == BoundedCache.key("a", "b")
    assert BoundedCache.key("a", "b") != BoundedCache.key("ab", "")
    assert BoundedCache.key("model-1", "q") != BoundedCache.key("model-2", "q")


def test_cache_returns_first_answer_and_evicts_oldest():
    cache = BoundedCache(2)
    cache.put("k1", "first")
    cache.put("k1", "second")
    assert cache.get("k1") == "second"
    cache.put("k2", "x")
    cache.get("k1")  # refresh k1 so k2 is the eviction victim
    cache.put("k3", "y")
    assert cache.get("k2") is None
    assert cache.get("k1") == "second"
    assert cache.get("k3") == "y"


def test_cache_size_zero_disables_storage():
    cache = BoundedCache(0)
    cache.put("k", "v")
    assert cache.get("k") is None


def test_get_cache_rebuilds_when_capacity_changes():
    first = get_cache("test-namespace", 4)
    first.put("k", "v")
    same = get_cache("test-namespace", 4)
    assert same.get("k") == "v"
    resized = get_cache("test-namespace", 8)
    assert resized.get("k") is None


def _candidate(chunk_id: str, source: str, score: float) -> Candidate:
    return Candidate(
        chunk_id=chunk_id,
        file_path=f"src/{chunk_id}.py",
        content="body",
        sources={source: score},
    )


def test_fusion_ties_break_by_chunk_id_not_arrival_order():
    # Two chunks at the same rank in two equally-weighted branches have the
    # same reciprocal-rank score and the same raw score; only the chunk_id
    # tiebreak keeps the output order independent of arrival order.
    forward = fuse_candidates([
        [_candidate("aaa", "vector", 0.9)],
        [_candidate("bbb", "bm25", 0.9)],
    ], weights={"vector": 1.0, "bm25": 1.0})
    swapped = fuse_candidates([
        [_candidate("bbb", "bm25", 0.9)],
        [_candidate("aaa", "vector", 0.9)],
    ], weights={"vector": 1.0, "bm25": 1.0})
    assert [c.chunk_id for c in forward] == [c.chunk_id for c in swapped]


def test_fusion_output_is_repeatable_for_identical_inputs():
    def branches() -> list[list[Candidate]]:
        return [
            [_candidate("v1", "vector", 0.8), _candidate("v2", "vector", 0.7)],
            [_candidate("v2", "bm25", 11.0), _candidate("b1", "bm25", 9.0)],
        ]

    first = [c.chunk_id for c in fuse_candidates(branches())]
    second = [c.chunk_id for c in fuse_candidates(branches())]
    assert first == second


def test_query_embedding_cache_round_trips_numpy_vectors():
    cache = get_cache("test-embed", 4)
    vector = np.arange(4, dtype=np.float32)
    key = BoundedCache.key("model", "query text")
    cache.put(key, vector)
    cached = cache.get(key)
    assert cached is not None
    assert np.array_equal(cached, vector)
