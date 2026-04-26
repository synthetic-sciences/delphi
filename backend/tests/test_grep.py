"""Unit tests for GrepService."""
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_grep_service_matches_pattern_in_reconstructed_file():
    from synsc.services.grep_service import GrepService

    svc = GrepService()

    fake_files = {
        "src/auth.py": (
            "def login(user):\n"
            "    # TODO: handle MFA\n"
            "    if user.is_active:\n"
            "        return True\n"
            "    return False\n"
        ),
        "src/utils.py": "def noop():\n    pass\n",
    }

    with patch.object(svc, "_iter_source_files", return_value=list(fake_files.items())):
        matches = svc.grep_source(
            source_id="r1",
            source_type="repo",
            pattern=r"TODO.*MFA",
            path_prefix=None,
            max_matches=10,
            context_lines=1,
            user_id="u1",
        )

    assert len(matches) == 1
    m = matches[0]
    assert m["path"] == "src/auth.py"
    assert m["line_no"] == 2
    assert "MFA" in m["line"]
    assert m["context_before"] == ["def login(user):"]
    assert m["context_after"] == ["    if user.is_active:"]


def test_grep_service_respects_path_prefix():
    from synsc.services.grep_service import GrepService

    svc = GrepService()
    fake_files = {
        "src/a.py": "match_here\n",
        "tests/a.py": "match_here\n",
    }
    with patch.object(svc, "_iter_source_files", return_value=list(fake_files.items())):
        matches = svc.grep_source(
            source_id="r1",
            source_type="repo",
            pattern="match_here",
            path_prefix="src/",
            max_matches=10,
            context_lines=0,
            user_id="u1",
        )
    assert len(matches) == 1
    assert matches[0]["path"] == "src/a.py"


def test_grep_service_caps_at_max_matches():
    from synsc.services.grep_service import GrepService

    svc = GrepService()
    fake_files = {"a.py": "\n".join(["x"] * 500)}
    with patch.object(svc, "_iter_source_files", return_value=list(fake_files.items())):
        matches = svc.grep_source(
            source_id="r1",
            source_type="repo",
            pattern="x",
            path_prefix=None,
            max_matches=50,
            context_lines=0,
            user_id="u1",
        )
    assert len(matches) == 50


def test_grep_service_rejects_invalid_regex():
    from synsc.services.grep_service import GrepService

    svc = GrepService()
    with pytest.raises(ValueError, match="invalid regex"):
        svc.grep_source(
            source_id="r1",
            source_type="repo",
            pattern="(unclosed",
            path_prefix=None,
            max_matches=10,
            context_lines=0,
            user_id="u1",
        )


def test_post_grep_endpoint_returns_matches(client, monkeypatch):
    """POST /v1/sources/{id}/grep dispatches to GrepService and returns
    matches under the standard envelope."""
    from synsc.services import grep_service as gs_mod

    fake_matches = [
        {
            "path": "src/a.py",
            "line_no": 3,
            "line": "TODO: refactor",
            "context_before": [],
            "context_after": [],
        }
    ]

    def fake_grep(self, **kwargs):
        return fake_matches

    monkeypatch.setattr(gs_mod.GrepService, "grep_source", fake_grep)

    r = client.post(
        "/v1/sources/repo-uuid/grep",
        json={"pattern": "TODO", "source_type": "repo", "max_matches": 10},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["source_id"] == "repo-uuid"
    assert body["matches"] == fake_matches


def test_post_grep_endpoint_invalid_regex_returns_400(client, monkeypatch):
    """A regex compile error must surface as a 400, not propagate as a 500."""
    from synsc.services import grep_service as gs_mod

    def raise_value(self, **kwargs):
        raise ValueError("invalid regex: unbalanced parenthesis")

    monkeypatch.setattr(gs_mod.GrepService, "grep_source", raise_value)

    r = client.post(
        "/v1/sources/repo-uuid/grep",
        json={"pattern": "(unclosed", "source_type": "repo"},
    )
    assert r.status_code == 400
    assert "invalid regex" in r.json()["detail"]


def test_mcp_grep_source_tool_is_registered():
    from synsc.api.mcp_server import create_server

    server = create_server()
    tool = server._tool_manager._tools.get("grep_source")
    assert tool is not None

    import inspect

    params = inspect.signature(tool.fn).parameters
    assert list(params) == [
        "source_id",
        "pattern",
        "source_type",
        "path_prefix",
        "max_matches",
        "context_lines",
    ]


def test_mcp_grep_source_invalid_regex_returns_structured_error(monkeypatch):
    """A bad regex returns the same structured envelope as the research tool
    so agents can pattern-match on error_code."""
    import synsc.api.mcp_server as mcp_mod
    from synsc.services import grep_service as gs_mod

    def raise_value(self, **kwargs):
        raise ValueError("invalid regex: unbalanced")

    monkeypatch.setattr(gs_mod.GrepService, "grep_source", raise_value)
    # Ensure SYNSC_API_KEY isn't picked up from a prior test's environment
    # leak — get_authenticated_user_id would otherwise hit the DB validation
    # path and clobber the test with a logger-config side effect.
    monkeypatch.delenv("SYNSC_API_KEY", raising=False)
    monkeypatch.setattr(mcp_mod, "_current_api_key", mcp_mod.contextvars.ContextVar("test_key", default=None))
    monkeypatch.setattr(mcp_mod, "_current_user_id", mcp_mod.contextvars.ContextVar("test_uid", default=None))

    server = mcp_mod.create_server()
    tool = server._tool_manager._tools["grep_source"]
    result = tool.fn(source_id="r1", pattern="(x", source_type="repo")
    assert result["success"] is False
    assert result["error_code"] == "invalid_input"
    assert "invalid regex" in result["message"]


def test_grep_service_unsupported_source_type():
    """source_type outside {'repo', 'paper'} must raise ValueError."""
    from synsc.services.grep_service import GrepService

    svc = GrepService()
    with pytest.raises(ValueError, match="unsupported source_type"):
        svc.grep_source(
            source_id="x",
            source_type="dataset",
            pattern=".",
            user_id="u1",
        )
