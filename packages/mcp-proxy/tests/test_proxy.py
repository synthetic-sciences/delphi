"""Behavioral tests for the transparent Delphi MCP relay."""

import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent, Tool

import synsci_delphi_proxy as proxy


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _jsonrpc_response(request: httpx.Request, result: dict) -> httpx.Response:
    request_body = json.loads(request.content)
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": request_body["id"], "result": result},
    )


@pytest.mark.anyio
async def test_stdio_server_exposes_the_remote_catalog(monkeypatch) -> None:
    """An MCP client sees dynamically listed tools and can call them."""
    listed_tool = Tool(
        name="dynamic_backend_tool",
        description="Only the backend knows about this tool.",
        inputSchema={"type": "object"},
    )

    async def list_remote_tools() -> list[Tool]:
        return [listed_tool]

    async def call_remote_tool(
        name: str,
        arguments: dict,
    ) -> CallToolResult:
        assert name == listed_tool.name
        assert arguments == {"value": 42}
        return CallToolResult(
            content=[TextContent(type="text", text="relayed")],
            isError=False,
        )

    monkeypatch.setattr(proxy, "_list_remote_tools", list_remote_tools)
    monkeypatch.setattr(proxy, "_call_remote_tool", call_remote_tool)

    async with create_connected_server_and_client_session(proxy.server) as session:
        catalog = await session.list_tools()
        result = await session.call_tool(listed_tool.name, {"value": 42})

    assert catalog.tools == [listed_tool]
    assert result.content == [TextContent(type="text", text="relayed")]
    assert result.isError is False


@pytest.mark.anyio
async def test_list_remote_tools_mirrors_backend_profile(monkeypatch) -> None:
    """Only tools returned by the active backend profile are exposed locally."""
    monkeypatch.setattr(proxy, "API_KEY", "test-key")
    expected_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "branch": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
            },
        },
        "required": ["query"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["method"] == "tools/list"
        assert body["params"] == {}
        assert request.headers["Authorization"] == "Bearer test-key"
        return _jsonrpc_response(
            request,
            {
                "tools": [
                    {
                        "name": "build_context_pack",
                        "description": "Build agent-ready context.",
                        "inputSchema": expected_schema,
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tools = await proxy._list_remote_tools(client=client)

    assert tools == [
        Tool(
            name="build_context_pack",
            description="Build agent-ready context.",
            inputSchema=expected_schema,
        )
    ]


@pytest.mark.anyio
async def test_call_remote_tool_preserves_complete_mcp_result(monkeypatch) -> None:
    """Content blocks, structured output, and error state survive the relay."""
    monkeypatch.setattr(proxy, "API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["method"] == "tools/call"
        assert body["params"] == {
            "name": "build_context_pack",
            "arguments": {"query": "trace authentication"},
        }
        return _jsonrpc_response(
            request,
            {
                "content": [
                    {"type": "text", "text": "context ready"},
                    {
                        "type": "resource_link",
                        "uri": "file:///src/auth.py",
                        "name": "auth.py",
                    },
                ],
                "structuredContent": {"source_ids": ["repo-1"]},
                "isError": False,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await proxy._call_remote_tool(
            "build_context_pack",
            {"query": "trace authentication"},
            client=client,
        )

    assert isinstance(result, CallToolResult)
    assert result.structuredContent == {"source_ids": ["repo-1"]}
    assert result.isError is False
    assert result.content[0] == TextContent(type="text", text="context ready")
    assert result.content[1].type == "resource_link"


@pytest.mark.anyio
async def test_remote_request_accepts_streamable_http_sse(monkeypatch) -> None:
    """Streamable HTTP event responses decode to the same JSON-RPC result."""
    monkeypatch.setattr(proxy, "API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payload = {
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {"tools": []},
        }
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=f"event: message\ndata: {json.dumps(payload)}\n\n",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await proxy._request_remote("tools/list", {}, client=client)

    assert result == {"tools": []}


@pytest.mark.anyio
async def test_remote_jsonrpc_error_becomes_mcp_tool_error(monkeypatch) -> None:
    """Backend JSON-RPC failures reach clients as failed MCP tool results."""
    monkeypatch.setattr(proxy, "API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32601, "message": "Tool not found"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await proxy._call_remote_tool(
            "missing_tool",
            {},
            client=client,
        )

    assert result.isError is True
    assert result.content == [
        TextContent(type="text", text="Delphi backend error: Tool not found")
    ]


@pytest.mark.anyio
async def test_missing_api_key_does_not_contact_backend(monkeypatch) -> None:
    """A missing credential produces a local MCP error without an HTTP request."""
    monkeypatch.setattr(proxy, "API_KEY", "")
    contacted = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal contacted
        contacted = True
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await proxy._call_remote_tool("search", {}, client=client)

    assert contacted is False
    assert result.isError is True
    assert result.content == [
        TextContent(
            type="text",
            text="SYNSC_API_KEY environment variable is not set.",
        )
    ]
