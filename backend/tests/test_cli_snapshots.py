"""CLI contracts for immutable source snapshot inspection."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from synsc import cli


def _snapshot() -> dict[str, object]:
    return {
        "snapshot_id": "snapshot-1",
        "source_id": "source-1",
        "source_type": "repo",
        "version": "commit-a",
        "content_hash": "a" * 64,
        "item_count": 2,
    }


def test_parser_accepts_snapshot_subcommands() -> None:
    parser = cli.create_parser()

    listed = parser.parse_args(
        [
            "snapshots",
            "list",
            "--type",
            "repo",
            "--source-id",
            "source-1",
            "--user-id",
            "user-1",
            "--json",
        ]
    )
    shown = parser.parse_args(
        [
            "snapshots",
            "show",
            "snapshot-1",
            "--include-items",
            "--json",
        ]
    )
    captured = parser.parse_args(
        [
            "snapshots",
            "capture",
            "source-1",
            "--type",
            "repo",
            "--user-id",
            "user-1",
        ]
    )

    assert listed.func is cli.cmd_snapshots_list
    assert shown.func is cli.cmd_snapshots_show
    assert captured.func is cli.cmd_snapshots_capture


def test_snapshots_list_json_is_deterministic(capsys) -> None:
    service = MagicMock()
    service.list.return_value = [_snapshot()]
    args = SimpleNamespace(
        source_type="repo",
        source_id="source-1",
        user_id="user-1",
        limit=25,
        json=True,
    )
    with patch(
        "synsc.snapshots.service.SnapshotService",
        return_value=service,
    ):
        exit_code = cli.cmd_snapshots_list(args)

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "snapshots": [_snapshot()]
    }
    assert service.list.call_args.kwargs["source_type"].value == "repo"


def test_snapshots_show_can_include_items(capsys) -> None:
    service = MagicMock()
    service.get.return_value = {
        **_snapshot(),
        "items": [{"content": "alpha"}],
    }
    args = SimpleNamespace(
        snapshot_id="snapshot-1",
        user_id="user-1",
        include_items=True,
        item_offset=0,
        item_limit=10,
        json=True,
    )
    with patch(
        "synsc.snapshots.service.SnapshotService",
        return_value=service,
    ):
        exit_code = cli.cmd_snapshots_show(args)

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["content"] == "alpha"


def test_snapshots_capture_publishes_current_source(capsys) -> None:
    service = MagicMock()
    published = MagicMock()
    published.to_dict.return_value = _snapshot()
    service.publish.return_value = published
    args = SimpleNamespace(
        source_id="source-1",
        source_type="repo",
        user_id="user-1",
        json=False,
    )
    with patch(
        "synsc.snapshots.service.SnapshotService",
        return_value=service,
    ):
        exit_code = cli.cmd_snapshots_capture(args)

    assert exit_code == 0
    assert "snapshot-1" in capsys.readouterr().out
    assert service.publish.call_args.args[0].value == "repo"
    assert service.publish.call_args.args[1] == "source-1"
