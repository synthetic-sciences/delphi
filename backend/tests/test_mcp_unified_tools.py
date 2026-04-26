"""Hermetic tests for the unified MCP tool surface (search, index_source,
list_sources, read_source). Each test isolates the auth contextvar to keep
the DB-validation path from firing in environments without Postgres."""
from __future__ import annotations

from unittest.mock import MagicMock


def _isolate_mcp_auth(monkeypatch):
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


def test_unified_mcp_tools_are_registered(monkeypatch):
    _isolate_mcp_auth(monkeypatch)
    from synsc.api.mcp_server import create_server

    server = create_server()
    names = set(server._tool_manager._tools.keys())
    assert {"search", "index_source", "list_sources", "read_source"}.issubset(names)


def test_mcp_search_dispatches_to_unified_search(monkeypatch):
    _isolate_mcp_auth(monkeypatch)
    from synsc.api.mcp_server import create_server
    from synsc.services import source_service

    captured: dict = {}

    def fake_unified_search(**kwargs):
        captured.update(kwargs)
        return {"results": [], "total": 0, "mode_applied": "precise"}

    monkeypatch.setattr(source_service, "unified_search", fake_unified_search)

    server = create_server()
    tool = server._tool_manager._tools["search"]
    out = tool.fn(query="q", k=5, mode="thorough")
    assert out["success"] is True
    assert captured["query"] == "q"
    assert captured["mode"] == "thorough"


def test_mcp_search_invalid_mode_returns_structured_error(monkeypatch):
    _isolate_mcp_auth(monkeypatch)
    from synsc.api.mcp_server import create_server

    server = create_server()
    tool = server._tool_manager._tools["search"]
    out = tool.fn(query="q", mode="zoomzoom")
    assert out["success"] is False
    assert out["error_code"] == "invalid_input"
    assert "unsupported search mode" in out["message"]


def test_mcp_index_source_repo_dispatches(monkeypatch):
    _isolate_mcp_auth(monkeypatch)
    from synsc.api.mcp_server import create_server
    from synsc.services import source_service

    fake_indexer = MagicMock()
    fake_indexer.index_repository.return_value = {
        "success": True,
        "repo_id": "r-uuid",
        "status": "indexed",
    }
    monkeypatch.setattr(
        source_service, "_get_indexing_service", lambda user_id: fake_indexer
    )

    server = create_server()
    tool = server._tool_manager._tools["index_source"]
    out = tool.fn(source_type="repo", url="https://github.com/owner/repo")
    assert out["success"] is True
    assert out["source_id"] == "r-uuid"


def test_mcp_index_source_failure_returns_structured_error(monkeypatch):
    """Per-type service failure must surface as the structured error envelope
    on the MCP side too, mirroring the HTTP 502."""
    _isolate_mcp_auth(monkeypatch)
    from synsc.api.mcp_server import create_server
    from synsc.services import source_service

    fake_indexer = MagicMock()
    fake_indexer.index_repository.return_value = {
        "success": False,
        "error": "clone failed: dead repo",
    }
    monkeypatch.setattr(
        source_service, "_get_indexing_service", lambda user_id: fake_indexer
    )

    server = create_server()
    tool = server._tool_manager._tools["index_source"]
    out = tool.fn(source_type="repo", url="https://github.com/dead/dead")
    assert out["success"] is False
    assert out["error_code"] == "indexing_failed"
    assert "clone failed" in out["message"]


def test_mcp_index_source_docs_dispatches(monkeypatch):
    """Docs landed — MCP tool returns the canonical success envelope."""
    _isolate_mcp_auth(monkeypatch)
    import synsc.api.mcp_server as mcp_mod
    from synsc.api.mcp_server import create_server
    from synsc.services import docs_service as ds_mod

    # Docs branch requires user_id; pre-seed the per-test contextvar.
    mcp_mod._current_user_id.set("u1")

    fake = MagicMock()
    fake.index_docs.return_value = {
        "success": True,
        "status": "indexed",
        "docs_id": "d-uuid",
    }
    monkeypatch.setattr(ds_mod, "get_docs_service", lambda user_id=None: fake)

    server = create_server()
    tool = server._tool_manager._tools["index_source"]
    out = tool.fn(source_type="docs", url="https://example.com")
    assert out["success"] is True
    assert out["source_id"] == "d-uuid"


def test_mcp_list_sources_returns_envelope(monkeypatch):
    _isolate_mcp_auth(monkeypatch)
    from synsc.api.mcp_server import create_server
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service, "list_sources", lambda **kw: [{"source_type": "repo"}]
    )

    server = create_server()
    tool = server._tool_manager._tools["list_sources"]
    out = tool.fn(source_type="repo")
    assert out["success"] is True
    assert out["total"] == 1
    assert out["sources"][0]["source_type"] == "repo"


def test_mcp_read_source_repo_requires_path(monkeypatch):
    _isolate_mcp_auth(monkeypatch)
    from synsc.api.mcp_server import create_server

    server = create_server()
    tool = server._tool_manager._tools["read_source"]
    out = tool.fn(source_id="r1", source_type="repo")
    assert out["success"] is False
    assert out["error_code"] == "invalid_input"
    assert "path" in out["message"]


def test_mcp_read_source_unsupported_type(monkeypatch):
    _isolate_mcp_auth(monkeypatch)
    from synsc.api.mcp_server import create_server

    server = create_server()
    tool = server._tool_manager._tools["read_source"]
    out = tool.fn(source_id="x", source_type="movie")
    assert out["success"] is False
    assert out["error_code"] == "invalid_input"
    assert "unsupported source_type" in out["message"]
