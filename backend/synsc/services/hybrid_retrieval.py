"""Hybrid retrieval: vector + BM25/full-text + trigram + exact symbol/path lookup.

Pure vector search misses identifier-heavy queries. An agent searching for
``handleAuthCallback`` should hit it on the first try — not get a list of
semantically-similar middleware functions. We fan out across four candidate
sources and union them before reranking.

Candidate sources:
  1. **Vector**: cosine similarity in pgvector (existing path).
  2. **BM25 / full-text**: ``ts_rank_cd`` over the content tsvector column
     (added by migration 004). Captures keyword recall the embedding misses.
  3. **Trigram**: ``pg_trgm.word_similarity`` over indexed symbol names.
     Catches misspellings and partial identifier matches that BM25 splits.
  4. **Exact symbol**: lookup in the ``symbols`` table by name /
     qualified_name. Pinpoints function/class definitions on the first hit.
  5. **Exact path**: lookup in ``repository_files`` by path or glob.
  6. **Path token** (opt-in): repository-local IDF overlap between query
     tokens and normalized file paths. Recovers terse issue/commit vocabulary
     that appears in a filename but not in chunk content.

Each branch produces ``Candidate`` rows; we score-normalize per branch,
union (keyed by chunk_id), then optionally rerank the top 50.
"""
from __future__ import annotations

import math
import os
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from synsc.services.file_okapi import (
    FILE_OKAPI_B,
    FILE_OKAPI_INDEX_VERSION,
    FILE_OKAPI_K1,
    FILE_OKAPI_QUERY_TERM_CAP,
    tokenize_file_okapi,
)

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
    # Per-source raw contributions, kept for observability and as a tiebreak.
    # These are NOT comparable across branches — see ``fuse_candidates``.
    sources: dict[str, float] = field(default_factory=dict)
    # Best (lowest) rank this chunk reached in each branch, 1-based. This is
    # what fusion actually scores on, because ranks are comparable across
    # branches and raw scores are not.
    source_ranks: dict[str, int] = field(default_factory=dict)
    fused_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
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
            "candidate_ranks": dict(self.source_ranks),
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
    "work", "works", "working", "doing", "make", "made",
    "want", "need", "needs", "should", "would", "could", "have", "has",
    "had", "been", "are", "was", "were", "will", "can", "may",
    "explain", "tell", "give", "want's",
})

_FILE_EXTENSION_TOKENS: frozenset[str] = frozenset({
    "c", "cc", "cfg", "cpp", "cs", "go", "h", "hpp", "java", "js",
    "json", "jsx", "kt", "md", "php", "py", "rb", "rs", "rst", "swift",
    "toml", "ts", "tsx", "vue", "yaml", "yml",
})


def _symbol_search_needles(query: str, *, limit: int = 8) -> list[str]:
    """Choose bounded, symbol-shaped lookup terms from a developer query.

    Diagnostic queries often start with environment variables and prose while
    the useful APIs appear later as dotted expressions such as
    ``click.Option`` or ``ctx.forward``. Prioritize dotted leaf names, then
    snake/camel identifiers, before qualified and plain-text fallbacks.
    File-like tokens such as ``setup.cfg`` are not symbol lookups.
    """
    if limit <= 0:
        return []

    dotted: list[str] = []
    structured: list[str] = []
    plain: list[str] = []
    for identifier in extract_identifiers(query):
        if "." in identifier:
            leaf = identifier.rsplit(".", 1)[-1]
            if leaf.lower() in _FILE_EXTENSION_TOKENS:
                continue
            # Keep each qualified form adjacent to its leaf so the bounded
            # list cannot retain every leaf while dropping its API identity.
            dotted.extend((leaf, identifier))
            continue
        if (
            ("_" in identifier and not identifier.isupper())
            or identifier[0].isupper()
            or any(character.isupper() for character in identifier[1:])
        ):
            structured.append(identifier)
        else:
            plain.append(identifier)

    selected: list[str] = []
    seen: set[str] = set()
    for needle in (*dotted, *structured, *plain):
        normalized = needle.lower()
        if len(needle) <= 2 or normalized in seen:
            continue
        seen.add(normalized)
        selected.append(needle)
        if len(selected) >= limit:
            break
    return selected


def _trigram_search_needles(query: str, *, limit: int = 1) -> list[str]:
    """Select the most code-shaped term for indexed fuzzy content matching."""
    if limit <= 0:
        return []

    code_ranked: list[tuple[float, int, str]] = []
    prose_ranked: list[tuple[float, int, str]] = []
    noisy_fallbacks: list[tuple[float, int, str]] = []
    for order, identifier in enumerate(extract_identifiers(query)):
        is_environment_noise = (
            len(identifier) >= 24
            and identifier.isupper()
            and identifier.count("_") >= 2
        )
        if is_environment_noise:
            # Build environments and test runners often prepend long variable
            # names that are rarer than, but unrelated to, the failing symbol.
            specificity = min(len(identifier), 24) / 24
            noisy_fallbacks.append((2.0 + specificity, order, identifier))
            continue
        values = [identifier]
        if "." in identifier:
            leaf = identifier.rsplit(".", 1)[-1]
            if leaf.lower() in _FILE_EXTENSION_TOKENS:
                continue
            values.append(leaf)
        for value in values:
            code_shape = (
                2.0
                if (
                    "." in value
                    or "_" in value
                    or any(character.isupper() for character in value[1:])
                )
                else 0.0
            )
            specificity = min(len(value), 24) / 24
            ranked_value = (code_shape + specificity, order, value)
            if code_shape:
                code_ranked.append(ranked_value)
            else:
                prose_ranked.append(ranked_value)

    # Prefer clear code identifiers, then long uppercase constants, then plain
    # prose. This suppresses environment noise beside a camel/snake-case
    # symbol without letting words such as "defined" hide a constant typo.
    ranked = code_ranked or noisy_fallbacks or prose_ranked

    selected: list[str] = []
    seen: set[str] = set()
    for _, _, needle in sorted(
        ranked,
        key=lambda item: (-item[0], item[1]),
    ):
        normalized = needle.lower()
        if len(needle) < 4 or normalized in seen:
            continue
        seen.add(normalized)
        selected.append(needle)
        if len(selected) >= limit:
            break
    return selected


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
        "query": " or ".join(extract_identifiers(query)) or query,
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
        ORDER BY score DESC, rf.file_path, cc.chunk_index, cc.repo_id, cc.chunk_id
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
        # Raw ts_rank_cd. Unbounded and not comparable to a cosine score, which
        # is exactly why fusion uses rank position rather than magnitude.
        c.sources["bm25"] = float(r["score"])
        out.append(c)
    return out


