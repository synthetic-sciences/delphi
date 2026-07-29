from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from synsc.services.hybrid_retrieval import Candidate
from synsc.services.search_service import _select_file_diverse_results


def _result(
    chunk_id: str,
    file_path: str,
    similarity: float,
) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "file_path": file_path,
        "similarity": similarity,
        "content": chunk_id,
    }


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


def test_agent_search_uses_high_recall_file_selection(monkeypatch) -> None:
    import synsc.services.hybrid_retrieval as hybrid_module
    import synsc.services.search_service as search_module

    class FakeEmbeddingGenerator:
        def generate_single(self, _query: str) -> list[float]:
            return [1.0, 0.0]

    class FakeSession:
        def execute(self, *_args, **_kwargs) -> None:
            return None

    @contextmanager
    def fake_session() -> Iterator[FakeSession]:
        yield FakeSession()

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

    monkeypatch.setattr(search_module, "get_session", fake_session)
    monkeypatch.setattr(
        search_module,
        "get_embedding_generator",
        lambda: FakeEmbeddingGenerator(),
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
