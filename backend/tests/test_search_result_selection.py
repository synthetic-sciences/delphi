from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

from synsc.services.hybrid_retrieval import Candidate
from synsc.services.search_service import (
    _select_file_diverse_results,
    _select_source_diverse_results,
)


def _result(
    chunk_id: str,
    file_path: str,
    similarity: float,
    *,
    file_id: str = "",
    repo_id: str = "",
) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "file_id": file_id,
        "file_path": file_path,
        "repo_id": repo_id,
        "similarity": similarity,
        "content": chunk_id,
    }


class _FakeEmbeddingGenerator:
    def generate_single(self, _query: str) -> list[float]:
        return [1.0, 0.0]


class _FakeSession:
    def execute(self, *_args, **_kwargs) -> None:
        return None


@contextmanager
def _fake_session() -> Iterator[_FakeSession]:
    yield _FakeSession()


def _agent_candidates() -> list[Candidate]:
    candidates = [
        Candidate(
            chunk_id="a-1",
            file_id="file-a",
            file_path="src/a.py",
            content="first",
        ),
        Candidate(
            chunk_id="a-2",
            file_id="file-a",
            file_path="src/a.py",
            content="second",
        ),
        Candidate(
            chunk_id="b-1",
            file_id="file-b",
            file_path="src/b.py",
            content="third",
        ),
    ]
    for index, candidate in enumerate(candidates):
        candidate.fused_score = 1.0 - index * 0.1
        candidate.sources["vector"] = candidate.fused_score
    return candidates


def _stub_agent_search(monkeypatch, candidates: list[Candidate]):
    import synsc.services.hybrid_retrieval as hybrid_module
    import synsc.services.search_service as search_module

    monkeypatch.setattr(search_module, "get_session", _fake_session)
    monkeypatch.setattr(
        search_module,
        "get_embedding_generator",
        lambda: _FakeEmbeddingGenerator(),
    )
    monkeypatch.setattr(
        hybrid_module,
        "hybrid_retrieve",
        lambda **_kwargs: candidates,
    )
    monkeypatch.setattr(
        search_module,
        "_enrich_results_with_context",
        lambda results: results,
    )
    return search_module


def test_file_diversity_preserves_ranked_first_hit_per_file() -> None:
    ranked = [
        _result("a-1", "src/a.py", 0.9),
        _result("a-2", "src/a.py", 0.85),
        _result("b-1", "src/b.py", 0.8),
        _result("c-1", "src/c.py", 0.7),
    ]

    selected = _select_file_diverse_results(ranked, top_k=3)

    assert [row["chunk_id"] for row in selected] == ["a-1", "b-1", "c-1"]


def test_file_diversity_fills_remaining_slots_in_original_order() -> None:
    ranked = [
        _result("a-1", "src/a.py", 0.9),
        _result("a-2", "src/a.py", 0.85),
        _result("b-1", "src/b.py", 0.8),
        _result("b-2", "src/b.py", 0.75),
    ]

    selected = _select_file_diverse_results(ranked, top_k=4)

    assert [row["chunk_id"] for row in selected] == [
        "a-1",
        "b-1",
        "a-2",
        "b-2",
    ]


def test_file_diversity_treats_missing_paths_as_distinct_chunks() -> None:
    ranked = [
        _result("unknown-1", "", 0.9),
        _result("unknown-2", "", 0.8),
    ]

    selected = _select_file_diverse_results(ranked, top_k=2)

    assert [row["chunk_id"] for row in selected] == [
        "unknown-1",
        "unknown-2",
    ]


def test_file_diversity_keeps_same_path_from_distinct_repositories() -> None:
    ranked = [
        _result(
            "repo-a-readme",
            "README.md",
            0.9,
            file_id="file-a",
            repo_id="repo-a",
        ),
        _result(
            "repo-b-readme",
            "README.md",
            0.8,
            file_id="file-b",
            repo_id="repo-b",
        ),
        _result(
            "repo-c-source",
            "src/main.py",
            0.7,
            file_id="file-c",
            repo_id="repo-c",
        ),
    ]

    selected = _select_file_diverse_results(ranked, top_k=2)

    assert [row["chunk_id"] for row in selected] == [
        "repo-a-readme",
        "repo-b-readme",
    ]


def test_source_diversity_prioritizes_typo_recovery_in_two_result_window() -> None:
    ranked = [
        _result("vector-1", "src/vector_1.py", 0.9),
        _result("vector-2", "src/vector_2.py", 0.8),
        _result("bm25-1", "src/bm25.py", 0.2),
        _result("trigram-1", "src/trigram.py", 0.1),
    ]
    ranked[0]["candidate_sources"] = {"vector": 1.0}
    ranked[1]["candidate_sources"] = {"vector": 0.9}
    ranked[2]["candidate_sources"] = {"bm25": 0.8}
    ranked[3]["candidate_sources"] = {"trigram": 0.8}

    selected = _select_source_diverse_results(ranked, top_k=2)

    assert [row["chunk_id"] for row in selected] == [
        "vector-1",
        "trigram-1",
    ]


def test_source_diversity_top_one_preserves_best_ranked_result() -> None:
    ranked = [
        _result("vector-1", "src/vector.py", 0.9),
        _result("trigram-1", "src/trigram.py", 0.1),
    ]
    ranked[0]["candidate_sources"] = {"vector": 1.0}
    ranked[1]["candidate_sources"] = {"trigram": 0.8}

    selected = _select_source_diverse_results(ranked, top_k=1)

    assert [row["chunk_id"] for row in selected] == ["vector-1"]


