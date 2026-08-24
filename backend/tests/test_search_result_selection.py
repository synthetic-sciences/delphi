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
    from synsc.services.hybrid_retrieval import HybridRetrieveResult

    monkeypatch.setattr(search_module, "get_session", _fake_session)
    monkeypatch.setattr(
        search_module,
        "get_embedding_generator",
        lambda: _FakeEmbeddingGenerator(),
    )
    monkeypatch.setattr(
        hybrid_module,
        "hybrid_retrieve",
        lambda **_kwargs: HybridRetrieveResult(candidates=candidates),
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


def test_source_diversity_preserves_file_level_lexical_branch() -> None:
    ranked = [
        _result("vector-1", "src/vector_1.py", 0.9),
        _result("vector-2", "src/vector_2.py", 0.8),
        _result("vector-3", "src/vector_3.py", 0.7),
        _result("bm25-1", "src/bm25.py", 0.6),
        _result("trigram-1", "src/trigram.py", 0.5),
        _result("file-bm25-1", "src/file_bm25.py", 0.4),
    ]
    for row in ranked[:3]:
        row["candidate_sources"] = {"vector": 1.0}
    ranked[3]["candidate_sources"] = {"bm25": 1.0}
    ranked[4]["candidate_sources"] = {"trigram": 1.0}
    ranked[5]["candidate_sources"] = {"file_bm25": 1.0}

    selected = _select_source_diverse_results(ranked, top_k=3)

    assert [row["chunk_id"] for row in selected] == [
        "vector-1",
        "trigram-1",
        "file-bm25-1",
    ]


def test_source_diversity_preserves_related_path_branch() -> None:
    ranked = [
        _result("vector-1", "src/vector_1.py", 0.9),
        _result("vector-2", "src/vector_2.py", 0.8),
        _result("path-affinity-1", "tests/test_related.py", 0.2),
    ]
    ranked[0]["candidate_sources"] = {"vector": 1.0}
    ranked[1]["candidate_sources"] = {"vector": 0.9}
    ranked[2]["candidate_sources"] = {"path_affinity": 0.8}

    selected = _select_source_diverse_results(ranked, top_k=2)

    assert [row["chunk_id"] for row in selected] == [
        "vector-1",
        "path-affinity-1",
    ]


def test_source_diversity_preserves_path_token_branch() -> None:
    ranked = [
        _result("vector-1", "src/vector_1.py", 0.9),
        _result("vector-2", "src/vector_2.py", 0.8),
        _result("path-token-1", "src/direct_origin.py", 0.2),
    ]
    ranked[0]["candidate_sources"] = {"vector": 1.0}
    ranked[1]["candidate_sources"] = {"vector": 0.9}
    ranked[2]["candidate_sources"] = {"path_token": 0.8}

    selected = _select_source_diverse_results(ranked, top_k=2)

    assert [row["chunk_id"] for row in selected] == [
        "vector-1",
        "path-token-1",
    ]


def test_source_diversity_preserves_file_okapi_branch() -> None:
    ranked = [
        _result("vector-1", "src/vector_1.py", 0.9),
        _result("vector-2", "src/vector_2.py", 0.8),
        _result("vector-3", "src/vector_3.py", 0.7),
        _result("bm25-1", "src/bm25.py", 0.6),
        _result("trigram-1", "src/trigram.py", 0.5),
        _result("file-okapi-1", "src/user_service.py", 0.4),
    ]
    for row in ranked[:3]:
        row["candidate_sources"] = {"vector": 1.0}
    ranked[3]["candidate_sources"] = {"bm25": 1.0}
    ranked[4]["candidate_sources"] = {"trigram": 1.0}
    ranked[5]["candidate_sources"] = {"file_okapi": 1.0}

    selected = _select_source_diverse_results(ranked, top_k=3)

    assert [row["chunk_id"] for row in selected] == [
        "vector-1",
        "trigram-1",
        "file-okapi-1",
    ]


def test_source_diversity_preserves_novel_file_okapi_file() -> None:
    ranked = [
        _result("aligned-1", "src/types.py", 0.9),
        _result("vector-2", "src/vector_2.py", 0.8),
        _result("file-okapi-only", "src/default_types.py", 0.2),
    ]
    ranked[0]["candidate_sources"] = {"vector": 1.0, "file_okapi": 0.9}
    ranked[1]["candidate_sources"] = {"vector": 0.8}
    ranked[2]["candidate_sources"] = {"file_okapi": 0.7}

    selected = _select_source_diverse_results(ranked, top_k=2)

    assert [row["chunk_id"] for row in selected] == [
        "aligned-1",
        "file-okapi-only",
    ]


def test_source_diversity_preserves_novel_path_token_file() -> None:
    ranked = [
        _result("aligned-1", "src/types.py", 0.9),
        _result("vector-2", "src/vector_2.py", 0.8),
        _result("path-token-only", "src/default_types.py", 0.2),
    ]
    ranked[0]["candidate_sources"] = {"vector": 1.0, "path_token": 0.9}
    ranked[1]["candidate_sources"] = {"vector": 0.8}
    ranked[2]["candidate_sources"] = {"path_token": 0.7}

    selected = _select_source_diverse_results(ranked, top_k=2)

    assert [row["chunk_id"] for row in selected] == [
        "aligned-1",
        "path-token-only",
    ]


def test_source_diversity_replaces_aligned_candidate_with_novel_file() -> None:
    ranked = [
        _result("aligned-1", "src/types.py", 0.9),
        _result("vector-symbol", "src/parser.py", 0.8),
        _result("path-token-only", "src/default_types.py", 0.2),
    ]
    ranked[0]["candidate_sources"] = {"vector": 1.0, "path_token": 0.9}
    ranked[1]["candidate_sources"] = {"vector": 0.8, "symbol": 0.7}
    ranked[2]["candidate_sources"] = {"path_token": 0.7}

    selected = _select_source_diverse_results(ranked, top_k=2)

    assert [row["chunk_id"] for row in selected] == [
        "vector-symbol",
        "path-token-only",
    ]


def test_source_diversity_reorders_duplicate_files_without_truncation() -> None:
    ranked = [
        _result("a-1", "src/a.py", 0.9),
        _result("a-2", "src/a.py", 0.85),
        _result("b-1", "src/b.py", 0.8),
        _result("c-1", "src/c.py", 0.7),
    ]
    for row in ranked:
        row["candidate_sources"] = {"vector": 1.0}

    selected = _select_source_diverse_results(ranked, top_k=len(ranked))

    assert [row["chunk_id"] for row in selected] == [
        "a-1",
        "b-1",
        "c-1",
        "a-2",
    ]


def test_source_diversity_keeps_duplicate_files_deferred_after_selection() -> None:
    ranked = [
        _result("a-1", "src/a.py", 0.9),
        _result("a-2", "src/a.py", 0.85),
        _result("b-1", "src/b.py", 0.8),
        _result("b-2", "src/b.py", 0.75),
        _result("c-1", "src/c.py", 0.7),
    ]
    for row in ranked:
        row["candidate_sources"] = {"vector": 1.0}

    selected = _select_source_diverse_results(ranked, top_k=4)

    assert [row["chunk_id"] for row in selected] == [
        "a-1",
        "b-1",
        "c-1",
        "a-2",
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


def test_agent_search_reports_related_path_branch_coverage(monkeypatch) -> None:
    candidates = _agent_candidates()
    candidates[2].sources["path_affinity"] = 0.75
    search_module = _stub_agent_search(monkeypatch, candidates)

    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    result = service.search_code(
        query="find the related implementation",
        repo_ids=["repo-id"],
        top_k=3,
        quality_mode="agent",
    )

    assert result["success"] is True
    assert result["hybrid"]["sources_hit"]["path_affinity"] == 1


def test_agent_search_reports_path_token_branch_coverage(monkeypatch) -> None:
    candidates = _agent_candidates()
    candidates[2].sources["path_token"] = 0.75
    search_module = _stub_agent_search(monkeypatch, candidates)

    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    result = service.search_code(
        query="find the direct origin implementation",
        repo_ids=["repo-id"],
        top_k=3,
        quality_mode="agent",
    )

    assert result["success"] is True
    assert result["hybrid"]["sources_hit"]["path_token"] == 1


def test_agent_search_reports_serving_retrieval_configuration(monkeypatch) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())
    monkeypatch.setenv(
        "SYNSC_FUSION_WEIGHTS",
        "file_bm25=0.17,path_token=0.11",
    )

    service = search_module.SearchService(user_id="user-id")
    monkeypatch.setattr(service.config.search, "enable_reranker", False)
    monkeypatch.setattr(service.config.search, "vector_exact_scan", True)
    monkeypatch.setattr(service.config.search, "hnsw_ef_search", 321)
    monkeypatch.setattr(
        service.config.search,
        "enable_file_diverse_bm25",
        True,
    )
    monkeypatch.setattr(
        service.config.search,
        "enable_path_token_search",
        True,
    )
    result = service.search_code(
        query="find the related implementation",
        repo_ids=["repo-id"],
        top_k=3,
        quality_mode="agent",
    )

    assert result["retrieval_config"]["vector_mode"] == "exact"
    assert result["retrieval_config"]["hnsw_ef_search"] == 321
    assert result["retrieval_config"]["file_diverse_bm25"] is True
    assert result["retrieval_config"]["fusion_weights"]["file_bm25"] == 0.17
    assert result["retrieval_config"]["path_token_search"] is True
    assert result["retrieval_config"]["fusion_weights"]["path_token"] == 0.11


def test_agent_search_reports_file_okapi_serving_configuration(monkeypatch) -> None:
    candidates = _agent_candidates()
    candidates[0].sources["file_okapi"] = 0.75
    search_module = _stub_agent_search(monkeypatch, candidates)
    monkeypatch.delenv("SYNSC_FUSION_WEIGHTS", raising=False)

    service = search_module.SearchService(user_id="user-id")
    monkeypatch.setattr(service.config.search, "enable_reranker", False)
    monkeypatch.setattr(service.config.search, "enable_file_okapi", True)
    result = service.search_code(
        query="find the user service implementation",
        repo_ids=["repo-id"],
        top_k=3,
        quality_mode="agent",
    )

    config = result["retrieval_config"]
    assert config["file_okapi_configured"] is True
    assert config["file_okapi"] is True
    assert config["fusion_weights"]["file_okapi"] == 0.15
    assert config["file_okapi_candidates"] == 50
    assert config["file_okapi_index_version"] == "v1"
    assert config["file_okapi_k1"] == 1.2
    assert config["file_okapi_b"] == 0.75


def test_agent_search_reports_file_okapi_configured_but_inactive_without_hits(
    monkeypatch,
) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())
    monkeypatch.delenv("SYNSC_FUSION_WEIGHTS", raising=False)

    service = search_module.SearchService(user_id="user-id")
    monkeypatch.setattr(service.config.search, "enable_reranker", False)
    monkeypatch.setattr(service.config.search, "enable_file_okapi", True)
    result = service.search_code(
        query="find the user service implementation",
        repo_ids=["repo-id"],
        top_k=3,
        quality_mode="agent",
    )

    config = result["retrieval_config"]
    assert config["file_okapi_configured"] is True
    assert config["file_okapi"] is False
    assert "file_okapi" not in config["fusion_weights"]
    assert config["file_okapi_candidates"] == 50
    assert config["file_okapi_index_version"] == "v1"
    assert config["file_okapi_k1"] == 1.2
    assert config["file_okapi_b"] == 0.75


