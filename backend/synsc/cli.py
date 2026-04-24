"""CLI for Synsc Context - unified code and paper indexing."""

import argparse
import logging
import sys

import structlog


def configure_logging():
    """Configure structlog for CLI output."""
    # Set stdlib root logger to INFO so structlog's filter_by_level doesn't drop info/debug
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=logging.INFO)
    
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


def cmd_serve_mcp(args: argparse.Namespace) -> int:
    """Start the MCP server (stdio transport)."""
    from synsc.api.mcp_server import run_server
    
    run_server()
    return 0


def cmd_serve_http(args: argparse.Namespace) -> int:
    """Start the HTTP API server."""
    from synsc.api.http_server import run_http_server
    
    run_http_server(host=args.host, port=args.port)
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    """Run the background indexing worker."""
    from synsc.database.connection import init_db
    from synsc.workers.indexing_worker import IndexingWorker
    
    init_db()
    worker = IndexingWorker(
        worker_id=args.worker_id,
        max_workers=args.max_workers,
    )
    worker.run(poll_interval=args.poll_interval)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show server status and statistics."""
    from synsc.config import get_config
    from synsc.database.connection import init_db, get_session
    from synsc.database.models import Repository, CodeChunk, Paper, PaperChunk
    
    config = get_config()
    init_db()
    
    with get_session() as session:
        repo_count = session.query(Repository).count()
        code_chunk_count = session.query(CodeChunk).count()
        paper_count = session.query(Paper).count()
        paper_chunk_count = session.query(PaperChunk).count()
    
    print("\n📊 Synsc Context Status")
    print("=" * 40)
    print(f"\n   Server name: {config.server_name}")
    print(f"\n   Code Indexing:")
    print(f"     Repositories: {repo_count}")
    print(f"     Code chunks: {code_chunk_count}")
    print(f"\n   Paper Indexing:")
    print(f"     Papers: {paper_count}")
    print(f"     Paper chunks: {paper_chunk_count}")
    print(f"\n   API host: {config.api.host}")
    print(f"   API port: {config.api.port}")
    print(f"   Auth required: {config.api.require_auth}")
    print()
    
    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="synsc-context",
        description="Synsc Context - Unified code and paper indexing for AI agents",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start a server")
    serve_subparsers = serve_parser.add_subparsers(dest="server_type", help="Server type")
    
    # serve mcp
    mcp_parser = serve_subparsers.add_parser("mcp", help="Start MCP server (stdio)")
    mcp_parser.set_defaults(func=cmd_serve_mcp)
    
    # serve http
    http_parser = serve_subparsers.add_parser("http", help="Start HTTP API server")
    http_parser.add_argument("--host", default=None, help="Host to bind to")
    http_parser.add_argument("--port", type=int, default=None, help="Port to bind to")
    http_parser.set_defaults(func=cmd_serve_http)
    
    # status command
    status_parser = subparsers.add_parser("status", help="Show server status")
    status_parser.set_defaults(func=cmd_status)
    
    # worker command
    worker_parser = subparsers.add_parser("worker", help="Run background indexing worker")
    worker_parser.add_argument("--worker-id", help="Unique worker identifier")
    worker_parser.add_argument("--max-workers", type=int, default=4, help="Max parallel threads")
    worker_parser.add_argument("--poll-interval", type=float, default=2.0, help="Seconds between job polls")
    worker_parser.set_defaults(func=cmd_worker)
    
    return parser


def main() -> int:
    """Main entry point for CLI."""
    configure_logging()
    
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    if args.command == "serve" and not getattr(args, "server_type", None):
        print("Usage: synsc-context serve {mcp|http}")
        return 1
    
    if hasattr(args, "func"):
        return args.func(args)
    
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
