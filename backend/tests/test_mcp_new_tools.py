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
def server_tool_names(monkeypatch):
    """Spin up the MCP server in test mode and return the registered tool names.

    Force the ``all`` profile so the full tool surface is registered — the
    default profile is ``code``, which intentionally prunes papers/atlas/etc.
    """
    monkeypatch.setenv("SYNSC_MCP_PROFILE", "all")
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

# Phase 7: Atlas connector
ATLAS_TOOLS = {
    "atlas_register_workspace",
    "atlas_ingest_node",
    "atlas_ingest_edge",
    "atlas_ingest_artifact",
    "atlas_ingest_execution",
    "atlas_ingest_tool_contract",
    "atlas_search_nodes",
    "find_related_nodes",
    "find_relevant_artifacts",
    "atlas_retrieve_tool_contract",
    "summarize_relevant_subgraph",
    "build_atlas_context",
    "atlas_what_was_tried",
    "atlas_what_not_to_repeat",
    "atlas_active_work_context",
    "atlas_find_decisions",
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


def test_atlas_tools_registered(server_tool_names):
    missing = ATLAS_TOOLS - server_tool_names
    assert not missing, f"Missing Atlas tools: {missing}"


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