def test_agent_search_warns_when_file_okapi_configured_but_inactive(
    monkeypatch,
) -> None:
    import synsc.services.hybrid_retrieval as hybrid_module
    import synsc.services.search_service as search_module
    from synsc.services.hybrid_retrieval import HybridRetrieveResult

    monkeypatch.setattr(search_module, "get_session", _fake_session)
    monkeypatch.setattr(
        search_module,
        "get_embedding_generator",
        lambda: _FakeEmbeddingGenerator(),
    )
    monkeypatch.setattr(
        hybrid_module,
        "hybrid_retrieve",
        lambda **_kwargs: HybridRetrieveResult(
            candidates=_agent_candidates(),
            file_okapi_inactive={
                "reason": "index_missing_or_stale",
                "document_count": 0,
            },
        ),
    )
    monkeypatch.setattr(
        search_module,
        "_enrich_results_with_context",
        lambda results: results,
    )

    service = search_module.SearchService(user_id="user-id")
    monkeypatch.setattr(service.config.search, "enable_reranker", False)
    monkeypatch.setattr(service.config.search, "enable_file_okapi", True)
    result = service.search_code(
        query="find the user service implementation",
        repo_ids=["repo-id"],
        top_k=3,
        quality_mode="agent",
    )

    assert result["retrieval_config"]["file_okapi_configured"] is True
    assert result["retrieval_config"]["file_okapi"] is False
    assert result["warnings"] == [
        {
            "code": "file_okapi_inactive",
            "reason": "index_missing_or_stale",
            "document_count": 0,
        }
    ]


