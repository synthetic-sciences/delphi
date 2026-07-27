"""CLI for Synsc Context - unified code and paper indexing."""

import argparse
import json
import logging
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

import structlog

if TYPE_CHECKING:
    from synsc.client import SynscClient


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


def _api_client(args: argparse.Namespace) -> "SynscClient":
    from synsc.client import SynscAPIError, SynscClient

    try:
        return SynscClient(base_url=getattr(args, "api_url", None))
    except ValueError as exc:
        raise SynscAPIError(0, str(exc)) from None


def cmd_workspace(args: argparse.Namespace) -> int:
    """Show one safe snapshot of providers, connectors, research, and contexts."""

    with _api_client(args) as client:
        workspace = client.workspace()
    if args.json:
        print(json.dumps(workspace, sort_keys=True))
        return 0
    print("RESOURCE\tCOUNT")
    for key in (
        "providers",
        "connector_providers",
        "connectors",
        "research_sessions",
        "context_sessions",
    ):
        print(f"{key}\t{len(workspace[key])}")
    return 0


def cmd_contexts_list(args: argparse.Namespace) -> int:
    """List reproducible context sessions."""

    with _api_client(args) as client:
        sessions = client.list_context_sessions(
            limit=args.limit,
            include_expired=args.include_expired,
        )
    if args.json:
        print(json.dumps({"sessions": sessions}, sort_keys=True))
        return 0
    print("SESSION\tSTATUS\tVERSION\tREVISION\tNAME")
    for session in sessions:
        print(
            f"{session.get('session_id', '')}\t"
            f"{session.get('status', '')}\t"
            f"{session.get('write_version', '')}\t"
            f"{session.get('current_revision', '')}\t"
            f"{session.get('name', '')}"
        )
    return 0


def cmd_contexts_show(args: argparse.Namespace) -> int:
    """Show one authorized context revision."""

    with _api_client(args) as client:
        context = client.get_context_session(
            args.session_id,
            revision=args.revision,
        )
    print(json.dumps(context, sort_keys=True, indent=None if args.json else 2))
    return 0


def cmd_contexts_create(args: argparse.Namespace) -> int:
    """Create a reproducible context session from pinned snapshots."""

    with _api_client(args) as client:
        context = client.create_context_session(
            name=args.name,
            objective=args.objective,
            snapshot_ids=args.snapshot_ids or [],
            token_budget=args.token_budget,
            sharing_policy=args.sharing_policy,
        )
    print(json.dumps(context, sort_keys=True, indent=None if args.json else 2))
    return 0


def cmd_contexts_handoff(args: argparse.Namespace) -> int:
    """Create a linked child context from the current parent revision."""

    with _api_client(args) as client:
        context = client.handoff_context_session(
            args.session_id,
            name=args.name,
            objective=args.objective,
            handoff_note=args.note,
            token_budget=args.token_budget,
            sharing_policy=args.sharing_policy,
        )
    print(json.dumps(context, sort_keys=True, indent=None if args.json else 2))
    return 0


def cmd_contexts_export(args: argparse.Namespace) -> int:
    """Export one authorized context revision."""

    with _api_client(args) as client:
        context = client.export_context_session(
            args.session_id,
            revision=args.revision,
        )
    print(json.dumps(context, sort_keys=True, indent=None if args.json else 2))
    return 0


def cmd_connectors_list(args: argparse.Namespace) -> int:
    """List encrypted connector sources without configuration secrets."""

    with _api_client(args) as client:
        connectors = client.list_connectors(
            provider=args.provider,
            limit=args.limit,
        )
    if args.json:
        print(json.dumps({"connectors": connectors}, sort_keys=True))
        return 0
    print("SOURCE\tPROVIDER\tSTATUS\tNAME")
    for source in connectors:
        source_status = "enabled" if source.get("enabled", False) else "disabled"
        print(
            f"{source.get('source_id', '')}\t"
            f"{source.get('provider', '')}\t"
            f"{source_status}\t"
            f"{source.get('display_name', '')}"
        )
    return 0


