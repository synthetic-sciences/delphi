"""Unit tests for section-aware get_paper + GET /v1/sources/{id}/read."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _disable_slowapi():
    from synsc.api.rate_limit import limiter

    was = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = was


# ---------------------------------------------------------------------------
# _compile_section_matcher
# ---------------------------------------------------------------------------


def test_canonical_section_synonym_resolves_to_anchored_pattern():
    from synsc.services.paper_service import _compile_section_matcher

    m = _compile_section_matcher("methods")
    # Anchored to start of section title.
    assert m.search("Methods")
    assert m.search("3.2. Methodology")
    assert not m.search("This work uses methods from prior literature.")


def test_arbitrary_regex_falls_through_unchanged():
    from synsc.services.paper_service import _compile_section_matcher

    m = _compile_section_matcher(r"Section\s+\d+")
    assert m.search("Section 4")
    assert not m.search("Discussion")


def test_invalid_regex_raises_value_error():
    from synsc.services.paper_service import _compile_section_matcher

    with pytest.raises(ValueError, match="invalid section regex"):
        _compile_section_matcher("(unclosed")


# ---------------------------------------------------------------------------
# HTTP: GET /v1/sources/{id}/read
# ---------------------------------------------------------------------------


def test_read_source_paper_filters_by_section(client, monkeypatch):
    from synsc.services import paper_service as ps_mod

    fake_paper = {
        "paper_id": "p1",
        "title": "X",
        "authors": ["A"],
        "abstract": "abstract text",
        "arxiv_id": "2301.0001",
        "pdf_hash": None,
        "page_count": 10,
        "indexed_at": None,
    }

    def fake_get_paper(self, paper_id, section=None):
        if section == "results":
            return {
                **fake_paper,
                "section_title": "Results",
                "content": "Results bit.",
                "chunks": [
                    {
                        "chunk_id": "c2",
                        "chunk_index": 1,
                        "content": "Results bit.",
                        "section_title": "Results",
                    }
                ],
                "section_query": "results",
            }
        return {**fake_paper, "chunks": []}

    monkeypatch.setattr(ps_mod.PaperService, "get_paper", fake_get_paper)

    r = client.get("/v1/sources/p1/read?source_type=paper&section=results")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["source_type"] == "paper"
    assert body["section_title"] == "Results"
    assert body["content"] == "Results bit."
    assert body["section_query"] == "results"


def test_read_source_paper_invalid_regex_returns_400(client, monkeypatch):
    from synsc.services import paper_service as ps_mod

    def raise_value(self, paper_id, section=None):
        raise ValueError("invalid section regex: unbalanced")

    monkeypatch.setattr(ps_mod.PaperService, "get_paper", raise_value)

    r = client.get("/v1/sources/p1/read?source_type=paper&section=(unclosed")
    assert r.status_code == 400
    assert "invalid section regex" in r.json()["detail"]


def test_read_source_paper_404_when_missing(client, monkeypatch):
    from synsc.services import paper_service as ps_mod

    monkeypatch.setattr(ps_mod.PaperService, "get_paper", lambda *a, **k: None)

    r = client.get("/v1/sources/missing/read?source_type=paper")
    assert r.status_code == 404


def test_read_source_repo_requires_path(client):
    r = client.get("/v1/sources/r1/read?source_type=repo")
    assert r.status_code == 400
    assert "path" in r.json()["detail"]


def test_read_source_repo_returns_file_content(client, monkeypatch):
    from synsc.services import search_service as ss_mod

    fake_get_file = MagicMock(return_value={"success": True, "content": "x = 1\n"})
    monkeypatch.setattr(ss_mod.SearchService, "get_file", fake_get_file)

    r = client.get("/v1/sources/r1/read?source_type=repo&path=src/a.py")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["source_type"] == "repo"
    assert body["content"] == "x = 1\n"


def test_read_source_unsupported_type_returns_400(client):
    r = client.get("/v1/sources/x/read?source_type=movie")
    assert r.status_code == 400
    assert "unsupported source_type" in r.json()["detail"]


# ---------------------------------------------------------------------------
# MCP get_paper section filter
# ---------------------------------------------------------------------------


def _isolate_mcp_auth(monkeypatch):
    """Stop the MCP tool from hitting the DB-validation auth path, which
    crashes test ordering when an earlier test reconfigured Python logging."""
    import synsc.api.mcp_server as mcp_mod

    monkeypatch.delenv("SYNSC_API_KEY", raising=False)
    monkeypatch.setattr(
        mcp_mod,
        "_current_api_key",
        mcp_mod.contextvars.ContextVar("test_key", default=None),
    )
    monkeypatch.setattr(
        mcp_mod,
        "_current_user_id",
        mcp_mod.contextvars.ContextVar("test_uid", default=None),
    )


def test_mcp_get_paper_passes_section_to_service(monkeypatch):
    _isolate_mcp_auth(monkeypatch)
    from synsc.api.mcp_server import create_server
    from synsc.services import paper_service as ps_mod

    captured: dict = {}

    def fake_get_paper(self, paper_id, section=None):
        captured["paper_id"] = paper_id
        captured["section"] = section
        return {"paper_id": paper_id, "title": "X"}

    monkeypatch.setattr(ps_mod.PaperService, "get_paper", fake_get_paper)

    server = create_server()
    tool = server._tool_manager._tools["get_paper"]
    result = tool.fn(paper_id="p1", section="methods")

    assert result["success"] is True
    assert captured["section"] == "methods"


def test_mcp_get_paper_invalid_regex_returns_structured_error(monkeypatch):
    _isolate_mcp_auth(monkeypatch)
    from synsc.api.mcp_server import create_server
    from synsc.services import paper_service as ps_mod

    def raise_value(self, paper_id, section=None):
        raise ValueError("invalid section regex: unbalanced")

    monkeypatch.setattr(ps_mod.PaperService, "get_paper", raise_value)

    server = create_server()
    tool = server._tool_manager._tools["get_paper"]
    result = tool.fn(paper_id="p1", section="(unclosed")
    assert result["success"] is False
    assert result["error_code"] == "invalid_input"
    assert "invalid section regex" in result["message"]