def test_disabled_file_okapi_does_not_emit_inactive_warning(monkeypatch) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())

    service = search_module.SearchService(user_id="user-id")
    monkeypatch.setattr(service.config.search, "enable_reranker", False)
    monkeypatch.setattr(service.config.search, "enable_file_okapi", False)
    result = service.search_code(
        query="find the user service implementation",
        repo_ids=["repo-id"],
        top_k=3,
        quality_mode="agent",
    )

    assert "warnings" not in result


def test_serving_configuration_marks_file_okapi_inactive_when_disabled(
    monkeypatch,
) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())
    monkeypatch.setenv("SYNSC_FUSION_WEIGHTS", "file_okapi=0.17")

    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    service.config.search.enable_file_okapi = False
    result = service.search_code(
        query="find the user service implementation",
        repo_ids=["repo-id"],
        top_k=3,
        quality_mode="agent",
    )

    config = result["retrieval_config"]
    assert config["file_okapi_configured"] is False
    assert config["file_okapi"] is False
    assert "file_okapi" not in config["fusion_weights"]
    assert "file_okapi_candidates" not in config


def test_serving_configuration_marks_file_okapi_inactive_without_scope(
    monkeypatch,
) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())

    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    service.config.search.enable_file_okapi = True
    result = service.search_code(
        query="find the user service implementation",
        repo_ids=None,
        top_k=3,
        quality_mode="agent",
    )

    config = result["retrieval_config"]
    assert config["file_okapi_configured"] is False
    assert config["file_okapi"] is False
    assert "file_okapi" not in config["fusion_weights"]
    assert "file_okapi_candidates" not in config


