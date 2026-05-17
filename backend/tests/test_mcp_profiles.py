"""Verify SYNSC_MCP_PROFILE prunes the tool surface."""
from __future__ import annotations

import asyncio

import pytest


def _names_for_profile(monkeypatch, profile: str) -> list[str]:
    monkeypatch.setenv("SYNSC_MCP_PROFILE", profile)
    # Force a fresh import path — create_server reads env at call time so a
    # fresh call picks up the new env, but module-level caching elsewhere
    # is irrelevant here.
    from synsc.api.mcp_server import create_server

    server = create_server()
    tools = asyncio.run(server.list_tools())
    return sorted(t.name for t in tools)


def test_profile_all_exposes_everything(monkeypatch):
    names = _names_for_profile(monkeypatch, "all")
    assert "index_repository" in names
    assert "index_paper" in names
    assert "thesis_search_nodes" in names
    assert "research" in names
    assert "resolve_source" in names


def test_profile_code_excludes_thesis_and_papers(monkeypatch):
    names = _names_for_profile(monkeypatch, "code")
    assert "index_repository" in names
    assert "search_code" in names
    assert "resolve_source" in names  # sources still on (cross-cutting)
    assert not any(n.startswith("thesis_") for n in names)
    assert "index_paper" not in names
    assert "research" not in names


def test_profile_papers_includes_research(monkeypatch):
    names = _names_for_profile(monkeypatch, "papers")
    assert "index_paper" in names
    assert "search_papers" in names
    assert "research" in names
    assert "index_repository" not in names
    assert not any(n.startswith("thesis_") for n in names)


def test_profile_thesis_only_thesis_and_sources(monkeypatch):
    names = _names_for_profile(monkeypatch, "thesis")
    assert any(n.startswith("thesis_") for n in names)
    assert "build_thesis_context" in names
    assert "search" in names  # sources cross-cut
    assert "index_repository" not in names
    assert "index_paper" not in names


def test_profile_minimal_is_tiny(monkeypatch):
    names = _names_for_profile(monkeypatch, "minimal")
    assert "resolve_source" in names
    assert "search" in names
    assert "read_source" in names
    # Should not include heavy index/admin tools
    assert "index_repository" not in names
    assert "delete_paper" not in names


def test_profile_unknown_falls_back_to_all(monkeypatch):
    names = _names_for_profile(monkeypatch, "nonexistent")
    assert "index_repository" in names
    assert "thesis_search_nodes" in names
