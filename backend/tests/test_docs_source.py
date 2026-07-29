"""Unit tests for DocsService + docs branch in unified index dispatch."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Sitemap discovery + chunking (pure helpers, no DB)
# ---------------------------------------------------------------------------


def test_discover_sitemap_returns_passed_xml_unchanged():
    from synsc.services.docs_service import DocsService

    svc = DocsService(user_id="u1")
    assert svc._discover_sitemap("https://x.com/sitemap.xml") == "https://x.com/sitemap.xml"


def test_discover_sitemap_falls_back_to_origin_root():
    from synsc.services.docs_service import DocsService

    svc = DocsService(user_id="u1")
    assert (
        svc._discover_sitemap("https://docs.example.com/getting-started")
        == "https://docs.example.com/sitemap.xml"
    )


def test_crawl_pages_stays_within_documentation_subtree(monkeypatch):
    from synsc.services.docs_service import DocsService

    pages = {
        "https://docs.example.com/stable/": b"""
            <a href="guide.html">Guide</a>
            <a href="/stable/api.html#method">API</a>
            <a href="/other/private.html">Other subtree</a>
            <a href="https://outside.example/docs.html">External</a>
            <a href="asset.css">Asset</a>
        """,
        "https://docs.example.com/stable/guide.html": (
            b'<a href="api.html">API duplicate</a>'
        ),
        "https://docs.example.com/stable/api.html": b"<p>API</p>",
    }
    monkeypatch.setattr(
        DocsService,
        "_fetch",
        lambda self, client, url: pages[url],
    )

    crawled = list(
        DocsService(user_id="u1")._iter_crawl_pages(
            object(),
            "https://docs.example.com/stable/",
            max_pages=5,
        )
    )

    assert [url for url, _body in crawled] == [
        "https://docs.example.com/stable/",
        "https://docs.example.com/stable/guide.html",
        "https://docs.example.com/stable/api.html",
    ]


def test_auto_discovered_sitemap_failure_falls_back_to_bounded_crawl(
    monkeypatch,
):
    from synsc.services.docs_service import DocsService

    service = DocsService(user_id="u1")
    monkeypatch.setattr(
        service,
        "_iter_sitemap_urls",
        lambda *args: (_ for _ in ()).throw(RuntimeError("404 sitemap")),
    )
    monkeypatch.setattr(
        service,
        "_iter_crawl_pages",
        lambda *args, **kwargs: iter(
            [("https://docs.example.com/stable/", b"<h1>Docs</h1>")]
        ),
    )

    pages = service._resolve_pages(
        object(),
        "https://docs.example.com/stable/",
        sitemap_url=None,
        max_pages=3,
    )

    assert pages == [
        ("https://docs.example.com/stable/", b"<h1>Docs</h1>")
    ]


def test_auto_discovered_sitemap_outside_docs_subtree_falls_back_to_crawl(
    monkeypatch,
):
    from synsc.services.docs_service import DocsService

    service = DocsService(user_id="u1")
    monkeypatch.setattr(
        service,
        "_iter_sitemap_urls",
        lambda *args: iter(
            [
                "https://example.com/about/",
                "https://example.com/es/news/",
            ]
        ),
    )
    monkeypatch.setattr(
        service,
        "_iter_crawl_pages",
        lambda *args, **kwargs: iter(
            [
                (
                    "https://example.com/doc/stable/",
                    b"<h1>Versioned API docs</h1>",
                )
            ]
        ),
    )

    pages = service._resolve_pages(
        object(),
        "https://example.com/doc/stable/",
        sitemap_url=None,
        max_pages=3,
    )

    assert pages == [
        (
            "https://example.com/doc/stable/",
            b"<h1>Versioned API docs</h1>",
        )
    ]


def test_auto_discovered_sitemap_keeps_only_pages_in_requested_subtree(
    monkeypatch,
):
    from synsc.services.docs_service import DocsService

    service = DocsService(user_id="u1")
    monkeypatch.setattr(
        service,
        "_iter_sitemap_urls",
        lambda *args: iter(
            [
                "https://example.com/about/",
                "https://example.com/doc/stable/api.html",
                "https://other.example.com/doc/stable/private.html",
            ]
        ),
    )
    monkeypatch.setattr(
        service,
        "_iter_crawl_pages",
        lambda *args, **kwargs: pytest.fail(
            "an in-scope sitemap page should avoid crawl fallback"
        ),
    )

    pages = service._resolve_pages(
        object(),
        "https://example.com/doc/stable/",
        sitemap_url=None,
        max_pages=3,
    )

    assert pages == [
        ("https://example.com/doc/stable/api.html", None),
    ]


def test_extensionless_docs_root_without_slash_stays_in_its_subtree(
    monkeypatch,
):
    from synsc.services.docs_service import DocsService

    service = DocsService(user_id="u1")
    monkeypatch.setattr(
        service,
        "_iter_sitemap_urls",
        lambda *args: iter(
            [
                "https://example.com/about/",
                "https://example.com/docs",
                "https://example.com/docs/api/client",
                "https://example.com/docs-old/archive",
            ]
        ),
    )

    pages = service._resolve_pages(
        object(),
        "https://example.com/docs",
        sitemap_url=None,
        max_pages=4,
    )

    assert pages == [
        ("https://example.com/docs", None),
        ("https://example.com/docs/api/client", None),
    ]


@pytest.mark.parametrize(
    "candidate",
    [
        "https://example.com/docs/%2e%2e/admin",
        "https://example.com/docs/%252e%252e/admin",
        "https://example.com/docs/%2E%2E%2Fadmin",
        "https://example.com/docs/%5c..%5cadmin",
    ],
)
def test_documentation_scope_rejects_encoded_traversal(candidate):
    from synsc.services.docs_service import _in_documentation_scope

    assert not _in_documentation_scope(
        "https://example.com/docs/",
        candidate,
    )


@pytest.mark.parametrize("suffix", [".md", ".rst", ".txt"])
def test_document_entrypoint_files_scope_to_sibling_pages(suffix):
    from synsc.services.docs_service import _in_documentation_scope

    assert _in_documentation_scope(
        f"https://example.com/docs/guide{suffix}",
        "https://example.com/docs/reference/api.html",
    )


def test_explicit_sitemap_failure_does_not_silently_change_scope(monkeypatch):
    from synsc.services.docs_service import DocsService

    service = DocsService(user_id="u1")
    monkeypatch.setattr(
        service,
        "_iter_sitemap_urls",
        lambda *args: (_ for _ in ()).throw(RuntimeError("404 sitemap")),
    )

    with pytest.raises(RuntimeError, match="404 sitemap"):
        service._resolve_pages(
            object(),
            "https://docs.example.com/stable/",
            sitemap_url="https://docs.example.com/custom-sitemap.xml",
            max_pages=3,
        )


def test_docs_url_validation_rejects_loopback_and_private_addresses():
    from synsc.services.docs_service import _validate_public_url

    for url in (
        "http://127.0.0.1/admin",
        "http://[::1]/admin",
        "http://10.0.0.5/docs",
        "http://169.254.169.254/latest/meta-data/",
    ):
        with pytest.raises(ValueError, match="public"):
            _validate_public_url(url)


def test_docs_fetch_rejects_redirect_to_private_address():
    from synsc.services.docs_service import DocsService

    class RedirectResponse:
        status_code = 302
        headers = {"location": "http://127.0.0.1/secrets"}

    class FakeClient:
        def get(self, url, **kwargs):
            return RedirectResponse()

    with pytest.raises(ValueError, match="public"):
        DocsService(user_id="u1")._fetch(FakeClient(), "https://8.8.8.8/docs")


def test_public_network_backend_pins_connection_to_validated_address(monkeypatch):
    import socket

    from synsc.services.docs_service import _PublicNetworkBackend

    resolutions = [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("93.184.216.34", 443),
        )
    ]
    connected_to = []

    class FakeSocket:
        def setsockopt(self, *args):
            pass

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: resolutions)
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda address, *args, **kwargs: connected_to.append(address) or FakeSocket(),
    )

    _PublicNetworkBackend().connect_tcp("attacker-controlled.test", 443)

    assert connected_to == [("93.184.216.34", 443)]


def test_public_network_backend_rejects_rebound_private_address(monkeypatch):
    import socket

    from synsc.services.docs_service import _PublicNetworkBackend

    private_resolution = [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("127.0.0.1", 443),
        )
    ]
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *args, **kwargs: private_resolution
    )

    with pytest.raises(ValueError, match="public"):
        _PublicNetworkBackend().connect_tcp("attacker-controlled.test", 443)


def test_html_to_markdown_extracts_first_h1_as_heading():
    from synsc.services.docs_service import DocsService

    md, heading = DocsService._html_to_markdown(
        b"<html><body><h1>Hello</h1><p>World</p></body></html>"
    )
    assert "Hello" in md
    assert heading == "Hello"


def test_chunk_markdown_oversized_single_section_splits():
    """A single heading-less mass of text bigger than the budget gets split."""
    from synsc.services.docs_service import DocsService

    big = "abcdefghij " * 1000  # ~11_000 chars
    chunks = DocsService._chunk_markdown(big, chunk_tokens=100)
    assert len(chunks) > 1
    # Each chunk is a (heading_path, text) tuple after the heading-aware
    # rewrite.
    for path, txt in chunks:
        assert isinstance(path, str)
        assert isinstance(txt, str)
        assert txt.strip()


def test_chunk_markdown_empty_input():
    from synsc.services.docs_service import DocsService

    assert DocsService._chunk_markdown("") == []
    assert DocsService._chunk_markdown("   \n   ") == []


def test_sanitize_text_strips_null_bytes():
    from synsc.services.docs_service import _sanitize_text

    assert _sanitize_text("hello\x00world") == "helloworld"
    assert _sanitize_text(None) == ""


# ---------------------------------------------------------------------------
# Service-level: index_docs requires user_id
# ---------------------------------------------------------------------------


def test_index_docs_requires_user_id():
    from synsc.services.docs_service import DocsService

    svc = DocsService(user_id=None)
    res = svc.index_docs(url="https://example.com")
    assert res["success"] is False
    assert "User ID is required" in res["error"]


# ---------------------------------------------------------------------------
# Wiring: docs branch in source_service.index_source
# ---------------------------------------------------------------------------


def test_index_source_docs_dispatches_to_docs_service(monkeypatch):
    from synsc.services import docs_service as ds_mod
    from synsc.services import source_service

    fake_svc = MagicMock()
    fake_svc.index_docs.return_value = {
        "success": True,
        "status": "indexed",
        "docs_id": "d-uuid",
        "url": "https://docs.example.com",
        "pages": 12,
        "chunks": 88,
    }
    monkeypatch.setattr(ds_mod, "get_docs_service", lambda user_id=None: fake_svc)
    monkeypatch.setattr(
        source_service,
        "publish_source_snapshot",
        lambda *args, **kwargs: {"snapshot_id": "snapshot-docs"},
    )

    out = source_service.index_source(
        source_type="docs",
        url="https://docs.example.com",
        user_id="u1",
    )

    fake_svc.index_docs.assert_called_once()
    assert out["source_id"] == "d-uuid"
    assert out["source_type"] == "docs"
    assert out["status"] == "indexed"


def test_index_source_docs_sitemap_failure_surfaces_as_error(monkeypatch):
    """A sitemap that 404s should propagate as status='error' so the HTTP
    layer can return 502 instead of a misleading 200."""
    from synsc.services import docs_service as ds_mod
    from synsc.services import source_service

    fake_svc = MagicMock()
    fake_svc.index_docs.return_value = {
        "success": False,
        "error": "sitemap fetch failed: 404 Not Found",
        "url": "https://example.com/sitemap.xml",
    }
    monkeypatch.setattr(ds_mod, "get_docs_service", lambda user_id=None: fake_svc)

    out = source_service.index_source(
        source_type="docs",
        url="https://example.com/sitemap.xml",
        user_id="u1",
    )

    assert out["status"] == "error"
    assert out["source_id"] == ""
    assert "sitemap fetch failed" in out["error"]


def test_index_source_docs_requires_user_id():
    from synsc.services.source_service import index_source

    with pytest.raises(ValueError, match="docs indexing requires"):
        index_source(source_type="docs", url="https://x.com", user_id=None)


def test_list_sources_includes_docs_branch(monkeypatch):
    from synsc.services import docs_service as ds_mod
    from synsc.services import source_service

    fake_svc = MagicMock()
    fake_svc.list_docs.return_value = [
        {
            "docs_id": "d1",
            "url": "https://docs.example.com",
            "display_name": "Example Docs",
            "indexed_at": "2026-04-01",
        }
    ]
    monkeypatch.setattr(ds_mod, "get_docs_service", lambda user_id=None: fake_svc)

    # Stub out other branches so we only see the docs one.
    monkeypatch.setattr(
        source_service,
        "_get_indexing_service",
        lambda user_id: MagicMock(list_repositories=lambda **kw: {"repositories": []}),
    )
    monkeypatch.setattr(
        source_service,
        "_get_paper_service",
        lambda user_id: MagicMock(list_papers=lambda: []),
    )
    monkeypatch.setattr(
        source_service,
        "_get_dataset_service",
        lambda user_id: MagicMock(list_datasets=lambda: []),
    )

    out = source_service.list_sources(user_id="u1")
    docs_entries = [s for s in out if s["source_type"] == "docs"]
    assert len(docs_entries) == 1
    assert docs_entries[0]["display_name"] == "Example Docs"


# ---------------------------------------------------------------------------
# Migration script structural assertion
# ---------------------------------------------------------------------------


def test_search_docs_requires_user_id():
    from synsc.services.docs_service import DocsService

    res = DocsService(user_id=None).search_docs(query="x")
    assert res["success"] is False
    assert res["results"] == []


def test_unified_retrieve_includes_docs_branch_by_default(monkeypatch):
    """Without an explicit source_types filter, the docs branch should fan out
    alongside repo / paper / dataset (P2 — was previously excluded)."""
    from synsc.services import docs_service as ds_mod
    from synsc.services import source_service

    fake_docs_svc = MagicMock()
    fake_docs_svc.search_docs.return_value = {
        "results": [
            {
                "chunk_id": "dc1",
                "docs_id": "d1",
                "page_url": "https://docs.example.com/page",
                "heading": "Intro",
                "content": "doc body",
                "similarity": 0.95,
                "docs_url": "https://docs.example.com",
                "display_name": "Example Docs",
            }
        ]
    }
    monkeypatch.setattr(ds_mod, "get_docs_service", lambda user_id=None: fake_docs_svc)

    # Stub out the other branches so the test isolates the docs branch.
    monkeypatch.setattr(
        source_service,
        "_get_search_service",
        lambda user_id: MagicMock(search_code=lambda **kw: {"results": []}),
    )
    monkeypatch.setattr(
        source_service,
        "_get_paper_service",
        lambda user_id: MagicMock(search_papers=lambda **kw: {"results": []}),
    )
    monkeypatch.setattr(
        source_service,
        "_get_dataset_service",
        lambda user_id: MagicMock(search_datasets=lambda **kw: {"results": []}),
    )

    hits = source_service.unified_retrieve(query="q", k=10, user_id="u1")
    assert len(hits) == 1
    assert hits[0]["source_type"] == "docs"
    assert hits[0]["metadata"]["page_url"] == "https://docs.example.com/page"
    assert hits[0]["metadata"]["docs_url"] == "https://docs.example.com"
    # Per-branch normalization rescales the single docs hit to 1.0;
    # the raw similarity was 0.95.
    assert hits[0]["score"] in (0.95, 1.0)


def test_alembic_003_docs_sources_migration_exists():
    from pathlib import Path

    versions = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
    )
    f = next(versions.glob("003_docs_sources.py"))
    content = f.read_text()
    assert 'revision: str = "003_docs_sources"' in content
    assert 'down_revision: Union[str, None] = "002_research_jobs"' in content
    assert "documentation_sources" in content
    assert "documentation_chunk_embeddings" in content
    assert "vector(768)" in content
