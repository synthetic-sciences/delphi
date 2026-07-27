"""Authenticated HTTP contracts for connector lifecycle and sync jobs."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock


def _source() -> dict[str, object]:
    return {
        "source_id": "source-1",
        "source_type": "connector",
        "provider": "local-folder",
        "display_name": "Notes",
        "external_ref": "file:///notes",
        "classification": "local_sensitive",
        "enabled": True,
        "schedule_seconds": 300,
        "last_snapshot_id": None,
    }


def _fake_service(monkeypatch):
    from synsc.connectors import service as connector_service

    fake = MagicMock()
    monkeypatch.setattr(
        connector_service,
        "get_connector_sync_service",
        lambda: fake,
    )
    return fake


def test_connector_routes_require_auth_when_enabled(auth_client) -> None:
    response = auth_client.get("/v2/connectors")
    assert response.status_code == 401


def test_create_connector_is_owner_scoped_and_secret_safe(
    client,
    monkeypatch,
) -> None:
    fake = _fake_service(monkeypatch)
    fake.create_source.return_value = _source()

    response = client.post(
        "/v2/connectors",
        json={
            "provider": "local-folder",
            "display_name": "Notes",
            "external_ref": "file:///notes",
            "classification": "local_sensitive",
            "configuration": {
                "path": "/notes",
                "api_token": "must-not-return",
            },
            "schedule_seconds": 300,
        },
    )

    assert response.status_code == 201
    assert response.json() == {"source": _source()}
    assert "must-not-return" not in response.text
    assert fake.create_source.call_args.kwargs["user_id"] == (
        "00000000-0000-0000-0000-000000000000"
    )


def test_list_get_and_delete_connector(client, monkeypatch) -> None:
    fake = _fake_service(monkeypatch)
    fake.list_sources.return_value = [_source()]
    fake.get_source.return_value = _source()
    fake.delete_source.return_value = True

    listed = client.get("/v2/connectors?provider=local-folder&limit=20")
    loaded = client.get("/v2/connectors/source-1")
    deleted = client.delete("/v2/connectors/source-1")

    assert listed.status_code == 200
    assert listed.json() == {"sources": [_source()], "total": 1}
    assert loaded.status_code == 200
    assert loaded.json() == {"source": _source()}
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "source_id": "source-1"}


def test_enqueue_and_get_connector_sync_job(client, monkeypatch) -> None:
    fake = _fake_service(monkeypatch)
    job = {
        "job_id": "job-1",
        "source_id": "source-1",
        "status": "pending",
        "attempt_count": 0,
    }
    fake.enqueue_sync.return_value = job
    fake.get_job.return_value = job

    accepted = client.post(
        "/v2/connectors/source-1/sync",
        json={"priority": 4},
    )
    status = client.get("/v2/connector-sync-jobs/job-1")

    assert accepted.status_code == 202
    assert accepted.json() == {
        "job": job,
        "status_url": "/v2/connector-sync-jobs/job-1",
    }
    assert status.status_code == 200
    assert status.json() == {"job": job}


def test_connector_not_found_is_generic(client, monkeypatch) -> None:
    from synsc.connectors.postgres import ConnectorSourceNotFoundError

    fake = _fake_service(monkeypatch)
    fake.get_source.side_effect = ConnectorSourceNotFoundError("secret")

    response = client.get("/v2/connectors/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Connector source not found."}


def test_invalid_connector_payload_is_rejected_before_service(
    client,
    monkeypatch,
) -> None:
    fake = _fake_service(monkeypatch)
    response = client.post(
        "/v2/connectors",
        json={
            "provider": "local-folder",
            "display_name": "Notes",
            "external_ref": "file:///notes",
            "classification": "invalid",
            "configuration": {},
        },
    )

    assert response.status_code == 422
    fake.create_source.assert_not_called()


def test_connector_routes_are_in_openapi(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/v2/connectors"]["get"]
    assert paths["/v2/connectors"]["post"]
    assert paths["/v2/connectors/{source_id}"]["get"]
    assert paths["/v2/connectors/{source_id}/sync"]["post"]
    assert paths["/v2/connector-sync-jobs/{job_id}"]["get"]


def test_standard_http_read_supports_connector_snapshots(
    client,
    monkeypatch,
) -> None:
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "read_connector_source",
        lambda source_id, **_kwargs: {
            "source_id": source_id,
            "source_type": "connector",
            "snapshot_id": "snapshot-1",
            "items": [{"locator": "notes.md", "content": "safe"}],
            "count": 1,
        },
    )

    response = client.get(
        "/v1/sources/source-1/read?source_type=connector"
    )

    assert response.status_code == 200
    assert response.json()["snapshot_id"] == "snapshot-1"


def test_mcp_connector_tools_are_compact_and_registered(monkeypatch) -> None:
    monkeypatch.setenv("SYNSC_MCP_PROFILE", "all")
    from synsc.api.mcp_server import create_server

    tools = create_server()._tool_manager._tools
    names = {
        name for name in tools if name.startswith("connector_")
    }
    assert names == {
        "connector_create",
        "connector_list",
        "connector_sync",
        "connector_status",
        "connector_delete",
    }
    create_params = inspect.signature(tools["connector_create"].fn).parameters
    assert "configuration" in create_params
    assert "user_id" not in create_params
