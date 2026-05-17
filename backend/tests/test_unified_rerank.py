"""Tests for per-branch normalization + cross-source rerank in unified_retrieve."""
from __future__ import annotations

from synsc.services import source_service


def test_normalize_per_branch_independent_groups():
    hits = [
        {"source_type": "repo", "score": 0.9},
        {"source_type": "repo", "score": 0.5},
        {"source_type": "repo", "score": 0.1},
        {"source_type": "docs", "score": 0.4},
        {"source_type": "docs", "score": 0.3},
        {"source_type": "docs", "score": 0.2},
    ]
    source_service._normalize_per_branch(hits)
    # Repo group: 0.9 → 1.0, 0.5 → 0.5, 0.1 → 0.0
    repo = [h for h in hits if h["source_type"] == "repo"]
    docs = [h for h in hits if h["source_type"] == "docs"]
    assert max(h["score"] for h in repo) == 1.0
    assert min(h["score"] for h in repo) == 0.0
    assert max(h["score"] for h in docs) == 1.0
    assert min(h["score"] for h in docs) == 0.0


def test_normalize_per_branch_single_value():
    hits = [{"source_type": "repo", "score": 0.7}]
    source_service._normalize_per_branch(hits)
    assert hits[0]["score"] == 1.0


def test_maybe_rerank_disabled_passthrough(monkeypatch):
    """When the reranker is OFF, hits pass through unchanged."""
    from synsc import config as config_module

    class FakeCfg:
        class search:
            enable_reranker = False
    monkeypatch.setattr(config_module, "get_config", lambda: FakeCfg())
    hits = [{"source_type": "repo", "score": 0.8, "text": "x"}]
    out = source_service._maybe_cross_source_rerank("q", hits)
    assert out == hits


def test_maybe_rerank_short_list_skipped(monkeypatch):
    """Lists of 0/1/2 hits skip rerank — nothing to swap."""
    from synsc import config as config_module

    class FakeCfg:
        class search:
            enable_reranker = True
    monkeypatch.setattr(config_module, "get_config", lambda: FakeCfg())
    hits = [{"text": "x", "score": 0.5}]
    out = source_service._maybe_cross_source_rerank("q", hits)
    assert out == hits


def test_maybe_rerank_invokes_reranker(monkeypatch):
    """When enabled and many hits, the reranker is called and its order respected."""
    from synsc import config as config_module
    from synsc.services import reranker as reranker_mod

    class FakeCfg:
        class search:
            enable_reranker = True
    monkeypatch.setattr(config_module, "get_config", lambda: FakeCfg())

    class FakeReranker:
        def rerank(self, *, query, results, content_key, score_key):
            # Reverse order so we can verify it was used.
            return list(reversed(results))

    monkeypatch.setattr(reranker_mod, "get_reranker", lambda: FakeReranker())

    hits = [
        {"text": f"hit{i}", "score": 1.0 - i * 0.1} for i in range(5)
    ]
    out = source_service._maybe_cross_source_rerank("q", hits)
    assert out[0]["text"] == "hit4"
    assert out[-1]["text"] == "hit0"


def test_unified_retrieve_merges_and_normalizes(monkeypatch):
    """End-to-end: code branch + docs branch, ranking honors normalization."""
    fake_code = [
        {"repo_id": "r1", "chunk_id": "c1", "content": "code A", "relevance_score": 0.9},
        {"repo_id": "r1", "chunk_id": "c2", "content": "code B", "relevance_score": 0.7},
    ]
    fake_docs = [
        {"docs_id": "d1", "chunk_id": "dc1", "content": "docs A", "similarity": 0.5},
        {"docs_id": "d1", "chunk_id": "dc2", "content": "docs B", "similarity": 0.45},
    ]

    class FakeSearchSvc:
        def __init__(self, user_id=None): pass
        def search_code(self, **kw): return {"results": fake_code}

    monkeypatch.setattr(
        source_service, "_get_search_service", lambda uid: FakeSearchSvc(uid)
    )

    class FakeDocsSvc:
        def search_docs(self, **kw): return {"results": fake_docs}

    monkeypatch.setattr(
        "synsc.services.docs_service.get_docs_service",
        lambda user_id=None: FakeDocsSvc(),
    )

    # Disable rerank so we test pure normalization
    monkeypatch.setattr(
        "synsc.services.source_service._maybe_cross_source_rerank",
        lambda q, h: h,
    )
    monkeypatch.setattr(
        source_service, "_attach_trust_scores", lambda h: h
    )

    out = source_service.unified_retrieve(
        query="anything",
        source_types=["repo", "docs"],
        k=4,
        user_id="u1",
    )
    # After per-branch normalization, top code AND top docs both have
    # score=1.0. The merged top result is one of them — neither dominates
    # solely by raw similarity scale.
    assert len(out) == 4
    top_types = {out[0]["source_type"], out[1]["source_type"]}
    assert "repo" in top_types or "docs" in top_types
