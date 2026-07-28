import json

from synsc.services.search_service import (
    _diagnostic_identifier_query,
    _prepare_search_query,
)


def test_prepare_search_query_compacts_structured_failure_logs() -> None:
    query = json.dumps(
        {
            "command": "go test ./...",
            "failure_excerpt": "\n".join(
                [
                    "go: downloading example.org/noise v1.2.3",
                    "   Compiling irrelevant v0.1.0",
                    "test unrelated_case ... ok",
                    '@click.option("--foo", is_flag=True)',
                    "def command(foo):",
                    "    click.echo(foo)",
                    "FAIL github.com/example/project [build failed]",
                    "./logger_test.go:325:12: p.LatencyColor undefined "
                    "(type LogFormatterParams has no field or method LatencyColor)",
                ]
            ),
            "run_strategy": "go_test_package",
            "source_type": "local_test_reproduction",
        }
    )

    prepared = _prepare_search_query(query)

    assert "LatencyColor" in prepared
    assert "LogFormatterParams" in prepared
    assert "click.option" in prepared
    assert "is_flag" in prepared
    assert "downloading" not in prepared
    assert "Compiling irrelevant" not in prepared
    assert "unrelated_case ... ok" not in prepared
    assert "\n" not in prepared


def test_prepare_search_query_keeps_natural_language_unchanged() -> None:
    query = "Where is request authentication handled?"

    assert _prepare_search_query(query) == query


def test_prepare_search_query_bounds_large_diagnostics_without_losing_tail() -> None:
    query = json.dumps(
        {
            "command": "pytest tests/test_core.py",
            "failure_excerpt": (
                ("noise that is not diagnostic\n" * 1000)
                + "tests/test_core.py:44: AssertionError: expected 3, actual 2"
            ),
        }
    )

    prepared = _prepare_search_query(query, max_chars=4000)

    assert len(prepared) <= 4000
    assert "tests/test_core.py:44" in prepared
    assert "expected 3, actual 2" in prepared


def test_diagnostic_identifier_query_keeps_api_symbols_not_test_scaffolding() -> None:
    diagnostic = (
        "tests/test_options.py:1032: AssertionError "
        "test_flag_value_is_correctly_set "
        "click.BOOL click.option click.echo is_flag flag_value result.output"
    )

    focused = _diagnostic_identifier_query(diagnostic)

    assert "click.BOOL" in focused
    assert "click.option" in focused
    assert "click.echo" in focused
    assert "is_flag" in focused
    assert "flag_value" in focused
    assert "pytest.param" not in focused
    assert "runner.invoke" not in focused
    assert "result.output" not in focused
    assert "test_options.py" not in focused
    assert "test_flag_value_is_correctly_set" not in focused
    assert "flag_value_is_correctly_set" not in focused


def test_diagnostic_identifier_query_splits_camel_case_test_names() -> None:
    focused = _diagnostic_identifier_query(
        "TestRenderData TestRenderDataContentLength"
    )

    assert focused == "Render Data Content Length"


def test_diagnostic_identifier_query_ignores_machine_specific_paths() -> None:
    focused = _diagnostic_identifier_query(
        "/Users/dev/worktrees/sample_repo/tests/test_core.py:44: "
        "AssertionError: ClientResponse.retry_count expected 3"
    )

    assert focused == "ClientResponse.retry_count"
