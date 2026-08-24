"""Unit tests for hybrid retrieval (vector + BM25 + symbol + path + trigram).

These tests exercise the parts that don't need a real Postgres connection:
  - Identifier extraction from queries.
  - Candidate fusion: union by chunk_id, multi-source bonus, weight blending.
  - vector_to_candidates normalization.

The DB-backed branches (bm25_search, trigram_search, exact_symbol_search,
exact_path_search) are integration-tested separately with a real Postgres.
"""
from __future__ import annotations

from types import SimpleNamespace

from synsc.services.hybrid_retrieval import (
    DEFAULT_WEIGHTS,
    Candidate,
    _align_file_level_candidates,
    _symbol_search_needles,
    _trigram_search_needles,
    bm25_search,
    exact_path_search,
    exact_symbol_search,
    extract_identifiers,
    file_diverse_bm25_search,
    fuse_candidates,
    path_affinity_search,
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
        statement = ""

        def execute(self, statement, params):
            self.statement = str(statement)
            self.params = params
            return EmptyRows()

    session = RecordingSession()

    assert bm25_search(session, "alpha beta", "user-id") == []
    assert session.params["query"] == "alpha or beta"
    assert (
        "ORDER BY score DESC, rf.file_path, cc.chunk_index, "
        "cc.repo_id, cc.chunk_id"
    ) in session.statement


def test_file_diverse_bm25_selects_one_totally_ordered_chunk_per_file():
    class EmptyRows:
        def mappings(self):
            return self

        def all(self):
            return []

    class RecordingSession:
        params = None
        statement = ""

        def execute(self, statement, params):
            self.statement = " ".join(str(statement).split())
            self.params = params
            return EmptyRows()

    session = RecordingSession()

    assert file_diverse_bm25_search(
        session,
        "alpha beta",
        "user-id",
    ) == []
    assert session.params["query"] == "alpha or beta"
    assert (
        "ROW_NUMBER() OVER ( PARTITION BY file_id "
        "ORDER BY score DESC, chunk_index, repo_id, chunk_id )"
    ) in session.statement
    assert (
        "ORDER BY score DESC, file_path, chunk_index, repo_id, chunk_id"
    ) in session.statement


def test_symbol_and_path_queries_use_total_sql_orders():
    class EmptyRows:
        def mappings(self):
            return self

        def all(self):
            return []

    class RecordingSession:
        statements = []

        def execute(self, statement, _params):
            self.statements.append(str(statement))
            return EmptyRows()

    symbol_session = RecordingSession()
    assert exact_symbol_search(symbol_session, "click.Context", "user-id") == []
    symbol_sql = " ".join(symbol_session.statements[-1].split())
    assert (
        "ORDER BY sym_score DESC, s.repo_id, s.file_id, "
        "s.start_line, s.symbol_id"
    ) in symbol_sql
    assert (
        "ORDER BY ms.sym_score DESC, rf.file_path, cc.chunk_index, "
        "cc.repo_id, cc.chunk_id, ms.symbol_id"
    ) in symbol_sql

    affinity_session = RecordingSession()
    assert (
        path_affinity_search(
            affinity_session,
            "update server/grpc_proxy.go",
            "user-id",
        )
        == []
    )
    affinity_sql = " ".join(affinity_session.statements[-1].split())
    assert (
        "ORDER BY score DESC, length(file_path), file_path, "
        "repo_id, chunk_id"
    ) in affinity_sql

    exact_path_session = RecordingSession()
    assert exact_path_search(exact_path_session, "*.py", "user-id") == []
    exact_path_sql = " ".join(exact_path_session.statements[-1].split())
    assert (
        "ORDER BY rf.file_path, cc.chunk_index, cc.repo_id, cc.chunk_id"
    ) in exact_path_sql


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


def test_file_level_branch_aligns_to_strongest_existing_chunk_in_file():
    vector = Candidate(chunk_id="vector-a", file_id="file-a")
    vector.sources["vector"] = 0.8
    shared_vector = Candidate(chunk_id="shared-a", file_id="file-a")
    shared_vector.sources["vector"] = 0.7
    shared_bm25 = Candidate(chunk_id="shared-a", file_id="file-a")
    shared_bm25.sources["bm25"] = 9.0
    lexical_a = Candidate(chunk_id="lexical-a", file_id="file-a")
    lexical_a.sources["file_bm25"] = 4.0
    lexical_b = Candidate(chunk_id="lexical-b", file_id="file-b")
    lexical_b.sources["file_bm25"] = 3.0

    aligned = _align_file_level_candidates(
        [[vector, shared_vector], [shared_bm25]],
        [lexical_a, lexical_b],
        {**DEFAULT_WEIGHTS, "file_bm25": 0.15},
    )

    assert [candidate.chunk_id for candidate in aligned] == [
        "shared-a",
        "lexical-b",
    ]
    assert aligned[0].sources == {"file_bm25": 4.0}
    assert vector.sources == {"vector": 0.8}
    assert shared_vector.sources == {"vector": 0.7}


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


# ── Path affinity ────────────────────────────────────────────────────────────


def test_path_stems_extracts_named_file():
    from synsc.services.hybrid_retrieval import path_stems_from_query

    stems = path_stems_from_query(
        "what tests cover server/etcdmain/grpc_proxy.go"
    )
    # Separators are stripped so the stem matches etcd_grpcproxy_test.go,
    # which underscore-sensitive comparison would miss.
    assert "grpcproxy" in stems


def test_path_stems_handles_multiple_extensions():
    from synsc.services.hybrid_retrieval import path_stems_from_query

    stems = path_stems_from_query("auth/tokens.py and frontend/api_client.js")
    assert "tokens" in stems
    assert "apiclient" in stems


def test_path_stems_ignores_prose_without_paths():
    from synsc.services.hybrid_retrieval import path_stems_from_query

    assert path_stems_from_query("how does authentication work") == []


def test_path_stems_drops_two_character_stems():
    from synsc.services.hybrid_retrieval import path_stems_from_query

    # 'io.go' is too short a stem to anchor anything useful.
    assert path_stems_from_query("see io.go for details") == []


def test_path_stems_are_bounded():
    from synsc.services.hybrid_retrieval import path_stems_from_query

    query = " ".join(f"pkg/module_{i}.py" for i in range(20))
    assert len(path_stems_from_query(query, limit=4)) == 4


def test_path_affinity_returns_empty_without_a_named_file():
    from synsc.services.hybrid_retrieval import path_affinity_search

    class _Session:
        def execute(self, *a, **k):  # pragma: no cover - must not be reached
            raise AssertionError("should not query without a path stem")

    assert path_affinity_search(_Session(), "how does auth work", "u") == []


def test_path_stems_ignores_filenames_inside_urls():
    """A CONTRIBUTING.md link in a PR template is not a retrieval anchor."""
    from synsc.services.hybrid_retrieval import path_stems_from_query

    stems = path_stems_from_query(
        "fix server/etcdmain/grpc_proxy.go -- see "
        "https://github.com/etcd-io/etcd/blob/main/CONTRIBUTING.md"
    )
    assert "grpcproxy" in stems
    assert "contributing" not in stems


def test_path_token_ranking_matches_query_words_to_normalized_paths():
    from synsc.services.hybrid_retrieval import _rank_path_token_files

    files = [
        {
            "file_id": "default-types",
            "repo_id": "repo",
            "file_path": "crates/ignore/src/default_types.rs",
        },
        {
            "file_id": "types",
            "repo_id": "repo",
            "file_path": "crates/ignore/src/types.rs",
        },
        {
            "file_id": "unrelated",
            "repo_id": "repo",
            "file_path": "crates/printer/src/termcolor.rs",
        },
    ]

    ranked = _rank_path_token_files(
        "ignore/types: add PKGBUILD type",
        files,
        top_k=3,
    )

    assert [row["file_id"] for row in ranked] == ["types", "default-types"]
    assert all(row["path_token_score"] > 0 for row in ranked)


def test_path_token_ranking_splits_punctuation_and_snake_case():
    from synsc.services.hybrid_retrieval import _rank_path_token_files

    files = [
        {
            "file_id": "origin",
            "repo_id": "repo",
            "file_path": "src/poetry/utils/authenticator/direct_origin.py",
        },
        {
            "file_id": "other",
            "repo_id": "repo",
            "file_path": "src/poetry/utils/authenticator/request.py",
        },
    ]

    ranked = _rank_path_token_files(
        "direct-origin: add size to file info",
        files,
        top_k=1,
    )

    assert [row["file_id"] for row in ranked] == ["origin"]


def test_path_token_ranking_splits_acronym_prefixed_camel_case():
    from synsc.services.hybrid_retrieval import _rank_path_token_files

    files = [
        {
            "file_id": "http-server",
            "repo_id": "repo",
            "file_path": "src/HTTPServer.py",
        },
        {
            "file_id": "other",
            "repo_id": "repo",
            "file_path": "src/socket.py",
        },
    ]

    ranked = _rank_path_token_files("HTTP server", files, top_k=1)

    assert [row["file_id"] for row in ranked] == ["http-server"]


def test_path_token_ranking_is_repository_local_and_totally_ordered():
    from synsc.services.hybrid_retrieval import _rank_path_token_files

    files = [
        {"file_id": "b", "repo_id": "repo-b", "file_path": "src/direct.py"},
        {"file_id": "z", "repo_id": "repo-a", "file_path": "z/direct.py"},
        {"file_id": "a", "repo_id": "repo-a", "file_path": "a/direct.py"},
    ]

    ranked = _rank_path_token_files("direct", files, top_k=3)

    assert [(row["repo_id"], row["file_id"]) for row in ranked] == [
        ("repo-a", "a"),
        ("repo-a", "z"),
        ("repo-b", "b"),
    ]


def test_path_token_search_returns_first_chunk_from_ranked_file():
    from synsc.services.hybrid_retrieval import path_token_search

    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class RecordingSession:
        def __init__(self):
            self.calls = []

        def execute(self, statement, params):
            self.calls.append((" ".join(str(statement).split()), params))
            if len(self.calls) == 1:
                return Rows(
                    [
                        {
                            "file_id": "request",
                            "repo_id": "repo",
                            "file_path": "src/authenticator/request.py",
                        },
                        {
                            "file_id": "origin",
                            "repo_id": "repo",
                            "file_path": "src/authenticator/direct_origin.py",
                        },
                    ]
                )
            return Rows(
                [
                    {
                        "chunk_id": "origin-0",
                        "repo_id": "repo",
                        "file_id": "origin",
                        "content": "class DirectOrigin: ...",
                        "start_line": 1,
                        "end_line": 10,
                        "chunk_index": 0,
                        "chunk_type": "code",
                        "language": "python",
                        "symbol_names": "DirectOrigin",
                        "file_path": "src/authenticator/direct_origin.py",
                        "repo_name": "python-poetry/poetry",
                        "is_public": True,
                    }
                ]
            )

    session = RecordingSession()
    results = path_token_search(
        session,
        "direct-origin: add size to file info",
        "user-id",
        repo_ids=["repo"],
        top_k=1,
    )

    assert [candidate.chunk_id for candidate in results] == ["origin-0"]
    assert results[0].sources["path_token"] > 0
    assert "ORDER BY rf.repo_id, rf.file_path, rf.file_id" in session.calls[0][0]
    assert "EXISTS (" in session.calls[0][0]
    assert "LIMIT :path_scan_limit" in session.calls[0][0]
    assert "ur.user_id = :user_id" in session.calls[0][0]
    assert "r.is_public = TRUE OR r.indexed_by = :user_id" in session.calls[0][0]


def test_path_token_search_skips_unscoped_queries():
    from synsc.services.hybrid_retrieval import path_token_search

    class Session:
        def execute(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("unscoped path-token search must not scan files")

    assert path_token_search(Session(), "direct origin", "user-id") == []


def test_path_token_search_fails_closed_when_scope_exceeds_file_limit():
    from synsc.services.hybrid_retrieval import path_token_search

    class Rows:
        def mappings(self):
            return self

        def all(self):
            return [
                {"file_id": "one", "repo_id": "repo", "file_path": "one.py"},
                {"file_id": "two", "repo_id": "repo", "file_path": "two.py"},
            ]

    class Session:
        calls = 0

        def execute(self, *_args, **_kwargs):
            self.calls += 1
            return Rows()

    session = Session()
    results = path_token_search(
        session,
        "one two",
        "user-id",
        repo_ids=["repo"],
        top_k=1,
        max_files=1,
    )

    assert results == []
    assert session.calls == 1


def test_hybrid_retrieve_runs_opt_in_path_token_branch(monkeypatch):
    import synsc.services.hybrid_retrieval as hybrid_module

    called = {}

    def fake_path_token_search(*args, **kwargs):
        called.update(kwargs)
        candidate = Candidate(chunk_id="path-token", file_path="src/direct.py")
        candidate.sources["path_token"] = 1.0
        return [candidate]

    monkeypatch.setattr(
        hybrid_module,
        "path_token_search",
        fake_path_token_search,
    )

    results = hybrid_module.hybrid_retrieve(
        session=object(),
        query="direct origin",
        query_embedding=object(),
        vector_search_fn=lambda **kwargs: [],
        user_id="user-id",
        repo_ids=["repo-id"],
        top_k=20,
        enable_bm25=False,
        enable_trigram=False,
        enable_symbol=False,
        enable_path=False,
        enable_path_token_search=True,
    )

    assert [candidate.chunk_id for candidate in results] == ["path-token"]
    assert called["repo_ids"] == ["repo-id"]
    assert called["top_k"] == 20


def test_zero_hit_path_token_branch_does_not_rescale_fusion(monkeypatch):
    import synsc.services.hybrid_retrieval as hybrid_module

    calls = 0

    def empty_path_token_search(*args, **kwargs):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(
        hybrid_module,
        "path_token_search",
        empty_path_token_search,
    )

    def vector_search(**kwargs):
        return [
            {
                "chunk_id": "vector-1",
                "file_id": "file-1",
                "file_path": "src/vector.py",
                "similarity": 0.9,
            }
        ]

    common = {
        "session": object(),
        "query": "direct origin",
        "query_embedding": object(),
        "vector_search_fn": vector_search,
        "user_id": "user-id",
        "repo_ids": ["repo-id"],
        "top_k": 20,
        "enable_bm25": False,
        "enable_trigram": False,
        "enable_symbol": False,
        "enable_path": False,
    }
    disabled = hybrid_module.hybrid_retrieve(
        **common,
        enable_path_token_search=False,
    )
    enabled_without_hits = hybrid_module.hybrid_retrieve(
        **common,
        enable_path_token_search=True,
    )

    assert enabled_without_hits[0].fused_score == disabled[0].fused_score
    assert calls == 1


def test_hybrid_retrieve_runs_opt_in_file_okapi_branch(monkeypatch):
    import synsc.services.hybrid_retrieval as hybrid_module

    called = {}

    def fake_file_okapi_search(*args, **kwargs):
        called["args"] = args
        called.update(kwargs)
        candidate = Candidate(
            chunk_id="file-okapi",
            file_path="src/user_service.py",
        )
        candidate.sources["file_okapi"] = 1.0
        return [candidate]

    monkeypatch.setattr(
        hybrid_module,
        "file_okapi_search",
        fake_file_okapi_search,
    )

    results = hybrid_module.hybrid_retrieve(
        session=object(),
        query="user service",
        query_embedding=object(),
        vector_search_fn=lambda **kwargs: [],
        user_id="user-id",
        repo_ids=["repo-id"],
        top_k=20,
        enable_bm25=False,
        enable_trigram=False,
        enable_symbol=False,
        enable_path=False,
        enable_file_okapi=True,
    )

    assert [candidate.chunk_id for candidate in results] == ["file-okapi"]
    assert called["args"][3] == ["repo-id"]
    assert called["top_k"] == 20


def test_hybrid_retrieve_aligns_file_okapi_onto_strongest_existing_chunk(
    monkeypatch,
):
    import synsc.services.hybrid_retrieval as hybrid_module

    def fake_file_okapi_search(*args, **kwargs):
        aligned = Candidate(chunk_id="lexical-a", file_id="file-a")
        aligned.sources["file_okapi"] = 4.0
        novel = Candidate(chunk_id="lexical-c", file_id="file-c")
        novel.sources["file_okapi"] = 3.0
        return [aligned, novel]

    monkeypatch.setattr(
        hybrid_module,
        "file_okapi_search",
        fake_file_okapi_search,
    )

    def vector_search(**kwargs):
        return [
            {
                "chunk_id": "shared-a",
                "file_id": "file-a",
                "file_path": "src/a.py",
                "similarity": 0.8,
            },
        ]

    results = hybrid_module.hybrid_retrieve(
        session=object(),
        query="user service",
        query_embedding=object(),
        vector_search_fn=vector_search,
        user_id="user-id",
        repo_ids=["repo-id"],
        top_k=20,
        enable_bm25=False,
        enable_trigram=False,
        enable_symbol=False,
        enable_path=False,
        enable_file_okapi=True,
    )

    by_id = {candidate.chunk_id: candidate for candidate in results}
    assert by_id["shared-a"].sources["file_okapi"] == 4.0
    assert by_id["lexical-c"].sources["file_okapi"] == 3.0


def test_zero_hit_file_okapi_branch_does_not_rescale_fusion(monkeypatch):
    import synsc.services.hybrid_retrieval as hybrid_module

    calls = 0

    def empty_file_okapi_search(*args, **kwargs):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(
        hybrid_module,
        "file_okapi_search",
        empty_file_okapi_search,
    )

    def vector_search(**kwargs):
        return [
            {
                "chunk_id": "vector-1",
                "file_id": "file-1",
                "file_path": "src/vector.py",
                "similarity": 0.9,
            }
        ]

    common = {
        "session": object(),
        "query": "user service",
        "query_embedding": object(),
        "vector_search_fn": vector_search,
        "user_id": "user-id",
        "repo_ids": ["repo-id"],
        "top_k": 20,
        "enable_bm25": False,
        "enable_trigram": False,
        "enable_symbol": False,
        "enable_path": False,
    }
    disabled = hybrid_module.hybrid_retrieve(
        **common,
        enable_file_okapi=False,
    )
    enabled_without_hits = hybrid_module.hybrid_retrieve(
        **common,
        enable_file_okapi=True,
    )

    assert enabled_without_hits[0].fused_score == disabled[0].fused_score
    assert calls == 1


def test_disabled_file_okapi_does_not_call_search(monkeypatch):
    import synsc.services.hybrid_retrieval as hybrid_module

    calls = 0

    def counting_file_okapi_search(*args, **kwargs):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(
        hybrid_module,
        "file_okapi_search",
        counting_file_okapi_search,
    )

    hybrid_module.hybrid_retrieve(
        session=object(),
        query="user service",
        query_embedding=object(),
        vector_search_fn=lambda **kwargs: [],
        user_id="user-id",
        repo_ids=["repo-id"],
        top_k=20,
        enable_bm25=False,
        enable_trigram=False,
        enable_symbol=False,
        enable_path=False,
        enable_file_okapi=False,
    )

    assert calls == 0


def test_unscoped_file_okapi_does_not_fuse_branch(monkeypatch):
    import synsc.services.hybrid_retrieval as hybrid_module

    calls = 0

    def counting_file_okapi_search(*args, **kwargs):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(
        hybrid_module,
        "file_okapi_search",
        counting_file_okapi_search,
    )

    def vector_search(**kwargs):
        return [
            {
                "chunk_id": "vector-1",
                "file_id": "file-1",
                "file_path": "src/vector.py",
                "similarity": 0.9,
            }
        ]

    hybrid_module.hybrid_retrieve(
        session=object(),
        query="user service",
        query_embedding=object(),
        vector_search_fn=vector_search,
        user_id="user-id",
        repo_ids=None,
        top_k=20,
        enable_bm25=False,
        enable_trigram=False,
        enable_symbol=False,
        enable_path=False,
        enable_file_okapi=True,
    )

    assert calls == 0


# ── File-level Okapi ─────────────────────────────────────────────────────────


class _FileOkapiRecordingSession:
    """Records SQL execute() calls and returns scripted row sets."""

    def __init__(self, scripted: list[list[dict]] | None = None) -> None:
        self.calls: list[SimpleNamespace] = []
        self._scripted = list(scripted or [])

    def execute(self, statement, params):
        call = SimpleNamespace(
            sql=" ".join(str(statement).split()),
            params=params,
        )
        self.calls.append(call)
        rows = self._scripted.pop(0) if self._scripted else []

        class _Result:
            def mappings(_self):
                return _self

            def all(_self):
                return rows

        return _Result()


def test_file_okapi_requires_repository_scope():
    from synsc.services.hybrid_retrieval import file_okapi_search

    session = _FileOkapiRecordingSession([])
    assert file_okapi_search(session, "user service", "u1", repo_ids=None) == []
    assert session.calls == []


def test_file_okapi_returns_empty_for_blank_query():
    from synsc.services.hybrid_retrieval import file_okapi_search

    session = _FileOkapiRecordingSession([])
    assert file_okapi_search(session, "   ", "u1", repo_ids=["repo-1"]) == []
    assert session.calls == []


def test_file_okapi_sql_uses_canonical_formula_scope_and_total_order():
    from synsc.services.hybrid_retrieval import file_okapi_search

    scope_count_row = {
        "requested_count": 1,
        "accessible_count": 1,
        "document_count": 2,
    }
    candidate_row = {
        "chunk_id": "chunk-1",
        "repo_id": "repo-1",
        "file_id": "file-1",
        "content": "class HTTPServer:\n    def get_user(self): pass",
        "start_line": 1,
        "end_line": 2,
        "chunk_index": 0,
        "chunk_type": "code",
        "language": "python",
        "symbol_names": '["HTTPServer"]',
        "file_path": "src/HTTPServer.py",
        "repo_name": "acme/service",
        "is_public": True,
        "score": 3.5,
    }
    session = _FileOkapiRecordingSession([[scope_count_row], [candidate_row]])
    candidates = file_okapi_search(
        session,
        "HTTPServer get_user",
        "u1",
        repo_ids=["repo-1"],
        top_k=7,
    )
    sql = session.calls[-1].sql
    assert "LN(1 +" in sql
    assert "document_frequency" in sql
    assert "average_document_length" in sql
    assert "ur.user_id = :user_id" in sql
    assert "r.is_public = TRUE OR r.indexed_by = :user_id" in sql
    assert "ORDER BY score DESC, rf.file_path" in sql
    assert candidates[0].sources["file_okapi"] > 0


def test_file_okapi_fails_closed_when_index_version_missing():
    from synsc.services.hybrid_retrieval import file_okapi_search

    session = _FileOkapiRecordingSession(
        [[{"requested_count": 1, "accessible_count": 0, "document_count": 0}]]
    )
    assert (
        file_okapi_search(session, "user service", "u1", repo_ids=["repo-1"])
        == []
    )
    assert len(session.calls) == 1


def test_file_okapi_fails_closed_when_scope_exceeds_file_limit():
    from synsc.services.hybrid_retrieval import (
        FILE_OKAPI_MAX_FILES,
        file_okapi_search,
    )

    session = _FileOkapiRecordingSession(
        [
            [
                {
                    "requested_count": 1,
                    "accessible_count": 1,
                    "document_count": FILE_OKAPI_MAX_FILES + 1,
                }
            ]
        ]
    )
    assert (
        file_okapi_search(session, "user service", "u1", repo_ids=["repo-1"])
        == []
    )
    assert len(session.calls) == 1


def test_file_okapi_applies_language_filter():
    from synsc.services.hybrid_retrieval import file_okapi_search

    session = _FileOkapiRecordingSession(
        [
            [{"requested_count": 1, "accessible_count": 1, "document_count": 1}],
            [],
        ]
    )
    file_okapi_search(
        session,
        "user service",
        "u1",
        repo_ids=["repo-1"],
        language="python",
    )
    assert session.calls[-1].params["language"] == "python"
    assert "rf.language = :language" in session.calls[-1].sql


def test_file_okapi_term_df_uses_language_filtered_scope_docs():
    from synsc.services.hybrid_retrieval import file_okapi_search

    session = _FileOkapiRecordingSession(
        [
            [{"requested_count": 1, "accessible_count": 1, "document_count": 1}],
            [],
        ]
    )
    file_okapi_search(
        session,
        "user service",
        "u1",
        repo_ids=["repo-1"],
        language="python",
    )
    sql = session.calls[-1].sql
    term_stats_start = sql.index("term_stats AS (")
    term_stats_end = sql.index("), file_scores AS (")
    term_stats_sql = sql[term_stats_start:term_stats_end]
    assert "scope_docs" in term_stats_sql
    assert "lt.repo_id IN" not in term_stats_sql


def test_file_okapi_clamps_top_k_to_candidate_cap():
    from synsc.services.hybrid_retrieval import (
        FILE_OKAPI_CANDIDATES,
        file_okapi_search,
    )

    session = _FileOkapiRecordingSession(
        [
            [{"requested_count": 1, "accessible_count": 1, "document_count": 1}],
            [],
        ]
    )
    file_okapi_search(
        session,
        "user service",
        "u1",
        repo_ids=["repo-1"],
        top_k=500,
    )
    assert session.calls[-1].params["top_k"] == FILE_OKAPI_CANDIDATES


def test_file_okapi_deduplicates_repo_ids_before_validation():
    from synsc.services.hybrid_retrieval import file_okapi_search

    session = _FileOkapiRecordingSession(
        [
            [{"requested_count": 1, "accessible_count": 1, "document_count": 1}],
            [],
        ]
    )
    candidates = file_okapi_search(
        session,
        "user service",
        "u1",
        repo_ids=["repo-1", "repo-1"],
        top_k=5,
    )
    assert candidates == []
    assert len(session.calls) == 2
    assert session.calls[-1].params["repo_id_0"] == "repo-1"
    assert "repo_id_1" not in session.calls[-1].params


def test_file_okapi_rolls_back_session_after_sql_failure():
    from synsc.services.hybrid_retrieval import file_okapi_search

    class FailingSession(_FileOkapiRecordingSession):
        rollbacks = 0

        def rollback(self) -> None:
            self.rollbacks += 1

        def execute(self, statement, params):
            if len(self.calls) == 0:
                raise RuntimeError("scope query failed")
            return super().execute(statement, params)

    session = FailingSession([])
    assert (
        file_okapi_search(session, "user service", "u1", repo_ids=["repo-1"]) == []
    )
    assert session.rollbacks == 1


def test_file_okapi_selects_best_chunk_with_total_order():
    from synsc.services.hybrid_retrieval import file_okapi_search

    session = _FileOkapiRecordingSession(
        [
            [{"requested_count": 1, "accessible_count": 1, "document_count": 1}],
            [],
        ]
    )
    file_okapi_search(session, "alpha beta", "u1", repo_ids=["repo-1"])
    sql = session.calls[-1].sql
    assert (
        "ROW_NUMBER() OVER ( PARTITION BY cc.file_id "
        "ORDER BY ts_rank_cd("
    ) in sql
    assert (
        "ORDER BY score DESC, rf.file_path, chunk_index, repo_id, chunk_id"
    ) in sql