def file_diverse_bm25_search(
    session: Session,
    query: str,
    user_id: str,
    repo_ids: list[str] | None = None,
    language: str | None = None,
    top_k: int = 50,
) -> list[Candidate]:
    """Return the best lexical chunk from each of the top distinct files.

    Chunk-level BM25 can spend most of its window on several chunks from one
    large file. This branch uses the same indexed query but collapses matches
    by ``file_id`` before applying ``top_k``, exposing file-diverse lexical
    evidence to fusion without a benchmark-specific final-list quota.
    """
    if not query.strip():
        return []

    params: dict[str, Any] = {
        "query": " or ".join(extract_identifiers(query)) or query,
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
        WITH lexical_chunks AS (
            SELECT
                cc.chunk_id, cc.repo_id, cc.file_id,
                cc.content, cc.start_line, cc.end_line,
                cc.chunk_index, cc.chunk_type, cc.language, cc.symbol_names,
                rf.file_path,
                r.owner || '/' || r.name AS repo_name,
                r.is_public,
                ts_rank_cd(
                    cc.content_tsv,
                    websearch_to_tsquery('english', :query)
                ) AS score
            FROM code_chunks cc
            {_user_repo_filter()}
            INNER JOIN repository_files rf ON cc.file_id = rf.file_id
            WHERE cc.content_tsv @@ websearch_to_tsquery('english', :query)
            {extra}
        ),
        ranked_files AS (
            SELECT
                lexical_chunks.*,
                ROW_NUMBER() OVER (
                    PARTITION BY file_id
                    ORDER BY score DESC, chunk_index, repo_id, chunk_id
                ) AS file_rank
            FROM lexical_chunks
        )
        SELECT
            chunk_id, repo_id, file_id,
            content, start_line, end_line,
            chunk_index, chunk_type, language, symbol_names,
            file_path, repo_name, is_public, score
        FROM ranked_files
        WHERE file_rank = 1
        ORDER BY score DESC, file_path, chunk_index, repo_id, chunk_id
        LIMIT :top_k
        """
    )
    try:
        rows = session.execute(sql, params).mappings().all()
    except Exception as e:
        logger.warning("file-diverse BM25 branch failed", error=str(e))
        return []

    out: list[Candidate] = []
    for row in rows:
        candidate = Candidate(
            chunk_id=str(row["chunk_id"]),
            repo_id=str(row["repo_id"]),
            file_id=str(row["file_id"]),
            repo_name=row["repo_name"] or "",
            file_path=row["file_path"] or "",
            content=row["content"] or "",
            start_line=row["start_line"],
            end_line=row["end_line"],
            chunk_index=row["chunk_index"],
            chunk_type=row["chunk_type"] or "code",
            language=row["language"],
            symbol_names=row["symbol_names"],
            is_public=bool(row["is_public"]),
        )
        candidate.sources["file_bm25"] = float(row["score"])
        out.append(candidate)
    return out


def trigram_search(
    session: Session,
    query: str,
    user_id: str,
    repo_ids: list[str] | None = None,
    language: str | None = None,
    top_k: int = 50,
) -> list[Candidate]:
    """Trigram similarity over chunk symbol names. Catches partial identifier
    matches and misspellings that BM25 splits.

    pg_trgm similarity returns [0, 1]; we keep that scale.
    """
    if not query.strip():
        return []

    needles = _trigram_search_needles(query)
    if not needles:
        return []

    params: dict[str, Any] = {
        "needle": needles[0],
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
            word_similarity(:needle, cc.symbol_names) AS score
        FROM code_chunks cc
        {_user_repo_filter()}
        INNER JOIN repository_files rf ON cc.file_id = rf.file_id
        WHERE :needle <% cc.symbol_names
        {extra}
        ORDER BY score DESC, rf.file_path, cc.chunk_index, cc.repo_id, cc.chunk_id
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
        c.sources["trigram"] = float(r["score"])
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
    needles = _symbol_search_needles(query)
    if not needles:
        return []

    placeholders = ", ".join([f":n_{i}" for i in range(len(needles))])
    lower_needles = ", ".join([f":nl_{i}" for i in range(len(needles))])
    qualified_indices = [
        index for index, needle in enumerate(needles) if "." in needle
    ]
    qualified_placeholders = ", ".join(
        f":n_{index}" for index in qualified_indices
    )
    lower_qualified_placeholders = ", ".join(
        f":nl_{index}" for index in qualified_indices
    )
    exact_qualified_match = (
        f"s.qualified_name IN ({qualified_placeholders})"
        if qualified_indices
        else "FALSE"
    )
    lower_qualified_match = (
        f"lower(s.qualified_name) IN ({lower_qualified_placeholders})"
        if qualified_indices
        else "FALSE"
    )
    match_conditions = " OR ".join(
        (
            f"lower(s.name) LIKE '%' || :nl_{i} || '%' "
            f"OR lower(s.qualified_name) LIKE '%' || :nl_{i} || '%'"
        )
        for i in range(len(needles))
    )

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
                       WHEN {exact_qualified_match} THEN 1.0
                       WHEN {lower_qualified_match} THEN 0.97
                       WHEN s.name IN ({placeholders}) THEN 0.95
                       WHEN lower(s.name) IN ({lower_needles}) THEN 0.85
                       ELSE 0.7
                   END AS sym_score
            FROM symbols s
            INNER JOIN user_repos ur ON s.repo_id = ur.repo_id
            INNER JOIN repositories r ON s.repo_id = r.repo_id
                AND (r.is_public = TRUE OR r.indexed_by = :user_id)
            WHERE ({match_conditions})
            {extra}
            ORDER BY sym_score DESC, s.repo_id, s.file_id,
                     s.start_line, s.symbol_id
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
        ORDER BY ms.sym_score DESC, rf.file_path, cc.chunk_index,
                 cc.repo_id, cc.chunk_id, ms.symbol_id
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


# File extensions worth treating as "the query named a file".
_PATH_EXT_RE = re.compile(
    r"[\w./-]+\.(?:py|pyi|go|rs|java|kt|swift|rb|php|cs|scala|c|cc|cpp|h|hpp|"
    r"m|mm|js|jsx|ts|tsx|vue|svelte|sql|sh|bash|yaml|yml|toml|json|md|proto)\b",
    re.IGNORECASE,
)


def _normalize_path_token(value: str) -> str:
    """Casefold and drop separators so ``grpc_proxy`` matches ``grpcproxy``."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


_PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
PATH_TOKEN_MAX_FILES = 50_000
FILE_OKAPI_WEIGHT = 0.15
FILE_OKAPI_MAX_FILES = 50_000
FILE_OKAPI_CANDIDATES = 50


def _path_tokens(value: str) -> list[str]:
    """Split prose or paths on punctuation, separators, and camel case."""
    value = _ACRONYM_BOUNDARY_RE.sub(r"\1 \2", value)
    value = _CAMEL_BOUNDARY_RE.sub(r"\1 \2", value)
    return [token.lower() for token in _PATH_TOKEN_RE.findall(value)]


def _rank_path_token_files(
    query: str,
    files: list[dict[str, Any]],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    """Rank repository paths by repository-local IDF token overlap.

    The score deliberately mirrors the development diagnostic: repeated query
    terms receive logarithmic weight, path terms use repository-local inverse
    document frequency, and long paths receive square-root normalization.
    """
    if top_k <= 0 or not query.strip() or not files:
        return []

    query_counts = Counter(_path_tokens(query))
    if not query_counts:
        return []

    by_repo: dict[str, list[tuple[dict[str, Any], set[str]]]] = {}
    for row in files:
        path_tokens = set(_path_tokens(str(row.get("file_path") or "")))
        by_repo.setdefault(str(row.get("repo_id") or ""), []).append(
            (row, path_tokens)
        )

    scored: list[tuple[float, str, str, str, dict[str, Any]]] = []
    for repo_id, repo_files in by_repo.items():
        document_frequency = Counter(
            token for _, tokens in repo_files for token in tokens
        )
        repository_size = max(1, len(repo_files))
        for row, path_tokens in repo_files:
            score = sum(
                (1.0 + math.log(count))
                * math.log(
                    (repository_size + 1)
                    / (1 + document_frequency[token])
                    + 1
                )
                for token, count in query_counts.items()
                if token in path_tokens
            ) / max(1.0, math.sqrt(len(path_tokens)))
            if score <= 0:
                continue
            scored.append(
                (
                    -score,
                    repo_id,
                    str(row.get("file_path") or ""),
                    str(row.get("file_id") or ""),
                    row,
                )
            )

    scored.sort(key=lambda item: item[:4])
    ranked: list[dict[str, Any]] = []
    for negative_score, _, _, _, row in scored[:top_k]:
        ranked_row = dict(row)
        ranked_row["path_token_score"] = -negative_score
        ranked.append(ranked_row)
    return ranked


def path_token_search(
    session: Session,
    query: str,
    user_id: str,
    repo_ids: list[str] | None = None,
    language: str | None = None,
    top_k: int = 25,
    max_files: int = PATH_TOKEN_MAX_FILES,
) -> list[Candidate]:
    """Return one representative chunk from paths sharing rare query tokens.

    The branch is intentionally repository-scoped. Pulling every visible path
    for an account-wide query would turn a bounded recall signal into an
    unbounded scan.
    """
    if not repo_ids or top_k <= 0 or max_files <= 0 or not query.strip():
        return []

    params: dict[str, Any] = {
        "user_id": user_id,
        "path_scan_limit": max_files + 1,
    }
    repo_placeholders = ", ".join(
        f":repo_id_{index}" for index in range(len(repo_ids))
    )
    for index, repo_id in enumerate(repo_ids):
        params[f"repo_id_{index}"] = repo_id
    language_filter = ""
    if language:
        language_filter = " AND rf.language = :language"
        params["language"] = language

    file_sql = text(
        f"""
        SELECT rf.file_id, rf.repo_id, rf.file_path
        FROM repository_files rf
        INNER JOIN user_repositories ur
            ON rf.repo_id = ur.repo_id AND ur.user_id = :user_id
        INNER JOIN repositories r
            ON rf.repo_id = r.repo_id
            AND (r.is_public = TRUE OR r.indexed_by = :user_id)
        WHERE rf.repo_id IN ({repo_placeholders})
        {language_filter}
        AND EXISTS (
            SELECT 1
            FROM code_chunks path_chunk
            WHERE path_chunk.file_id = rf.file_id
        )
        ORDER BY rf.repo_id, rf.file_path, rf.file_id
        LIMIT :path_scan_limit
        """
    )
    try:
        file_rows = session.execute(file_sql, params).mappings().all()
    except Exception as exc:
        logger.warning("path-token file scan failed", error=str(exc))
        return []

    if len(file_rows) > max_files:
        logger.warning(
            "path-token file scan exceeded limit",
            files_seen=len(file_rows),
            max_files=max_files,
        )
        return []

    ranked_files = _rank_path_token_files(
        query,
        [dict(row) for row in file_rows],
        top_k=top_k,
    )
    if not ranked_files:
        return []

    chunk_params: dict[str, Any] = {}
    file_placeholders = []
    for index, row in enumerate(ranked_files):
        placeholder = f"file_id_{index}"
        file_placeholders.append(f":{placeholder}")
        chunk_params[placeholder] = row["file_id"]

    chunk_sql = text(
        f"""
        WITH ranked_chunks AS (
            SELECT
                cc.chunk_id, cc.repo_id, cc.file_id,
                cc.content, cc.start_line, cc.end_line,
                cc.chunk_index, cc.chunk_type, cc.language, cc.symbol_names,
                rf.file_path,
                r.owner || '/' || r.name AS repo_name,
                r.is_public,
                ROW_NUMBER() OVER (
                    PARTITION BY cc.file_id
                    ORDER BY cc.chunk_index, cc.repo_id, cc.chunk_id
                ) AS file_chunk_rank
            FROM code_chunks cc
            INNER JOIN repository_files rf ON cc.file_id = rf.file_id
            INNER JOIN repositories r ON cc.repo_id = r.repo_id
            WHERE cc.file_id IN ({", ".join(file_placeholders)})
        )
        SELECT *
        FROM ranked_chunks
        WHERE file_chunk_rank = 1
        ORDER BY repo_id, file_path, chunk_index, chunk_id
        """
    )
    try:
        chunk_rows = session.execute(chunk_sql, chunk_params).mappings().all()
    except Exception as exc:
        logger.warning("path-token chunk lookup failed", error=str(exc))
        return []

    chunks_by_file = {str(row["file_id"]): row for row in chunk_rows}
    candidates: list[Candidate] = []
    for file_row in ranked_files:
        chunk_row = chunks_by_file.get(str(file_row["file_id"]))
        if chunk_row is None:
            continue
        candidate = Candidate(
            chunk_id=str(chunk_row["chunk_id"]),
            repo_id=str(chunk_row["repo_id"]),
            file_id=str(chunk_row["file_id"]),
            repo_name=chunk_row["repo_name"] or "",
            file_path=chunk_row["file_path"] or "",
            content=chunk_row["content"] or "",
            start_line=chunk_row["start_line"],
            end_line=chunk_row["end_line"],
            chunk_index=chunk_row["chunk_index"],
            chunk_type=chunk_row["chunk_type"] or "code",
            language=chunk_row["language"],
            symbol_names=chunk_row["symbol_names"],
            is_public=bool(chunk_row["is_public"]),
        )
        candidate.sources["path_token"] = float(
            file_row["path_token_score"]
        )
        candidates.append(candidate)
    return candidates


def _file_okapi_repo_placeholders(
    repo_ids: list[str],
    params: dict[str, Any],
    *,
    prefix: str = "repo_id",
) -> str:
    placeholders = []
    for index, repo_id in enumerate(repo_ids):
        key = f"{prefix}_{index}"
        placeholders.append(f":{key}")
        params[key] = repo_id
    return ", ".join(placeholders)


def _file_okapi_query_term_cte(terms: list[str], params: dict[str, Any]) -> str:
    selects = []
    for index, term in enumerate(terms):
        key = f"okapi_term_{index}"
        params[key] = term
        selects.append(f"SELECT :{key} AS term")
    return "\n            UNION ALL\n            ".join(selects)


def _file_okapi_rollback(session: Session) -> None:
    rollback = getattr(session, "rollback", None)
    if callable(rollback):
        rollback()


def file_okapi_search(
    session: Session,
    query: str,
    user_id: str,
    repo_ids: list[str] | None = None,
    language: str | None = None,
    top_k: int = FILE_OKAPI_CANDIDATES,
) -> list[Candidate]:
    """Return one representative chunk per file ranked by scoped Okapi BM25.

    Requires an explicit repository scope. Every requested repository must be
    accessible to the caller and indexed at ``FILE_OKAPI_INDEX_VERSION``; the
    total lexical document count across the scope must not exceed
    ``FILE_OKAPI_MAX_FILES``.
    """
    if not repo_ids:
        return []

    repo_ids = list(dict.fromkeys(repo_ids))
    top_k = min(top_k, FILE_OKAPI_CANDIDATES)
    if top_k <= 0:
        return []

    terms = tokenize_file_okapi(query, limit=FILE_OKAPI_QUERY_TERM_CAP)
    if not terms:
        return []

    params: dict[str, Any] = {
        "user_id": user_id,
        "index_version": FILE_OKAPI_INDEX_VERSION,
        "k1": FILE_OKAPI_K1,
        "b": FILE_OKAPI_B,
        "top_k": top_k,
        "search_query": " ".join(terms),
    }
    repo_placeholders = _file_okapi_repo_placeholders(repo_ids, params)
    language_filter = ""
    if language:
        language_filter = " AND rf.language = :language"
        params["language"] = language

    scope_sql = text(
        f"""
        WITH requested_repos AS (
            SELECT repo_id
            FROM repositories
            WHERE repo_id IN ({repo_placeholders})
        ),
        accessible_repos AS (
            SELECT r.repo_id
            FROM repositories r
            INNER JOIN user_repositories ur
                ON r.repo_id = ur.repo_id AND ur.user_id = :user_id
            INNER JOIN requested_repos req ON r.repo_id = req.repo_id
            WHERE (r.is_public = TRUE OR r.indexed_by = :user_id)
              AND r.file_okapi_index_version = :index_version
        )
        SELECT
            (SELECT COUNT(*) FROM requested_repos) AS requested_count,
            (SELECT COUNT(*) FROM accessible_repos) AS accessible_count,
            (
                SELECT COUNT(*)
                FROM repository_file_lexical_documents d
                INNER JOIN accessible_repos ar ON d.repo_id = ar.repo_id
                WHERE d.index_version = :index_version
            ) AS document_count
        """
    )
    try:
        scope_rows = session.execute(scope_sql, params).mappings().all()
    except Exception as exc:
        logger.warning("file-okapi scope validation failed", error=str(exc))
        _file_okapi_rollback(session)
        return []

    scope_row = scope_rows[0]

    requested_count = int(scope_row["requested_count"] or 0)
    accessible_count = int(scope_row["accessible_count"] or 0)
    document_count = int(scope_row["document_count"] or 0)
    if (
        requested_count != len(repo_ids)
        or accessible_count != len(repo_ids)
        or document_count == 0
        or document_count > FILE_OKAPI_MAX_FILES
    ):
        return []

    query_terms_cte = _file_okapi_query_term_cte(terms, params)
    search_sql = text(
        f"""
        WITH scope_docs AS (
            SELECT
                docs.file_id,
                docs.repo_id,
                docs.document_length,
                rf.file_path,
                rf.language
            FROM repository_file_lexical_documents docs
            INNER JOIN repository_files rf ON docs.file_id = rf.file_id
            INNER JOIN repositories r ON docs.repo_id = r.repo_id
            INNER JOIN user_repositories ur
                ON r.repo_id = ur.repo_id AND ur.user_id = :user_id
            WHERE docs.repo_id IN ({repo_placeholders})
              AND (r.is_public = TRUE OR r.indexed_by = :user_id)
              AND docs.index_version = :index_version
              {language_filter}
        ),
        scope_stats AS (
            SELECT
                COUNT(*)::int AS document_count,
                AVG(scope_docs.document_length)::float AS average_document_length
            FROM scope_docs
        ),
        query_terms AS (
            {query_terms_cte}
        ),
        term_stats AS (
            SELECT
                query_terms.term,
                COUNT(DISTINCT scope_docs.file_id)::int AS document_frequency
            FROM query_terms
            LEFT JOIN repository_file_lexical_terms lt
                ON lt.term = query_terms.term
            LEFT JOIN scope_docs
                ON scope_docs.file_id = lt.file_id
            GROUP BY query_terms.term
        ),
        file_scores AS (
            SELECT
                scope_docs.file_id,
                scope_docs.repo_id,
                scope_docs.file_path,
                SUM(
                    LN(1 + (
                        stats.document_count - term_stats.document_frequency + 0.5
                    ) / (term_stats.document_frequency + 0.5))
                    * lt.term_frequency * (:k1 + 1)
                    / (
                        lt.term_frequency
                        + :k1 * (
                            1 - :b
                            + :b * scope_docs.document_length
                              / stats.average_document_length
                        )
                    )
                ) AS score
            FROM scope_docs
            CROSS JOIN scope_stats stats
            INNER JOIN repository_file_lexical_terms lt
                ON lt.file_id = scope_docs.file_id
            INNER JOIN query_terms ON lt.term = query_terms.term
            INNER JOIN term_stats ON term_stats.term = query_terms.term
            GROUP BY
                scope_docs.file_id,
                scope_docs.repo_id,
                scope_docs.file_path,
                stats.document_count,
                stats.average_document_length
        ),
        ranked_files AS (
            SELECT file_scores.*
            FROM file_scores
            WHERE score > 0
        ),
        best_chunks AS (
            SELECT
                cc.chunk_id,
                cc.repo_id,
                cc.file_id,
                cc.content,
                cc.start_line,
                cc.end_line,
                cc.chunk_index,
                cc.chunk_type,
                cc.language,
                cc.symbol_names,
                rf.file_path,
                r.owner || '/' || r.name AS repo_name,
                r.is_public,
                ts_rank_cd(
                    cc.content_tsv,
                    websearch_to_tsquery('english', :search_query)
                ) AS chunk_score,
                ROW_NUMBER() OVER (
                    PARTITION BY cc.file_id
                    ORDER BY
                        ts_rank_cd(
                            cc.content_tsv,
                            websearch_to_tsquery('english', :search_query)
                        ) DESC,
                        cc.chunk_index,
                        cc.repo_id,
                        cc.chunk_id
                ) AS file_chunk_rank
            FROM code_chunks cc
            INNER JOIN repository_files rf ON cc.file_id = rf.file_id
            INNER JOIN repositories r ON cc.repo_id = r.repo_id
            WHERE cc.file_id IN (SELECT file_id FROM ranked_files)
        )
        SELECT
            best_chunks.chunk_id,
            best_chunks.repo_id,
            best_chunks.file_id,
            best_chunks.content,
            best_chunks.start_line,
            best_chunks.end_line,
            best_chunks.chunk_index,
            best_chunks.chunk_type,
            best_chunks.language,
            best_chunks.symbol_names,
            best_chunks.file_path,
            best_chunks.repo_name,
            best_chunks.is_public,
            rf.score
        FROM ranked_files rf
        INNER JOIN best_chunks
            ON best_chunks.file_id = rf.file_id
            AND best_chunks.file_chunk_rank = 1
        ORDER BY score DESC, rf.file_path, chunk_index, repo_id, chunk_id
        LIMIT :top_k
        """
    )
    try:
        rows = session.execute(search_sql, params).mappings().all()
    except Exception as exc:
        logger.warning("file-okapi search failed", error=str(exc))
        _file_okapi_rollback(session)
        return []

    candidates: list[Candidate] = []
    for row in rows:
        candidate = Candidate(
            chunk_id=str(row["chunk_id"]),
            repo_id=str(row["repo_id"]),
            file_id=str(row["file_id"]),
            repo_name=row["repo_name"] or "",
            file_path=row["file_path"] or "",
            content=row["content"] or "",
            start_line=row["start_line"],
            end_line=row["end_line"],
            chunk_index=row["chunk_index"],
            chunk_type=row["chunk_type"] or "code",
            language=row["language"],
            symbol_names=row["symbol_names"],
            is_public=bool(row["is_public"]),
        )
        candidate.sources["file_okapi"] = float(row["score"])
        candidates.append(candidate)
    return candidates


# URLs in a pasted issue body or PR description carry filenames that have
# nothing to do with the repository under search — a CONTRIBUTING.md link in
# a PR template would otherwise become a retrieval anchor.
_URL_RE = re.compile(r"\b(?:https?:)?//\S+", re.IGNORECASE)


def path_stems_from_query(query: str, *, limit: int = 4) -> list[str]:
    """Pull the file stems a query is talking about.

    Agents constantly anchor a request on a path — "what tests cover
    ``server/etcdmain/grpc_proxy.go``", "why did ``auth/tokens.py`` change".
    The stem of that path is a strong retrieval signal for *related* files,
    which is not the same thing as the exact-path lookup: the file the query
    names is usually the one file the caller already has.
    """
    if not query:
        return []

    stems: list[str] = []
    for match in _PATH_EXT_RE.findall(_URL_RE.sub(" ", query)):
        basename = match.rsplit("/", 1)[-1]
        stem = basename.rsplit(".", 1)[0]
        normalized = _normalize_path_token(stem)
        # Two characters of stem is noise, not an anchor.
        if len(normalized) >= 3 and normalized not in stems:
            stems.append(normalized)
        if len(stems) >= limit:
            break
    return stems


def path_affinity_search(
    session: Session,
    query: str,
    user_id: str,
    repo_ids: list[str] | None = None,
    top_k: int = 25,
) -> list[Candidate]:
    """Rank files whose *path* resembles a path the query named.

    BM25 indexes chunk content, and nothing else indexes ``file_path``, so
    until this branch existed a query naming a file could not retrieve that
    file's neighbours lexically at all — the path was invisible to search.
    Matching is done on separator-stripped lowercase so ``grpc_proxy`` finds
    ``etcd_grpcproxy_test.go``, which underscore-sensitive matching misses.
    """
    stems = path_stems_from_query(query)
    if not stems:
        return []

    params: dict[str, Any] = {"user_id": user_id, "top_k": top_k}
    extra = ""
    if repo_ids:
        ph = ", ".join([f":rid_{i}" for i in range(len(repo_ids))])
        extra += f" AND cc.repo_id IN ({ph})"
        for i, rid in enumerate(repo_ids):
            params[f"rid_{i}"] = rid

    # Score each file by its best stem match, then keep one chunk per file so
    # a single large file cannot crowd out the rest of the branch.
    score_terms = []
    for i, stem in enumerate(stems):
        params[f"stem_{i}"] = stem
        score_terms.append(
            f"word_similarity(:stem_{i}, "
            f"replace(replace(lower(rf.file_path), '_', ''), '-', ''))"
        )
    best_score = "GREATEST(" + ", ".join(score_terms) + ")" if len(score_terms) > 1 else score_terms[0]

    # A stem like "grpc_proxy" matches every file under server/proxy/grpcproxy/
    # at a perfect score, and thirty sibling files would fill the branch before
    # the one test in tests/e2e/ ever appeared. Capping per directory keeps the
    # branch spanning the places a related file could actually live.
    sql = text(
        f"""
        WITH scored AS (
            SELECT
                cc.chunk_id, cc.repo_id, cc.file_id,
                cc.content, cc.start_line, cc.end_line,
                cc.chunk_index, cc.chunk_type, cc.language, cc.symbol_names,
                rf.file_path,
                r.owner || '/' || r.name AS repo_name,
                r.is_public,
                {best_score} AS score,
                ROW_NUMBER() OVER (
                    PARTITION BY cc.file_id
                    ORDER BY cc.chunk_index, cc.repo_id, cc.chunk_id
                ) AS chunk_rank
            FROM code_chunks cc
            {_user_repo_filter()}
            INNER JOIN repository_files rf ON cc.file_id = rf.file_id
            WHERE {best_score} > 0.3
            {extra}
        ),
        per_directory AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY regexp_replace(file_path, '/[^/]*$', '')
                    ORDER BY score DESC, length(file_path), file_path,
                             repo_id, chunk_id
                ) AS dir_rank
            FROM scored
            WHERE chunk_rank = 1
        )
        SELECT * FROM per_directory
        WHERE dir_rank <= :per_dir
        ORDER BY score DESC, length(file_path), file_path, repo_id, chunk_id
        LIMIT :top_k
        """
    )
    params["per_dir"] = 2
    try:
        rows = session.execute(sql, params).mappings().all()
    except Exception as e:
        logger.warning("path affinity branch failed", error=str(e))
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
        c.sources["path_affinity"] = float(r["score"])
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
        ORDER BY rf.file_path, cc.chunk_index, cc.repo_id, cc.chunk_id
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


def vector_to_candidates(raw_results: list[dict[str, Any]]) -> list[Candidate]:
    """Convert pgvector search results into the unified Candidate shape."""
    out: list[Candidate] = []
    if not raw_results:
        return out

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
        # Raw cosine similarity, deliberately not rescaled against this
        # result set's best hit: fusion ranks these, and a rescaled score
        # would claim a perfect match whenever nothing better existed.
        c.sources["vector"] = float(r.get("similarity", 0.0))
        out.append(c)
    return out


# Default fusion weights. Vector dominates because it's our most reliable
# signal, but BM25 + symbol provide irreplaceable identifier-recall.
DEFAULT_WEIGHTS = {
    "vector": 0.5,
    "bm25": 0.25,
    "symbol": 0.20,
    "path": 0.15,
    # Path affinity is a precise signal when it fires at all — it only fires
    # when the query actually named a file — so it is weighted alongside the
    # exact-path branch rather than treated as a weak fallback.
    "path_affinity": 0.15,
    "trigram": 0.05,
}


# Reciprocal-rank-fusion damping constant. The standard value from Cormack
# et al. (2009); large enough that the gap between rank 1 and rank 2 does not
# dwarf the agreement signal from a second branch.
RRF_K = 60
FILE_DIVERSE_BM25_WEIGHT = 0.15
PATH_TOKEN_WEIGHT = 0.10


def configured_weights() -> dict[str, float]:
    """Fusion weights, overridable per deployment.

    The right balance is corpus-dependent: an embedding that reads a codebase
    well earns a high vector weight, and one that does not should yield to the
    lexical and path branches. ``SYNSC_FUSION_WEIGHTS`` takes a comma-separated
    ``branch=weight`` list so this can be measured rather than guessed.
    """
    raw = os.getenv("SYNSC_FUSION_WEIGHTS", "").strip()
    if not raw:
        return DEFAULT_WEIGHTS

    weights = dict(DEFAULT_WEIGHTS)
    for part in raw.split(","):
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        try:
            weights[name.strip()] = float(value)
        except ValueError:
            logger.warning("ignoring malformed fusion weight", entry=part)
    return weights


def _align_file_level_candidates(
    candidate_branches: list[list[Candidate]],
    file_candidates: list[Candidate],
    weights: dict[str, float],
    rrf_k: int = RRF_K,
) -> list[Candidate]:
    """Attach one file-level signal to that file's strongest existing chunk.

    Fusion is chunk-based so independently retrieved chunks from the same file
    would otherwise fail to agree. For each file-level candidate, reuse the
    identity of the strongest already retrieved chunk in that file while
    retaining the file branch's own rank and score. Files absent from all
    existing branches keep their lexical chunk and can still enter the union.
    """
    strength_by_chunk: dict[tuple[str, str], tuple[float, Candidate]] = {}
    for branch in candidate_branches:
        for rank, candidate in enumerate(branch, start=1):
            if not candidate.file_id:
                continue
            contribution = sum(
                weights.get(source, 0.0) / (rrf_k + rank)
                for source in candidate.sources
            )
            key = (candidate.file_id, str(candidate.chunk_id))
            current_chunk = strength_by_chunk.get(key)
            if current_chunk is None:
                strength_by_chunk[key] = (contribution, candidate)
            else:
                representative = current_chunk[1]
                if len(candidate.content) > len(representative.content):
                    representative = candidate
                strength_by_chunk[key] = (
                    current_chunk[0] + contribution,
                    representative,
                )

    strongest_by_file: dict[str, tuple[float, Candidate]] = {}
    for (file_id, _chunk_id), (strength, candidate) in strength_by_chunk.items():
        current = strongest_by_file.get(file_id)
        if (
            current is None
            or strength > current[0]
            or (
                strength == current[0]
                and str(candidate.chunk_id) < str(current[1].chunk_id)
            )
        ):
            strongest_by_file[file_id] = (strength, candidate)

    aligned: list[Candidate] = []
    for file_candidate in file_candidates:
        existing = strongest_by_file.get(file_candidate.file_id)
        if existing is None:
            aligned.append(file_candidate)
            continue
        aligned.append(
            replace(
                existing[1],
                sources=dict(file_candidate.sources),
                source_ranks={},
                fused_score=0.0,
            )
        )
    return aligned


def fuse_candidates(
    branches: list[list[Candidate]],
    weights: dict[str, float] | None = None,
    rrf_k: int = RRF_K,
) -> list[Candidate]:
    """Union candidates by chunk_id and fuse them by weighted reciprocal rank.

    Fusion scores **ranks, not raw scores**. Each branch previously normalized
    its own scores by dividing by that branch's top score, which meant the best
    hit of every branch was pinned to exactly 1.0 no matter how bad it was in
    absolute terms. A query with no good semantic match still handed its
    least-bad vector hit a perfect score, and at weight 0.5 that junk outranked
    genuine multi-branch agreement.

    Reciprocal rank fusion is immune to that because it never compares scores
    across branches — only positions:

        score(c) = Σ_b  weights[b] / (rrf_k + rank_b(c))

    A chunk that several branches independently rank highly beats a chunk that
    one branch happened to put first, which is the behaviour the weighted sum
    was reaching for. Raw per-branch scores are kept on the candidate for
    observability and as a deterministic tiebreak.

    The result is rescaled to [0, 1] against the best achievable score (every
    branch ranking the chunk first). Rescaling is a single positive linear
    factor, so it cannot reorder anything — it just keeps ``fused_score`` in
    the range downstream threshold and blending code already expects.
    """
    weights = weights or configured_weights()

    by_chunk: dict[str, Candidate] = {}
    for branch in branches:
        for rank, c in enumerate(branch, start=1):
            existing = by_chunk.get(c.chunk_id)
            if existing is None:
                by_chunk[c.chunk_id] = c
                for src in c.sources:
                    c.source_ranks[src] = rank
                continue
            # Merge sources — same chunk hit by multiple branches. Keep the
            # best score and the best (lowest) rank seen for each branch.
            for src, score in c.sources.items():
                existing.sources[src] = max(existing.sources.get(src, 0.0), score)
                previous = existing.source_ranks.get(src)
                existing.source_ranks[src] = (
                    rank if previous is None else min(previous, rank)
                )
            # Take the longest content (some branches don't read content).
            if len(c.content) > len(existing.content):
                existing.content = c.content

    # Best achievable score: every contributing branch ranks the chunk first.
    best_possible = sum(weights.get(src, 0.0) for src in weights) / (rrf_k + 1)

    for c in by_chunk.values():
        raw = sum(
            weights.get(src, 0.0) / (rrf_k + rank)
            for src, rank in c.source_ranks.items()
        )
        c.fused_score = raw / best_possible if best_possible > 0 else 0.0

    # Ties on reciprocal rank fall back to the strongest raw branch score and
    # finally to chunk_id, so ordering is a total order that never depends on
    # dict insertion (which itself inherits branch arrival order).
    out = sorted(
        by_chunk.values(),
        key=lambda c: (
            -c.fused_score,
            -max(c.sources.values(), default=0.0),
            str(c.chunk_id),
        ),
    )
    return out


def hybrid_retrieve(
    session: Session,
    query: str,
    query_embedding: np.ndarray,
    vector_search_fn: Callable[..., list[dict[str, Any]]],
    user_id: str,
    repo_ids: list[str] | None = None,
    language: str | None = None,
    file_pattern: str | None = None,
    top_k: int = 50,
    enable_bm25: bool = True,
    enable_file_diverse_bm25: bool = False,
    enable_path_token_search: bool = False,
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
    file_bm25_candidates: list[Candidate] = []
    path_token_candidates: list[Candidate] = []
    timing: dict[str, Any] = {}

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

    # 2b. Path affinity — fires whenever the query itself names a file, with
    # no explicit glob from the caller. Without it a path mentioned in the
    # query is invisible to retrieval, since BM25 only indexes chunk content.
    if enable_path:
        t = time.time()
        branches.append(
            path_affinity_search(
                session, query, user_id, repo_ids, top_k=min(top_k, 25)
            )
        )
        timing["path_affinity_ms"] = (time.time() - t) * 1000

    # 2c. Query/path token overlap — a bounded, repository-scoped file signal
    # for terse requests whose vocabulary appears in the path but not content.
    if enable_path_token_search:
        t = time.time()
        path_token_candidates = path_token_search(
            session=session,
            query=query,
            user_id=user_id,
            repo_ids=repo_ids,
            language=language,
            top_k=min(top_k, 25),
        )
        timing["path_token_ms"] = (time.time() - t) * 1000

    # 3. BM25
    if enable_bm25:
        t = time.time()
        branches.append(
            bm25_search(
                session, query, user_id, repo_ids, language, top_k=top_k
            )
        )
        timing["bm25_ms"] = (time.time() - t) * 1000

    # 3b. File-diverse BM25 — opt-in until the native ablation is complete.
    if enable_file_diverse_bm25:
        t = time.time()
        file_bm25_candidates = file_diverse_bm25_search(
            session, query, user_id, repo_ids, language, top_k=top_k
        )
        timing["file_bm25_ms"] = (time.time() - t) * 1000

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

    weights = dict(configured_weights())
    if enable_file_diverse_bm25 and file_bm25_candidates:
        weights.setdefault("file_bm25", FILE_DIVERSE_BM25_WEIGHT)
        branches.append(
            _align_file_level_candidates(
                branches,
                file_bm25_candidates,
                weights,
            )
        )
    else:
        weights.pop("file_bm25", None)
    if enable_path_token_search and path_token_candidates:
        weights.setdefault("path_token", PATH_TOKEN_WEIGHT)
        branches.append(
            _align_file_level_candidates(
                branches,
                path_token_candidates,
                weights,
            )
        )
    else:
        weights.pop("path_token", None)
    fused = fuse_candidates(branches, weights=weights)
    timing["total_ms"] = (time.time() - t_start) * 1000
    timing["candidates"] = len(fused)
    timing["sources"] = {
        "vector": sum(1 for c in fused if "vector" in c.sources),
        "bm25": sum(1 for c in fused if "bm25" in c.sources),
        "file_bm25": sum(1 for c in fused if "file_bm25" in c.sources),
        "symbol": sum(1 for c in fused if "symbol" in c.sources),
        "path": sum(1 for c in fused if "path" in c.sources),
        "path_affinity": sum(1 for c in fused if "path_affinity" in c.sources),
        "path_token": sum(1 for c in fused if "path_token" in c.sources),
        "trigram": sum(1 for c in fused if "trigram" in c.sources),
    }
    logger.debug("hybrid_retrieve timing", **timing)
    return fused
