"""CLI for Synsc Context - unified code and paper indexing."""

import argparse
import json
import logging
import sys
from collections.abc import Callable
from typing import cast

import structlog


def configure_logging() -> None:
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
    from synsc.database.connection import get_session, init_db
    from synsc.database.models import CodeChunk, Paper, PaperChunk, Repository
    
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
    print("\n   Code Indexing:")
    print(f"     Repositories: {repo_count}")
    print(f"     Code chunks: {code_chunk_count}")
    print("\n   Paper Indexing:")
    print(f"     Papers: {paper_count}")
    print(f"     Paper chunks: {paper_chunk_count}")
    print(f"\n   API host: {config.api.host}")
    print(f"   API port: {config.api.port}")
    print(f"   Auth required: {config.api.require_auth}")
    print()
    
    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    """List registered provider capabilities without constructing them."""

    from synsc.services.provider_service import list_providers

    providers = list_providers()
    if args.json:
        print(json.dumps({"providers": providers}, sort_keys=True))
        return 0

    print("NAME\tEXECUTION\tHEALTH\tCAPABILITIES")
    for provider in providers:
        capabilities = provider.get("capabilities", [])
        capability_text = (
            ",".join(str(item) for item in capabilities)
            if isinstance(capabilities, list)
            else ""
        )
        print(
            f"{provider.get('name', '')}\t"
            f"{provider.get('execution', '')}\t"
            f"{provider.get('health', '')}\t"
            f"{capability_text}"
        )
    return 0


def cmd_policy_check(args: argparse.Namespace) -> int:
    """Evaluate a prospective provider call without executing it."""

    from synsc.services.provider_service import evaluate_egress

    payload = {
        "provider": args.provider,
        "capability": args.capability,
        "classification": args.classification,
        "purpose": args.purpose,
        "fields": args.fields,
        "source_opt_in": args.source_opt_in,
        "one_request_override": args.one_request_override,
    }
    if args.network is not None:
        payload["network"] = args.network
    if args.allowed_providers is not None:
        payload["allowed_providers"] = args.allowed_providers
    decision = evaluate_egress(payload)
    allowed = decision.get("allowed") is True
    if args.json:
        print(json.dumps(decision, sort_keys=True))
    else:
        status = "ALLOWED" if allowed else "DENIED"
        print(
            f"{status}: {decision.get('reason_code', '')} — "
            f"{decision.get('policy_basis', '')}"
        )
    return 0 if allowed else 2


def cmd_snapshots_list(args: argparse.Namespace) -> int:
    """List source snapshots visible to the selected identity."""

    from synsc.snapshots.contracts import SnapshotSourceType
    from synsc.snapshots.service import SnapshotService

    source_type = (
        SnapshotSourceType(args.source_type)
        if args.source_type is not None
        else None
    )
    snapshots = SnapshotService().list(
        user_id=args.user_id,
        source_type=source_type,
        source_id=args.source_id,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps({"snapshots": snapshots}, sort_keys=True))
        return 0

    print("SNAPSHOT\tTYPE\tSOURCE\tVERSION\tITEMS")
    for snapshot in snapshots:
        print(
            f"{snapshot.get('snapshot_id', '')}\t"
            f"{snapshot.get('source_type', '')}\t"
            f"{snapshot.get('source_id', '')}\t"
            f"{snapshot.get('version', '')}\t"
            f"{snapshot.get('item_count', '')}"
        )
    return 0


def cmd_snapshots_show(args: argparse.Namespace) -> int:
    """Show one source snapshot, optionally including copied items."""

    from synsc.snapshots.service import SnapshotService

    snapshot = SnapshotService().get(
        args.snapshot_id,
        user_id=args.user_id,
        include_items=args.include_items,
        item_offset=args.item_offset,
        item_limit=args.item_limit,
    )
    if args.json:
        print(json.dumps(snapshot, sort_keys=True))
        return 0

    print(f"Snapshot: {snapshot.get('snapshot_id', '')}")
    print(f"Source: {snapshot.get('source_type', '')}/{snapshot.get('source_id', '')}")
    print(f"Version: {snapshot.get('version', '')}")
    print(f"Items: {snapshot.get('item_count', 0)}")
    if args.include_items:
        for item in snapshot.get("items", []):
            print(
                f"  [{item.get('ordinal', '')}] "
                f"{item.get('locator', '')}"
            )
    return 0


