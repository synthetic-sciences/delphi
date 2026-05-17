"""Tests for the batch_read MCP tool."""
from __future__ import annotations

import asyncio

import pytest


def _call_batch_read(monkeypatch, requests, **kwargs):
    """Helper: invoke batch_read by name via the registered MCP server."""
    from synsc.api.mcp_server import create_server

    server = create_server()
    args = {"requests": requests, **kwargs}
    result = asyncio.run(server.call_tool("batch_read", args))
    # FastMCP returns a (content_list, raw_result) tuple on newer versions
    # or a Content list on older versions. The structured payload lives on
    # the call_tool path; we extract it from the JSON-text content block.
    if hasattr(result, "structured_content") and result.structured_content:
        return result.structured_content
    if isinstance(result, tuple):
        content, raw = result
        if isinstance(raw, dict):
            return raw
        # raw may already be the payload
        return raw
    # Fall through: parse the first content block's text as JSON
    import json

    content = result if isinstance(result, list) else getattr(result, "content", result)
    if content and hasattr(content[0], "text"):
        return json.loads(content[0].text)
    return content


def test_batch_read_rejects_empty_list(monkeypatch):
    out = _call_batch_read(monkeypatch, [])
    assert out["success"] is False
    assert out["error_code"] == "invalid_input"


def test_batch_read_caps_at_32(monkeypatch):
    out = _call_batch_read(monkeypatch, [{"source_id": "x"}] * 33)
    assert out["success"] is False
    assert "max 32" in out["message"]


def test_batch_read_missing_source_id_marked_per_item(monkeypatch):
    # Patch _do_read indirectly by patching the underlying services so each
    # OK request resolves cleanly.
    from synsc.services import paper_service

    class FakePaperService:
        def __init__(self, user_id=None):
            pass

        def get_paper(self, source_id, section=None):
            return {"chunks": [{"content": "abc", "section": "Methods"}]}

    monkeypatch.setattr(
        paper_service,
        "get_paper_service",
        lambda user_id=None: FakePaperService(),
    )

    out = _call_batch_read(
        monkeypatch,
        [
            {"source_id": "good-id", "source_type": "paper"},
            {"not_a_source_id": "oops"},
            {"source_id": "another", "source_type": "paper"},
        ],
    )
    assert out["success"] is True
    assert out["count"] == 3
    assert out["results"][1]["success"] is False
    assert out["results"][1]["error_code"] == "invalid_input"
    assert out["results"][0]["success"] is True
    assert out["results"][2]["success"] is True


def test_batch_read_inherits_default_topic_and_tokens(monkeypatch):
    """When a request omits topic/tokens, the top-level defaults apply."""
    from synsc.services import paper_service

    seen = {"section_calls": []}

    class FakePaperService:
        def __init__(self, user_id=None):
            pass

        def get_paper(self, source_id, section=None):
            seen["section_calls"].append((source_id, section))
            return {
                "chunks": [
                    {"content": "routing details here", "section": "Routing"},
                    {"content": "auth", "section": "Security"},
                ]
            }

    monkeypatch.setattr(
        paper_service,
        "get_paper_service",
        lambda user_id=None: FakePaperService(),
    )

    out = _call_batch_read(
        monkeypatch,
        [
            {"source_id": "p1", "source_type": "paper"},
            {"source_id": "p2", "source_type": "paper", "topic": "auth"},
        ],
        topic="routing",
        tokens=5000,
    )
    assert out["success"] is True
    # p1 used the default topic 'routing' → should keep the Routing chunk
    p1 = out["results"][0]
    p2 = out["results"][1]
    chunk_sections_p1 = [c["section"] for c in p1["chunks"]]
    chunk_sections_p2 = [c["section"] for c in p2["chunks"]]
    assert "Routing" in chunk_sections_p1
    assert "Security" not in chunk_sections_p1
    # p2 overrode topic to 'auth' → should keep Security
    assert "Security" in chunk_sections_p2
    assert "Routing" not in chunk_sections_p2
