"""Tests for docs auto-discovery + opt-in repo-indexing pipeline."""
from __future__ import annotations

import pytest

from synsc.services import docs_autodiscover, source_service


def test_looks_like_docs_positive():
    for u in (
        "https://fastapi.tiangolo.com",
        "https://docs.pydantic.dev",
        "https://www.python-httpx.org/docs/",
        "https://something.readthedocs.io",
        "https://acme.rtd.io",
    ):
        assert docs_autodiscover._looks_like_docs(u), u


def test_looks_like_docs_negative():
    for u in (
        "https://github.com/x/y",
        "https://example.com",
        "https://twitter.com/x",
    ):
        assert not docs_autodiscover._looks_like_docs(u), u


def test_normalize_docs_root_collapses_deep_paths():
    out = docs_autodiscover._normalize_docs_root(
        "https://docs.example.com/en/latest/intro"
    )
    assert out == "https://docs.example.com/"


def test_discover_docs_url_skips_non_github(monkeypatch):
    out = docs_autodiscover.discover_docs_url("https://gitlab.com/x/y")
    assert out is None


def test_discover_docs_url_returns_github_homepage(monkeypatch):
    class FakeResp:
        status_code = 200

        def json(self):
            return {"homepage": "https://fastapi.tiangolo.com"}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **kw):
            if "api.github.com/repos" in url:
                return FakeResp()
            r = FakeResp()
            r.status_code = 404
            return r

    monkeypatch.setattr(docs_autodiscover.httpx, "Client", FakeClient)
    out = docs_autodiscover.discover_docs_url("https://github.com/fastapi/fastapi")
    assert out == "https://fastapi.tiangolo.com/"


def test_discover_docs_url_falls_back_to_readme(monkeypatch):
    state = {"phase": "homepage"}

    class FakeResp:
        def __init__(self, body, code=200):
            self.text = body
            self.status_code = code

        def json(self):
            import json
            return json.loads(self.text)

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **kw):
            if "api.github.com" in url:
                return FakeResp('{"homepage": ""}')
            if url.endswith("README.md"):
                return FakeResp(
                    "Welcome\nVisit our docs at https://docs.example.com/ for details."
                )
            return FakeResp("", code=404)

    monkeypatch.setattr(docs_autodiscover.httpx, "Client", FakeClient)
    out = docs_autodiscover.discover_docs_url("https://github.com/x/y")
    assert out == "https://docs.example.com/"


def test_discover_docs_url_uses_pyproject(monkeypatch):
    class FakeResp:
        def __init__(self, body, code=200):
            self.text = body
            self.status_code = code

        def json(self):
            import json
            return json.loads(self.text)

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **kw):
            if "api.github.com" in url:
                return FakeResp('{"homepage": ""}')
            if url.endswith("README.md") or url.endswith("README.rst") or url.endswith("README"):
                return FakeResp("", code=404)
            if url.endswith("pyproject.toml"):
                return FakeResp(
                    '[project.urls]\nDocumentation = "https://docs.example.com/v1/"\n'
                )
            return FakeResp("", code=404)

    monkeypatch.setattr(docs_autodiscover.httpx, "Client", FakeClient)
    out = docs_autodiscover.discover_docs_url("https://github.com/x/y")
    assert out == "https://docs.example.com/"


def test_index_source_auto_docs_opt_in(monkeypatch):
    """When auto_index_docs=true, the repo index also indexes the docs site."""
    captured_indexes: list[tuple[str, str]] = []

    class FakeIndexingService:
        def __init__(self, user_id=None):
            pass

        def index_repository(self, **kw):
            return {
                "success": True,
                "repo_id": "r-1",
                "status": "indexed",
                "owner": "x",
                "name": "y",
            }

    monkeypatch.setattr(
        source_service,
        "_get_indexing_service",
        lambda uid: FakeIndexingService(),
    )
    monkeypatch.setattr(
        docs_autodiscover,
        "discover_docs_url",
        lambda repo_url, branch="main": "https://docs.example.com/",
    )

    # Patch the docs branch of index_source to capture rather than crawl.
    original_index_source = source_service.index_source

    def wrap(**kw):
        if kw.get("source_type") == "docs":
            captured_indexes.append((kw["source_type"], kw["url"]))
            return {
                "source_id": "d-1",
                "source_type": "docs",
                "status": "indexed",
                "external_ref": kw["url"],
            }
        return original_index_source(**kw)

    monkeypatch.setattr(source_service, "index_source", wrap)
    out = wrap(
        source_type="repo",
        url="https://github.com/fastapi/fastapi",
        options={"auto_index_docs": True},
        user_id="u1",
    )
    assert out["source_type"] == "repo"
    assert ("docs", "https://docs.example.com/") in captured_indexes
    assert out["docs_index"]["source_id"] == "d-1"


def test_index_source_no_auto_when_opted_out(monkeypatch):
    """Default behavior unchanged: no docs auto-index when option absent."""
    seen = {"docs_calls": 0}

    class FakeIndexingService:
        def __init__(self, user_id=None):
            pass

        def index_repository(self, **kw):
            return {
                "success": True,
                "repo_id": "r-1",
                "status": "indexed",
                "owner": "x",
                "name": "y",
            }

    monkeypatch.setattr(
        source_service,
        "_get_indexing_service",
        lambda uid: FakeIndexingService(),
    )

    def boom(*a, **k):
        seen["docs_calls"] += 1
        raise AssertionError("docs auto-index should not run by default")

    monkeypatch.setattr(docs_autodiscover, "discover_docs_url", boom)
    out = source_service.index_source(
        source_type="repo",
        url="https://github.com/fastapi/fastapi",
        user_id="u1",
    )
    assert out["status"] == "indexed"
    assert seen["docs_calls"] == 0
    assert "docs_index" not in out
