"""Improved paper retrieval.

Three changes over the legacy pure-vector path:

1. **Hybrid**: vector + BM25 over the new ``paper_chunks.content_tsv``
   column (migration 004). Identifier-style queries on technical papers
   ("layer normalization", "RMSNorm") need keyword recall.

2. **Section-aware ranking**: results from "Methods", "Results", and
   "Algorithm" sections rank higher than from "Related Work" /
   "Acknowledgements". A small section-name boost / penalty.

3. **Citation-aware ranking**: chunks in papers cited by other indexed
   papers get a small boost (works as a low-cost PageRank-on-citations).

4. **Quote-grounded synthesis**: ``extract_quoted_evidence(paper_id, claim)``
   pulls the literal sentences supporting a claim, so the agent can quote
   the paper rather than paraphrasing.

5. **Reranker**: cross-encoder reranks the top fused window, same as code
   search.
"""
from __future__ import annotations

import re
import time
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from synsc.database.connection import get_session

logger = structlog.get_logger(__name__)


# Section-name → ranking multiplier. Weighted toward sections an agent is
# usually trying to ground a claim in (Methods, Results, Algorithm). Penalty
# for sections that *describe* prior work rather than the paper's own claims.
_SECTION_WEIGHTS = {
    "abstract": 1.05,
    "method": 1.20, "methods": 1.20, "methodology": 1.20,
    "approach": 1.15, "algorithm": 1.20, "model": 1.10,
    "experiment": 1.15, "experiments": 1.15,
    "result": 1.18, "results": 1.18, "evaluation": 1.15,
    "discussion": 1.05,
    "introduction": 1.0, "background": 0.95,
    "related work": 0.85, "related": 0.85, "prior work": 0.85,
    "conclusion": 1.0, "conclusions": 1.0,
    "references": 0.5, "bibliography": 0.5,
    "acknowledgements": 0.4, "acknowledgments": 0.4,
    "appendix": 0.85,
}


def _section_weight(section_title: str | None) -> float:
    if not section_title:
        return 1.0
    s = section_title.lower().strip()
    # Try exact match first, then prefix match.
    if s in _SECTION_WEIGHTS:
        return _SECTION_WEIGHTS[s]
    for key, w in _SECTION_WEIGHTS.items():
        if s.startswith(key + " ") or s.startswith(key + ":"):
            return w
    return 1.0


