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
    DEFAULT_WEIGHTS,
    Candidate,
    _symbol_search_needles,
    _trigram_search_needles,
    bm25_search,
    exact_symbol_search,
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


def test_symbol_needles_prioritize_dotted_api_leaves():
    needles = _symbol_search_needles(
        "setup.cfg show_default ctx_value "
        "click.Context click.Command click.Option opt.get_help",
    )

    assert needles == [
        "Context",
        "click.Context",
        "Command",
        "click.Command",
        "Option",
        "click.Option",
        "get_help",
        "opt.get_help",
    ]
    assert "cfg" not in needles


def test_trigram_needles_keep_legitimate_uppercase_constants():
    assert _trigram_search_needles("MAX_RETRI_COUNT") == ["MAX_RETRI_COUNT"]


def test_trigram_needles_prefer_code_symbol_over_long_environment_noise():
    assert _trigram_search_needles(
        "SETUPTOOLS_SCM_PRETEND_VERSION handlAuthCallback",
    ) == ["handlAuthCallback"]


def test_trigram_needles_keep_long_uppercase_typo_over_question_prose():
    assert _trigram_search_needles(
        "where is VERY_LONG_APPLICATION_SETTNG defined",
    ) == ["VERY_LONG_APPLICATION_SETTNG"]


def test_exact_symbol_search_uses_every_selected_needle():
    class EmptyRows:
        def mappings(self):
            return self

        def all(self):
            return []

    class RecordingSession:
        statement = ""
        params = None

        def execute(self, statement, params):
            self.statement = str(statement)
            self.params = params
            return EmptyRows()

    query = "click.Context click.Option ctx.forward forwarded_params"
    expected = _symbol_search_needles(query)
    session = RecordingSession()

    assert exact_symbol_search(session, query, "user-id") == []
    for index, needle in enumerate(expected):
        assert session.params[f"nl_{index}"] == needle.lower()
        assert f":nl_{index}" in session.statement
    assert session.statement.index(
        "s.qualified_name IN (:n_",
    ) < session.statement.index("s.name IN (:n_")
    assert session.statement.index("ORDER BY sym_score DESC") < (
        session.statement.index("LIMIT :top_k")
    )


def test_bm25_search_uses_websearch_or_syntax_for_multiple_terms():
    class EmptyRows:
        def mappings(self):
            return self

        def all(self):
            return []

    class RecordingSession:
        params = None

        def execute(self, _statement, params):
            self.params = params
            return EmptyRows()

    session = RecordingSession()

    assert bm25_search(session, "alpha beta", "user-id") == []
    assert session.params["query"] == "alpha or beta"


def test_vector_to_candidates_keeps_raw_similarity():
    raw = [
        {"chunk_id": "a", "similarity": 0.8, "content": "x"},
        {"chunk_id": "b", "similarity": 0.4, "content": "y"},
        {"chunk_id": "c", "similarity": 0.2, "content": "z"},
    ]
    cands = vector_to_candidates(raw)
    assert len(cands) == 3
    # Raw cosine is preserved. Rescaling against the best hit in the result
    # set used to report 1.0 here, which claimed a perfect semantic match
    # even when the whole result set was weak.
    assert cands[0].sources["vector"] == 0.8
    assert cands[1].sources["vector"] == 0.4
    assert cands[2].sources["vector"] == 0.2


def test_vector_to_candidates_handles_empty():
    assert vector_to_candidates([]) == []
    assert vector_to_candidates(None or []) == []


def _vector_branch(*scores: float) -> list[Candidate]:
    """A rank-ordered vector branch, one candidate per score."""
    branch = []
    for index, score in enumerate(scores):
        c = Candidate(chunk_id=f"v{index}", content="")
        c.sources["vector"] = score
        branch.append(c)
    return branch


