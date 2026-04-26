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


def test_html_to_markdown_extracts_first_h1_as_heading():
    from synsc.services.docs_service import DocsService

    md, heading = DocsService._html_to_markdown(
        b"<html><body><h1>Hello</h1><p>World</p></body></html>"
    )
    assert "Hello" in md
    assert heading == "Hello"


def test_chunk_markdown_respects_overlap():
    from synsc.services.docs_service import DocsService

    big = "abcdefghij" * 1000  # 10_000 chars
    chunks = DocsService._chunk_markdown(big, chunk_tokens=100, overlap=10)
    assert len(chunks) > 1
    # Chunk N-1 end should overlap with chunk N start
    overlap_chars = 10 * 4
    assert chunks[1].startswith(chunks[0][-overlap_chars:])


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
    from synsc.services import source_service
    from synsc.services import docs_service as ds_mod

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
    from synsc.services import source_service
    from synsc.services import docs_service as ds_mod

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
    from synsc.services import source_service
    from synsc.services import docs_service as ds_mod

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
    from synsc.services import source_service
    from synsc.services import docs_service as ds_mod

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
    assert hits[0]["score"] == 0.95


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