def test_agent_search_passes_file_okapi_flag(monkeypatch) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())
    captured: dict[str, object] = {}

    def capture_hybrid(**kwargs):
        captured.update(kwargs)
        from synsc.services.hybrid_retrieval import HybridRetrieveResult

        return HybridRetrieveResult(candidates=_agent_candidates())

    import synsc.services.hybrid_retrieval as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_retrieve", capture_hybrid)
    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    service.config.search.enable_file_okapi = True
    result = service.search_code(
        query="find user service",
        repo_ids=["repo-id"],
        top_k=2,
        quality_mode="agent",
    )

    assert result["success"] is True
    assert captured["enable_file_okapi"] is True


def test_agent_search_reports_file_okapi_branch_coverage(monkeypatch) -> None:
    candidates = _agent_candidates()
    candidates[2].sources["file_okapi"] = 0.75
    search_module = _stub_agent_search(monkeypatch, candidates)

    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    result = service.search_code(
        query="find user service",
        repo_ids=["repo-id"],
        top_k=3,
        quality_mode="agent",
    )

    assert result["success"] is True
    assert result["hybrid"]["sources_hit"]["file_okapi"] == 1


def test_path_token_default_fusion_weight_is_point_one(monkeypatch) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())
    monkeypatch.delenv("SYNSC_FUSION_WEIGHTS", raising=False)

    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    service.config.search.enable_path_token_search = True
    result = service.search_code(
        query="find the related implementation",
        repo_ids=["repo-id"],
        top_k=3,
        quality_mode="agent",
    )

    assert result["retrieval_config"]["fusion_weights"]["path_token"] == 0.10


