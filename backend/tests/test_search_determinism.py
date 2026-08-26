"""Identical searches must return identical results within a process.

Three stages used to break that: hosted chat models resample at temperature 0
(query expansion, listwise rerank), hosted embedding APIs jitter, and fusion
ties fell back to insertion order. These tests pin the caching and total-order
behavior that closes each hole.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

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


def test_cache_singleflights_concurrent_computation_for_same_key():
    cache = BoundedCache(4)
    calculation_started = threading.Event()
    release_calculation = threading.Event()
    second_started = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def calculate() -> str:
        nonlocal calls
        with calls_lock:
            calls += 1
        calculation_started.set()
        assert release_calculation.wait(timeout=2)
        return "first answer"

    def second_call() -> str:
        second_started.set()
        return cache.get_or_compute("same-key", calculate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get_or_compute, "same-key", calculate)
        assert calculation_started.wait(timeout=1)
        second = pool.submit(second_call)
        assert second_started.wait(timeout=1)
        release_calculation.set()

    assert first.result() == "first answer"
    assert second.result() == "first answer"
    assert calls == 1


def test_cache_shares_transient_none_with_waiters_but_does_not_store_it():
    cache = BoundedCache(4)
    calculation_started = threading.Event()
    release_calculation = threading.Event()
    second_started = threading.Event()
    calls = 0

    def calculate():
        nonlocal calls
        calls += 1
        calculation_started.set()
        assert release_calculation.wait(timeout=2)
        return None if calls == 1 else "divergent retry"

    def second_call():
        second_started.set()
        return cache.get_or_compute("same-key", calculate)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get_or_compute, "same-key", calculate)
        assert calculation_started.wait(timeout=1)
        second = pool.submit(second_call)
        assert second_started.wait(timeout=1)
        time.sleep(0.05)
        release_calculation.set()

    assert first.result() is None
    assert second.result() is None
    assert calls == 1
    assert cache.get_or_compute("same-key", lambda: "later retry") == (
        "later retry"
    )


def test_cache_shares_transient_exception_with_waiters():
    cache = BoundedCache(4)
    calculation_started = threading.Event()
    release_calculation = threading.Event()
    calls = 0

    def calculate():
        nonlocal calls
        calls += 1
        calculation_started.set()
        assert release_calculation.wait(timeout=2)
        raise RuntimeError("provider unavailable")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get_or_compute, "same-key", calculate)
        assert calculation_started.wait(timeout=1)
        second = pool.submit(cache.get_or_compute, "same-key", calculate)
        time.sleep(0.05)
        release_calculation.set()

    with pytest.raises(RuntimeError, match="provider unavailable"):
        first.result()
    with pytest.raises(RuntimeError, match="provider unavailable"):
        second.result()
    assert calls == 1
    assert cache.get_or_compute("same-key", lambda: "later retry") == (
        "later retry"
    )


def test_get_cache_rebuilds_when_capacity_changes():
    first = get_cache("test-namespace", 4)
    first.put("k", "v")
    same = get_cache("test-namespace", 4)
    assert same.get("k") == "v"
    resized = get_cache("test-namespace", 8)
    assert resized.get("k") is None


def test_persistent_cache_survives_instance_recreation(tmp_path):
    cache_path = tmp_path / "search-cache.sqlite3"
    first = BoundedCache(
        4,
        namespace="query-expansion",
        persistent_path=cache_path,
    )
    assert first.get_or_compute("same-key", lambda: "first answer") == (
        "first answer"
    )

    recreated = BoundedCache(
        4,
        namespace="query-expansion",
        persistent_path=cache_path,
    )

    assert recreated.get_or_compute(
        "same-key",
        lambda: pytest.fail("persisted answer was not reused"),
    ) == "first answer"


def test_persistent_cache_singleflights_across_live_instances(tmp_path):
    cache_path = tmp_path / "search-cache.sqlite3"
    first = BoundedCache(
        4,
        namespace="query-expansion",
        persistent_path=cache_path,
    )
    second = BoundedCache(
        4,
        namespace="query-expansion",
        persistent_path=cache_path,
    )
    calculation_started = threading.Event()
    release_calculation = threading.Event()
    second_calculation_started = threading.Event()

    def calculate_first() -> str:
        calculation_started.set()
        assert release_calculation.wait(timeout=2)
        return "first answer"

    def calculate_second() -> str:
        second_calculation_started.set()
        return "divergent answer"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(
            first.get_or_compute,
            "same-key",
            calculate_first,
        )
        assert calculation_started.wait(timeout=1)
        second_result = pool.submit(
            second.get_or_compute,
            "same-key",
            calculate_second,
        )
        time.sleep(0.05)
        release_calculation.set()

    assert first_result.result() == "first answer"
    assert second_result.result() == "first answer"
    assert not second_calculation_started.is_set()


def test_persistent_cache_round_trips_numpy_vectors(tmp_path):
    cache_path = tmp_path / "search-cache.sqlite3"
    vector = np.arange(6, dtype=np.float32).reshape(2, 3)
    first = BoundedCache(
        4,
        namespace="query-embedding",
        persistent_path=cache_path,
    )
    first.put("vector-key", vector)

    recreated = BoundedCache(
        4,
        namespace="query-embedding",
        persistent_path=cache_path,
    )
    cached = recreated.get("vector-key")

    assert isinstance(cached, np.ndarray)
    assert cached.dtype == np.float32
    assert np.array_equal(cached, vector)


def test_persistent_cache_evicts_oldest_entry(tmp_path):
    cache_path = tmp_path / "search-cache.sqlite3"
    first = BoundedCache(
        2,
        namespace="listwise-rerank",
        persistent_path=cache_path,
    )
    first.put("oldest", "one")
    first.put("middle", "two")
    first.put("newest", "three")

    recreated = BoundedCache(
        2,
        namespace="listwise-rerank",
        persistent_path=cache_path,
    )

    assert recreated.get("oldest") is None
    assert recreated.get("middle") == "two"
    assert recreated.get("newest") == "three"


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
