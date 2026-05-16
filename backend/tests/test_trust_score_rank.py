"""Trust-score boost factors into unified_retrieve ranking."""
from __future__ import annotations

from synsc.services import source_service


def test_attach_trust_scores_passthrough_when_present():
    hits = [{"source_type": "repo", "source_id": "r1", "trust_score": 0.5}]
    out = source_service._attach_trust_scores(hits)
    assert out[0]["trust_score"] == 0.5


def test_unified_retrieve_applies_trust_boost(monkeypatch):
    # Two hits with identical retrieval scores; the higher-trust one should win.
    fake_results = [
        {
            "repo_id": "r-low-trust",
            "chunk_id": "c1",
            "content": "x",
            "relevance_score": 0.8,
        },
        {
            "repo_id": "r-high-trust",
            "chunk_id": "c2",
            "content": "x",
            "relevance_score": 0.8,
        },
    ]

    class FakeSearchService:
        def __init__(self, user_id):
            pass

        def search_code(self, **kwargs):
            return {"results": fake_results}

    monkeypatch.setattr(source_service, "_get_search_service", lambda uid: FakeSearchService(uid))

    def fake_attach(hits):
        for h in hits:
            if h["source_id"] == "r-high-trust":
                h["trust_score"] = 0.9
            else:
                h["trust_score"] = 0.1
        return hits

    monkeypatch.setattr(source_service, "_attach_trust_scores", fake_attach)

    out = source_service.unified_retrieve(
        query="foo", source_types=["repo"], k=2, user_id="u1"
    )
    assert out[0]["source_id"] == "r-high-trust"
    assert out[1]["source_id"] == "r-low-trust"


def test_unified_retrieve_relevance_beats_trust(monkeypatch):
    # Even with huge trust gap, a clear relevance lead should win.
    fake_results = [
        {
            "repo_id": "r-low-trust",
            "chunk_id": "c1",
            "content": "x",
            "relevance_score": 0.95,
        },
        {
            "repo_id": "r-high-trust",
            "chunk_id": "c2",
            "content": "x",
            "relevance_score": 0.30,
        },
    ]

    class FakeSearchService:
        def __init__(self, user_id):
            pass

        def search_code(self, **kwargs):
            return {"results": fake_results}

    monkeypatch.setattr(source_service, "_get_search_service", lambda uid: FakeSearchService(uid))

    def fake_attach(hits):
        for h in hits:
            h["trust_score"] = 1.0 if h["source_id"] == "r-high-trust" else 0.0
        return hits

    monkeypatch.setattr(source_service, "_attach_trust_scores", fake_attach)

    out = source_service.unified_retrieve(
        query="foo", source_types=["repo"], k=2, user_id="u1"
    )
    # 0.95 + 0 vs 0.30 + 0.1 = 0.95 vs 0.40 → relevance wins
    assert out[0]["source_id"] == "r-low-trust"
