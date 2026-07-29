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


def test_prepare_search_query_keeps_literal_json_search_unchanged() -> None:
    query = '{"type":"module","private":true}'

    assert _prepare_search_query(query) == query


def test_prepare_search_query_keeps_literal_diagnostic_json_unchanged() -> None:
    query = '{"error":"ENOENT","message":"file not found"}'

    assert _prepare_search_query(query) == query


def test_prepare_search_query_keeps_literal_patch_json_unchanged() -> None:
    query = '{"filename":"src/auth.py","patch":"@@ -1 +1 @@"}'

    assert _prepare_search_query(query) == query


def test_prepare_search_query_compacts_structured_developer_context() -> None:
    query = json.dumps(
        {
            "changed_file_summary": (
                "1 implementation file and 1 existing test file changed."
            ),
            "implementation_file_count": 1,
            "implementation_files": ["server/etcdmain/grpc_proxy.go"],
            "pr_body": "This adds TLS version support to the grpc proxy.",
            "pr_title": "add tls min/max version to grpc proxy",
        }
    )

    prepared = _prepare_search_query(query)

    assert prepared == (
        "add tls min/max version to grpc proxy "
        "server/etcdmain/grpc_proxy.go "
        "This adds TLS version support to the grpc proxy. "
        "1 implementation file and 1 existing test file changed."
    )
    assert "implementation_file_count" not in prepared
    assert not prepared.startswith("{")


def test_prepare_search_query_compacts_nested_developer_context() -> None:
    query = json.dumps(
        {
            "context": {
                "title": "Fix auth",
                "files": ["src/auth.py"],
                "diff": "large generated diff line\n" * 1_000,
            }
        }
    )

    prepared = _prepare_search_query(query, max_chars=120)

    assert len(prepared) <= 120
    assert prepared.startswith("Fix auth src/auth.py ")
    assert "large generated diff line" in prepared
    assert not prepared.startswith("{")


def test_prepare_search_query_compacts_nested_pull_request_envelope() -> None:
    query = json.dumps(
        {
            "pull_request": {
                "title": "Fix auth",
                "files": ["src/auth.py"],
                "diff": "large generated diff line\n" * 1_000,
            }
        }
    )

    prepared = _prepare_search_query(query, max_chars=120)

    assert len(prepared) <= 120
    assert prepared.startswith("Fix auth src/auth.py ")
    assert "large generated diff line" in prepared
    assert not prepared.startswith("{")


def test_prepare_search_query_prioritizes_intent_and_path_over_large_diff() -> None:
    query = json.dumps(
        {
            "anchor_diff": "low-signal generated diff line\n" * 1_000,
            "anchor_file": "binding/form_mapping.go",
            "intent": "Fix multipart form binding errors",
        }
    )

    prepared = _prepare_search_query(query, max_chars=160)

    assert len(prepared) <= 160
    assert prepared.startswith(
        "Fix multipart form binding errors binding/form_mapping.go "
    )
    assert "low-signal generated diff line" in prepared


def test_prepare_search_query_preserves_intent_and_path_after_large_error() -> None:
    query = json.dumps(
        {
            "error_log": "low-signal error detail " * 1_000,
            "intent": "Fix multipart form binding errors",
            "anchor_file": "binding/form_mapping.go",
        }
    )

    prepared = _prepare_search_query(query, max_chars=120)

    assert len(prepared) <= 120
    assert prepared.startswith(
        "Fix multipart form binding errors binding/form_mapping.go "
    )


def test_prepare_search_query_prioritizes_task_and_objective_over_patch() -> None:
    query = json.dumps(
        {
            "patch": "low-signal patch line " * 1_000,
            "task": "Repair retry behavior",
            "objective": "Preserve transient failures",
            "target_path": "src/client.py",
        }
    )

    prepared = _prepare_search_query(query, max_chars=120)

    assert len(prepared) <= 120
    assert "Repair retry behavior" in prepared
    assert "Preserve transient failures" in prepared
    assert "src/client.py" in prepared


def test_prepare_search_query_keeps_intent_and_complete_paths_in_large_change() -> None:
    paths = [f"src/shared/component_{index}/implementation.py" for index in range(100)]
    query = json.dumps(
        {
            "intent": "Repair authentication behavior without regressions",
            "target_files": paths,
            "anchor_patch": "low-signal generated patch line " * 1_000,
        }
    )

    prepared = _prepare_search_query(query, max_chars=4000)
    path_tokens = [
        token for token in prepared.split() if token.startswith("src/")
    ]

    assert len(prepared) <= 4000
    assert prepared.startswith(
        "Repair authentication behavior without regressions "
    )
    assert path_tokens
    assert all(token in paths for token in path_tokens)
    assert "low-signal generated patch line" in prepared


def test_prepare_search_query_respects_tiny_character_budget() -> None:
    query = json.dumps(
        {
            "intent": "Fix authentication",
            "target_path": "src/auth.py",
            "patch": "large patch",
        }
    )

    assert len(_prepare_search_query(query, max_chars=1)) <= 1


def test_prepare_search_query_respects_zero_character_budget() -> None:
    query = json.dumps(
        {
            "intent": "Fix authentication",
            "target_path": "src/auth.py",
            "patch": "large patch",
        }
    )

    assert _prepare_search_query(query, max_chars=0) == ""


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
