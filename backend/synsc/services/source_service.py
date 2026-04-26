"""Unified source-dispatch layer.

P0 surface: `unified_retrieve` (powers research).
P1 surface: adds unified index/search/list endpoints.
P2 surface: adds canonical source_id resolution + docs.
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def _get_search_service(user_id: str | None):
    from synsc.services.search_service import SearchService

    return SearchService(user_id=user_id)


def _get_paper_service(user_id: str):
    from synsc.services.paper_service import PaperService

    return PaperService(user_id=user_id)


def _get_dataset_service(user_id: str):
    from synsc.services.dataset_service import DatasetService

    return DatasetService(user_id=user_id)


def _norm_code_hit(r: dict) -> dict:
    return {
        "source_type": "repo",
        "source_id": r.get("repo_id", ""),
        "chunk_id": r.get("chunk_id", ""),
        "text": r.get("content", ""),
        "score": float(r.get("relevance_score", 0.0)),
        "path": r.get("file_path"),
        "line_no": r.get("start_line"),
        "metadata": {
            "repo_name": r.get("repo_name"),
            "language": r.get("language"),
            "chunk_type": r.get("chunk_type"),
            "end_line": r.get("end_line"),
        },
    }


def _norm_paper_hit(r: dict) -> dict:
    return {
        "source_type": "paper",
        "source_id": r.get("paper_id", ""),
        "chunk_id": r.get("chunk_id", ""),
        "text": r.get("content", ""),
        "score": float(r.get("similarity", 0.0)),
        "path": r.get("section_title"),
        "line_no": r.get("page_number"),
        "metadata": {
            "paper_title": r.get("paper_title"),
            "chunk_type": r.get("chunk_type"),
        },
    }


def _norm_dataset_hit(r: dict) -> dict:
    return {
        "source_type": "dataset",
        "source_id": r.get("dataset_id", ""),
        "chunk_id": r.get("chunk_id", ""),
        "text": r.get("content", r.get("text", "")),
        "score": float(r.get("similarity", r.get("score", 0.0))),
        "path": r.get("section"),
        "line_no": None,
        "metadata": r.get("metadata", {}),
    }


def _any_looks_like_uuid(ids: list[str] | None) -> bool:
    if not ids:
        return False
    return any(len(x) == 36 and x.count("-") == 4 for x in ids)


def unified_retrieve(
    query: str,
    source_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    k: int = 10,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Fan out a query across code / papers / datasets, merge and sort.

    Each branch is best-effort: a failure (missing user_id, service error)
    is logged and the branch contributes zero hits rather than aborting
    the whole call.
    """
    types = set(source_types or ["repo", "paper", "dataset"])
    hits: list[dict] = []

    if "repo" in types:
        try:
            res = _get_search_service(user_id).search_code(
                query=query,
                repo_ids=source_ids if _any_looks_like_uuid(source_ids) else None,
                top_k=k,
                user_id=user_id,
            )
            for r in res.get("results", []):
                hits.append(_norm_code_hit(r))
        except Exception as exc:
            logger.warning("unified_retrieve: code branch failed", error=str(exc))

    if "paper" in types and user_id:
        try:
            res = _get_paper_service(user_id).search_papers(query=query, top_k=k)
            for r in res.get("results", []):
                hits.append(_norm_paper_hit(r))
        except Exception as exc:
            logger.warning("unified_retrieve: paper branch failed", error=str(exc))

    if "dataset" in types and user_id:
        try:
            res = _get_dataset_service(user_id).search_datasets(query=query, top_k=k)
            for r in res.get("results", []):
                hits.append(_norm_dataset_hit(r))
        except Exception as exc:
            logger.warning("unified_retrieve: dataset branch failed", error=str(exc))

    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:k]
