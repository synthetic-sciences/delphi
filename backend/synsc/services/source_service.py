"""Unified source-dispatch layer.

P0 surface: `unified_retrieve` (powers research).
P1 surface: adds unified index/search/list endpoints.
P2 surface: adds canonical source_id resolution + docs.
"""
from __future__ import annotations

import hashlib
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


# ---------------------------------------------------------------------------
# Unified search (precise / thorough / web) with Nia-compatibility aliases
# ---------------------------------------------------------------------------

_MODE_ALIASES = {
    "targeted": "precise",
    "universal": "thorough",
    "precise": "precise",
    "thorough": "thorough",
    "web": "web",
}


def normalize_mode(mode: str) -> str:
    """Resolve Nia-compatibility aliases. Raises ValueError on unknown modes."""
    m = _MODE_ALIASES.get(mode)
    if m is None:
        raise ValueError(f"unsupported search mode: {mode}")
    return m


def unified_search(
    query: str,
    source_ids: list[str] | None = None,
    source_types: list[str] | None = None,
    k: int = 10,
    mode: str = "precise",
    user_id: str | None = None,
) -> dict:
    """Unified search across code + papers + datasets.

    Aliases: targeted -> precise, universal -> thorough.
    Modes: precise, thorough, web.

    Deduplicates by SHA-256 of the hit text; returns up to k results sorted
    by score descending.
    """
    normalized = normalize_mode(mode)

    if normalized == "web":
        return _web_search_stub(query, k)

    hits = unified_retrieve(
        query=query,
        source_ids=source_ids,
        source_types=source_types,
        k=max(k * 2, 20),
        user_id=user_id,
    )

    seen: set[str] = set()
    out: list[dict] = []
    for h in hits:
        digest = hashlib.sha256(
            (h.get("text") or "").strip().encode("utf-8")
        ).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        out.append(h)
        if len(out) >= k:
            break

    return {"results": out, "total": len(out), "mode_applied": normalized}


def _web_search_stub(query: str, k: int) -> dict:
    """Stub for web-mode search. Real provider wiring is a P2 follow-up."""
    logger.info("unified_search: web mode stub returned empty", query=query)
    return {
        "results": [],
        "total": 0,
        "mode_applied": "web",
        "notice": "web mode not yet implemented",
    }


# ---------------------------------------------------------------------------
# Unified index dispatch (POST /v1/sources)
# ---------------------------------------------------------------------------


def _get_indexing_service(user_id: str | None):
    from synsc.services.indexing_service import IndexingService

    return IndexingService(user_id=user_id)


def index_source(
    source_type: str,
    url: str,
    display_name: str | None = None,
    options: dict | None = None,
    user_id: str | None = None,
) -> dict:
    """Dispatch to the per-type indexer and normalize the response.

    Returns ``{source_id, source_type, status, external_ref, raw}`` where
    ``raw`` carries the full per-type response for callers that need more.
    """
    opts = options or {}

    if source_type == "repo":
        res = _get_indexing_service(user_id).index_repository(
            url=url,
            branch=opts.get("branch", "main"),
            user_id=user_id,
            deep_index=bool(opts.get("deep_index", False)),
        )
        return {
            "source_id": res.get("repo_id", ""),
            "source_type": "repo",
            "status": res.get("status", "pending"),
            "external_ref": url,
            "raw": res,
        }

    if source_type == "paper":
        if not user_id:
            raise ValueError("paper indexing requires an authenticated user")

        import os
        import tempfile

        from synsc.core.arxiv_client import (
            ArxivError,
            download_arxiv_pdf,
            get_arxiv_metadata,
            parse_arxiv_id,
        )

        svc = _get_paper_service(user_id)

        if os.path.isfile(url) and url.lower().endswith(".pdf"):
            res = svc.index_paper(pdf_path=url, source="upload")
            ext_ref = url
        else:
            try:
                arxiv_id = (
                    parse_arxiv_id(url) if "arxiv" in url.lower() else url.strip()
                )
            except ArxivError:
                arxiv_id = url.strip()
            meta = None
            try:
                meta = get_arxiv_metadata(arxiv_id)
            except Exception:
                pass
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                pdf_path = tmp.name
            try:
                download_arxiv_pdf(arxiv_id, pdf_path)
                res = svc.index_paper(
                    pdf_path=pdf_path,
                    source="arxiv",
                    arxiv_id=arxiv_id,
                    arxiv_metadata=meta,
                )
            finally:
                try:
                    os.unlink(pdf_path)
                except OSError:
                    pass
            ext_ref = arxiv_id

        return {
            "source_id": res.get("paper_id", ""),
            "source_type": "paper",
            "status": res.get("status", "indexed"),
            "external_ref": ext_ref,
            "raw": res,
        }

    if source_type == "dataset":
        if not user_id:
            raise ValueError("dataset indexing requires an authenticated user")

        from synsc.core.huggingface_client import HuggingFaceError, parse_hf_dataset_id

        try:
            hf_id = parse_hf_dataset_id(url)
        except HuggingFaceError:
            hf_id = url.strip()

        res = _get_dataset_service(user_id).index_dataset(hf_id)
        return {
            "source_id": res.get("dataset_id", ""),
            "source_type": "dataset",
            "status": res.get("status", "indexed"),
            "external_ref": hf_id,
            "raw": res,
        }

    if source_type == "docs":
        raise NotImplementedError("docs indexer lands in the docs source_type task")

    raise ValueError(f"unsupported source_type: {source_type}")


# ---------------------------------------------------------------------------
# Unified list (GET /v1/sources)
# ---------------------------------------------------------------------------


def list_sources(
    source_type: str | None = None,
    user_id: str | None = None,
) -> list[dict]:
    """List indexed sources, optionally filtered by type."""
    wanted = {source_type} if source_type else {"repo", "paper", "dataset"}
    out: list[dict] = []

    if "repo" in wanted:
        try:
            res = _get_indexing_service(user_id).list_repositories(user_id=user_id)
            for r in res.get("repositories", []):
                out.append(
                    {
                        "source_id": r.get("repo_id", ""),
                        "source_type": "repo",
                        "display_name": f"{r.get('owner', '')}/{r.get('name', '')}",
                        "external_ref": r.get("url", ""),
                        "status": "indexed",
                        "created_at": r.get("indexed_at"),
                    }
                )
        except Exception as exc:
            logger.warning("list_sources: repo branch failed", error=str(exc))

    if "paper" in wanted and user_id:
        try:
            papers = _get_paper_service(user_id).list_papers()
            for p in papers:
                out.append(
                    {
                        "source_id": p.get("paper_id", ""),
                        "source_type": "paper",
                        "display_name": p.get("title", "Untitled"),
                        "external_ref": p.get("arxiv_id") or p.get("pdf_hash", ""),
                        "status": "indexed",
                        "created_at": p.get("indexed_at") or p.get("created_at"),
                    }
                )
        except Exception as exc:
            logger.warning("list_sources: paper branch failed", error=str(exc))

    if "dataset" in wanted and user_id:
        try:
            datasets = _get_dataset_service(user_id).list_datasets()
            for d in datasets:
                out.append(
                    {
                        "source_id": d.get("dataset_id", ""),
                        "source_type": "dataset",
                        "display_name": d.get("name") or d.get("hf_id", ""),
                        "external_ref": d.get("hf_id", ""),
                        "status": "indexed",
                        "created_at": d.get("indexed_at") or d.get("created_at"),
                    }
                )
        except Exception as exc:
            logger.warning("list_sources: dataset branch failed", error=str(exc))

    return out
