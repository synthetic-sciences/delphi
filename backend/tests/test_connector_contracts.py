"""Transport-neutral contracts for incremental connector synchronization."""

from __future__ import annotations

import pytest

from synsc.connectors.contracts import (
    ConnectorRecord,
    ConnectorSyncRequest,
    ConnectorSyncResponse,
)
from synsc.providers.contracts import CancellationToken


def test_connector_request_is_bounded_and_copies_json_configuration() -> None:
    configuration = {"path": "/workspace", "include": ["*.md"]}
    request = ConnectorSyncRequest(
        user_id="user-1",
        configuration=configuration,
        cursor={"generation": 3},
        limit=25,
        timeout_ms=2_000,
    )

    configuration["include"].append("*.txt")

    assert request.to_dict() == {
        "user_id": "user-1",
        "configuration": {"path": "/workspace", "include": ["*.md"]},
        "cursor": {"generation": 3},
        "limit": 25,
        "timeout_ms": 2_000,
    }
    assert isinstance(request.cancellation, CancellationToken)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("user_id", "", "user_id"),
        ("limit", 0, "limit"),
        ("limit", 1001, "limit"),
        ("timeout_ms", 0, "timeout_ms"),
        ("timeout_ms", 300_001, "timeout_ms"),
    ],
)
def test_connector_request_rejects_invalid_bounds(
    field: str,
    value: object,
    message: str,
) -> None:
    kwargs = {
        "user_id": "user-1",
        "configuration": {},
        "limit": 100,
        "timeout_ms": 10_000,
    }
    kwargs[field] = value
    with pytest.raises((TypeError, ValueError), match=message):
        ConnectorSyncRequest(**kwargs)


def test_connector_record_requires_content_unless_tombstoned() -> None:
    with pytest.raises(ValueError, match="content"):
        ConnectorRecord(
            external_id="doc-1",
            locator="docs/one.md",
            content="",
        )

    tombstone = ConnectorRecord(
        external_id="doc-1",
        locator="docs/one.md",
        deleted=True,
    )
    assert tombstone.to_dict()["deleted"] is True


def test_connector_record_freezes_permissions_and_metadata() -> None:
    metadata = {"labels": ["design"]}
    record = ConnectorRecord(
        external_id="doc-1",
        locator="docs/one.md",
        content="hello",
        accessible_principals=("user-1",),
        metadata=metadata,
    )
    metadata["labels"].append("mutated")

    assert record.to_dict() == {
        "external_id": "doc-1",
        "locator": "docs/one.md",
        "content": "hello",
        "deleted": False,
        "accessible_principals": ["user-1"],
        "metadata": {"labels": ["design"]},
    }


def test_connector_response_requires_cursor_when_more_pages_exist() -> None:
    with pytest.raises(ValueError, match="cursor"):
        ConnectorSyncResponse(records=(), next_cursor=None, has_more=True)


def test_connector_response_rejects_duplicate_record_ids() -> None:
    duplicate = ConnectorRecord(
        external_id="doc-1",
        locator="docs/one.md",
        content="hello",
    )
    with pytest.raises(ValueError, match="duplicate"):
        ConnectorSyncResponse(
            records=(duplicate, duplicate),
            next_cursor={"page": 2},
        )
