#!/usr/bin/env python3
"""Synsc Context Server - Entry point for MCP and HTTP servers."""

import sys

import structlog

# Configure structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)


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
