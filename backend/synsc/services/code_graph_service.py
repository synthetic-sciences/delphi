"""Code-dependency graph: call edges, caller/callee lookup, blast radius.

This is the code-intelligence surface that separates Delphi from pure-retrieval
context servers. After a repo is indexed we extract call sites from every code
chunk, resolve callee names to symbols in the same repository, and persist
directed edges in ``symbol_references``. Agents can then ask:

- ``who_calls(symbol)``  — direct callers
- ``get_callees(symbol)`` — what a symbol calls (resolved + external)
- ``blast_radius(symbol)`` — transitive callers: "what breaks if I change this?"

Resolution is name-based (like aider's repo-map and sverklo's symbol graph): a
callee ``foo`` resolves to symbols named ``foo`` in the repo, preferring a
same-file match. Unresolved callees (stdlib / third-party) are still recorded
with ``is_resolved=False`` so impact analysis can show external dependencies.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

import structlog

from synsc.database.connection import get_session
from synsc.database.models import (
    CodeChunk,
    Symbol,
    SymbolReference,
)
from synsc.parsing.registry import get_parser_registry

logger = structlog.get_logger(__name__)

# A callee name that resolves to more candidates than this is treated as too
# ambiguous to link confidently — recorded as an unresolved reference instead.
_MAX_AMBIGUOUS_TARGETS = 8
_CALLABLE_TYPES = ("function", "method")


class CodeGraphService:
    """Build and query the per-repository code-dependency graph."""

    def __init__(self, user_id: str | None = None) -> None:
        self.user_id = user_id

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------
    def build_for_repo(self, repo_id: str, session: Any | None = None) -> dict[str, Any]:
        """(Re)build the call graph for one repository.

        Idempotent: deletes existing edges for the repo, then re-extracts from
        the stored code chunks. Safe to call after every (re)index.
        """
        if session is not None:
            return self._build(session, repo_id)
        with get_session() as own_session:
            result = self._build(own_session, repo_id)
            own_session.commit()
            return result

    def _build(self, session: Any, repo_id: str) -> dict[str, Any]:
        registry = get_parser_registry()

        symbols = session.query(Symbol).filter(Symbol.repo_id == repo_id).all()
        if not symbols:
            return {"success": True, "edges": 0, "resolved": 0, "unresolved": 0, "symbols": 0}

        by_id: dict[str, Symbol] = {s.symbol_id: s for s in symbols}
        name_to_ids: dict[str, list[str]] = defaultdict(list)
        file_qual_to_id: dict[tuple[str, str], str] = {}
        file_name_to_id: dict[tuple[str, str], str] = {}
        for s in symbols:
            if s.symbol_type in _CALLABLE_TYPES:
                name_to_ids[s.name].append(s.symbol_id)
            file_qual_to_id[(s.file_id, s.qualified_name)] = s.symbol_id
            file_name_to_id.setdefault((s.file_id, s.name), s.symbol_id)

        chunks = session.query(CodeChunk).filter(CodeChunk.repo_id == repo_id).all()

        seen: set[tuple[str | None, str | None, str]] = set()
        rows: list[dict[str, Any]] = []
        resolved = 0
        unresolved = 0

        for chunk in chunks:
            if not chunk.language:
                continue
            parser = registry.get_parser(chunk.language)
            if parser is None or not hasattr(parser, "extract_calls"):
                continue
            try:
                calls = parser.extract_calls(chunk.content)
            except Exception:
                continue

            for call in calls:
                src_id = file_qual_to_id.get((chunk.file_id, call.caller))
                if src_id is None:
                    src_id = file_name_to_id.get(
                        (chunk.file_id, call.caller.split(".")[-1])
                    )
                line = (chunk.start_line or 1) + max(call.line - 1, 0)

                targets = name_to_ids.get(call.callee, [])
                same_file = [t for t in targets if by_id[t].file_id == chunk.file_id]
                chosen = same_file or targets

                if not chosen or len(chosen) > _MAX_AMBIGUOUS_TARGETS:
                    key = (src_id, None, call.callee)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(
                        {
                            "repo_id": repo_id,
                            "source_symbol_id": src_id,
                            "target_symbol_id": None,
                            "source_file_id": chunk.file_id,
                            "callee_name": call.callee[:255],
                            "reference_type": "calls",
                            "line": line,
                            "is_resolved": False,
                        }
                    )
                    unresolved += 1
                    continue

                for target_id in chosen:
                    if target_id == src_id:
                        continue
                    key = (src_id, target_id, call.callee)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(
                        {
                            "repo_id": repo_id,
                            "source_symbol_id": src_id,
                            "target_symbol_id": target_id,
                            "source_file_id": chunk.file_id,
                            "callee_name": call.callee[:255],
                            "reference_type": "calls",
                            "line": line,
                            "is_resolved": True,
                        }
                    )
                    resolved += 1

        # Rebuild: clear old edges, insert fresh.
        session.query(SymbolReference).filter(
            SymbolReference.repo_id == repo_id
        ).delete(synchronize_session=False)
        if rows:
            session.bulk_insert_mappings(SymbolReference, rows)
        session.flush()

        logger.info(
            "Built code graph",
            repo_id=repo_id,
            edges=len(rows),
            resolved=resolved,
            unresolved=unresolved,
        )
        return {
            "success": True,
            "edges": len(rows),
            "resolved": resolved,
            "unresolved": unresolved,
            "symbols": len(symbols),
        }

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def who_calls(
        self, repo_id: str, symbol: str, limit: int = 50
    ) -> dict[str, Any]:
        """Direct callers of a symbol (resolved by id, qualified name, or name)."""
        with get_session() as session:
            targets = self._resolve_symbols(session, repo_id, symbol)
            if not targets:
                return {"success": False, "error": f"symbol not found: {symbol}"}
            target_ids = [s.symbol_id for s in targets]
            edges = (
                session.query(SymbolReference)
                .filter(
                    SymbolReference.repo_id == repo_id,
                    SymbolReference.target_symbol_id.in_(target_ids),
                    SymbolReference.reference_type == "calls",
                )
                .limit(limit)
                .all()
            )
            callers = self._symbol_payloads(
                session, [e.source_symbol_id for e in edges if e.source_symbol_id]
            )
            return {
                "success": True,
                "symbol": symbol,
                "resolved_to": [self._symbol_brief(s) for s in targets],
                "caller_count": len(callers),
                "callers": callers,
            }

    def get_callees(
        self, repo_id: str, symbol: str, limit: int = 100
    ) -> dict[str, Any]:
        """What a symbol calls — resolved internal symbols plus external names."""
        with get_session() as session:
            sources = self._resolve_symbols(session, repo_id, symbol)
            if not sources:
                return {"success": False, "error": f"symbol not found: {symbol}"}
            source_ids = [s.symbol_id for s in sources]
            edges = (
                session.query(SymbolReference)
                .filter(
                    SymbolReference.repo_id == repo_id,
                    SymbolReference.source_symbol_id.in_(source_ids),
                    SymbolReference.reference_type == "calls",
                )
                .limit(limit)
                .all()
            )
            internal = self._symbol_payloads(
                session, [e.target_symbol_id for e in edges if e.target_symbol_id]
            )
            external = sorted(
                {e.callee_name for e in edges if e.target_symbol_id is None}
            )
            return {
                "success": True,
                "symbol": symbol,
                "resolved_to": [self._symbol_brief(s) for s in sources],
                "internal_callees": internal,
                "external_callees": external,
            }

    def blast_radius(
        self,
        repo_id: str,
        symbol: str,
        max_depth: int = 3,
        max_nodes: int = 100,
    ) -> dict[str, Any]:
        """Transitive callers — the impact set if ``symbol`` changes.

        BFS over reverse (caller) edges up to ``max_depth`` hops, capped at
        ``max_nodes``. Returns impacted symbols with the hop distance, so an
        agent can reason about how far a change ripples.
        """
        with get_session() as session:
            seeds = self._resolve_symbols(session, repo_id, symbol)
            if not seeds:
                return {"success": False, "error": f"symbol not found: {symbol}"}

            # Preload the reverse adjacency (target -> sources) for the repo.
            reverse: dict[str, set[str]] = defaultdict(set)
            edges = (
                session.query(
                    SymbolReference.source_symbol_id,
                    SymbolReference.target_symbol_id,
                )
                .filter(
                    SymbolReference.repo_id == repo_id,
                    SymbolReference.reference_type == "calls",
                    SymbolReference.target_symbol_id.isnot(None),
                    SymbolReference.source_symbol_id.isnot(None),
                )
                .all()
            )
            for source_id, target_id in edges:
                reverse[target_id].add(source_id)

            seed_ids = {s.symbol_id for s in seeds}
            visited = self.bfs_reachable(reverse, seed_ids, max_depth, max_nodes)
            impacted_ids = [sid for sid in visited if sid not in seed_ids]
            impacted = self._symbol_payloads(session, impacted_ids)
            for payload in impacted:
                payload["depth"] = visited.get(payload["symbol_id"], 0)
            impacted.sort(key=lambda p: (p["depth"], p["qualified_name"]))

            return {
                "success": True,
                "symbol": symbol,
                "resolved_to": [self._symbol_brief(s) for s in seeds],
                "impacted_count": len(impacted),
                "max_depth": max_depth,
                "truncated": len(impacted) >= max_nodes,
                "impacted": impacted,
            }

    def graph_stats(self, repo_id: str) -> dict[str, Any]:
        """Edge/resolution counts for a repo's graph (for dashboards / tests)."""
        with get_session() as session:
            total = (
                session.query(SymbolReference)
                .filter(SymbolReference.repo_id == repo_id)
                .count()
            )
            resolved = (
                session.query(SymbolReference)
                .filter(
                    SymbolReference.repo_id == repo_id,
                    SymbolReference.is_resolved.is_(True),
                )
                .count()
            )
            return {
                "success": True,
                "repo_id": repo_id,
                "edges": total,
                "resolved": resolved,
                "unresolved": total - resolved,
            }

    # ------------------------------------------------------------------
    # Pure graph traversal (DB-free, unit-testable)
    # ------------------------------------------------------------------
    @staticmethod
    def bfs_reachable(
        adjacency: dict[str, set[str]],
        seed_ids: set[str],
        max_depth: int,
        max_nodes: int,
    ) -> dict[str, int]:
        """BFS over ``adjacency`` from ``seed_ids``; return node -> hop depth.

        Seeds are depth 0. Stops at ``max_depth`` hops or once ``max_nodes``
        non-seed nodes have been discovered.
        """
        visited: dict[str, int] = dict.fromkeys(seed_ids, 0)
        queue: deque[tuple[str, int]] = deque((sid, 0) for sid in seed_ids)
        discovered = 0
        while queue:
            node_id, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbor in adjacency.get(node_id, ()):
                if neighbor in visited:
                    continue
                visited[neighbor] = depth + 1
                discovered += 1
                if discovered >= max_nodes:
                    return visited
                queue.append((neighbor, depth + 1))
        return visited

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_symbols(
        self, session: Any, repo_id: str, identifier: str
    ) -> list[Symbol]:
        """Resolve a symbol id, qualified name, or bare name to Symbol rows."""
        exact = (
            session.query(Symbol)
            .filter(Symbol.repo_id == repo_id, Symbol.symbol_id == identifier)
            .first()
        )
        if exact is not None:
            return [exact]
        qualified = (
            session.query(Symbol)
            .filter(
                Symbol.repo_id == repo_id,
                Symbol.qualified_name == identifier,
            )
            .all()
        )
        if qualified:
            return qualified
        return (
            session.query(Symbol)
            .filter(Symbol.repo_id == repo_id, Symbol.name == identifier)
            .limit(25)
            .all()
        )

    def _symbol_payloads(self, session: Any, symbol_ids: list[str]) -> list[dict[str, Any]]:
        unique_ids = list(dict.fromkeys(sid for sid in symbol_ids if sid))
        if not unique_ids:
            return []
        rows = (
            session.query(Symbol, Symbol.file_id)
            .filter(Symbol.symbol_id.in_(unique_ids))
            .all()
        )
        from synsc.database.models import RepositoryFile

        file_ids = {s.file_id for s, _ in rows}
        path_by_file = {
            f.file_id: f.file_path
            for f in session.query(RepositoryFile)
            .filter(RepositoryFile.file_id.in_(file_ids))
            .all()
        }
        payloads = []
        for symbol, _ in rows:
            payload = self._symbol_brief(symbol)
            payload["file_path"] = path_by_file.get(symbol.file_id)
            payloads.append(payload)
        return payloads

    @staticmethod
    def _symbol_brief(symbol: Symbol) -> dict[str, Any]:
        return {
            "symbol_id": symbol.symbol_id,
            "name": symbol.name,
            "qualified_name": symbol.qualified_name,
            "symbol_type": symbol.symbol_type,
            "language": symbol.language,
            "start_line": symbol.start_line,
            "end_line": symbol.end_line,
            "signature": symbol.signature,
        }
