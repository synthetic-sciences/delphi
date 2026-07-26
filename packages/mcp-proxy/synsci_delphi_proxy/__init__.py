"""Transparent stdio-to-HTTP relay for the Delphi MCP server.

The backend owns the MCP tool catalog. This proxy deliberately does not
duplicate that catalog: it forwards ``tools/list`` and ``tools/call`` so
desktop clients always see the backend profile selected for their API key.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any

import anyio
import httpx
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool


REMOTE_URL = os.environ.get("SYNSC_API_URL", "http://localhost:8742").rstrip("/")
API_KEY = os.environ.get("SYNSC_API_KEY")


class ProxyConfigurationError(RuntimeError):
    """The local proxy is missing required configuration."""


class RemoteMCPError(RuntimeError):
    """The remote MCP server returned an invalid or unsuccessful response."""


def _json_from_sse(body: str) -> dict[str, Any]:
    """Return the first JSON payload from a Server-Sent Events response."""

    data_lines: list[str] = []
    for line in body.splitlines():
        if not line:
            if data_lines:
                break
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())

    if not data_lines:
        raise RemoteMCPError("The Delphi backend returned an empty event stream")

    try:
        payload = json.loads("\n".join(data_lines))
    except json.JSONDecodeError as exc:
        raise RemoteMCPError("The Delphi backend returned an invalid event stream") from exc

    if not isinstance(payload, dict):
        raise RemoteMCPError("The Delphi backend returned an invalid MCP response")
    return payload


def _decode_response(response: httpx.Response) -> dict[str, Any]:
    if response.is_error:
        detail = response.text.strip()
        if len(detail) > 500:
            detail = f"{detail[:500]}…"
        suffix = f": {detail}" if detail else ""
        raise RemoteMCPError(f"HTTP {response.status_code}{suffix}")

    content_type = response.headers.get("content-type", "")
    try:
        if "text/event-stream" in content_type:
            payload = _json_from_sse(response.text)
        else:
            decoded = response.json()
            if not isinstance(decoded, dict):
                raise RemoteMCPError("The Delphi backend returned an invalid MCP response")
            payload = decoded
    except json.JSONDecodeError as exc:
        raise RemoteMCPError("The Delphi backend returned invalid JSON") from exc

    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        raise RemoteMCPError(str(message or "Unknown MCP error"))

    result = payload.get("result")
    if not isinstance(result, dict):
        raise RemoteMCPError("The Delphi backend response did not contain an MCP result")
    return result


async def _request_remote(
    method: str,
    params: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Send one JSON-RPC request to the remote Streamable HTTP endpoint."""

    if not API_KEY:
        raise ProxyConfigurationError("SYNSC_API_KEY environment variable is not set.")

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params,
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    async def send(http_client: httpx.AsyncClient) -> dict[str, Any]:
        response = await http_client.post(f"{REMOTE_URL}/mcp", json=payload, headers=headers)
        return _decode_response(response)

    if client is not None:
        return await send(client)

    async with httpx.AsyncClient(timeout=300.0) as owned_client:
        return await send(owned_client)


async def _list_remote_tools(
    *,
    client: httpx.AsyncClient | None = None,
) -> list[Tool]:
    result = await _request_remote("tools/list", {}, client=client)
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise RemoteMCPError("The Delphi backend returned an invalid tool list")
    try:
        return [Tool.model_validate(tool) for tool in tools]
    except (TypeError, ValueError) as exc:
        raise RemoteMCPError("The Delphi backend returned an invalid tool definition") from exc


def _call_error(message: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        isError=True,
    )


async def _call_remote_tool(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    client: httpx.AsyncClient | None = None,
) -> CallToolResult:
    try:
        result = await _request_remote(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            client=client,
        )
        return CallToolResult.model_validate(result)
    except ProxyConfigurationError as exc:
        return _call_error(str(exc))
    except RemoteMCPError as exc:
        return _call_error(f"Delphi backend error: {exc}")
    except (TypeError, ValueError) as exc:
        return _call_error(f"Delphi backend returned an invalid tool result: {exc}")


server = Server("synsc-context")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return await _list_remote_tools()


@server.call_tool(validate_input=True)
async def call_tool(
    name: str,
    arguments: dict[str, Any],
) -> CallToolResult:
    return await _call_remote_tool(name, arguments)


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    try:
        anyio.run(_run)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"Delphi MCP proxy failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