def hybrid_search_papers(
    user_id: str,
    query: str,
    query_embedding,
    top_k: int = 10,
    paper_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Hybrid paper retrieval: vector + BM25 + section/citation-aware boost."""
    if not query.strip():
        return []

    embedding_list = (
        query_embedding.tolist()
        if hasattr(query_embedding, "tolist")
        else list(query_embedding)
    )
    embedding_str = "[" + ",".join(str(x) for x in embedding_list) + "]"

    params: dict[str, Any] = {
        "embedding": embedding_str,
        "user_id": user_id,
        "top_k": top_k * 3,
        "query_text": query,
    }
    paper_clause = ""
    if paper_ids:
        ph = ", ".join([f":pid_{i}" for i in range(len(paper_ids))])
        paper_clause = f"AND p.paper_id IN ({ph})"
        for i, pid in enumerate(paper_ids):
            params[f"pid_{i}"] = pid

    # Citation-aware boost: chunks in papers that are cited by ≥1 other
    # indexed paper get a 1.05 multiplier. Cheap, runs as a join.
    sql = text(
        f"""
        WITH cited_count AS MATERIALIZED (
            SELECT cited_paper_id, COUNT(DISTINCT paper_id) AS n
            FROM citations
            WHERE cited_paper_id IS NOT NULL
            GROUP BY cited_paper_id
        )
        SELECT
            pc.chunk_id, pc.paper_id, pc.content,
            pc.section_title, pc.chunk_type, pc.page_number,
            p.title AS paper_title, p.authors AS paper_authors,
            COALESCE(cc.n, 0) AS cited_count,
            1 - (pce.embedding <=> CAST(:embedding AS vector)) AS vector_similarity,
            ts_rank_cd(
                pc.content_tsv,
                websearch_to_tsquery('english', :query_text)
            ) AS bm25_score
        FROM paper_chunk_embeddings pce
        JOIN paper_chunks pc ON pc.chunk_id = pce.chunk_id
        JOIN papers p ON p.paper_id = pc.paper_id
        JOIN user_papers up ON up.paper_id = p.paper_id
        LEFT JOIN cited_count cc ON cc.cited_paper_id = p.paper_id
        WHERE up.user_id = :user_id
        {paper_clause}
        ORDER BY pce.embedding <=> CAST(:embedding AS vector)
        LIMIT :top_k
        """
    )
    try:
        with get_session() as session:
            rows = session.execute(sql, params).mappings().all()
    except Exception as e:
        logger.warning("hybrid paper search failed", error=str(e))
        return []

    if not rows:
        return []

    # Normalize BM25 within this result set; it's unbounded but usually
    # max ~1.0 for paper-scale queries.
    max_bm25 = max((r["bm25_score"] or 0.0 for r in rows), default=1.0) or 1.0

    results: list[dict[str, Any]] = []
    for r in rows:
        vec = float(r["vector_similarity"] or 0.0)
        bm = float(r["bm25_score"] or 0.0) / max_bm25
        section_w = _section_weight(r["section_title"])
        # Citation boost: log-scaled so 100-cited-by papers don't dominate.
        cite = r["cited_count"] or 0
        cite_boost = 1.0 + min(0.10, 0.02 * (cite ** 0.5))

        # Final blend: 60% vector + 25% BM25 + section/citation multipliers.
        score = (0.60 * vec + 0.25 * bm) * section_w * cite_boost
        # Snap to [0, 1] for API consistency.
        score = max(0.0, min(1.0, score))

        results.append(
            {
                "chunk_id": str(r["chunk_id"]),
                "paper_id": str(r["paper_id"]),
                "paper_title": r["paper_title"],
                "paper_authors": r["paper_authors"],
                "content": r["content"],
                "section_title": r["section_title"],
                "chunk_type": r["chunk_type"],
                "page_number": r["page_number"],
                "similarity": round(score, 4),
                "components": {
                    "vector": round(vec, 4),
                    "bm25": round(bm, 4),
                    "section_weight": section_w,
                    "cited_count": cite,
                },
            }
        )

    results.sort(key=lambda r: r["similarity"], reverse=True)
    return results[:top_k]


def rerank_papers(query: str, results: list[dict]) -> list[dict]:
    """Cross-encoder rerank for papers — same path as code search but
    blended at α=0.45 because section/citation weighting already does some
    of the discrimination work.
    """
    if len(results) <= 1:
        return results
    try:
        from synsc.services.reranker import get_reranker
        reranker = get_reranker()
        return reranker.rerank(
            query=query,
            results=results,
            content_key="content",
            score_key="similarity",
            blend_alpha=0.45,
        )
    except Exception as e:
        logger.warning("paper rerank failed", error=str(e))
        return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Quote-grounded synthesis
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def _split_sentences(text_block: str) -> list[str]:
    """Cheap sentence splitter — doesn't need to be perfect for grounding."""
    return [s.strip() for s in _SENT_SPLIT.split(text_block) if s.strip()]


def extract_quoted_evidence(
    paper_id: str,
    claim: str,
    user_id: str,
    max_quotes: int = 5,
) -> dict[str, Any]:
    """Pull the literal sentences from a paper that best support a claim.

    For each chunk we score sentences by token overlap with the claim;
    the top sentences are returned with their section + page so the agent
    can quote them directly. Avoids paraphrase drift.
    """
    if not claim or not paper_id:
        return {"success": False, "error": "missing inputs"}

    claim_tokens = {
        t.lower()
        for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]+", claim)
        if len(t) >= 3
    }
    if not claim_tokens:
        return {
            "success": False,
            "error": "claim too short to ground",
            "quotes": [],
        }

    with get_session() as session:
        rows = session.execute(
            text(
                """
                SELECT pc.chunk_id, pc.content, pc.section_title, pc.page_number
                FROM paper_chunks pc
                INNER JOIN papers p ON p.paper_id = pc.paper_id
                INNER JOIN user_papers up ON up.paper_id = p.paper_id
                WHERE pc.paper_id = :pid AND up.user_id = :uid
                """
            ),
            {"pid": paper_id, "uid": user_id},
        ).mappings().all()

    if not rows:
        return {"success": False, "error": "paper not found or no access"}

    scored: list[dict[str, Any]] = []
    for r in rows:
        for sent in _split_sentences(r["content"] or ""):
            sent_tokens = {
                t.lower()
                for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]+", sent)
            }
            if not sent_tokens:
                continue
            overlap = len(claim_tokens & sent_tokens)
            if overlap == 0:
                continue
            score = overlap / max(len(claim_tokens), 1)
            scored.append(
                {
                    "chunk_id": str(r["chunk_id"]),
                    "section": r["section_title"],
                    "page": r["page_number"],
                    "quote": sent,
                    "score": round(score, 3),
                    "overlap_tokens": overlap,
                }
            )

    scored.sort(key=lambda s: (s["score"], s["overlap_tokens"]), reverse=True)
    top = scored[:max_quotes]
    return {
        "success": True,
        "paper_id": paper_id,
        "claim": claim,
        "quotes": top,
        "total_candidates": len(scored),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Joint retrieval: papers + graph + code
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def joint_retrieval(
    query: str,
    user_id: str,
    paper_ids: list[str] | None = None,
    repo_ids: list[str] | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    """One-shot: paper hits, code hits, and Thesis-graph hits, fused.

    Useful for research workflows where the agent needs to cite a paper,
    reference an implementation, and pick up prior decisions from the
    Thesis graph in a single response.
    """
    from synsc.embeddings.generator import get_embedding_generator
    from synsc.services.search_service import SearchService

    t0 = time.time()
    embed = get_embedding_generator()
    qemb = embed.generate_single(query)

    paper_hits = hybrid_search_papers(
        user_id=user_id, query=query, query_embedding=qemb,
        top_k=top_k, paper_ids=paper_ids,
    )
    paper_hits = rerank_papers(query, paper_hits)

    code_hits = (
        SearchService(user_id=user_id)
        .search_code(query=query, repo_ids=repo_ids, top_k=top_k,
                     user_id=user_id, quality_mode="agent")
        .get("results", [])
    )

    # Graph hits — best-effort, may not be installed.
    graph_hits: list[dict] = []
    try:
        from synsc.services.thesis_connector import (
            search_thesis_nodes,
        )
        graph_hits = search_thesis_nodes(query=query, user_id=user_id, top_k=top_k)
    except Exception:
        pass

    return {
        "query": query,
        "paper_hits": paper_hits,
        "code_hits": code_hits,
        "graph_hits": graph_hits,
        "elapsed_ms": round((time.time() - t0) * 1000),
    }