def test_agent_search_uses_high_recall_file_selection(monkeypatch) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())

    def unexpected(*_args, **_kwargs):
        raise AssertionError("lossy post-processing ran in agent mode")

    monkeypatch.setattr(search_module, "_apply_metadata_scoring", unexpected)
    monkeypatch.setattr(search_module, "_apply_dynamic_threshold", unexpected)
    monkeypatch.setattr(search_module, "_apply_mmr", unexpected)

    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    result = service.search_code(
        query="find the related implementation",
        repo_ids=["repo-id"],
        top_k=2,
        quality_mode="agent",
    )

    assert result["success"] is True
    assert [row["chunk_id"] for row in result["results"]] == ["a-1", "b-1"]


def test_agent_search_probes_related_paths_from_structured_context(
    monkeypatch,
) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())
    captured: dict[str, object] = {}

    def capture_hybrid(**kwargs):
        captured.update(kwargs)
        return _agent_candidates()

    import synsc.services.hybrid_retrieval as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_retrieve", capture_hybrid)
    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    result = service.search_code(
        query=json.dumps(
            {
                "intent": "Find affected tests",
                "implementation_files": ["src/client/core_model_loading.py"],
            }
        ),
        repo_ids=["repo-id"],
        top_k=2,
        quality_mode="agent",
    )

    assert result["success"] is True
    assert captured["file_pattern"] == "*model*loading*"


def test_agent_search_preserves_explicit_file_pattern(monkeypatch) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())
    captured: dict[str, object] = {}

    def capture_hybrid(**kwargs):
        captured.update(kwargs)
        return _agent_candidates()

    import synsc.services.hybrid_retrieval as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_retrieve", capture_hybrid)
    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    service.search_code(
        query=json.dumps(
            {
                "intent": "Find affected tests",
                "implementation_files": ["src/client/core_model_loading.py"],
            }
        ),
        repo_ids=["repo-id"],
        file_pattern="tests/**",
        top_k=2,
        quality_mode="agent",
    )

    assert captured["file_pattern"] == "tests/**"


def test_agent_search_honors_explicit_reranker(monkeypatch) -> None:
    import synsc.services.reranker as reranker_module

    search_module = _stub_agent_search(monkeypatch, _agent_candidates())
    calls: list[list[str]] = []

    class _FakeReranker:
        def rerank(
            self,
            *,
            query: str,
            results: list[dict[str, object]],
            blend_alpha: float,
        ) -> list[dict[str, object]]:
            del query, blend_alpha
            calls.append([str(row["chunk_id"]) for row in results])
            return list(reversed(results))

    monkeypatch.setattr(
        reranker_module,
        "get_reranker",
        lambda: _FakeReranker(),
    )

    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = True
    result = service.search_code(
        query="find the related implementation",
        repo_ids=["repo-id"],
        top_k=2,
        quality_mode="agent",
    )

    assert calls == [["a-1", "a-2", "b-1"]]
    assert [row["chunk_id"] for row in result["results"]] == ["b-1", "a-2"]


# ── Intent-aware demotion ────────────────────────────────────────────────────


def test_metadata_scoring_demotes_tests_for_implementation_query():
    from synsc.services.search_service import _apply_metadata_scoring

    results = [
        {"file_path": "tests/test_auth.py", "content": "", "similarity": 0.9},
        {"file_path": "src/auth.py", "content": "", "similarity": 0.9},
    ]
    _apply_metadata_scoring(results, query="where is login implemented")
    assert results[0]["similarity"] < results[1]["similarity"]


def test_metadata_scoring_spares_tests_when_query_asks_for_them():
    """The regression: 'which test covers X' must not bury test files."""
    from synsc.services.search_service import _apply_metadata_scoring

    results = [
        {"file_path": "tests/test_auth.py", "content": "", "similarity": 0.9},
        {"file_path": "src/auth.py", "content": "", "similarity": 0.9},
    ]
    _apply_metadata_scoring(results, query="which regression test covers login")
    assert results[0]["similarity"] == 0.9
    assert results[1]["similarity"] == 0.9


def test_metadata_scoring_spares_docs_when_query_asks_for_docs():
    from synsc.services.search_service import _apply_metadata_scoring

    results = [{"file_path": "docs/guide.md", "content": "", "similarity": 0.8}]
    _apply_metadata_scoring(results, query="documentation for the auth guide")
    assert results[0]["similarity"] == 0.8


def test_metadata_scoring_test_intent_does_not_spare_docs():
    """Suppression is per-family, not a blanket amnesty."""
    from synsc.services.search_service import _apply_metadata_scoring

    results = [{"file_path": "docs/guide.md", "content": "", "similarity": 0.8}]
    _apply_metadata_scoring(results, query="which unit test covers login")
    assert results[0]["similarity"] < 0.8


def test_metadata_scoring_without_query_keeps_legacy_behavior():
    from synsc.services.search_service import _apply_metadata_scoring

    results = [{"file_path": "tests/test_auth.py", "content": "", "similarity": 0.9}]
    _apply_metadata_scoring(results)
    assert results[0]["similarity"] < 0.9
