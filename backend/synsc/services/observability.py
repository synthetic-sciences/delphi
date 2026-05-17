"""Observability for retrieval and indexing.

Three layers:

1. **Skipped-file logging** during indexing — what was filtered out and why.
2. **Per-result candidate-source logging** during search — which branch
   produced which hit.
3. **"Delphi failed because" classifier** — given a session (search ->
   no useful result -> agent fell back), label the failure mode so we can
   actually fix the right thing instead of guessing.

All three write to the existing ``activity_log`` table with stable
``action`` strings so SQL aggregation is straightforward.
"""
from __future__ import annotations

import contextlib
import json
from typing import Any

import structlog

from synsc.database.connection import get_session
from sqlalchemy import text

logger = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Indexing-time logging
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def log_skipped_files(
    repo_id: str,
    user_id: str | None,
    skip_reasons: dict[str, int],
    total_seen: int,
    total_kept: int,
) -> None:
    """Record one summary row per indexing run instead of one per file.

    A 30k-file repo has tens of thousands of skip events; per-file logging
    explodes the activity_log table for no analytical benefit. We aggregate
    by reason ('extension_not_included', 'pattern_excluded',
    'fast_mode_skip', 'too_large') and write one row.
    """
    try:
        _write(
            user_id=user_id,
            action="indexing_skip_summary",
            resource_type="repository",
            resource_id=repo_id,
            metadata={
                "skip_reasons": skip_reasons,
                "total_seen": total_seen,
                "total_kept": total_kept,
            },
        )
    except Exception as e:
        logger.warning("log_skipped_files failed", error=str(e))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Search-time logging
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def log_search_telemetry(
    user_id: str | None,
    query: str,
    quality_mode: str,
    hybrid_meta: dict | None,
    top_results: list[dict],
    elapsed_ms: float,
) -> None:
    """Log per-search telemetry: which branches contributed, what scored top,
    how many results we returned. Cheap to write, very useful for
    "why did Delphi miss this?" investigations.
    """
    if not user_id:
        return
    summary_top = []
    for r in top_results[:5]:
        summary_top.append(
            {
                "chunk_id": r.get("chunk_id"),
                "file_path": r.get("file_path"),
                "score": r.get("relevance_score") or r.get("similarity"),
                "candidate_sources": r.get("candidate_sources"),
            }
        )
    try:
        _write(
            user_id=user_id,
            action="search_telemetry",
            resource_type="repository",
            query=query,
            duration_ms=int(elapsed_ms),
            results_count=len(top_results),
            metadata={
                "quality_mode": quality_mode,
                "hybrid": hybrid_meta,
                "top": summary_top,
            },
        )
    except Exception as e:
        logger.warning("log_search_telemetry failed", error=str(e))


def log_chunk_used(
    user_id: str | None,
    chunk_id: str,
    query_id: str | None = None,
) -> None:
    """Mark a chunk as 'used' in a downstream answer.

    Agents call this (or it's stamped automatically when ``get_context`` /
    ``get_file`` is called for a chunk that came out of search) so we can
    measure used-vs-returned and learn which retrieval branches are
    actually pulling weight.
    """
    if not user_id or not chunk_id:
        return
    try:
        _write(
            user_id=user_id,
            action="chunk_used",
            resource_type="chunk",
            resource_id=chunk_id,
            metadata={"query_id": query_id},
        )
    except Exception:
        pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 'Delphi failed because' classifier
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# Stable failure-mode codes. Agents (or the human running a benchmark) call
# ``classify_failure`` with a description and we tag it. The codes are
# stable so we can aggregate over time.
FAILURE_MODES = {
    "no_hits": "search_returned_zero_results",
    "wrong_repo": "answer_came_from_unindexed_repo",
    "filtered_by_pattern": "intended_file_was_skipped_during_indexing",
    "stale_index": "indexed_commit_is_behind_remote",
    "small_chunk_dropped": "small_but_useful_chunk_dropped_by_min_chunk_threshold",
    "symbol_not_extracted": "language_parser_missing_or_failed",
    "no_test_link": "no_test_chunk_mentions_the_symbol_returned",
    "rerank_unavailable": "reranker_failed_to_load_falling_back_to_vector",
    "embedding_drift": "query_embedding_mismatch_with_indexed_model",
    "branch_mismatch": "queried_branch_was_not_the_indexed_branch",
    "private_repo_token": "github_token_missing_or_expired_for_private_repo",
    "unknown": "uncategorized",
}


def classify_failure(
    description: str,
    user_id: str | None = None,
    query: str | None = None,
    repo_id: str | None = None,
) -> dict[str, Any]:
    """Best-effort failure classification.

    Heuristic — we keyword-match the description against a few known
    failure modes. The classifier improves when more sessions feed it; for
    now it's a starting set covering the categories from the diagnosis.

    Returns ``{"code": <key>, "message": <human-readable>}``.
    """
    desc = (description or "").lower()
    code = "unknown"

    if any(k in desc for k in ("no result", "zero hit", "empty result", "nothing returned")):
        code = "no_hits"
    elif "stale" in desc or "outdated" in desc or "old commit" in desc:
        code = "stale_index"
    elif "skipped" in desc or "filtered out" in desc or "excluded" in desc:
        code = "filtered_by_pattern"
    elif "rerank" in desc and ("fail" in desc or "unavail" in desc):
        code = "rerank_unavailable"
    elif "small" in desc and "chunk" in desc:
        code = "small_chunk_dropped"
    elif "parser" in desc or "tree-sitter" in desc:
        code = "symbol_not_extracted"
    elif "branch" in desc and "wrong" in desc:
        code = "branch_mismatch"
    elif "token" in desc and ("github" in desc or "private" in desc):
        code = "private_repo_token"
    elif "embedding model" in desc or "dimension mismatch" in desc:
        code = "embedding_drift"
    elif "no test" in desc:
        code = "no_test_link"

    payload = {"code": code, "message": FAILURE_MODES[code]}
    try:
        _write(
            user_id=user_id,
            action="failure_classification",
            resource_type="repository",
            resource_id=repo_id,
            query=query,
            metadata={"code": code, "description": description},
        )
    except Exception:
        pass
    return payload


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Internal — write into activity_log
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _write(
    *,
    user_id: str | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    query: str | None = None,
    results_count: int | None = None,
    duration_ms: int | None = None,
    metadata: dict | None = None,
) -> None:
    """Best-effort insert into activity_log. Fails silently."""
    if not user_id:
        return
    with contextlib.suppress(Exception), get_session() as session:
        session.execute(
            text(
                "INSERT INTO activity_log "
                "(user_id, action, resource_type, resource_id, query, "
                " results_count, duration_ms, metadata) "
                "VALUES (:uid, :action, :rtype, :rid, :query, :rcnt, :dur, :meta)"
            ),
            {
                "uid": user_id,
                "action": action,
                "rtype": resource_type,
                "rid": resource_id,
                "query": query,
                "rcnt": results_count,
                "dur": duration_ms,
                "meta": json.dumps(metadata) if metadata else None,
            },
        )
        session.commit()
