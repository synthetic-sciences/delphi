"""Local-folder connector safety and incremental change contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from synsc.connectors.contracts import ConnectorSyncRequest
from synsc.connectors.local_folder import LocalFolderConnector


def _request(path: Path, **configuration: object) -> ConnectorSyncRequest:
    return ConnectorSyncRequest(
        user_id="user-1",
        configuration={"path": str(path), **configuration},
        limit=100,
        timeout_ms=5_000,
    )


def test_initial_sync_is_deterministic_and_skips_binary_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "b.md").write_text("beta", encoding="utf-8")
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "image.bin").write_bytes(b"\x00\x01\x02")

    result = LocalFolderConnector().sync(_request(tmp_path))

    assert [record.locator for record in result.records] == ["a.txt", "b.md"]
    assert [record.content for record in result.records] == ["alpha", "beta"]
    assert result.has_more is False
    assert result.next_cursor is not None


def test_followup_sync_emits_only_changes_and_tombstones(tmp_path: Path) -> None:
    first_path = tmp_path / "first.md"
    second_path = tmp_path / "second.md"
    first_path.write_text("one", encoding="utf-8")
    second_path.write_text("two", encoding="utf-8")
    connector = LocalFolderConnector()

    initial = connector.sync(_request(tmp_path))
    first_path.write_text("updated", encoding="utf-8")
    second_path.unlink()

    followup = connector.sync(
        ConnectorSyncRequest(
            user_id="user-1",
            configuration={"path": str(tmp_path)},
            cursor=initial.next_cursor,
            limit=100,
            timeout_ms=5_000,
        )
    )

    assert [
        (record.locator, record.content, record.deleted)
        for record in followup.records
    ] == [
        ("first.md", "updated", False),
        ("second.md", "", True),
    ]


def test_bounded_pages_advance_without_losing_remaining_changes(
    tmp_path: Path,
) -> None:
    for name in ("a.md", "b.md", "c.md"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    connector = LocalFolderConnector()

    first = connector.sync(
        ConnectorSyncRequest(
            user_id="user-1",
            configuration={"path": str(tmp_path)},
            limit=2,
            timeout_ms=5_000,
        )
    )
    second = connector.sync(
        ConnectorSyncRequest(
            user_id="user-1",
            configuration={"path": str(tmp_path)},
            cursor=first.next_cursor,
            limit=2,
            timeout_ms=5_000,
        )
    )

    assert [record.locator for record in first.records] == ["a.md", "b.md"]
    assert first.has_more is True
    assert [record.locator for record in second.records] == ["c.md"]
    assert second.has_more is False


def test_sync_rejects_root_escape_and_symlink_targets(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "escape.txt").symlink_to(outside)

    result = LocalFolderConnector().sync(_request(tmp_path))

    assert result.records == ()


def test_sync_requires_an_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="directory"):
        LocalFolderConnector().sync(_request(tmp_path / "missing"))


def test_sync_honors_file_and_total_byte_limits(tmp_path: Path) -> None:
    (tmp_path / "large.md").write_text("1234567890", encoding="utf-8")
    with pytest.raises(ValueError, match="max_file_bytes"):
        LocalFolderConnector().sync(
            _request(tmp_path, max_file_bytes=5, max_total_bytes=100)
        )


def test_sync_honors_cancellation(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
    request = _request(tmp_path)
    request.cancellation.cancel()

    with pytest.raises(TimeoutError, match="cancelled"):
        LocalFolderConnector().sync(request)
