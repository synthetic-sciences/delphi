"""Unit tests for the unified /v1/search + /v1/sources surface.

Covers the service-level dispatchers in ``synsc.services.source_service``
and the HTTP endpoints that call into them.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _disable_slowapi():
    """Slowapi keeps a global in-memory rate-limit counter that leaks across
    tests (no per-test reset hook). Disable it for this file so the tight
    INDEX_LIMIT (5/min) doesn't 429 the second /v1/sources test that runs."""
    from synsc.api.rate_limit import limiter

    was_enabled = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = was_enabled


# ---------------------------------------------------------------------------
# Service-level: unified_search
# ---------------------------------------------------------------------------


def test_normalize_mode_resolves_nia_aliases():
    from synsc.services.source_service import normalize_mode

    assert normalize_mode("targeted") == "precise"
    assert normalize_mode("universal") == "thorough"
    assert normalize_mode("precise") == "precise"
    assert normalize_mode("thorough") == "thorough"
    assert normalize_mode("web") == "web"


def test_normalize_mode_rejects_unknown_mode():
    import pytest

    from synsc.services.source_service import normalize_mode

    with pytest.raises(ValueError, match="unsupported search mode"):
        normalize_mode("zoomzoom")


def test_unified_search_dedupes_by_text_hash(monkeypatch):
    """Two hits with identical text collapse to one in the unified envelope."""
    from synsc.services import source_service

    duplicate = {
        "source_type": "repo",
        "source_id": "r1",
        "chunk_id": "c1",
        "text": "same body",
        "score": 0.9,
        "path": "a.py",
        "line_no": 1,
    }
    distinct = {
        "source_type": "paper",
        "source_id": "p1",
        "chunk_id": "c2",
        "text": "different body",
        "score": 0.8,
        "path": "Intro",
        "line_no": None,
    }

    monkeypatch.setattr(
        source_service,
        "unified_retrieve",
        lambda **kwargs: [duplicate, dict(duplicate, chunk_id="c1b"), distinct],
    )

    result = source_service.unified_search(query="q", k=10, mode="precise")

    assert result["mode_applied"] == "precise"
    assert result["total"] == 2
    assert {h["chunk_id"] for h in result["results"]} == {"c1", "c2"}


def test_unified_search_web_mode_returns_stub():
    from synsc.services.source_service import unified_search

    result = unified_search(query="anything", k=10, mode="web")
    assert result["mode_applied"] == "web"
    assert result["results"] == []
    assert result["total"] == 0
    assert result["notice"] == "web mode not yet implemented"


# ---------------------------------------------------------------------------
# Service-level: index_source
# ---------------------------------------------------------------------------


def test_index_source_repo_dispatches_to_indexing_service(monkeypatch):
    from synsc.services import source_service

    fake_indexer = MagicMock()
    fake_indexer.index_repository.return_value = {
        "repo_id": "r-uuid",
        "status": "indexed",
    }
    monkeypatch.setattr(
        source_service, "_get_indexing_service", lambda user_id: fake_indexer
    )

    result = source_service.index_source(
        source_type="repo",
        url="https://github.com/owner/repo",
        options={"branch": "main", "deep_index": False},
        user_id="u1",
    )

    fake_indexer.index_repository.assert_called_once()
    assert result["source_id"] == "r-uuid"
    assert result["source_type"] == "repo"
    assert result["external_ref"] == "https://github.com/owner/repo"


def test_index_source_unsupported_type_raises_value_error():
    import pytest

    from synsc.services.source_service import index_source

    with pytest.raises(ValueError, match="unsupported source_type"):
        index_source(source_type="movie", url="x", user_id="u1")


def test_index_source_docs_raises_not_implemented_pre_p2():
    import pytest

    from synsc.services.source_service import index_source

    with pytest.raises(NotImplementedError, match="docs indexer"):
        index_source(source_type="docs", url="x", user_id="u1")


def test_index_source_paper_requires_user_id():
    import pytest

    from synsc.services.source_service import index_source

    with pytest.raises(ValueError, match="paper indexing requires"):
        index_source(source_type="paper", url="2301.12345", user_id=None)


# ---------------------------------------------------------------------------
# Service-level: list_sources
# ---------------------------------------------------------------------------


def test_list_sources_filters_by_type(monkeypatch):
    from synsc.services import source_service

    fake_indexer = MagicMock()
    fake_indexer.list_repositories.return_value = {
        "repositories": [
            {
                "repo_id": "r1",
                "owner": "facebook",
                "name": "react",
                "url": "https://github.com/facebook/react",
                "indexed_at": "2026-04-01",
            }
        ]
    }
    monkeypatch.setattr(
        source_service, "_get_indexing_service", lambda user_id: fake_indexer
    )

    out = source_service.list_sources(source_type="repo", user_id="u1")
    assert len(out) == 1
    assert out[0]["source_type"] == "repo"
    assert out[0]["display_name"] == "facebook/react"
    # Paper / dataset branches must not be touched when filtering to repo only.
    assert all(o["source_type"] == "repo" for o in out)


# ---------------------------------------------------------------------------
# HTTP: /v1/search, /v1/sources, GET /v1/sources
# ---------------------------------------------------------------------------


def test_post_v1_search_returns_unified_envelope(client, monkeypatch):
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "unified_retrieve",
        lambda **kwargs: [
            {
                "source_type": "repo",
                "source_id": "r1",
                "chunk_id": "c1",
                "text": "match",
                "score": 0.9,
                "path": "a.py",
                "line_no": 1,
            }
        ],
    )

    r = client.post(
        "/v1/search",
        json={"query": "q", "mode": "precise", "k": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["mode_applied"] == "precise"
    assert body["total"] == 1
    assert body["results"][0]["chunk_id"] == "c1"


def test_post_v1_search_invalid_mode_returns_400(client):
    r = client.post("/v1/search", json={"query": "q", "mode": "zoomzoom"})
    assert r.status_code == 400
    assert "unsupported search mode" in r.json()["detail"]


def test_get_v1_sources_returns_listing(client, monkeypatch):
    from synsc.services import source_service

    fake_indexer = MagicMock()
    fake_indexer.list_repositories.return_value = {
        "repositories": [
            {
                "repo_id": "r1",
                "owner": "facebook",
                "name": "react",
                "url": "https://github.com/facebook/react",
                "indexed_at": "2026-04-01",
            }
        ]
    }
    monkeypatch.setattr(
        source_service, "_get_indexing_service", lambda user_id: fake_indexer
    )

    r = client.get("/v1/sources?type=repo")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["total"] == 1
    assert body["sources"][0]["source_type"] == "repo"


def test_post_v1_sources_dispatches_to_index_source(client, monkeypatch):
    from synsc.services import source_service

    fake_indexer = MagicMock()
    fake_indexer.index_repository.return_value = {
        "repo_id": "r-uuid",
        "status": "pending",
    }
    monkeypatch.setattr(
        source_service, "_get_indexing_service", lambda user_id: fake_indexer
    )

    r = client.post(
        "/v1/sources",
        json={
            "source_type": "repo",
            "url": "https://github.com/owner/repo",
            "options": {"branch": "main"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["source_id"] == "r-uuid"
    assert body["source_type"] == "repo"


def test_post_v1_sources_docs_returns_501(client):
    r = client.post(
        "/v1/sources",
        json={"source_type": "docs", "url": "https://example.com/sitemap.xml"},
    )
    assert r.status_code == 501
    assert "docs indexer" in r.json()["detail"]
