"""Unit tests for context_pack helpers (path classification, token estimator,
broad-query detection). The full builder is integration-tested separately.
"""
from __future__ import annotations

from synsc.services.context_pack import (
    _approx_tokens,
    _query_is_broad,
    classify_path,
    PackSnippet,
    ContextPack,
)


def test_classify_path_test_files():
    assert classify_path("tests/test_x.py") == "test"
    assert classify_path("src/foo.test.ts") == "test"
    assert classify_path("__tests__/foo.spec.js") == "test"
    assert classify_path("conftest.py") == "test"


def test_classify_path_doc_files():
    assert classify_path("README.md") == "doc"
    assert classify_path("docs/intro.mdx") == "doc"
    assert classify_path("CHANGELOG.rst") == "doc"


def test_classify_path_config_files():
    assert classify_path("Dockerfile") == "config"
    assert classify_path("Makefile") == "config"
    assert classify_path("go.mod") == "config"
    assert classify_path(".env.example") == "config"
    assert classify_path("pyproject.toml") == "config"


def test_classify_path_example_files():
    assert classify_path("examples/foo.py") == "example"
    assert classify_path("demo/x.py") == "example"
    assert classify_path("sample/bar.py") == "example"


def test_classify_path_default_code():
    assert classify_path("src/foo.py") == "code"
    assert classify_path("lib/bar.ts") == "code"


def test_approx_tokens_positive():
    assert _approx_tokens("") == 1  # min 1
    assert _approx_tokens("abcd") == 1
    assert _approx_tokens("a" * 400) == 100  # 400/4


def test_query_is_broad_long_no_identifier():
    assert _query_is_broad("how does the authentication system work") is True


def test_query_is_broad_short_query():
    # Too short to be "broad" by our heuristic
    assert _query_is_broad("auth flow") is False


def test_query_is_broad_with_identifier_is_specific():
    # Has CamelCase identifier — specific query, not broad
    assert _query_is_broad("explain how handleAuthCallback works") is False
    # snake_case
    assert _query_is_broad("walk me through the get_user_id_from_token flow") is False
    # dotted path
    assert _query_is_broad("understand fastapi.routing.APIRouter behavior") is False


def test_pack_snippet_to_dict_shape():
    s = PackSnippet(
        role="primary",
        chunk_id="abc",
        repo_id="r1",
        repo_name="org/repo",
        file_path="src/x.py",
        start_line=1,
        end_line=20,
        content="def foo(): pass",
        language="python",
    )
    d = s.to_dict()
    assert d["role"] == "primary"
    assert d["repo_name"] == "org/repo"
    assert d["start_line"] == 1
    assert d["end_line"] == 20


def test_context_pack_aggregates_snippets_and_estimates():
    p = ContextPack(query="x", quality_mode="agent", token_budget=1000)
    p.snippets.append(PackSnippet(
        role="primary", chunk_id="a", repo_id="r1", repo_name="o/r",
        file_path="x.py", start_line=1, end_line=1, content="x",
    ))
    p.used_tokens_estimate = _approx_tokens("x")
    d = p.to_dict()
    assert d["query"] == "x"
    assert d["quality_mode"] == "agent"
    assert d["token_budget"] == 1000
    assert len(d["snippets"]) == 1
    assert d["snippets"][0]["chunk_id"] == "a"


def test_classify_path_robust_to_edge_cases():
    assert classify_path("") == "code"
    assert classify_path("a") == "code"
    assert classify_path("/") == "code"
