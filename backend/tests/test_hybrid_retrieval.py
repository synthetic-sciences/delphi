"""Unit tests for hybrid retrieval (vector + BM25 + symbol + path + trigram).

These tests exercise the parts that don't need a real Postgres connection:
  - Identifier extraction from queries.
  - Candidate fusion: union by chunk_id, multi-source bonus, weight blending.
  - vector_to_candidates normalization.

The DB-backed branches (bm25_search, trigram_search, exact_symbol_search,
exact_path_search) are integration-tested separately with a real Postgres.
"""
from __future__ import annotations

from synsc.services.hybrid_retrieval import (
    Candidate,
    DEFAULT_WEIGHTS,
    extract_identifiers,
    fuse_candidates,
    vector_to_candidates,
)


def test_extract_identifiers_camelcase_and_snake_case():
    ids = extract_identifiers("how does handleAuthCallback work?")
    assert "handleAuthCallback" in ids


def test_extract_identifiers_drops_short_and_stopwords():
    ids = extract_identifiers("how the get does work for this method")
    # All filtered: 'how','the','get','does','work','for','this','method','of'
    assert ids == []


def test_extract_identifiers_keeps_dotted_paths():
    ids = extract_identifiers("call fastapi.routing.APIRouter")
    # The whole dotted thing should come through (or its parts).
    assert "fastapi.routing.APIRouter" in ids


def test_extract_identifiers_unique_order_preserved():
    ids = extract_identifiers("FooBar fooBar FooBar baz_qux baz_qux")
    # Each identifier appears once, in first-seen order.
    assert ids.index("FooBar") < ids.index("fooBar")
    assert ids.count("FooBar") == 1
    assert ids.count("baz_qux") == 1


def test_vector_to_candidates_normalizes_against_top():
    raw = [
        {"chunk_id": "a", "similarity": 0.8, "content": "x"},
        {"chunk_id": "b", "similarity": 0.4, "content": "y"},
        {"chunk_id": "c", "similarity": 0.2, "content": "z"},
    ]
    cands = vector_to_candidates(raw)
    assert len(cands) == 3
    assert cands[0].sources["vector"] == 1.0  # top is 1.0 after norm
    assert cands[1].sources["vector"] == 0.5
    assert cands[2].sources["vector"] == 0.25


def test_vector_to_candidates_handles_empty():
    assert vector_to_candidates([]) == []
    assert vector_to_candidates(None or []) == []


def test_fuse_single_source_basic_score():
    c = Candidate(chunk_id="x", content="foo")
    c.sources["vector"] = 0.8
    fused = fuse_candidates([[c]])
    assert len(fused) == 1
    # Single source: no multi-hit bonus, just weight * score.
    expected = DEFAULT_WEIGHTS["vector"] * 0.8
    assert abs(fused[0].fused_score - expected) < 1e-9


def test_fuse_multi_source_gets_bonus():
    # Same chunk hit by two branches.
    c1 = Candidate(chunk_id="x", content="foo")
    c1.sources["vector"] = 0.8
    c2 = Candidate(chunk_id="x", content="foo body longer")
    c2.sources["bm25"] = 0.5

    fused = fuse_candidates([[c1], [c2]])
    assert len(fused) == 1
    # Sources should be merged.
    assert set(fused[0].sources.keys()) == {"vector", "bm25"}
    # Multi-source bonus is 1.15× when ≥2 sources hit.
    base = (
        DEFAULT_WEIGHTS["vector"] * 0.8
        + DEFAULT_WEIGHTS["bm25"] * 0.5
    )
    expected = min(1.0, base * 1.15)
    assert abs(fused[0].fused_score - expected) < 1e-9
    # Longer content wins.
    assert fused[0].content == "foo body longer"


def test_fuse_three_sources_compounds_bonus():
    c1 = Candidate(chunk_id="x", content="")
    c1.sources["vector"] = 0.7
    c2 = Candidate(chunk_id="x", content="")
    c2.sources["symbol"] = 0.9
    c3 = Candidate(chunk_id="x", content="")
    c3.sources["bm25"] = 0.4

    fused = fuse_candidates([[c1], [c2], [c3]])
    assert len(fused) == 1
    # 2+ source bonus AND 3+ source bonus both apply.
    base = (
        DEFAULT_WEIGHTS["vector"] * 0.7
        + DEFAULT_WEIGHTS["symbol"] * 0.9
        + DEFAULT_WEIGHTS["bm25"] * 0.4
    )
    expected = min(1.0, base * 1.15 * 1.10)
    assert abs(fused[0].fused_score - expected) < 1e-9


def test_fuse_results_sorted_descending():
    a = Candidate(chunk_id="a", content="")
    a.sources["vector"] = 0.3
    b = Candidate(chunk_id="b", content="")
    b.sources["vector"] = 0.9
    c = Candidate(chunk_id="c", content="")
    c.sources["vector"] = 0.6

    fused = fuse_candidates([[a, b, c]])
    assert [f.chunk_id for f in fused] == ["b", "c", "a"]


def test_fuse_max_score_kept_when_same_source_appears_twice():
    # If two branches both contribute 'vector', the higher score wins.
    c1 = Candidate(chunk_id="x", content="")
    c1.sources["vector"] = 0.4
    c2 = Candidate(chunk_id="x", content="")
    c2.sources["vector"] = 0.9
    fused = fuse_candidates([[c1], [c2]])
    assert len(fused) == 1
    assert fused[0].sources["vector"] == 0.9


def test_candidate_to_dict_round_trip_fields():
    c = Candidate(
        chunk_id="abc", repo_id="r1", file_path="src/x.py",
        content="def f(): pass", start_line=1, end_line=1,
    )
    c.sources["vector"] = 0.7
    c.sources["bm25"] = 0.5
    c.fused_score = 0.65
    d = c.to_dict()
    # Shape stays compatible with the legacy search result format.
    assert d["chunk_id"] == "abc"
    assert d["repo_id"] == "r1"
    assert d["file_path"] == "src/x.py"
    assert d["similarity"] == 0.65
    assert d["candidate_sources"] == {"vector": 0.7, "bm25": 0.5}
