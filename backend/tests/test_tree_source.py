"""Unit tests for AnalysisService.list_directory + GET /v1/sources/{id}/tree
+ the MCP ``tree_source`` tool."""
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


# ---------------------------------------------------------------------------
# HTTP: GET /v1/sources/{id}/tree
# ---------------------------------------------------------------------------


def test_get_tree_source_default_calls_get_directory_structure(client, monkeypatch):
    from synsc.services import analysis_service as as_mod

    fake = MagicMock(
        return_value={"success": True, "repo_id": "r1", "tree": {}, "total_files": 0}
    )
    monkeypatch.setattr(as_mod.AnalysisService, "get_directory_structure", fake)

    r = client.get("/v1/sources/r1/tree?max_depth=2&annotate=false")
    assert r.status_code == 200, r.text
    fake.assert_called_once()
    kwargs = fake.call_args.kwargs
    assert kwargs["repo_id"] == "r1"
    assert kwargs["max_depth"] == 2
    assert kwargs["annotate"] is False


def test_get_tree_source_ls_calls_list_directory(client, monkeypatch):
    from synsc.services import analysis_service as as_mod

    fake = MagicMock(
        return_value={
            "success": True,
            "repo_id": "r1",
            "path": "src",
            "directories": [{"name": "auth", "path": "src/auth"}],
            "files": [{"name": "main.py", "path": "src/main.py"}],
        }
    )
    monkeypatch.setattr(as_mod.AnalysisService, "list_directory", fake)

    r = client.get("/v1/sources/r1/tree?action=ls&path=src")
    assert r.status_code == 200, r.text
    fake.assert_called_once()
    kwargs = fake.call_args.kwargs
    assert kwargs["repo_id"] == "r1"
    assert kwargs["path"] == "src"


def test_get_tree_source_invalid_action_returns_422(client):
    """The Literal['tree','ls'] type makes Pydantic reject other values."""
    r = client.get("/v1/sources/r1/tree?action=zoomzoom")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Service-level: list_directory
# ---------------------------------------------------------------------------


def test_list_directory_returns_subdirs_and_files_at_root(monkeypatch):
    """Without hitting a real DB, exercise the path-segmentation logic by
    monkeypatching the SQLAlchemy session out."""
    from synsc.services.analysis_service import AnalysisService

    svc = AnalysisService(user_id="u1")

    fake_repo = MagicMock()
    fake_repo.owner = "owner"
    fake_repo.name = "repo"
    fake_repo.can_user_access = MagicMock(return_value=True)

    fake_files = [
        MagicMock(file_path="src/auth.py"),
        MagicMock(file_path="src/utils/helpers.py"),
        MagicMock(file_path="README.md"),
        MagicMock(file_path="tests/test_auth.py"),
    ]

    from synsc.database.models import Repository, RepositoryFile

    class FakeSession:
        def query(self, model):
            q = MagicMock()

            def _filter(*args, **kwargs):
                inner = MagicMock()
                if model is Repository:
                    inner.first.return_value = fake_repo
                elif model is RepositoryFile:
                    inner.all.return_value = fake_files
                else:
                    inner.first.return_value = None
                    inner.all.return_value = []
                return inner

            q.filter = _filter
            return q

    class FakeContextManager:
        def __enter__(self):
            return FakeSession()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        "synsc.services.analysis_service.get_session",
        lambda: FakeContextManager(),
    )

    out = svc.list_directory(repo_id="r1", path="/", user_id="u1")
    assert out["success"] is True
    dirs = {d["name"] for d in out["directories"]}
    assert dirs == {"src", "tests"}
    files = {f["name"] for f in out["files"]}
    assert files == {"README.md"}


# ---------------------------------------------------------------------------
# MCP: tree_source
# ---------------------------------------------------------------------------


def test_mcp_tree_source_invalid_action(monkeypatch):
    _isolate_mcp_auth(monkeypatch)
    from synsc.api.mcp_server import create_server

    server = create_server()
    tool = server._tool_manager._tools["tree_source"]
    out = tool.fn(source_id="r1", action="zoomzoom")
    assert out["success"] is False
    assert out["error_code"] == "invalid_input"


def test_mcp_tree_source_ls_dispatches_to_list_directory(monkeypatch):
    _isolate_mcp_auth(monkeypatch)
    from synsc.api.mcp_server import create_server
    from synsc.services import analysis_service as as_mod

    fake = MagicMock(return_value={"success": True, "repo_id": "r1"})
    monkeypatch.setattr(as_mod.AnalysisService, "list_directory", fake)

    server = create_server()
    tool = server._tool_manager._tools["tree_source"]
    out = tool.fn(source_id="r1", action="ls", path="src")
    assert out["success"] is True
    fake.assert_called_once()
    assert fake.call_args.kwargs["path"] == "src"
