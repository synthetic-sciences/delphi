"""Public HTTP client contracts for local and hosted deployments."""

from __future__ import annotations

import json

import httpx
import pytest

from synsc.client import SynscAPIError, SynscClient


def test_client_sends_auth_and_context_payloads() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            201,
            json={"session": {"session_id": "session-1"}},
        )

    with SynscClient(
        base_url="https://context.example.test/",
        api_key="secret-key",
        transport=httpx.MockTransport(handler),
    ) as client:
        result = client.create_context_session(
            name="release",
            objective="Verify release evidence",
            snapshot_ids=["snapshot-1"],
            token_budget=4000,
        )

    assert result["session"]["session_id"] == "session-1"
    assert requests[0].url == (
        "https://context.example.test/v2/context-sessions"
    )
    assert requests[0].headers["authorization"] == "Bearer secret-key"
    assert json.loads(requests[0].content) == {
        "name": "release",
        "objective": "Verify release evidence",
        "snapshot_ids": ["snapshot-1"],
        "token_budget": 4000,
    }


def test_client_exposes_workspace_resources() -> None:
    routes = {
        "/v2/providers": {"providers": [{"name": "local-index"}]},
        "/v2/connectors/providers": {"providers": [{"name": "local-folder"}]},
        "/v2/connectors": {"sources": [{"source_id": "source-1"}]},
        "/v2/research": {"sessions": [{"session_id": "research-1"}]},
        "/v2/context-sessions": {"sessions": [{"session_id": "context-1"}]},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=routes[request.url.path])

    with SynscClient(
        transport=httpx.MockTransport(handler),
    ) as client:
        workspace = client.workspace()

    assert workspace["providers"][0]["name"] == "local-index"
    assert workspace["connector_providers"][0]["name"] == "local-folder"
    assert workspace["connectors"][0]["source_id"] == "source-1"
    assert workspace["research_sessions"][0]["session_id"] == "research-1"
    assert workspace["context_sessions"][0]["session_id"] == "context-1"


def test_client_raises_safe_structured_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"detail": "Context session changed."},
        )

    with SynscClient(
        api_key="must-not-leak",
        transport=httpx.MockTransport(handler),
    ) as client, pytest.raises(SynscAPIError) as captured:
        client.revise_context_session(
            "session-1",
            expected_version=1,
            task_state={"status": "done"},
        )

    assert captured.value.status_code == 409
    assert str(captured.value) == "Context session changed."
    assert "must-not-leak" not in repr(captured.value)


def test_client_transport_error_detaches_secret_bearing_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network unavailable", request=request)

    with SynscClient(
        api_key="must-not-leak",
        transport=httpx.MockTransport(handler),
    ) as client, pytest.raises(SynscAPIError) as captured:
        client.list_providers()

    assert str(captured.value) == "Unable to reach the context service."
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert "must-not-leak" not in repr(captured.value)


def test_client_rejects_plaintext_remote_api_with_bearer_key() -> None:
    with pytest.raises(
        ValueError,
        match="HTTPS is required for non-loopback context service URLs",
    ):
        SynscClient(
            base_url="http://context.example.test",
            api_key="must-not-leak",
        )
