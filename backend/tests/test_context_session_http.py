"""Typed HTTP contracts for context sessions, revisions, and handoffs."""

from __future__ import annotations

from unittest.mock import MagicMock


def _bundle(session_id: str = "session-1") -> dict[str, object]:
    return {
        "session": {
            "session_id": session_id,
            "name": "Work",
            "objective": "Ship the work",
            "status": "active",
            "sharing_policy": "private",
            "expires_at": None,
            "parent_session_id": None,
            "parent_revision_id": None,
            "handoff_note": None,
            "current_revision_id": "revision-1",
            "current_revision": 1,
            "write_version": 1,
        },
        "revision": {
            "revision_id": "revision-1",
            "session_id": session_id,
            "revision_number": 1,
            "token_budget": 100,
            "tokens_used": 0,
            "state": {},
            "pinned_snapshots": [],
            "context_manifest": {"items": [], "tokens_used": 0},
            "content_hash": "a" * 64,
        },
        "context_items": [],
        "unavailable_items": [],
    }


def _fake_service(monkeypatch):
    from synsc.contexts import service as context_service

    fake = MagicMock()
    monkeypatch.setattr(
        context_service,
        "get_context_session_service",
        lambda: fake,
    )
    return fake


def test_context_routes_require_auth_when_enabled(auth_client) -> None:
    response = auth_client.get("/v2/context-sessions")
    assert response.status_code == 401


def test_create_context_session_is_typed_and_owner_scoped(
    client,
    monkeypatch,
) -> None:
    fake = _fake_service(monkeypatch)
    fake.create_session.return_value = _bundle()

    response = client.post(
        "/v2/context-sessions",
        json={
            "name": "Work",
            "objective": "Ship the work",
            "snapshot_ids": ["snapshot-1"],
            "token_budget": 4000,
            "task_state": {"status": "active"},
            "sharing_policy": "private",
        },
    )

    assert response.status_code == 201
    assert response.json()["session"]["session_id"] == "session-1"
    assert fake.create_session.call_args.kwargs["user_id"] == (
        "00000000-0000-0000-0000-000000000000"
    )
    assert fake.create_session.call_args.kwargs["snapshot_ids"] == [
        "snapshot-1"
    ]


def test_list_get_revise_policy_handoff_and_export(
    client,
    monkeypatch,
) -> None:
    fake = _fake_service(monkeypatch)
    fake.list_sessions.return_value = [_bundle()["session"]]
    fake.get_session.return_value = _bundle()
    fake.revise_session.return_value = _bundle()
    fake.update_policy.return_value = {
        **_bundle()["session"],
        "sharing_policy": "shared",
    }
    fake.handoff.return_value = _bundle("session-child")
    fake.export_session.return_value = {
        "schema_version": 1,
        "selected_content": [],
        "export_hash": "b" * 64,
    }

    listed = client.get("/v2/context-sessions?limit=20")
    loaded = client.get("/v2/context-sessions/session-1?revision=1")
    revised = client.post(
        "/v2/context-sessions/session-1/revisions",
        json={
            "expected_version": 1,
            "task_state": {"status": "done"},
        },
    )
    policy = client.patch(
        "/v2/context-sessions/session-1",
        json={
            "expected_version": 1,
            "sharing_policy": "shared",
            "status": "completed",
        },
    )
    handoff = client.post(
        "/v2/context-sessions/session-1/handoffs",
        json={
            "name": "Child",
            "objective": "Continue",
            "handoff_note": "Verify it",
        },
    )
    exported = client.get("/v2/context-sessions/session-1/export")

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert loaded.status_code == 200
    assert revised.status_code == 201
    assert policy.status_code == 200
    assert "expires_at" not in fake.update_policy.call_args.kwargs
    assert handoff.status_code == 201
    assert handoff.json()["session"]["session_id"] == "session-child"
    assert exported.status_code == 200
    assert exported.json()["export_hash"] == "b" * 64
    assert fake.get_session.call_args.kwargs["revision_number"] == 1


def test_context_conflict_expiry_and_not_found_have_stable_statuses(
    client,
    monkeypatch,
) -> None:
    from synsc.contexts.service import (
        ContextRevisionConflictError,
        ContextSessionExpiredError,
        ContextSessionNotFoundError,
    )

    fake = _fake_service(monkeypatch)
    fake.get_session.side_effect = ContextSessionNotFoundError()
    not_found = client.get("/v2/context-sessions/missing")

    fake.revise_session.side_effect = ContextRevisionConflictError()
    conflict = client.post(
        "/v2/context-sessions/session-1/revisions",
        json={"expected_version": 1},
    )

    fake.export_session.side_effect = ContextSessionExpiredError()
    expired = client.get("/v2/context-sessions/session-1/export")

    assert not_found.status_code == 404
    assert not_found.json() == {"detail": "Context session not found."}
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "Context session changed."}
    assert expired.status_code == 410
    assert expired.json() == {"detail": "Context session has expired."}


def test_context_routes_are_in_openapi(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/v2/context-sessions"]["post"]
    assert paths["/v2/context-sessions/{session_id}"]["get"]
    assert paths["/v2/context-sessions/{session_id}"]["patch"]
    assert paths["/v2/context-sessions/{session_id}/revisions"]["post"]
    assert paths["/v2/context-sessions/{session_id}/handoffs"]["post"]
    assert paths["/v2/context-sessions/{session_id}/export"]["get"]
