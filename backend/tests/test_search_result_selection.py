from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from synsc.services.hybrid_retrieval import Candidate
from synsc.services.search_service import _select_file_diverse_results


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