def cmd_snapshots_capture(args: argparse.Namespace) -> int:
    """Capture the current indexed state as an immutable snapshot."""

    from synsc.snapshots.contracts import SnapshotSourceType
    from synsc.snapshots.service import SnapshotService

    snapshot = SnapshotService().publish(
        SnapshotSourceType(args.source_type),
        args.source_id,
        user_id=args.user_id,
    ).to_dict()
    if args.json:
        print(json.dumps(snapshot, sort_keys=True))
    else:
        print(
            f"Captured snapshot {snapshot.get('snapshot_id', '')} "
            f"for {snapshot.get('source_type', '')}/"
            f"{snapshot.get('source_id', '')}"
        )
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
    worker_parser = subparsers.add_parser(
        "worker",
        help="Run background source-indexing and research worker",
    )
    worker_parser.add_argument("--worker-id", help="Unique worker identifier")
    worker_parser.add_argument("--max-workers", type=int, default=4, help="Max parallel threads")
    worker_parser.add_argument("--poll-interval", type=float, default=2.0, help="Seconds between job polls")
    worker_parser.set_defaults(func=cmd_worker)

    providers_parser = subparsers.add_parser(
        "providers",
        help="List local and optional provider capabilities",
    )
    providers_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable output",
    )
    providers_parser.set_defaults(func=cmd_providers)

    policy_parser = subparsers.add_parser(
        "policy-check",
        help="Evaluate provider egress policy without executing a call",
    )
    policy_parser.add_argument("--provider", required=True)
    policy_parser.add_argument("--capability", required=True)
    policy_parser.add_argument(
        "--network",
        default=None,
        choices=("offline", "local_only", "allowlisted", "online"),
    )
    policy_parser.add_argument("--classification", required=True)
    policy_parser.add_argument("--purpose", required=True)
    policy_parser.add_argument(
        "--field",
        action="append",
        dest="fields",
        required=True,
    )
    policy_parser.add_argument(
        "--allowed-provider",
        action="append",
        dest="allowed_providers",
        default=None,
    )
    policy_parser.add_argument("--source-opt-in", action="store_true")
    policy_parser.add_argument("--one-request-override", action="store_true")
    policy_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable output",
    )
    policy_parser.set_defaults(func=cmd_policy_check)

    snapshots_parser = subparsers.add_parser(
        "snapshots",
        help="Capture and inspect immutable source snapshots",
    )
    snapshot_subparsers = snapshots_parser.add_subparsers(
        dest="snapshot_command",
        help="Snapshot command",
    )
    snapshot_types = ("repo", "paper", "dataset", "docs")

    snapshots_list_parser = snapshot_subparsers.add_parser(
        "list",
        help="List visible snapshots",
    )
    snapshots_list_parser.add_argument(
        "--type",
        choices=snapshot_types,
        dest="source_type",
    )
    snapshots_list_parser.add_argument("--source-id")
    snapshots_list_parser.add_argument("--user-id")
    snapshots_list_parser.add_argument("--limit", type=int, default=100)
    snapshots_list_parser.add_argument("--json", action="store_true")
    snapshots_list_parser.set_defaults(func=cmd_snapshots_list)

    snapshots_show_parser = snapshot_subparsers.add_parser(
        "show",
        help="Show one visible snapshot",
    )
    snapshots_show_parser.add_argument("snapshot_id")
    snapshots_show_parser.add_argument("--user-id")
    snapshots_show_parser.add_argument(
        "--include-items",
        action="store_true",
    )
    snapshots_show_parser.add_argument(
        "--item-offset",
        type=int,
        default=0,
    )
    snapshots_show_parser.add_argument(
        "--item-limit",
        type=int,
        default=100,
    )
    snapshots_show_parser.add_argument("--json", action="store_true")
    snapshots_show_parser.set_defaults(func=cmd_snapshots_show)

    snapshots_capture_parser = snapshot_subparsers.add_parser(
        "capture",
        help="Capture the current indexed source state",
    )
    snapshots_capture_parser.add_argument("source_id")
    snapshots_capture_parser.add_argument(
        "--type",
        choices=snapshot_types,
        dest="source_type",
        required=True,
    )
    snapshots_capture_parser.add_argument("--user-id")
    snapshots_capture_parser.add_argument("--json", action="store_true")
    snapshots_capture_parser.set_defaults(func=cmd_snapshots_capture)
    
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
        command = cast(Callable[[argparse.Namespace], int], args.func)
        return command(args)
    
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
