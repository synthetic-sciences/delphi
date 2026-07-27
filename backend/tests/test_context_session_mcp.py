"""Compact MCP contracts for reproducible context sessions."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock


def _server(monkeypatch, profile: str = "all"):
    import synsc.api.mcp_server as mcp_module

    monkeypatch.setenv("SYNSC_MCP_PROFILE", profile)
    monkeypatch.delenv("SYNSC_API_KEY", raising=False)
    monkeypatch.setattr(
        mcp_module,
        "_current_user_id",
        mcp_module.contextvars.ContextVar("context_uid", default="user-1"),
    )
    return mcp_module.create_server()


def test_context_session_tools_are_registered_and_not_in_minimal(
    monkeypatch,
) -> None:
    server = _server(monkeypatch)
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert {
        "context_session_create",
        "context_session_list",
        "context_session_get",
        "context_session_revise",
        "context_session_handoff",
    }.issubset(names)

    minimal = _server(monkeypatch, "minimal")
    minimal_names = {tool.name for tool in asyncio.run(minimal.list_tools())}
    assert not any(name.startswith("context_session_") for name in minimal_names)


def test_context_session_create_and_revise_are_owner_scoped(
    monkeypatch,
) -> None:
    from synsc.contexts import service as context_service

    fake = MagicMock()
    fake.create_session.return_value = {"session": {"session_id": "session-1"}}
    fake.revise_session.return_value = {
        "session": {"session_id": "session-1"},
        "revision": {"revision_number": 2},
    }
    monkeypatch.setattr(
        context_service,
        "get_context_session_service",
        lambda: fake,
    )
    server = _server(monkeypatch)

    created = server._tool_manager._tools["context_session_create"].fn(
        name="release",
        objective="Verify release evidence",
        snapshot_ids=["snapshot-1"],
        token_budget=4000,
        task_state={"status": "active"},
    )
    revised = server._tool_manager._tools["context_session_revise"].fn(
        session_id="session-1",
        expected_version=1,
        task_state={"status": "done"},
    )

    assert created["success"] is True
    assert revised["success"] is True
    assert fake.create_session.call_args.kwargs["user_id"] == "user-1"
    assert fake.revise_session.call_args.kwargs["user_id"] == "user-1"
    assert fake.revise_session.call_args.kwargs["expected_version"] == 1


def test_context_session_mcp_returns_stable_conflict(
    monkeypatch,
) -> None:
    from synsc.contexts import service as context_service
    from synsc.contexts.service import ContextRevisionConflictError

    fake = MagicMock()
    fake.revise_session.side_effect = ContextRevisionConflictError()
    monkeypatch.setattr(
        context_service,
        "get_context_session_service",
        lambda: fake,
    )
    server = _server(monkeypatch)

    result = server._tool_manager._tools["context_session_revise"].fn(
        session_id="session-1",
        expected_version=1,
    )

    assert result == {
        "success": False,
        "error_code": "conflict",
        "message": "Context session changed.",
    }


def test_context_session_read_and_handoff_tools_are_owner_scoped(
    monkeypatch,
) -> None:
    from synsc.contexts import service as context_service

    fake = MagicMock()
    fake.list_sessions.return_value = [{"session_id": "session-1"}]
    fake.get_session.return_value = {"session": {"session_id": "session-1"}}
    fake.export_session.return_value = {
        "session": {"session_id": "session-1"},
        "selected_items": [],
    }
    fake.handoff.return_value = {"session": {"session_id": "session-2"}}
    monkeypatch.setattr(
        context_service,
        "get_context_session_service",
        lambda: fake,
    )
    server = _server(monkeypatch)
    tools = server._tool_manager._tools

    tools["context_session_list"].fn(limit=20)
    tools["context_session_get"].fn(session_id="session-1")
    tools["context_session_get"].fn(session_id="session-1", export=True)
    tools["context_session_handoff"].fn(
        session_id="session-1",
        name="follow-up",
        objective="Continue verification",
        handoff_note="Use approved evidence",
    )

    assert fake.list_sessions.call_args.kwargs["user_id"] == "user-1"
    assert fake.get_session.call_args.kwargs["user_id"] == "user-1"
    assert fake.export_session.call_args.kwargs["user_id"] == "user-1"
    assert fake.handoff.call_args.kwargs["user_id"] == "user-1"


def test_context_session_mcp_sanitizes_unknown_service_failures(
    monkeypatch,
) -> None:
    import synsc.api.mcp_server as mcp_module
    from synsc.contexts import service as context_service

    fake = MagicMock()
    fake.list_sessions.side_effect = RuntimeError(
        "db at private-host password=must-not-leak"
    )
    log = MagicMock()
    monkeypatch.setattr(
        context_service,
        "get_context_session_service",
        lambda: fake,
    )
    monkeypatch.setattr(mcp_module, "logger", log)
    server = _server(monkeypatch)

    result = server._tool_manager._tools["context_session_list"].fn()

    assert result == {
        "success": False,
        "error_code": "internal_error",
        "message": "Context session operation failed.",
    }
    assert "must-not-leak" not in repr(result)
    log.error.assert_called_once_with(
        "Context session operation failed",
        error_type="RuntimeError",
    )


def test_all_context_session_mcp_tools_require_authenticated_owner(
    monkeypatch,
) -> None:
    import synsc.api.mcp_server as mcp_module

    server = _server(monkeypatch)
    mcp_module._current_user_id.set(None)
    tools = server._tool_manager._tools

    results = [
        tools["context_session_create"].fn(name="release", objective="verify"),
        tools["context_session_list"].fn(),
        tools["context_session_get"].fn(session_id="session-1"),
        tools["context_session_revise"].fn(
            session_id="session-1",
            expected_version=1,
        ),
        tools["context_session_handoff"].fn(
            session_id="session-1",
            name="follow-up",
            objective="continue",
            handoff_note="approved evidence",
        ),
    ]

    assert results == [
        {"success": False, "error_code": "auth_required"}
        for _ in range(len(results))
    ]