def test_serving_configuration_omits_disabled_optional_branch_weights(
    monkeypatch,
) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())
    monkeypatch.setenv(
        "SYNSC_FUSION_WEIGHTS",
        "file_bm25=0.17,path_token=0.11",
    )

    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    service.config.search.enable_file_diverse_bm25 = False
    service.config.search.enable_path_token_search = False
    result = service.search_code(
        query="find the related implementation",
        repo_ids=["repo-id"],
        top_k=3,
        quality_mode="agent",
    )

    weights = result["retrieval_config"]["fusion_weights"]
    assert "file_bm25" not in weights
    assert "path_token" not in weights


def test_serving_configuration_marks_path_token_inactive_without_scope_or_hybrid(
    monkeypatch,
) -> None:
    from synsc.services.search_service import _retrieval_config_snapshot

    search_module = _stub_agent_search(monkeypatch, _agent_candidates())

    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    service.config.search.enable_path_token_search = True

    unscoped = service.search_code(
        query="find the related implementation",
        repo_ids=None,
        top_k=3,
        quality_mode="agent",
    )
    non_hybrid_config = _retrieval_config_snapshot(
        service.config.search,
        use_hybrid=False,
        use_rerank=False,
        embedding_model="fake-embedding",
        repo_scoped=True,
    )

    for config in (unscoped["retrieval_config"], non_hybrid_config):
        assert config["path_token_search"] is False
        assert "path_token" not in config["fusion_weights"]


def test_agent_search_uses_persistent_query_embedding_cache(
    monkeypatch,
) -> None:
    import synsc.core.llm_cache as cache_module

    search_module = _stub_agent_search(monkeypatch, _agent_candidates())
    cache_calls: list[tuple[str, dict[str, object]]] = []

    class _ComputeCache:
        def get_or_compute(self, _key, compute):
            return compute()

    def capture_cache(*_args, **kwargs):
        cache_calls.append((str(_args[0]), kwargs))
        return _ComputeCache()

    monkeypatch.setattr(cache_module, "get_cache", capture_cache)
    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    service.config.search.llm_cache_db = "/tmp/search-stage-cache.sqlite3"

    service.search_code(
        query="find the related implementation",
        repo_ids=["repo-id"],
        top_k=2,
        quality_mode="agent",
    )

    assert (
        "query-embedding",
        {"persistent_path": "/tmp/search-stage-cache.sqlite3"},
    ) in cache_calls


def test_agent_search_probes_related_paths_from_structured_context(
    monkeypatch,
) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())
    captured: dict[str, object] = {}

    def capture_hybrid(**kwargs):
        captured.update(kwargs)
        from synsc.services.hybrid_retrieval import HybridRetrieveResult

        return HybridRetrieveResult(candidates=_agent_candidates())

    import synsc.services.hybrid_retrieval as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_retrieve", capture_hybrid)
    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    service.config.search.enable_file_diverse_bm25 = True
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
    assert captured["enable_file_diverse_bm25"] is True


def test_agent_search_passes_path_token_flag(monkeypatch) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())
    captured: dict[str, object] = {}

    def capture_hybrid(**kwargs):
        captured.update(kwargs)
        from synsc.services.hybrid_retrieval import HybridRetrieveResult

        return HybridRetrieveResult(candidates=_agent_candidates())

    import synsc.services.hybrid_retrieval as hybrid_module

    monkeypatch.setattr(hybrid_module, "hybrid_retrieve", capture_hybrid)
    service = search_module.SearchService(user_id="user-id")
    service.config.search.enable_reranker = False
    service.config.search.enable_path_token_search = True
    result = service.search_code(
        query="find direct origin",
        repo_ids=["repo-id"],
        top_k=2,
        quality_mode="agent",
    )

    assert result["success"] is True
    assert captured["enable_path_token_search"] is True


def test_agent_search_preserves_explicit_file_pattern(monkeypatch) -> None:
    search_module = _stub_agent_search(monkeypatch, _agent_candidates())
    captured: dict[str, object] = {}

    def capture_hybrid(**kwargs):
        captured.update(kwargs)
        from synsc.services.hybrid_retrieval import HybridRetrieveResult

        return HybridRetrieveResult(candidates=_agent_candidates())

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

    assert calls == [["a-1", "b-1", "a-2"]]
    assert [row["chunk_id"] for row in result["results"]] == ["a-2", "b-1"]


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