def test_fuse_scores_rank_not_magnitude():
    # Two branches, each with one hit at rank 1. Raw magnitudes differ wildly
    # (a cosine and a ts_rank_cd are not the same unit) but both are rank 1,
    # so the only thing separating them is the branch weight.
    vec = Candidate(chunk_id="a", content="")
    vec.sources["vector"] = 0.31
    bm = Candidate(chunk_id="b", content="")
    bm.sources["bm25"] = 87.0

    fused = fuse_candidates([[vec], [bm]])
    by_id = {f.chunk_id: f.fused_score for f in fused}
    assert by_id["a"] > by_id["b"]  # vector weight 0.5 beats bm25 weight 0.25
    # The 87.0 magnitude bought nothing: score depends only on rank + weight.
    expected_ratio = DEFAULT_WEIGHTS["bm25"] / DEFAULT_WEIGHTS["vector"]
    assert abs(by_id["b"] / by_id["a"] - expected_ratio) < 1e-9


def test_fuse_weak_top_hit_loses_to_multi_branch_agreement():
    """The regression this fusion exists to prevent.

    A query with no good semantic match still produces a vector branch, and
    its first result is rank 1 no matter how irrelevant it is. Under the old
    max-normalized weighted sum that junk hit was rescaled to a perfect 1.0
    and outscored a chunk that three branches agreed on. It must not.
    """
    junk = Candidate(chunk_id="junk", content="")
    junk.sources["vector"] = 0.32  # least-bad hit of a hopeless vector search

    agreed_bm = Candidate(chunk_id="real", content="")
    agreed_bm.sources["bm25"] = 0.9
    agreed_sym = Candidate(chunk_id="real", content="")
    agreed_sym.sources["symbol"] = 0.8
    agreed_tri = Candidate(chunk_id="real", content="")
    agreed_tri.sources["trigram"] = 0.7

    fused = fuse_candidates(
        [[junk], [agreed_bm], [agreed_sym], [agreed_tri]]
    )
    assert fused[0].chunk_id == "real"
    assert set(fused[0].source_ranks) == {"bm25", "symbol", "trigram"}


def test_fuse_merges_sources_and_keeps_best_rank():
    c1 = Candidate(chunk_id="x", content="foo")
    c1.sources["vector"] = 0.8
    filler = Candidate(chunk_id="filler", content="")
    filler.sources["bm25"] = 0.1
    c2 = Candidate(chunk_id="x", content="foo body longer")
    c2.sources["bm25"] = 0.5

    # x is rank 1 in the vector branch and rank 2 in the bm25 branch.
    fused = fuse_candidates([[c1], [filler, c2]])
    x = next(f for f in fused if f.chunk_id == "x")
    assert set(x.sources) == {"vector", "bm25"}
    assert x.source_ranks == {"vector": 1, "bm25": 2}
    # Longer content wins.
    assert x.content == "foo body longer"


def test_fuse_rescales_to_unit_range():
    # A chunk ranked first by every weighted branch scores exactly 1.0.
    branches = []
    for src in DEFAULT_WEIGHTS:
        c = Candidate(chunk_id="x", content="")
        c.sources[src] = 1.0
        branches.append([c])
    fused = fuse_candidates(branches)
    assert abs(fused[0].fused_score - 1.0) < 1e-9
    # And nothing can exceed it.
    assert all(f.fused_score <= 1.0 + 1e-9 for f in fused)


def test_fuse_results_sorted_descending_by_rank():
    branch = _vector_branch(0.9, 0.6, 0.3)
    fused = fuse_candidates([branch])
    assert [f.chunk_id for f in fused] == ["v0", "v1", "v2"]
    assert [f.source_ranks["vector"] for f in fused] == [1, 2, 3]


def test_fuse_ties_broken_by_raw_score_not_insertion_order():
    # Both chunks are rank 1 in their own single-branch list, so reciprocal
    # rank ties. The stronger raw score must win deterministically.
    weak = Candidate(chunk_id="weak", content="")
    weak.sources["vector"] = 0.2
    strong = Candidate(chunk_id="strong", content="")
    strong.sources["vector"] = 0.95

    assert fuse_candidates([[weak], [strong]])[0].chunk_id == "strong"
    # Insertion order reversed: same answer.
    assert fuse_candidates([[strong], [weak]])[0].chunk_id == "strong"


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
