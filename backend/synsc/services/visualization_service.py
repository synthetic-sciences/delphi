"""Structural JSON graph of an indexed repository.

Surfaces the shape of a repo so agents can navigate without re-grepping the
whole tree:
  - file / language / symbol counts
  - directory rollup (size, languages, symbol density)
  - top exported symbols
  - directory-level import graph (when chunk_relationships are present)

Designed to fit in one MCP response — caps lists at 100 entries by default.
For agents that need more, they can call the underlying tools (search_symbols,
get_directory_structure) with the IDs surfaced here.
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from typing import Any

import structlog

from synsc.database.connection import get_session
from synsc.database.models import (
    Repository,
    RepositoryFile,
    Symbol,
)

logger = structlog.get_logger(__name__)


def visualize_codebase(
    repo_id: str,
    user_id: str | None = None,
    max_dirs: int = 30,
    max_symbols: int = 50,
    max_edges: int = 100,
) -> dict[str, Any]:
    """Return a structural JSON graph for ``repo_id``."""
    with get_session() as session:
        repo = (
            session.query(Repository)
            .filter(Repository.repo_id == repo_id)
            .first()
        )
        if not repo:
            return {
                "success": False,
                "error_code": "not_found",
                "message": f"repo {repo_id} not indexed",
            }
        if not repo.can_user_access(user_id):
            return {
                "success": False,
                "error_code": "forbidden",
                "message": "no access to this repo",
            }

        files = (
            session.query(RepositoryFile)
            .filter(RepositoryFile.repo_id == repo_id)
            .all()
        )
        symbols = (
            session.query(Symbol)
            .filter(Symbol.repo_id == repo_id)
            .all()
        )

        # ---------- directory rollup ----------
        dir_files: dict[str, int] = Counter()
        dir_loc: dict[str, int] = Counter()
        dir_languages: dict[str, Counter] = defaultdict(Counter)
        for f in files:
            d = _dir_of(f.file_path)
            dir_files[d] += 1
            dir_loc[d] += int(f.line_count or 0)
            if f.language:
                dir_languages[d][f.language] += 1

        dirs_sorted = sorted(
            dir_files.items(), key=lambda kv: kv[1], reverse=True
        )[:max_dirs]
        directories = [
            {
                "path": d,
                "files": cnt,
                "lines": dir_loc[d],
                "languages": [
                    {"name": k, "files": v}
                    for k, v in dir_languages[d].most_common(5)
                ],
            }
            for d, cnt in dirs_sorted
        ]

        # ---------- top symbols ----------
        # Prefer exported / public top-level symbols.
        sym_sorted = sorted(
            symbols,
            key=lambda s: (
                0 if s.is_exported else 1,
                0 if s.symbol_type in ("class", "function", "method") else 1,
                len(s.docstring or "") * -1,  # prefer documented
                s.qualified_name,
            ),
        )[:max_symbols]
        top_symbols = [
            {
                "symbol_id": s.symbol_id,
                "name": s.name,
                "qualified_name": s.qualified_name,
                "symbol_type": s.symbol_type,
                "is_exported": bool(s.is_exported),
                "is_async": bool(s.is_async),
                "language": s.language,
                "file_id": s.file_id,
                "start_line": s.start_line,
            }
            for s in sym_sorted
        ]

        # ---------- directory-level "module" graph ----------
        # Use ChunkRelationship rows (when present) to infer cross-directory
        # references. Each chunk_relationship of type 'imports' / 'calls'
        # contributes 1 weight to the dir(source) -> dir(target) edge.
        edges = _module_graph_edges(session, repo_id, files, max_edges)

        # ---------- language summary ----------
        langs = Counter(f.language for f in files if f.language)
        total = sum(langs.values()) or 1
        languages = {
            name: round(cnt / total, 3) for name, cnt in langs.most_common(10)
        }

        symbol_types = Counter(s.symbol_type for s in symbols)

        return {
            "success": True,
            "repo_id": repo_id,
            "repo_name": f"{repo.owner}/{repo.name}",
            "summary": {
                "files": len(files),
                "symbols": len(symbols),
                "lines": int(repo.total_lines or 0),
                "languages": languages,
                "symbol_types": dict(symbol_types.most_common()),
            },
            "directories": directories,
            "top_symbols": top_symbols,
            "module_graph": edges,
        }


def _dir_of(path: str | None) -> str:
    if not path:
        return ""
    parent = os.path.dirname(path)
    return parent + "/" if parent else "(root)"


def _module_graph_edges(
    session,
    repo_id: str,
    files: list[RepositoryFile],
    max_edges: int,
) -> list[dict[str, Any]]:
    """Build directory-level edges from chunk_relationships (best-effort).

    Returns ``[{source, target, weight, kinds:[...]}]`` ordered by weight.
    Falls back to an empty list when the chunk_relationships table is empty
    or unavailable.
    """
    try:
        from sqlalchemy import text

        # Map chunk_id -> dir via files table.
        chunk_to_dir = dict(
            session.execute(
                text(
                    """
                    SELECT c.chunk_id, f.file_path
                    FROM code_chunks c
                    JOIN repository_files f ON f.file_id = c.file_id
                    WHERE c.repo_id = :rid
                    """
                ),
                {"rid": repo_id},
            ).all()
        )
        if not chunk_to_dir:
            return []

        rels = session.execute(
            text(
                """
                SELECT source_chunk_id, target_chunk_id, relationship_type, weight
                FROM chunk_relationships
                WHERE source_chunk_id IN (SELECT chunk_id FROM code_chunks WHERE repo_id = :rid)
                  AND target_chunk_id IN (SELECT chunk_id FROM code_chunks WHERE repo_id = :rid)
                LIMIT 5000
                """
            ),
            {"rid": repo_id},
        ).all()
        if not rels:
            return []

        agg: dict[tuple[str, str], dict[str, Any]] = {}
        for r in rels:
            src_dir = _dir_of(chunk_to_dir.get(r.source_chunk_id))
            tgt_dir = _dir_of(chunk_to_dir.get(r.target_chunk_id))
            if not src_dir or not tgt_dir or src_dir == tgt_dir:
                continue
            key = (src_dir, tgt_dir)
            entry = agg.setdefault(
                key,
                {"source": src_dir, "target": tgt_dir, "weight": 0.0, "kinds": Counter()},
            )
            entry["weight"] += float(r.weight or 1.0)
            entry["kinds"][r.relationship_type] += 1

        out = []
        for v in sorted(agg.values(), key=lambda e: e["weight"], reverse=True)[:max_edges]:
            out.append(
                {
                    "source": v["source"],
                    "target": v["target"],
                    "weight": round(v["weight"], 2),
                    "kinds": dict(v["kinds"]),
                }
            )
        return out
    except Exception as exc:
        logger.debug("visualize: module graph failed", error=str(exc))
        return []
