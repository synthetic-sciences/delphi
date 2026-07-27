"""HTTP and MCP contracts for durable asynchronous research."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock


def _public_session(status: str = "pending"):
    payload = {
        "session_id": "job-1",
        "query": "q",
        "mode": "quick",
        "status": status,
        "answer_markdown": "",
        "citations": [],
        "usage": {},
        "error": None,
        "auto_indexed": [],
        "created_at": 1.0,
        "completed_at": None,
    }
    return SimpleNamespace(
        session_id="job-1",
        status=status,
        to_public=lambda: payload,
    )


def test_http_start_returns_durable_pending_session(client, monkeypatch) -> None:
    from synsc.services import research_sessions

    start = MagicMock()

    async def fake_start(**kwargs):
        start(**kwargs)
        return _public_session()

    monkeypatch.setattr(research_sessions, "start_session", fake_start)

    response = client.post(
        "/v2/research",
        json={"query": "q", "mode": "quick", "auto_index": False},
    )

    assert response.status_code == 202
    assert response.json() == {
        "success": True,
        "session_id": "job-1",
        "status": "pending",
    }
    assert start.call_args.kwargs["user_id"] == (
        "00000000-0000-0000-0000-000000000000"
    )


def test_http_start_rejects_invalid_mode_before_enqueue(client) -> None:
    response = client.post(
        "/v2/research",
        json={"query": "q", "mode": "slow"},
    )

    assert response.status_code == 422


def test_http_list_is_owner_scoped(client, monkeypatch) -> None:
    from synsc.services import research_sessions

    listed = MagicMock(return_value=[_public_session().to_public()])
    monkeypatch.setattr(research_sessions, "list_sessions", listed)

    response = client.get("/v2/research?limit=12&status=pending")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    listed.assert_called_once_with(
        user_id="00000000-0000-0000-0000-000000000000",
        limit=12,
        status="pending",
    )


def test_http_status_passes_authenticated_owner(client, monkeypatch) -> None:
    from synsc.services import research_sessions

    getter = MagicMock(return_value=_public_session(status="completed"))
    monkeypatch.setattr(research_sessions, "get_session", getter)

    response = client.get("/v2/research/job-1")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    getter.assert_called_once_with(
        "job-1",
        user_id="00000000-0000-0000-0000-000000000000",
    )


def test_http_followup_is_accepted_for_background_execution(
    client,
    monkeypatch,
) -> None:
    from synsc.services import research_sessions

    async def fake_followup(**kwargs):
        return {
            "session_id": kwargs["session_id"],
            "status": "pending",
            "accepted": True,
        }

    monkeypatch.setattr(research_sessions, "post_followup", fake_followup)

    response = client.post(
        "/v2/research/job-1/messages",
        json={"message": "What about Linux?"},
    )

    assert response.status_code == 202
    assert response.json()["accepted"] is True
    assert response.json()["status"] == "pending"


def test_http_cancel_returns_persisted_state(client, monkeypatch) -> None:
    from synsc.services import research_sessions

    cancel = MagicMock(return_value=_public_session(status="cancelling"))
    monkeypatch.setattr(research_sessions, "cancel_session", cancel)

    response = client.delete("/v2/research/job-1")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelling"
    cancel.assert_called_once_with(
        "job-1",
        user_id="00000000-0000-0000-0000-000000000000",
    )


def test_mcp_durable_research_tools_are_registered(monkeypatch) -> None:
    monkeypatch.setenv("SYNSC_MCP_PROFILE", "all")
    from synsc.api.mcp_server import create_server

    names = set(create_server()._tool_manager._tools)

    assert {
        "research_start",
        "research_list",
        "research_status",
        "research_events",
        "research_followup",
        "research_cancel",
    }.issubset(names)


def test_mcp_research_events_replays_initial_event_by_default(monkeypatch) -> None:
    monkeypatch.setenv("SYNSC_MCP_PROFILE", "all")
    from synsc.api.mcp_server import create_server

    tool = create_server()._tool_manager._tools["research_events"]
    params = inspect.signature(tool.fn).parameters

    assert params["since_seq"].default == -1
