"""Authenticated HTTP contracts for immutable source snapshots."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from synsc.snapshots.service import SnapshotNotFoundError


def _snapshot() -> dict[str, object]:
    return {
        "snapshot_id": "snapshot-1",
        "source_id": "source-1",
        "source_type": "repo",
        "version": "commit-a",
        "content_hash": "a" * 64,
        "classification": "private",
        "item_count": 1,
    }


def test_snapshot_routes_require_auth_when_enabled(auth_client) -> None:
    response = auth_client.get(
        "/v2/sources/source-1/snapshots",
        params={"type": "repo"},
    )

    assert response.status_code == 401


def test_list_source_snapshots_uses_authenticated_identity(client) -> None:
    service = MagicMock()
    service.list.return_value = [_snapshot()]
    with patch(
        "synsc.snapshots.service.SnapshotService",
        return_value=service,
    ):
        response = client.get(
            "/v2/sources/source-1/snapshots",
            params={"type": "repo", "limit": 25},
        )

    assert response.status_code == 200
    assert response.json() == {"snapshots": [_snapshot()], "total": 1}
    service.list.assert_called_once_with(
        user_id="00000000-0000-0000-0000-000000000000",
        source_type=service.list.call_args.kwargs["source_type"],
        source_id="source-1",
        limit=25,
    )
    assert service.list.call_args.kwargs["source_type"].value == "repo"


def test_capture_source_snapshot_returns_published_metadata(client) -> None:
    service = MagicMock()
    published = MagicMock()
    published.to_dict.return_value = _snapshot()
    service.publish.return_value = published
    with patch(
        "synsc.snapshots.service.SnapshotService",
        return_value=service,
    ):
        response = client.post(
            "/v2/sources/source-1/snapshots",
            json={"source_type": "repo"},
        )

    assert response.status_code == 201
    assert response.json() == {"snapshot": _snapshot()}
    assert service.publish.call_args.args[1] == "source-1"
    assert service.publish.call_args.args[0].value == "repo"


def test_get_snapshot_can_include_paged_items(client) -> None:
    service = MagicMock()
    service.get.return_value = {
        **_snapshot(),
        "items": [{"content": "alpha"}],
    }
    with patch(
        "synsc.snapshots.service.SnapshotService",
        return_value=service,
    ):
        response = client.get(
            "/v2/snapshots/snapshot-1",
            params={
                "include_items": "true",
                "item_offset": 10,
                "item_limit": 20,
            },
        )

    assert response.status_code == 200
    assert response.json()["snapshot"]["items"] == [{"content": "alpha"}]
    service.get.assert_called_once_with(
        "snapshot-1",
        user_id="00000000-0000-0000-0000-000000000000",
        include_items=True,
        item_offset=10,
        item_limit=20,
    )


def test_snapshot_not_found_is_generic(client) -> None:
    service = MagicMock()
    service.get.side_effect = SnapshotNotFoundError("internal detail")
    with patch(
        "synsc.snapshots.service.SnapshotService",
        return_value=service,
    ):
        response = client.get("/v2/snapshots/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Snapshot not found."}


def test_snapshot_routes_are_in_openapi(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert paths["/v2/sources/{source_id}/snapshots"]["get"]
    assert paths["/v2/sources/{source_id}/snapshots"]["post"]
    assert paths["/v2/snapshots/{snapshot_id}"]["get"]
