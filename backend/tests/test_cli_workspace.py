"""CLI contracts for the unified workspace and context surfaces."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from synsc import cli


def test_workspace_context_and_connector_commands_parse() -> None:
    parser = cli.create_parser()

    workspace = parser.parse_args(["workspace", "--json"])
    contexts = parser.parse_args(
        ["contexts", "show", "session-1", "--revision", "2", "--json"]
    )
    connectors = parser.parse_args(
        ["connectors", "sync", "source-1", "--priority", "4", "--json"]
    )

    assert workspace.func is cli.cmd_workspace
    assert contexts.func is cli.cmd_contexts_show
    assert contexts.revision == 2
    assert connectors.func is cli.cmd_connectors_sync
    assert connectors.priority == 4


def test_workspace_json_uses_public_client(capsys) -> None:
    client = MagicMock()
    client.__enter__.return_value = client
    client.workspace.return_value = {
        "providers": [],
        "connector_providers": [],
        "connectors": [],
        "research_sessions": [],
        "context_sessions": [],
    }
    args = SimpleNamespace(api_url="http://context.test", json=True)

    with patch("synsc.client.SynscClient", return_value=client):
        exit_code = cli.cmd_workspace(args)

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["context_sessions"] == []
    client.workspace.assert_called_once_with()


def test_context_create_and_connector_sync_dispatch(capsys) -> None:
    client = MagicMock()
    client.__enter__.return_value = client
    client.create_context_session.return_value = {
        "session": {"session_id": "session-1"}
    }
    client.sync_connector.return_value = {"job": {"job_id": "job-1"}}

    with patch("synsc.client.SynscClient", return_value=client):
        context_exit = cli.cmd_contexts_create(
            SimpleNamespace(
                api_url=None,
                name="release",
                objective="Verify release",
                snapshot_ids=["snapshot-1"],
                token_budget=4000,
                sharing_policy="private",
                json=True,
            )
        )
        connector_exit = cli.cmd_connectors_sync(
            SimpleNamespace(
                api_url=None,
                source_id="source-1",
                priority=3,
                json=True,
            )
        )

    assert context_exit == 0
    assert connector_exit == 0
    client.create_context_session.assert_called_once_with(
        name="release",
        objective="Verify release",
        snapshot_ids=["snapshot-1"],
        token_budget=4000,
        sharing_policy="private",
    )
    client.sync_connector.assert_called_once_with("source-1", priority=3)
    output = capsys.readouterr().out
    assert "session-1" in output
    assert "job-1" in output


def test_cli_reports_insecure_remote_url_without_traceback(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("SYNSC_API_KEY", "must-not-leak")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "synsc-context",
            "workspace",
            "--api-url",
            "http://context.example.test",
        ],
    )

    exit_code = cli.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert (
        "Context service error: HTTPS is required for non-loopback "
        "context service URLs" in captured.err
    )
    assert "Traceback" not in captured.err
    assert "must-not-leak" not in captured.err
