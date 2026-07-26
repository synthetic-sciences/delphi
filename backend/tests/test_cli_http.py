"""CLI-to-HTTP entry-point contract tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock


def test_cmd_serve_http_passes_cli_overrides(monkeypatch):
    from synsc import cli
    from synsc.api import http_server

    run_http_server = MagicMock()
    monkeypatch.setattr(http_server, "run_http_server", run_http_server)

    result = cli.cmd_serve_http(SimpleNamespace(host="127.0.0.1", port=9123))

    assert result == 0
    run_http_server.assert_called_once_with(host="127.0.0.1", port=9123)


def test_run_http_server_honors_host_and_port_overrides(monkeypatch):
    from synsc.api import http_server

    run = MagicMock()
    monkeypatch.setattr("uvicorn.run", run)

    http_server.run_http_server(host="127.0.0.1", port=9123)

    run.assert_called_once_with(
        http_server.app,
        host="127.0.0.1",
        port=9123,
    )


def test_run_http_server_uses_config_when_overrides_are_omitted(monkeypatch):
    from synsc.api import http_server

    run = MagicMock()
    monkeypatch.setattr("uvicorn.run", run)
    config = SimpleNamespace(api=SimpleNamespace(host="0.0.0.0", port=8742))
    monkeypatch.setattr(http_server, "get_config", lambda: config)

    http_server.run_http_server()

    run.assert_called_once_with(
        http_server.app,
        host="0.0.0.0",
        port=8742,
    )
