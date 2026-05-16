"""Unified source-dispatch layer.

P0 surface: `unified_retrieve` (powers research).
P1 surface: adds unified index/search/list endpoints.
P2 surface: adds canonical source_id resolution + docs.
"""
from __future__ import annotations

import hashlib
import re
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
        "trust_score": float(r.get("trust_score") or 0.0),
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


def _norm_docs_hit(r: dict) -> dict:
    return {
        "source_type": "docs",
        "source_id": r.get("docs_id", ""),
        "chunk_id": r.get("chunk_id", ""),
        "text": r.get("content", ""),
        "score": float(r.get("similarity", 0.0)),
        "path": r.get("heading") or r.get("page_url"),
        "line_no": None,
        "metadata": {
            "page_url": r.get("page_url"),
            "docs_url": r.get("docs_url"),
            "display_name": r.get("display_name"),
        },
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
    types = set(source_types or ["repo", "paper", "dataset", "docs"])
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

    if "docs" in types and user_id:
        try:
            from synsc.services.docs_service import get_docs_service

            res = get_docs_service(user_id=user_id).search_docs(query=query, top_k=k)
            for r in res.get("results", []):
                hits.append(_norm_docs_hit(r))
        except Exception as exc:
            logger.warning("unified_retrieve: docs branch failed", error=str(exc))

    # Apply per-source trust boost so high-authority sources tie-break above
    # low-authority ones at the same retrieval score. Boost is small (max
    # +0.1) so it never overwhelms semantic relevance.
    hits = _attach_trust_scores(hits)
    hits.sort(
        key=lambda h: (
            h["score"] + 0.1 * float(h.get("trust_score") or 0.0),
            h.get("trust_score") or 0.0,
        ),
        reverse=True,
    )
    return hits[:k]


def _attach_trust_scores(hits: list[dict]) -> list[dict]:
    """Backfill trust_score on hits by fetching the source row.

    One DB call per distinct source_id+source_type. Cheap enough at k<=100.
    """
    if not hits:
        return hits

    need = {
        (h.get("source_type"), h.get("source_id"))
        for h in hits
        if not h.get("trust_score") and h.get("source_id")
    }
    if not need:
        return hits

    scores: dict[tuple[str, str], float] = {}
    try:
        from synsc.database.connection import get_session
        from synsc.database.models import (
            DocumentationSource,
            Paper,
            Repository,
        )

        with get_session() as session:
            repo_ids = [sid for (stype, sid) in need if stype == "repo"]
            paper_ids = [sid for (stype, sid) in need if stype == "paper"]
            docs_ids = [sid for (stype, sid) in need if stype == "docs"]
            if repo_ids:
                for r in (
                    session.query(Repository)
                    .filter(Repository.repo_id.in_(repo_ids))
                    .all()
                ):
                    scores[("repo", str(r.repo_id))] = _trust_score(
                        r.repo_metadata
                    )
            if paper_ids:
                for p in (
                    session.query(Paper)
                    .filter(Paper.paper_id.in_(paper_ids))
                    .all()
                ):
                    scores[("paper", str(p.paper_id))] = _trust_score(
                        getattr(p, "paper_metadata", None)
                    )
            if docs_ids:
                for d in (
                    session.query(DocumentationSource)
                    .filter(DocumentationSource.docs_id.in_(docs_ids))
                    .all()
                ):
                    # Docs trust is conservative — explicit metadata only,
                    # no star/citation proxy available.
                    md = getattr(d, "doc_metadata", None) or getattr(
                        d, "metadata", None
                    )
                    scores[("docs", str(d.docs_id))] = _trust_score(md)
    except Exception as exc:
        logger.debug("trust: backfill failed", error=str(exc))
        return hits

    for h in hits:
        if h.get("trust_score"):
            continue
        h["trust_score"] = scores.get(
            (h.get("source_type"), h.get("source_id")), 0.0
        )
    return hits


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

    ``source_ids`` may be canonical UUIDs or any of the legacy aliases
    accepted by ``resolve_source_id`` (arxiv IDs, ``hf:<id>``, ``owner/repo``,
    ``https://github.com/owner/repo``, docs URLs). Aliases that don't resolve
    are dropped with a warning rather than failing the whole call.

    Deduplicates by SHA-256 of the hit text; returns up to k results sorted
    by score descending.
    """
    normalized = normalize_mode(mode)

    if normalized == "web":
        return _web_search_stub(query, k)

    resolved_ids: list[str] | None = None
    if source_ids:
        resolved_ids = []
        for raw in source_ids:
            try:
                uid, _stype = resolve_source_id(raw, user_id=user_id)
                resolved_ids.append(uid)
            except ValueError as exc:
                logger.warning(
                    "unified_search: dropping unresolvable source_id",
                    raw=raw,
                    error=str(exc),
                )

    hits = unified_retrieve(
        query=query,
        source_ids=resolved_ids,
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


def _normalize_index_response(
    *,
    source_type: str,
    res: dict,
    id_key: str,
    external_ref: str,
    default_status: str = "indexed",
) -> dict:
    """Translate a per-type indexer response into the unified envelope.

    Reflects the underlying ``success`` flag in the outer ``status`` so the
    HTTP layer can map a service-side failure to an HTTP error status code
    instead of falsely reporting 200 / status='indexed'.
    """
    if not res.get("success", True):
        return {
            "source_id": res.get(id_key, "") or "",
            "source_type": source_type,
            "status": "error",
            "external_ref": external_ref,
            "error": res.get("error") or res.get("message") or "indexing failed",
            "raw": res,
        }
    return {
        "source_id": res.get(id_key, "") or "",
        "source_type": source_type,
        "status": res.get("status", default_status),
        "external_ref": external_ref,
        "raw": res,
    }


def index_source(
    source_type: str,
    url: str,
    display_name: str | None = None,
    options: dict | None = None,
    user_id: str | None = None,
) -> dict:
    """Dispatch to the per-type indexer and normalize the response.

    Returns ``{source_id, source_type, status, external_ref, raw}``. On
    failure the envelope carries ``status='error'`` plus an ``error`` field
    so the HTTP endpoint can surface 5xx with a useful message rather than
    pretending the index succeeded.
    """
    opts = options or {}

    if source_type == "repo":
        res = _get_indexing_service(user_id).index_repository(
            url=url,
            # Pass None when caller didn't set a branch so default-branch
            # detection runs against the GitHub API.
            branch=opts.get("branch"),
            user_id=user_id,
            deep_index=bool(opts.get("deep_index", False)),
            force_reindex=bool(opts.get("force_reindex", False)),
            quality_mode=opts.get("quality_mode"),
            include_tests=opts.get("include_tests"),
            include_docs=opts.get("include_docs"),
            include_examples=opts.get("include_examples"),
        )
        return _normalize_index_response(
            source_type="repo",
            res=res,
            id_key="repo_id",
            external_ref=url,
            default_status="pending",
        )

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

        return _normalize_index_response(
            source_type="paper",
            res=res,
            id_key="paper_id",
            external_ref=ext_ref,
        )

    if source_type == "dataset":
        if not user_id:
            raise ValueError("dataset indexing requires an authenticated user")

        from synsc.core.huggingface_client import HuggingFaceError, parse_hf_dataset_id

        try:
            hf_id = parse_hf_dataset_id(url)
        except HuggingFaceError:
            hf_id = url.strip()

        res = _get_dataset_service(user_id).index_dataset(hf_id)
        return _normalize_index_response(
            source_type="dataset",
            res=res,
            id_key="dataset_id",
            external_ref=hf_id,
        )

    if source_type == "docs":
        if not user_id:
            raise ValueError("docs indexing requires an authenticated user")
        from synsc.services.docs_service import get_docs_service

        svc = get_docs_service(user_id=user_id)
        res = svc.index_docs(
            url=url,
            display_name=display_name,
            sitemap_url=opts.get("sitemap_url"),
            max_pages=int(opts.get("max_pages", 200)),
            req_delay_s=float(opts.get("req_delay_s", 1.0)),
        )
        return _normalize_index_response(
            source_type="docs",
            res=res,
            id_key="docs_id",
            external_ref=url,
        )

    raise ValueError(f"unsupported source_type: {source_type}")


# ---------------------------------------------------------------------------
# Unified list (GET /v1/sources)
# ---------------------------------------------------------------------------


def list_sources(
    source_type: str | None = None,
    user_id: str | None = None,
) -> list[dict]:
    """List indexed sources, optionally filtered by type."""
    wanted = {source_type} if source_type else {"repo", "paper", "dataset", "docs"}
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

    if "docs" in wanted and user_id:
        try:
            from synsc.services.docs_service import get_docs_service

            for d in get_docs_service(user_id=user_id).list_docs():
                out.append(
                    {
                        "source_id": d.get("docs_id", ""),
                        "source_type": "docs",
                        "display_name": d.get("display_name") or d.get("url", ""),
                        "external_ref": d.get("url", ""),
                        "status": "indexed",
                        "created_at": d.get("indexed_at"),
                    }
                )
        except Exception as exc:
            logger.warning("list_sources: docs branch failed", error=str(exc))

    return out


# ---------------------------------------------------------------------------
# Canonical source_id resolver (P2)
# ---------------------------------------------------------------------------


_ARXIV_RE = re.compile(r"^(?:arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)$", re.IGNORECASE)
_GITHUB_URL_RE = re.compile(
    r"^(?:https?://)?github\.com/([^/\s]+)/([^/\s#?]+)(?:[/?#].*)?$",
    re.IGNORECASE,
)
_OWNER_REPO_RE = re.compile(r"^([^/\s]+)/([^/\s]+)$")
_HF_PREFIX_RE = re.compile(r"^hf:(.+)$", re.IGNORECASE)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _is_uuid(s: str) -> bool:
    return bool(_UUID_RE.match(s or ""))


def _lookup_source_type_by_uuid(uid: str) -> str | None:
    """Detect which table a UUID belongs to via SQLAlchemy lookups."""
    from synsc.database.connection import get_session
    from synsc.database.models import (
        DocumentationSource,
        Paper,
        Repository,
    )

    try:
        with get_session() as session:
            if (
                session.query(Repository)
                .filter(Repository.repo_id == uid)
                .first()
            ):
                return "repo"
            if (
                session.query(Paper)
                .filter(Paper.paper_id == uid)
                .first()
            ):
                return "paper"
            # Dataset model lookup via raw SQL — Dataset model not always
            # imported in service layer; raw SELECT keeps it ORM-agnostic.
            from sqlalchemy import text as _text

            row = session.execute(
                _text("SELECT 1 FROM datasets WHERE dataset_id = :did LIMIT 1"),
                {"did": uid},
            ).first()
            if row:
                return "dataset"
            if (
                session.query(DocumentationSource)
                .filter(DocumentationSource.docs_id == uid)
                .first()
            ):
                return "docs"
    except Exception as exc:
        logger.debug("resolver: uuid lookup failed", error=str(exc))
    return None


def _lookup_paper_by_arxiv(arxiv_id: str) -> str | None:
    from synsc.database.connection import get_session
    from synsc.database.models import Paper

    try:
        with get_session() as session:
            row = (
                session.query(Paper.paper_id)
                .filter(Paper.arxiv_id == arxiv_id)
                .first()
            )
            return row[0] if row else None
    except Exception as exc:
        logger.debug("resolver: paper arxiv lookup failed", error=str(exc))
        return None


def _lookup_dataset_by_hf_id(hf_id: str) -> str | None:
    from sqlalchemy import text as _text

    from synsc.database.connection import get_session

    try:
        with get_session() as session:
            row = session.execute(
                _text(
                    "SELECT dataset_id FROM datasets WHERE hf_id = :hf LIMIT 1"
                ),
                {"hf": hf_id},
            ).first()
            return row[0] if row else None
    except Exception as exc:
        logger.debug("resolver: dataset hf lookup failed", error=str(exc))
        return None


def _lookup_repo_by_owner_name(
    owner: str, name: str, user_id: str | None = None
) -> str | None:
    from synsc.database.connection import get_session
    from synsc.database.models import Repository, UserRepository

    try:
        with get_session() as session:
            if user_id:
                row = (
                    session.query(Repository)
                    .join(
                        UserRepository,
                        Repository.repo_id == UserRepository.repo_id,
                    )
                    .filter(
                        Repository.owner == owner,
                        Repository.name == name,
                        UserRepository.user_id == str(user_id),
                    )
                    .first()
                )
                if row:
                    return str(row.repo_id)
            row = (
                session.query(Repository)
                .filter(
                    Repository.owner == owner,
                    Repository.name == name,
                    Repository.is_public == True,  # noqa: E712
                )
                .first()
            )
            return str(row.repo_id) if row else None
    except Exception as exc:
        logger.debug("resolver: repo owner/name lookup failed", error=str(exc))
        return None


def _lookup_docs_by_url(url: str) -> str | None:
    from synsc.database.connection import get_session
    from synsc.database.models import DocumentationSource

    try:
        with get_session() as session:
            row = (
                session.query(DocumentationSource.docs_id)
                .filter(DocumentationSource.url == url)
                .first()
            )
            return row[0] if row else None
    except Exception as exc:
        logger.debug("resolver: docs url lookup failed", error=str(exc))
        return None


def resolve_source_name(
    name: str,
    user_id: str | None = None,
    source_types: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Context7-style name→source resolver.

    Takes a free-form library / repo / dataset / paper name (e.g. ``"fastapi"``,
    ``"transformers"``, ``"Attention is All You Need"``) and returns ranked
    candidates ``{source_id, source_type, display_name, external_ref, trust_score,
    match_quality}`` so the caller can disambiguate before fetching.

    Two-call pattern: ``resolve_source_name(name)`` → ``read_source(source_id)``.

    Ranking signals:
      - exact name match > prefix > substring
      - higher ``trust_score`` (stars/citations/verified) tiebreaks
      - user-owned sources rank above public when scores tie
    """
    if not name or not isinstance(name, str):
        return []

    needle = name.strip().lower()
    wanted = set(source_types or ["repo", "paper", "dataset", "docs"])
    out: list[dict[str, Any]] = []

    if "repo" in wanted:
        out.extend(_resolve_repos_by_name(needle, user_id, limit))
    if "paper" in wanted and user_id:
        out.extend(_resolve_papers_by_name(needle, user_id, limit))
    if "dataset" in wanted and user_id:
        out.extend(_resolve_datasets_by_name(needle, user_id, limit))
    if "docs" in wanted and user_id:
        out.extend(_resolve_docs_by_name(needle, user_id, limit))

    out.sort(
        key=lambda r: (
            -r["match_quality"],
            -float(r.get("trust_score") or 0.0),
            r.get("display_name") or "",
        )
    )
    return out[:limit]


def _match_quality(needle: str, hay: str | None) -> int:
    """4 = exact, 3 = prefix-of-full-string, 2 = prefix-of-some-token, 1 = substring, 0 = miss.

    Distinguishes "fastapi" → ``tiangolo/fastapi`` (token-prefix=2) from
    "api" → ``tiangolo/fastapi`` (substring only=1). Token-prefix beats
    bare substring so users searching for a known name don't lose to
    partial mid-word hits.
    """
    if not hay:
        return 0
    h = hay.lower()
    if h == needle:
        return 4
    if h.startswith(needle):
        return 3
    for tok in re.split(r"[\s/_\-.]+", h):
        if tok and tok.startswith(needle):
            return 2
    if needle in h:
        return 1
    return 0


def _trust_score(metadata: Any | None, fallback: float = 0.0) -> float:
    """Extract a 0..1 trust score from a JSON metadata blob.

    Repos: stars normalized (log10). Papers: citation_count normalized.
    Falls back to ``fallback`` when no signal is present.
    """
    if not metadata:
        return fallback
    if isinstance(metadata, str):
        try:
            import json as _json

            metadata = _json.loads(metadata)
        except Exception:
            return fallback
    if not isinstance(metadata, dict):
        return fallback
    if "trust_score" in metadata:
        try:
            return max(0.0, min(1.0, float(metadata["trust_score"])))
        except Exception:
            pass
    stars = metadata.get("stars") or metadata.get("stargazers_count")
    if stars is not None:
        try:
            import math

            return min(1.0, math.log10(max(1.0, float(stars))) / 6.0)
        except Exception:
            pass
    citations = metadata.get("citation_count") or metadata.get("citations")
    if citations is not None:
        try:
            import math

            return min(1.0, math.log10(max(1.0, float(citations))) / 5.0)
        except Exception:
            pass
    return fallback


def _resolve_repos_by_name(
    needle: str, user_id: str | None, limit: int
) -> list[dict[str, Any]]:
    from synsc.database.connection import get_session
    from synsc.database.models import Repository

    try:
        with get_session() as session:
            q = session.query(Repository).filter(Repository.is_public == True)  # noqa: E712
            rows = q.limit(500).all()
            scored = []
            for r in rows:
                full = f"{r.owner}/{r.name}".lower()
                quality = max(
                    _match_quality(needle, r.name),
                    _match_quality(needle, full),
                )
                if quality == 0:
                    continue
                scored.append(
                    {
                        "source_id": str(r.repo_id),
                        "source_type": "repo",
                        "display_name": f"{r.owner}/{r.name}",
                        "external_ref": r.url,
                        "match_quality": quality,
                        "trust_score": _trust_score(r.repo_metadata),
                        "extra": {
                            "branch": r.branch,
                            "description": r.description,
                        },
                    }
                )
            scored.sort(
                key=lambda x: (-x["match_quality"], -x["trust_score"])
            )
            return scored[:limit]
    except Exception as exc:
        logger.debug("resolve_name: repo branch failed", error=str(exc))
        return []


def _resolve_papers_by_name(
    needle: str, user_id: str, limit: int
) -> list[dict[str, Any]]:
    from synsc.database.connection import get_session
    from synsc.database.models import Paper

    try:
        with get_session() as session:
            rows = session.query(Paper).limit(500).all()
            scored = []
            for p in rows:
                quality = max(
                    _match_quality(needle, p.title),
                    _match_quality(needle, p.arxiv_id),
                )
                if quality == 0:
                    continue
                scored.append(
                    {
                        "source_id": str(p.paper_id),
                        "source_type": "paper",
                        "display_name": p.title or p.arxiv_id or "Untitled",
                        "external_ref": p.arxiv_id or "",
                        "match_quality": quality,
                        "trust_score": _trust_score(
                            getattr(p, "paper_metadata", None)
                        ),
                        "extra": {},
                    }
                )
            scored.sort(
                key=lambda x: (-x["match_quality"], -x["trust_score"])
            )
            return scored[:limit]
    except Exception as exc:
        logger.debug("resolve_name: paper branch failed", error=str(exc))
        return []


def _resolve_datasets_by_name(
    needle: str, user_id: str, limit: int
) -> list[dict[str, Any]]:
    from sqlalchemy import text as _text

    from synsc.database.connection import get_session

    try:
        with get_session() as session:
            rows = session.execute(
                _text(
                    "SELECT dataset_id, hf_id, name FROM datasets LIMIT 500"
                )
            ).all()
            scored = []
            for r in rows:
                quality = max(
                    _match_quality(needle, r.name),
                    _match_quality(needle, r.hf_id),
                )
                if quality == 0:
                    continue
                scored.append(
                    {
                        "source_id": str(r.dataset_id),
                        "source_type": "dataset",
                        "display_name": r.name or r.hf_id,
                        "external_ref": r.hf_id,
                        "match_quality": quality,
                        "trust_score": 0.0,
                        "extra": {},
                    }
                )
            scored.sort(
                key=lambda x: (-x["match_quality"], -x["trust_score"])
            )
            return scored[:limit]
    except Exception as exc:
        logger.debug("resolve_name: dataset branch failed", error=str(exc))
        return []


def _resolve_docs_by_name(
    needle: str, user_id: str, limit: int
) -> list[dict[str, Any]]:
    from synsc.database.connection import get_session
    from synsc.database.models import DocumentationSource

    try:
        with get_session() as session:
            rows = session.query(DocumentationSource).limit(500).all()
            scored = []
            for d in rows:
                quality = max(
                    _match_quality(needle, d.display_name),
                    _match_quality(needle, d.url),
                )
                if quality == 0:
                    continue
                scored.append(
                    {
                        "source_id": str(d.docs_id),
                        "source_type": "docs",
                        "display_name": d.display_name or d.url,
                        "external_ref": d.url,
                        "match_quality": quality,
                        "trust_score": 0.0,
                        "extra": {},
                    }
                )
            scored.sort(
                key=lambda x: (-x["match_quality"], -x["trust_score"])
            )
            return scored[:limit]
    except Exception as exc:
        logger.debug("resolve_name: docs branch failed", error=str(exc))
        return []


def resolve_source_id(raw: str, user_id: str | None = None) -> tuple[str, str]:
    """Resolve a raw source reference to ``(canonical_uuid, source_type)``.

    Accepts:
      - A canonical UUID (type detected via table lookup).
      - ``arxiv:<id>`` or a bare arxiv-looking ID (e.g. ``2301.12345``).
      - ``hf:<id>`` (full HuggingFace dataset ID, may contain ``/``).
      - ``owner/repo`` or ``https://github.com/owner/repo``.
      - A fully-qualified docs URL previously indexed.

    Raises ``ValueError`` if nothing matches.
    """
    if not raw or not isinstance(raw, str):
        raise ValueError(f"could not resolve source_id: {raw!r}")

    candidate = raw.strip()

    if _is_uuid(candidate):
        stype = _lookup_source_type_by_uuid(candidate)
        if stype is None:
            raise ValueError(
                f"could not resolve source_id: unknown UUID {candidate}"
            )
        return candidate, stype

    m = _ARXIV_RE.match(candidate)
    if m:
        arxiv_id = m.group(1)
        paper_uid = _lookup_paper_by_arxiv(arxiv_id)
        if paper_uid:
            return paper_uid, "paper"
        raise ValueError(
            f"could not resolve source_id: arxiv:{arxiv_id} not indexed"
        )

    hf = _HF_PREFIX_RE.match(candidate)
    if hf:
        hf_id = hf.group(1).strip()
        ds_uid = _lookup_dataset_by_hf_id(hf_id)
        if ds_uid:
            return ds_uid, "dataset"
        raise ValueError(
            f"could not resolve source_id: hf:{hf_id} not indexed"
        )

    gh = _GITHUB_URL_RE.match(candidate)
    if gh:
        owner, name = gh.group(1), gh.group(2).removesuffix(".git")
        repo_uid = _lookup_repo_by_owner_name(owner, name, user_id)
        if repo_uid:
            return repo_uid, "repo"
        raise ValueError(
            f"could not resolve source_id: github {owner}/{name} not indexed"
        )

    if candidate.startswith(("http://", "https://")):
        docs_uid = _lookup_docs_by_url(candidate)
        if docs_uid:
            return docs_uid, "docs"
        raise ValueError(
            f"could not resolve source_id: docs url not indexed: {candidate}"
        )

    or_ = _OWNER_REPO_RE.match(candidate)
    if or_:
        owner, name = or_.group(1), or_.group(2)
        repo_uid = _lookup_repo_by_owner_name(owner, name, user_id)
        if repo_uid:
            return repo_uid, "repo"
        raise ValueError(
            f"could not resolve source_id: {owner}/{name} not indexed"
        )

    raise ValueError(f"could not resolve source_id: {candidate}")
