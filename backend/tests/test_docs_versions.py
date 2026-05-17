"""Tests for versioned docs lookup + resolver `url@version` syntax."""
from __future__ import annotations

import pytest

from synsc.services import source_service


def test_resolve_docs_url_with_version_calls_lookup(monkeypatch):
    seen = {}

    def fake_lookup(url, version=None):
        seen["url"] = url
        seen["version"] = version
        return "docs-uuid"

    monkeypatch.setattr(source_service, "_lookup_docs_by_url", fake_lookup)
    sid, stype = source_service.resolve_source_id(
        "https://docs.example.com/@v1.2.3"
    )
    assert sid == "docs-uuid"
    assert stype == "docs"
    assert seen["url"] == "https://docs.example.com/"
    assert seen["version"] == "v1.2.3"


def test_resolve_docs_url_without_version(monkeypatch):
    seen = {}

    def fake_lookup(url, version=None):
        seen["version"] = version
        return "docs-uuid"

    monkeypatch.setattr(source_service, "_lookup_docs_by_url", fake_lookup)
    source_service.resolve_source_id("https://docs.example.com/")
    assert seen["version"] is None


def test_resolve_at_in_path_not_treated_as_version(monkeypatch):
    """An @ inside the path (e.g. user@host) should not be a version separator."""
    seen = {}

    def fake_lookup(url, version=None):
        seen["url"] = url
        seen["version"] = version
        return "docs-uuid"

    monkeypatch.setattr(source_service, "_lookup_docs_by_url", fake_lookup)
    # 'foo/bar' after @ contains a slash → not a version
    source_service.resolve_source_id("https://docs.example.com/u@foo/bar")
    assert seen["version"] is None


def test_index_docs_persists_version(monkeypatch):
    """Verify index_docs forwards `version` into the DB session add()."""
    from synsc.services import docs_service

    captured: list = []

    class FakeQ:
        def filter(self, *a, **k):
            return self

        def first(self):
            return None  # nothing pre-existing

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def query(self, *a, **k):
            return FakeQ()

        def add(self, obj):
            captured.append(obj)

        def flush(self):
            pass

        def add_all(self, *a, **k):
            pass

        def execute(self, *a, **k):
            return None

        def commit(self):
            pass

    monkeypatch.setattr(docs_service, "get_session", lambda: FakeSession())
    # Force the sitemap fetch + crawl to short-circuit by patching the crawl
    # primitives to yield a single page.
    monkeypatch.setattr(
        docs_service.DocsService,
        "_iter_sitemap_urls",
        lambda self, c, sm, mp: iter(["https://docs.example.com/page"]),
    )
    monkeypatch.setattr(
        docs_service.DocsService,
        "_fetch",
        lambda self, c, u: b"<html><body><h1>hello</h1>routing details</body></html>",
    )
    monkeypatch.setattr(
        docs_service.DocsService,
        "_embed",
        lambda self, texts: [[0.0] * 768 for _ in texts],
    )

    svc = docs_service.DocsService(user_id="u1")
    res = svc.index_docs(
        url="https://docs.example.com/",
        version="v1.2.3",
        req_delay_s=0,
    )
    assert res["success"] is True
    from synsc.database.models import DocumentationSource

    docs_row = next(
        (o for o in captured if isinstance(o, DocumentationSource)), None
    )
    assert docs_row is not None
    assert docs_row.version == "v1.2.3"
    assert docs_row.url == "https://docs.example.com/"
