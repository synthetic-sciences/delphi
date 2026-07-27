"""CLI provider-catalog and policy-check tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

from synsc import cli


def test_parser_accepts_provider_diagnostic_commands() -> None:
    parser = cli.create_parser()

    providers = parser.parse_args(["providers", "--json"])
    policy = parser.parse_args(
        [
            "policy-check",
            "--provider",
            "gemini-research",
            "--capability",
            "synthesis",
            "--network",
            "allowlisted",
            "--classification",
            "private",
            "--purpose",
            "answer",
            "--field",
            "metadata",
            "--field",
            "excerpts",
            "--allowed-provider",
            "gemini-research",
            "--source-opt-in",
            "--json",
        ]
    )

    assert providers.func is cli.cmd_providers
    assert providers.json is True
    assert policy.func is cli.cmd_policy_check
    assert policy.fields == ["metadata", "excerpts"]
    assert policy.allowed_providers == ["gemini-research"]
    assert policy.source_opt_in is True


def test_providers_json_output_is_machine_readable(capsys) -> None:
    catalog = [{"name": "local-test", "execution": "local"}]
    with patch(
        "synsc.services.provider_service.list_providers",
        return_value=catalog,
    ):
        exit_code = cli.cmd_providers(SimpleNamespace(json=True))

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"providers": catalog}


def test_providers_human_output_excludes_sensitive_fields(capsys) -> None:
    catalog = [
        {
            "name": "remote-test",
            "execution": "remote",
            "health": "ready",
            "capabilities": ["synthesis", "research"],
        }
    ]
    with patch(
        "synsc.services.provider_service.list_providers",
        return_value=catalog,
    ):
        exit_code = cli.cmd_providers(SimpleNamespace(json=False))

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "remote-test" in output
    assert "synthesis,research" in output
    assert "api_key" not in output
    assert "credential" not in output.lower()


def _policy_args(*, json_output: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        provider="gemini-research",
        capability="synthesis",
        network="offline",
        classification="public",
        purpose="answer",
        fields=["excerpts"],
        allowed_providers=[],
        source_opt_in=False,
        one_request_override=False,
        json=json_output,
    )


def test_policy_check_denial_exits_two_and_passes_exact_payload(capsys) -> None:
    decision = {
        "allowed": False,
        "allowed_fields": [],
        "reason_code": "network_offline",
        "policy_basis": "offline policy prohibits every remote provider call",
    }
    with patch(
        "synsc.services.provider_service.evaluate_egress",
        return_value=decision,
    ) as evaluate:
        exit_code = cli.cmd_policy_check(_policy_args())

    assert exit_code == 2
    assert "DENIED" in capsys.readouterr().out
    evaluate.assert_called_once_with(
        {
            "provider": "gemini-research",
            "capability": "synthesis",
            "network": "offline",
            "classification": "public",
            "purpose": "answer",
            "fields": ["excerpts"],
            "allowed_providers": [],
            "source_opt_in": False,
            "one_request_override": False,
        }
    )


def test_policy_check_allowed_exits_zero_with_sorted_json(capsys) -> None:
    decision = {
        "allowed": True,
        "allowed_fields": ["excerpts"],
        "reason_code": "public_content",
        "policy_basis": "public content is permitted by online policy",
    }
    with patch(
        "synsc.services.provider_service.evaluate_egress",
        return_value=decision,
    ):
        exit_code = cli.cmd_policy_check(_policy_args(json_output=True))

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == decision


def test_policy_check_works_without_database_configuration(
    monkeypatch,
    capsys,
) -> None:
    from synsc import config as config_module

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    config_module._config = None

    exit_code = cli.cmd_policy_check(_policy_args(json_output=True))

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out)["reason_code"] == "network_offline"


def test_policy_check_subprocess_needs_no_database_configuration() -> None:
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("POSTGRES_PASSWORD", None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "synsc.cli",
            "policy-check",
            "--provider",
            "gemini-research",
            "--capability",
            "synthesis",
            "--network",
            "offline",
            "--classification",
            "public",
            "--purpose",
            "answer",
            "--field",
            "excerpts",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["reason_code"] == "network_offline"
    assert "Traceback" not in result.stderr
