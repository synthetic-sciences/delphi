"""Verify every new MCP tool from the agent-quality refactor is registered.

Each phase added tools that have to be callable by name from an agent.
We don't invoke them (most need a DB) — just assert they registered with
the FastMCP server.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


@pytest.fixture
def server_tool_names():
    """Spin up the MCP server in test mode and return the registered tool names."""
    with patch("synsc.embeddings.generator.get_embedding_generator"):
        from synsc.api.mcp_server import create_server

        server = create_server()
        tools = asyncio.run(server.list_tools())
        return {t.name for t in tools}


# Phase 1–2: agent-mode controls + observability
AGENT_MODE_TOOLS = {
    "index_repository",   # gets quality_mode/include_tests/etc kwargs
    "search_code",        # gets quality_mode kwarg
    "classify_failure",   # new
}

# Phase 3–4: context + drill-in primitives
CONTEXT_PACK_TOOLS = {
    "build_context_pack",
    "get_context",
    "get_symbol",  # now returns source body
}

# Phase 6: paper improvements
PAPER_IMPROVEMENT_TOOLS = {
    "search_papers",
    "extract_quoted_evidence",
    "joint_retrieval",
}

# Phase 7: Thesis connector
THESIS_TOOLS = {
    "thesis_register_workspace",
    "thesis_ingest_node",
    "thesis_ingest_edge",
    "thesis_ingest_artifact",
    "thesis_ingest_execution",
    "thesis_ingest_tool_contract",
    "thesis_search_nodes",
    "find_related_nodes",
    "find_relevant_artifacts",
    "thesis_retrieve_tool_contract",
    "summarize_relevant_subgraph",
    "build_thesis_context",
    "thesis_what_was_tried",
    "thesis_what_not_to_repeat",
    "thesis_active_work_context",
    "thesis_find_decisions",
}


def test_agent_mode_tools_registered(server_tool_names):
    missing = AGENT_MODE_TOOLS - server_tool_names
    assert not missing, f"Missing agent-mode tools: {missing}"


def test_context_pack_tools_registered(server_tool_names):
    missing = CONTEXT_PACK_TOOLS - server_tool_names
    assert not missing, f"Missing context-pack tools: {missing}"


def test_paper_improvement_tools_registered(server_tool_names):
    missing = PAPER_IMPROVEMENT_TOOLS - server_tool_names
    assert not missing, f"Missing paper tools: {missing}"


def test_thesis_tools_registered(server_tool_names):
    missing = THESIS_TOOLS - server_tool_names
    assert not missing, f"Missing Thesis tools: {missing}"


def test_no_tool_name_collisions(server_tool_names):
    """list_tools() returns no duplicates."""
    with patch("synsc.embeddings.generator.get_embedding_generator"):
        from synsc.api.mcp_server import create_server

        server = create_server()
        tools = asyncio.run(server.list_tools())
        names = [t.name for t in tools]
        # If names has duplicates, set conversion loses them.
        assert len(names) == len(set(names)), (
            f"Duplicate tool names: "
            f"{[n for n in names if names.count(n) > 1]}"
        )


def test_total_tool_count_unchanged_or_grew(server_tool_names):
    """Phase 1–7 should only have added tools, never removed any.
    The previous baseline (pre-refactor) had ~37 tools. We're at 54+.
    """
    assert len(server_tool_names) >= 50, (
        f"Tool count regressed: {len(server_tool_names)} (expected >= 50)"
    )
