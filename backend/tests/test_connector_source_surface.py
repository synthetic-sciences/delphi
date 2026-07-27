"""Connector sources participate in the unified source and search surfaces."""

from __future__ import annotations

from unittest.mock import MagicMock


def test_unified_retrieve_searches_current_connector_snapshot(
    monkeypatch,
) -> None:
    from synsc.services import source_service

    snapshots = MagicMock()
    snapshots.resolve.return_value = {"snapshot_id": "snapshot-1"}
    snapshots.search.return_value = [
        {
            "snapshot_id": "snapshot-1",
            "source_id": "source-1",
            "source_type": "connector",
            "origin_item_id": "item-1",
            "locator": "notes/one.md",
            "content": "connector context",
            "score": 0.8,
            "metadata": {"connector_external_id": "one"},
        }
    ]
    monkeypatch.setattr(
        source_service,
        "_get_snapshot_service",
        lambda: snapshots,
        raising=False,
    )
    monkeypatch.setattr(
        source_service,
        "_attach_trust_scores",
        lambda hits, **kwargs: hits,
    )
    monkeypatch.setattr(
        source_service,
        "_maybe_cross_source_rerank",
        lambda query, hits, **kwargs: hits,
    )

    hits = source_service.unified_retrieve(
        query="connector",
        source_bindings=[("connector", "source-1")],
        source_types=["connector"],
        user_id="user-1",
    )

    assert hits[0]["source_type"] == "connector"
    assert hits[0]["snapshot_id"] == "snapshot-1"
    assert hits[0]["text"] == "connector context"
    snapshots.search.assert_called_once()


def test_list_sources_includes_connector_lifecycle_state(
    monkeypatch,
) -> None:
    from synsc.connectors import service as connector_service
    from synsc.services import source_service

    connectors = MagicMock()
    connectors.list_sources.return_value = [
        {
            "source_id": "source-1",
            "source_type": "connector",
            "provider": "local-folder",
            "display_name": "Notes",
            "external_ref": "file:///notes",
            "last_snapshot_id": "snapshot-1",
            "created_at": "2026-07-27T00:00:00+00:00",
        }
    ]
    monkeypatch.setattr(
        connector_service,
        "get_connector_sync_service",
        lambda: connectors,
    )

    sources = source_service.list_sources(
        source_type="connector",
        user_id="user-1",
    )

    assert sources == [
        {
            "source_id": "source-1",
            "source_type": "connector",
            "display_name": "Notes",
            "external_ref": "file:///notes",
            "status": "indexed",
            "created_at": "2026-07-27T00:00:00+00:00",
            "provider": "local-folder",
            "snapshot_id": "snapshot-1",
        }
    ]


def test_resolve_source_name_includes_owned_connectors(monkeypatch) -> None:
    from synsc.connectors import service as connector_service
    from synsc.services import source_service

    connectors = MagicMock()
    connectors.list_sources.return_value = [
        {
            "source_id": "source-1",
            "provider": "local-folder",
            "display_name": "Project Notes",
            "external_ref": "file:///notes",
        }
    ]
    monkeypatch.setattr(
        connector_service,
        "get_connector_sync_service",
        lambda: connectors,
    )

    matches = source_service.resolve_source_name(
        "project",
        user_id="user-1",
        source_types=["connector"],
    )

    assert matches[0]["source_id"] == "source-1"
    assert matches[0]["source_type"] == "connector"
