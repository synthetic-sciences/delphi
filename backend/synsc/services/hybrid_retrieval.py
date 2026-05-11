"""Hybrid retrieval: vector + BM25/full-text + trigram + exact symbol/path lookup.

Pure vector search misses identifier-heavy queries. An agent searching for
``handleAuthCallback`` should hit it on the first try — not get a list of
semantically-similar middleware functions. We fan out across four candidate
sources and union them before reranking.

Candidate sources:
  1. **Vector**: cosine similarity in pgvector (existing path).
  2. **BM25 / full-text**: ``ts_rank_cd`` over the content tsvector column
     (added by migration 004). Captures keyword recall the embedding misses.
  3. **Trigram**: ``pg_trgm.similarity`` over chunk content. Catches
     misspellings and partial identifier matches that BM25 splits.
  4. **Exact symbol**: lookup in the ``symbols`` table by name /
     qualified_name. Pinpoints function/class definitions on the first hit.
  5. **Exact path**: lookup in ``repository_files`` by path or glob.

Each branch produces ``Candidate`` rows; we score-normalize per branch,
union (keyed by chunk_id), then optionally rerank the top 50.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)


# Allow dots inside identifiers so dotted paths like
# ``fastapi.routing.APIRouter`` come through as a single token (matches the
# behavior of the legacy ``_extract_query_symbols`` in search_service.py).
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")


@dataclass
class Candidate:
    """One retrieval candidate, possibly contributed by multiple branches."""

    chunk_id: str
    repo_id: str = ""
    file_id: str = ""
    repo_name: str = ""
    file_path: str = ""
    content: str = ""
    start_line: int = 0
    end_line: int = 0
    chunk_index: int | None = None
    chunk_type: str = "code"
    language: str | None = None
    symbol_names: Any | None = None
    is_public: bool = True
    # per-source contributions, normalized to [0, 1]. The fused score is a
    # weighted sum of these.
    sources: dict[str, float] = field(default_factory=dict)
    fused_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "repo_id": self.repo_id,
            "file_id": self.file_id,
            "repo_name": self.repo_name,
            "file_path": self.file_path,
            "content": self.content,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "chunk_index": self.chunk_index,
            "chunk_type": self.chunk_type,
            "language": self.language,
            "symbol_names": self.symbol_names,
            "is_public": self.is_public,
            # Mirror existing search_service shape so downstream consumers
            # (rerank, mmr, enrichment) work without changes.
            "similarity": self.fused_score,
            # Why-this-matched: surface candidate sources in the result so
            # agents can reason about it (and it's invaluable for debugging).
            "candidate_sources": dict(self.sources),
        }


def extract_identifiers(query: str) -> list[str]:
    """Pull identifier-shaped tokens out of a query.

    Returns CamelCase, snake_case, PascalCase, UPPER_CASE, and dotted
    path identifiers — in first-seen order, de-duplicated, longer than
    2 chars, excluding a small English-word stoplist that overlaps with
    code identifiers but is almost never useful to look up.
    """
    tokens = _IDENTIFIER_RE.findall(query)
    out: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        # Trailing dot from "foo." → strip
        tok = tok.rstrip(".")
        if len(tok) <= 2:
            continue
        # Skip common English verbs/articles that look like identifiers.
        # Kept narrow on purpose — false positives here cost recall on
        # legitimate identifiers like ``set``, ``get``.
        low = tok.lower()
        if low in _STOPWORDS:
            continue
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "how", "does", "what", "this", "that",
    "with", "from", "use", "get", "set", "not", "all", "any",
    "find", "list", "show", "code", "file", "function", "class",
    "method", "where", "which", "when", "why", "into", "via",
    # Additional everyday English words that show up in question form
    # but never as code we want to find by name.
    "work", "works", "working", "does", "doing", "make", "made",
    "want", "need", "needs", "should", "would", "could", "have", "has",
    "had", "been", "are", "was", "were", "will", "can", "may",
    "explain", "tell", "give", "show", "want", "want's",
})


def _user_repo_filter() -> str:
    """SQL fragment that restricts to repos the user has access to."""
    return (
        "INNER JOIN user_repositories ur ON cc.repo_id = ur.repo_id "
        "AND ur.user_id = :user_id "
        "INNER JOIN repositories r ON cc.repo_id = r.repo_id "
        "AND (r.is_public = TRUE OR r.indexed_by = :user_id)"
    )


def bm25_search(
    session: Session,
    query: str,
    user_id: str,
    repo_ids: list[str] | None = None,
    language: str | None = None,
    top_k: int = 50,
) -> list[Candidate]:
    """BM25-style ranking using PostgreSQL's ts_rank_cd over the tsvector
    column added by migration 004.
    """
    if not query.strip():
        return []

    params: dict[str, Any] = {
        "query": " | ".join(extract_identifiers(query)) or query,
        "user_id": user_id,
        "top_k": top_k,
    }
    extra = ""
    if repo_ids:
        ph = ", ".join([f":rid_{i}" for i in range(len(repo_ids))])
        extra += f" AND cc.repo_id IN ({ph})"
        for i, rid in enumerate(repo_ids):
            params[f"rid_{i}"] = rid
    if language:
        extra += " AND cc.language = :language"
        params["language"] = language

    sql = text(
        f"""
        SELECT
            cc.chunk_id, cc.repo_id, cc.file_id,
            cc.content, cc.start_line, cc.end_line,
            cc.chunk_index, cc.chunk_type, cc.language, cc.symbol_names,
            rf.file_path,
            r.owner || '/' || r.name AS repo_name,
            r.is_public,
            ts_rank_cd(cc.content_tsv, websearch_to_tsquery('english', :query)) AS score
        FROM code_chunks cc
        {_user_repo_filter()}
        INNER JOIN repository_files rf ON cc.file_id = rf.file_id
        WHERE cc.content_tsv @@ websearch_to_tsquery('english', :query)
        {extra}
        ORDER BY score DESC
        LIMIT :top_k
        """
    )
    try:
        rows = session.execute(sql, params).mappings().all()
    except Exception as e:
        logger.warning("bm25 branch failed", error=str(e))
        return []

    if not rows:
        return []

    # Normalize ts_rank_cd into [0, 1]. ts_rank_cd is unbounded but in practice
    # falls in [0, ~1.0] for common queries; we divide by the top score.
    top_score = max((r["score"] for r in rows), default=1.0) or 1.0
    out: list[Candidate] = []
    for r in rows:
        c = Candidate(
            chunk_id=str(r["chunk_id"]),
            repo_id=str(r["repo_id"]),
            file_id=str(r["file_id"]),
            repo_name=r["repo_name"] or "",
            file_path=r["file_path"] or "",
            content=r["content"] or "",
            start_line=r["start_line"],
            end_line=r["end_line"],
            chunk_index=r["chunk_index"],
            chunk_type=r["chunk_type"] or "code",
            language=r["language"],
            symbol_names=r["symbol_names"],
            is_public=bool(r["is_public"]),
        )
        c.sources["bm25"] = float(r["score"]) / top_score
        out.append(c)
    return out


def trigram_search(
    session: Session,
    query: str,
    user_id: str,
    repo_ids: list[str] | None = None,
    language: str | None = None,
    top_k: int = 50,
) -> list[Candidate]:
    """Trigram similarity over chunk content. Catches partial identifier
    matches and misspellings that BM25 splits.

    pg_trgm similarity returns [0, 1]; we keep that scale.
    """
    if not query.strip():
        return []

    # Use the longest identifier as the trigram needle; pg_trgm degrades
    # quickly on short tokens.
    idents = extract_identifiers(query)
    if not idents:
        return []
    needle = max(idents, key=len)
    if len(needle) < 4:
        return []

    params: dict[str, Any] = {
        "needle": needle,
        "user_id": user_id,
        "top_k": top_k,
    }
    extra = ""
    if repo_ids:
        ph = ", ".join([f":rid_{i}" for i in range(len(repo_ids))])
        extra += f" AND cc.repo_id IN ({ph})"
        for i, rid in enumerate(repo_ids):
            params[f"rid_{i}"] = rid
    if language:
        extra += " AND cc.language = :language"
        params["language"] = language

    sql = text(
        f"""
        SELECT
            cc.chunk_id, cc.repo_id, cc.file_id,
            cc.content, cc.start_line, cc.end_line,
            cc.chunk_index, cc.chunk_type, cc.language, cc.symbol_names,
            rf.file_path,
            r.owner || '/' || r.name AS repo_name,
            r.is_public
        FROM code_chunks cc
        {_user_repo_filter()}
        INNER JOIN repository_files rf ON cc.file_id = rf.file_id
        WHERE cc.content ILIKE '%' || :needle || '%'
        {extra}
        LIMIT :top_k
        """
    )
    try:
        rows = session.execute(sql, params).mappings().all()
    except Exception as e:
        logger.warning("trigram branch failed", error=str(e))
        return []

    out: list[Candidate] = []
    for r in rows:
        c = Candidate(
            chunk_id=str(r["chunk_id"]),
            repo_id=str(r["repo_id"]),
            file_id=str(r["file_id"]),
            repo_name=r["repo_name"] or "",
            file_path=r["file_path"] or "",
            content=r["content"] or "",
            start_line=r["start_line"],
            end_line=r["end_line"],
            chunk_index=r["chunk_index"],
            chunk_type=r["chunk_type"] or "code",
            language=r["language"],
            symbol_names=r["symbol_names"],
            is_public=bool(r["is_public"]),
        )
        # Crude scoring: token coverage. Better than nothing, refined by rerank.
        c.sources["trigram"] = 0.7
        out.append(c)
    return out


def exact_symbol_search(
    session: Session,
    query: str,
    user_id: str,
    repo_ids: list[str] | None = None,
    top_k: int = 25,
) -> list[Candidate]:
    """Look up symbols whose name/qualified_name contains a query identifier,
    then return the chunks overlapping each symbol's line range.
    """
    idents = extract_identifiers(query)
    if not idents:
        return []

    # Use the longest identifier as the primary key; pad with the next two so
    # chains like `Class.method` still hit when only one part is exact.
    needles = idents[:3]
    placeholders = ", ".join([f":n_{i}" for i in range(len(needles))])
    lower_needles = ", ".join([f":nl_{i}" for i in range(len(needles))])

    params: dict[str, Any] = {
        "user_id": user_id,
        "top_k": top_k,
    }
    for i, n in enumerate(needles):
        params[f"n_{i}"] = n
        params[f"nl_{i}"] = n.lower()

    extra = ""
    if repo_ids:
        ph = ", ".join([f":rid_{i}" for i in range(len(repo_ids))])
        extra += f" AND s.repo_id IN ({ph})"
        for i, rid in enumerate(repo_ids):
            params[f"rid_{i}"] = rid

    # Find candidate symbols, then join to overlapping chunks. Exact-name hits
    # rank highest (0.95), case-insensitive partials rank next (0.7).
    sql = text(
        f"""
        WITH user_repos AS MATERIALIZED (
            SELECT repo_id FROM user_repositories WHERE user_id = :user_id
        ),
        matched_symbols AS (
            SELECT s.symbol_id, s.repo_id, s.file_id,
                   s.start_line, s.end_line, s.name, s.qualified_name,
                   CASE
                       WHEN s.name IN ({placeholders}) THEN 0.95
                       WHEN lower(s.name) IN ({lower_needles}) THEN 0.85
                       ELSE 0.7
                   END AS sym_score
            FROM symbols s
            INNER JOIN user_repos ur ON s.repo_id = ur.repo_id
            INNER JOIN repositories r ON s.repo_id = r.repo_id
                AND (r.is_public = TRUE OR r.indexed_by = :user_id)
            WHERE (
                lower(s.name) LIKE '%' || :nl_0 || '%'
                OR lower(s.qualified_name) LIKE '%' || :nl_0 || '%'
            )
            {extra}
            LIMIT :top_k
        )
        SELECT
            cc.chunk_id, cc.repo_id, cc.file_id,
            cc.content, cc.start_line, cc.end_line,
            cc.chunk_index, cc.chunk_type, cc.language, cc.symbol_names,
            rf.file_path,
            r.owner || '/' || r.name AS repo_name,
            r.is_public,
            ms.sym_score
        FROM matched_symbols ms
        INNER JOIN code_chunks cc ON cc.file_id = ms.file_id
            AND cc.start_line <= ms.end_line
            AND cc.end_line >= ms.start_line
        INNER JOIN repository_files rf ON cc.file_id = rf.file_id
        INNER JOIN repositories r ON cc.repo_id = r.repo_id
        ORDER BY ms.sym_score DESC, cc.start_line
        LIMIT :top_k
        """
    )
    try:
        rows = session.execute(sql, params).mappings().all()
    except Exception as e:
        logger.warning("exact symbol branch failed", error=str(e))
        return []

    out: list[Candidate] = []
    for r in rows:
        c = Candidate(
            chunk_id=str(r["chunk_id"]),
            repo_id=str(r["repo_id"]),
            file_id=str(r["file_id"]),
            repo_name=r["repo_name"] or "",
            file_path=r["file_path"] or "",
            content=r["content"] or "",
            start_line=r["start_line"],
            end_line=r["end_line"],
            chunk_index=r["chunk_index"],
            chunk_type=r["chunk_type"] or "code",
            language=r["language"],
            symbol_names=r["symbol_names"],
            is_public=bool(r["is_public"]),
        )
        c.sources["symbol"] = float(r["sym_score"])
        out.append(c)
    return out


def exact_path_search(
    session: Session,
    file_pattern: str,
    user_id: str,
    repo_ids: list[str] | None = None,
    top_k: int = 50,
) -> list[Candidate]:
    """Pull chunks from files matching a pattern. Crucially this happens
    BEFORE vector retrieval, so an exact-file query never has its file
    filtered out by the embedding scorer.
    """
    if not file_pattern:
        return []

    # Translate glob → SQL LIKE
    sql_pattern = (
        file_pattern.replace("*", "%").replace("?", "_")
    )
    if "%" not in sql_pattern and "_" not in sql_pattern:
        sql_pattern = f"%{sql_pattern}%"

    params: dict[str, Any] = {
        "user_id": user_id,
        "pattern": sql_pattern,
        "top_k": top_k,
    }
    extra = ""
    if repo_ids:
        ph = ", ".join([f":rid_{i}" for i in range(len(repo_ids))])
        extra += f" AND cc.repo_id IN ({ph})"
        for i, rid in enumerate(repo_ids):
            params[f"rid_{i}"] = rid

    sql = text(
        f"""
        SELECT
            cc.chunk_id, cc.repo_id, cc.file_id,
            cc.content, cc.start_line, cc.end_line,
            cc.chunk_index, cc.chunk_type, cc.language, cc.symbol_names,
            rf.file_path,
            r.owner || '/' || r.name AS repo_name,
            r.is_public
        FROM code_chunks cc
        {_user_repo_filter()}
        INNER JOIN repository_files rf ON cc.file_id = rf.file_id
        WHERE rf.file_path ILIKE :pattern
        {extra}
        ORDER BY rf.file_path, cc.chunk_index
        LIMIT :top_k
        """
    )
    try:
        rows = session.execute(sql, params).mappings().all()
    except Exception as e:
        logger.warning("path branch failed", error=str(e))
        return []

    out: list[Candidate] = []
    for r in rows:
        c = Candidate(
            chunk_id=str(r["chunk_id"]),
            repo_id=str(r["repo_id"]),
            file_id=str(r["file_id"]),
            repo_name=r["repo_name"] or "",
            file_path=r["file_path"] or "",
            content=r["content"] or "",
            start_line=r["start_line"],
            end_line=r["end_line"],
            chunk_index=r["chunk_index"],
            chunk_type=r["chunk_type"] or "code",
            language=r["language"],
            symbol_names=r["symbol_names"],
            is_public=bool(r["is_public"]),
        )
        c.sources["path"] = 0.8
        out.append(c)
    return out


def vector_to_candidates(raw_results: list[dict]) -> list[Candidate]:
    """Convert pgvector search results into the unified Candidate shape."""
    out: list[Candidate] = []
    if not raw_results:
        return out

    top = max((r.get("similarity", 0.0) for r in raw_results), default=1.0) or 1.0
    for r in raw_results:
        c = Candidate(
            chunk_id=str(r.get("chunk_id", "")),
            repo_id=str(r.get("repo_id", "")),
            file_id=str(r.get("file_id", "")),
            repo_name=r.get("repo_name", ""),
            file_path=r.get("file_path", ""),
            content=r.get("content", ""),
            start_line=r.get("start_line", 0),
            end_line=r.get("end_line", 0),
            chunk_index=r.get("chunk_index"),
            chunk_type=r.get("chunk_type", "code"),
            language=r.get("language"),
            symbol_names=r.get("symbol_names"),
            is_public=r.get("is_public", True),
        )
        c.sources["vector"] = float(r.get("similarity", 0.0)) / top
        out.append(c)
    return out


# Default fusion weights. Vector dominates because it's our most reliable
# signal, but BM25 + symbol provide irreplaceable identifier-recall.
DEFAULT_WEIGHTS = {
    "vector": 0.5,
    "bm25": 0.25,
    "symbol": 0.20,
    "path": 0.15,
    "trigram": 0.05,
}


def fuse_candidates(
    branches: list[list[Candidate]],
    weights: dict[str, float] | None = None,
) -> list[Candidate]:
    """Union candidates by chunk_id and produce a fused score.

    Each branch contributes a normalized [0, 1] score; we sum them weighted
    by ``weights[branch_name]``. A chunk hit by multiple branches gets a
    higher fused score than one hit by a single branch alone — which is
    exactly the reciprocal-rank-fusion intuition adapted to weighted scores.
    """
    weights = weights or DEFAULT_WEIGHTS

    by_chunk: dict[str, Candidate] = {}
    for branch in branches:
        for c in branch:
            existing = by_chunk.get(c.chunk_id)
            if existing is None:
                by_chunk[c.chunk_id] = c
            else:
                # Merge sources — same chunk hit by multiple branches.
                for src, score in c.sources.items():
                    existing.sources[src] = max(existing.sources.get(src, 0.0), score)
                # Take the longest content (some branches don't read content).
                if len(c.content) > len(existing.content):
                    existing.content = c.content

    for c in by_chunk.values():
        c.fused_score = sum(
            weights.get(src, 0.0) * score for src, score in c.sources.items()
        )
        # Multi-source bonus: if a chunk is hit by ≥2 branches, boost it.
        # This is the heart of "did multiple retrievers agree?".
        if len(c.sources) >= 2:
            c.fused_score = min(1.0, c.fused_score * 1.15)
        if len(c.sources) >= 3:
            c.fused_score = min(1.0, c.fused_score * 1.10)

    out = sorted(by_chunk.values(), key=lambda c: c.fused_score, reverse=True)
    return out


def hybrid_retrieve(
    session: Session,
    query: str,
    query_embedding: np.ndarray,
    vector_search_fn,
    user_id: str,
    repo_ids: list[str] | None = None,
    language: str | None = None,
    file_pattern: str | None = None,
    top_k: int = 50,
    enable_bm25: bool = True,
    enable_trigram: bool = True,
    enable_symbol: bool = True,
    enable_path: bool = True,
) -> list[Candidate]:
    """Run all retrieval branches and return fused candidates.

    ``vector_search_fn`` is a callable that accepts the same args as
    ``VectorStore.search`` and returns the raw vector hits. We pass it in
    rather than importing to avoid circular deps with search_service.
    """
    t_start = time.time()
    branches: list[list[Candidate]] = []
    timing: dict[str, float] = {}

    # 1. Vector (always — it's the baseline)
    t = time.time()
    raw_vec = vector_search_fn(
        query_embedding=query_embedding,
        user_id=user_id,
        repo_ids=repo_ids,
        language=language,
        top_k=top_k,
    )
    branches.append(vector_to_candidates(raw_vec))
    timing["vector_ms"] = (time.time() - t) * 1000

    # 2. Path (cheap; goes early so file-anchored queries are stable)
    if enable_path and file_pattern:
        t = time.time()
        branches.append(
            exact_path_search(
                session, file_pattern, user_id, repo_ids, top_k=top_k
            )
        )
        timing["path_ms"] = (time.time() - t) * 1000

    # 3. BM25
    if enable_bm25:
        t = time.time()
        branches.append(
            bm25_search(
                session, query, user_id, repo_ids, language, top_k=top_k
            )
        )
        timing["bm25_ms"] = (time.time() - t) * 1000

    # 4. Exact symbol — biggest precision win for identifier queries
    if enable_symbol:
        t = time.time()
        branches.append(
            exact_symbol_search(
                session, query, user_id, repo_ids, top_k=min(top_k, 25)
            )
        )
        timing["symbol_ms"] = (time.time() - t) * 1000

    # 5. Trigram fallback for misspellings/partials
    if enable_trigram:
        t = time.time()
        branches.append(
            trigram_search(
                session, query, user_id, repo_ids, language, top_k=min(top_k, 25)
            )
        )
        timing["trigram_ms"] = (time.time() - t) * 1000

    fused = fuse_candidates(branches)
    timing["total_ms"] = (time.time() - t_start) * 1000
    timing["candidates"] = len(fused)
    timing["sources"] = {
        "vector": sum(1 for c in fused if "vector" in c.sources),
        "bm25": sum(1 for c in fused if "bm25" in c.sources),
        "symbol": sum(1 for c in fused if "symbol" in c.sources),
        "path": sum(1 for c in fused if "path" in c.sources),
        "trigram": sum(1 for c in fused if "trigram" in c.sources),
    }
    logger.debug("hybrid_retrieve timing", **timing)
    return fused
