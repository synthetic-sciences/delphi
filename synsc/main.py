#!/usr/bin/env python3
"""Synsc Context Server - Entry point for MCP and HTTP servers."""

import sys

from synsc.logging import configure_logging

configure_logging()


def main():
    """Run the Synsc Context server (CLI entry point)."""
    from synsc.cli import main as cli_main
    return cli_main()


def run_mcp():
    """Run the MCP server (stdio transport)."""
    from synsc.api.mcp_server import run_server
    run_server()


def run_http(host: str = "0.0.0.0", port: int = 8000):
    """Run the HTTP API server."""
    from synsc.api.http_server import run_http_server
    run_http_server(host, port)


if __name__ == "__main__":
    # Quick mode selection via argument
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == "mcp":
            run_mcp()
        elif mode == "http":
            run_http()
        else:
            sys.exit(main())
    else:
        # Default to CLI
        sys.exit(main())