def cmd_connectors_sync(args: argparse.Namespace) -> int:
    """Queue an incremental connector synchronization."""

    with _api_client(args) as client:
        result = client.sync_connector(
            args.source_id,
            priority=args.priority,
        )
    print(json.dumps(result, sort_keys=True, indent=None if args.json else 2))
    return 0


def _add_api_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--api-url",
        help="Context service URL (defaults to SYNSC_API_URL or localhost)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable output",
    )


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

    workspace_parser = subparsers.add_parser(
        "workspace",
        help="Summarize providers, connectors, research, and contexts",
    )
    _add_api_options(workspace_parser)
    workspace_parser.set_defaults(func=cmd_workspace)

    contexts_parser = subparsers.add_parser(
        "contexts",
        help="Create, inspect, hand off, and export context sessions",
    )
    context_subparsers = contexts_parser.add_subparsers(
        dest="context_command",
        help="Context command",
    )

    contexts_list_parser = context_subparsers.add_parser("list")
    contexts_list_parser.add_argument("--limit", type=int, default=100)
    contexts_list_parser.add_argument(
        "--include-expired",
        action="store_true",
    )
    _add_api_options(contexts_list_parser)
    contexts_list_parser.set_defaults(func=cmd_contexts_list)

    contexts_show_parser = context_subparsers.add_parser("show")
    contexts_show_parser.add_argument("session_id")
    contexts_show_parser.add_argument("--revision", type=int)
    _add_api_options(contexts_show_parser)
    contexts_show_parser.set_defaults(func=cmd_contexts_show)

    contexts_create_parser = context_subparsers.add_parser("create")
    contexts_create_parser.add_argument("name")
    contexts_create_parser.add_argument("--objective", required=True)
    contexts_create_parser.add_argument(
        "--snapshot-id",
        action="append",
        dest="snapshot_ids",
    )
    contexts_create_parser.add_argument(
        "--token-budget",
        type=int,
        default=8_000,
    )
    contexts_create_parser.add_argument(
        "--sharing-policy",
        choices=("private", "shared"),
        default="private",
    )
    _add_api_options(contexts_create_parser)
    contexts_create_parser.set_defaults(func=cmd_contexts_create)

    contexts_handoff_parser = context_subparsers.add_parser("handoff")
    contexts_handoff_parser.add_argument("session_id")
    contexts_handoff_parser.add_argument("--name", required=True)
    contexts_handoff_parser.add_argument("--objective", required=True)
    contexts_handoff_parser.add_argument("--note", required=True)
    contexts_handoff_parser.add_argument("--token-budget", type=int)
    contexts_handoff_parser.add_argument(
        "--sharing-policy",
        choices=("private", "shared"),
        default="private",
    )
    _add_api_options(contexts_handoff_parser)
    contexts_handoff_parser.set_defaults(func=cmd_contexts_handoff)

    contexts_export_parser = context_subparsers.add_parser("export")
    contexts_export_parser.add_argument("session_id")
    contexts_export_parser.add_argument("--revision", type=int)
    _add_api_options(contexts_export_parser)
    contexts_export_parser.set_defaults(func=cmd_contexts_export)

    connectors_parser = subparsers.add_parser(
        "connectors",
        help="List and synchronize connector sources",
    )
    connector_subparsers = connectors_parser.add_subparsers(
        dest="connector_command",
        help="Connector command",
    )

    connectors_list_parser = connector_subparsers.add_parser("list")
    connectors_list_parser.add_argument("--provider")
    connectors_list_parser.add_argument("--limit", type=int, default=100)
    _add_api_options(connectors_list_parser)
    connectors_list_parser.set_defaults(func=cmd_connectors_list)

    connectors_sync_parser = connector_subparsers.add_parser("sync")
    connectors_sync_parser.add_argument("source_id")
    connectors_sync_parser.add_argument(
        "--priority",
        type=int,
        default=0,
    )
    _add_api_options(connectors_sync_parser)
    connectors_sync_parser.set_defaults(func=cmd_connectors_sync)
    
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
        try:
            return command(args)
        except Exception as exc:
            from synsc.client import SynscAPIError

            if not isinstance(exc, SynscAPIError):
                raise
            print(f"Context service error: {exc}", file=sys.stderr)
            return 1
    
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
