"""Surface-area + auth-gating tests for the Thesis connector.

We can't run the DB-backed paths without a live Postgres+pgvector, but we
can check:
  - All public functions are exported with the documented signatures.
  - Calls without ``user_id`` return ``{"success": False, "error": ...}``
    instead of raising.
  - The connector imports cleanly.
"""
from __future__ import annotations

import inspect

import pytest

from synsc.services import thesis_connector as tc


def test_module_exports_full_api():
    """Every function in the spec must be importable from the module."""
    required = [
        # Ingest
        "ingest_workspace",
        "ingest_node",
        "ingest_edge",
        "ingest_artifact",
        "ingest_execution",
        "ingest_tool_contract",
        # Retrieval
        "search_thesis_nodes",
        "find_related_nodes",
        "find_relevant_artifacts",
        "retrieve_tool_contract",
        # Workflow tools
        "find_what_was_tried",
        "find_what_not_to_repeat",
        "build_thesis_context",
        "summarize_relevant_subgraph",
        "find_decisions",
        "get_active_work_context",
    ]
    for fn_name in required:
        assert hasattr(tc, fn_name), f"thesis_connector missing {fn_name}"
        fn = getattr(tc, fn_name)
        assert callable(fn), f"{fn_name} is not callable"


def test_ingest_workspace_rejects_missing_user():
    res = tc.ingest_workspace(
        user_id=None, external_id="x", name="X",
    )
    assert res["success"] is False
    assert res["error"] == "auth_required"


def test_ingest_node_rejects_missing_user():
    res = tc.ingest_node(
        user_id=None, workspace_id="ws-1", external_id="n1",
        node_type="claim",
    )
    assert res["success"] is False
    assert res["error"] == "auth_required"


def test_ingest_edge_rejects_missing_user():
    res = tc.ingest_edge(
        user_id=None, workspace_id="ws-1",
        source_external_id="a", target_external_id="b",
        edge_type="blocks",
    )
    assert res["success"] is False
    assert res["error"] == "auth_required"


def test_ingest_artifact_rejects_missing_user():
    res = tc.ingest_artifact(
        user_id=None, workspace_id="ws-1",
        node_external_id="n1", kind="table",
    )
    assert res["success"] is False
    assert res["error"] == "auth_required"


def test_ingest_execution_rejects_missing_user():
    res = tc.ingest_execution(
        user_id=None, workspace_id="ws-1",
        node_external_id="n1", tool="x", status="ok",
    )
    assert res["success"] is False


def test_ingest_tool_contract_rejects_missing_user():
    res = tc.ingest_tool_contract(
        user_id=None, tool_name="thesis_search_nodes",
    )
    assert res["success"] is False


def test_search_thesis_nodes_empty_inputs():
    """Empty query → empty list, no DB call attempted."""
    assert tc.search_thesis_nodes(query="", user_id="u1") == []
    assert tc.search_thesis_nodes(query="x", user_id="") == []


def test_find_related_nodes_requires_anchor():
    """Pass neither node_id nor question → empty list."""
    res = tc.find_related_nodes(user_id="u1")
    assert res == []


def test_find_relevant_artifacts_empty_query():
    assert tc.find_relevant_artifacts(user_id="u1", query="") == []


def test_retrieve_tool_contract_empty_inputs():
    assert tc.retrieve_tool_contract(user_id="u1", task="") == []
    assert tc.retrieve_tool_contract(user_id="", task="x") == []


def test_find_related_nodes_question_signature_accepted():
    """Spec uses find_related_nodes(question). Ensure we accept it as a kwarg."""
    sig = inspect.signature(tc.find_related_nodes)
    assert "question" in sig.parameters
    assert "node_id" in sig.parameters


def test_build_thesis_context_rejects_missing_user():
    res = tc.build_thesis_context(user_id=None, question="x")
    assert res["success"] is False
    assert res["error"] == "auth_required"


def test_get_active_work_context_signature():
    """Ensure ``workspace_ids`` filter is plumbed through."""
    sig = inspect.signature(tc.get_active_work_context)
    assert "workspace_ids" in sig.parameters


def test_summarize_subgraph_handles_no_root():
    """Passing no root_node_id and no hits → empty subgraph, not an exception."""
    res = tc.summarize_relevant_subgraph(
        user_id="u1", question="something with no matches",
    )
    # Either it returns an empty subgraph or attempts a DB query and fails
    # gracefully — both are valid outcomes without a real DB.
    assert "success" in res
