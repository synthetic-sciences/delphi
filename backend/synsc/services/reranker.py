"""Cross-encoder reranker for improving search result discrimination.

Uses a lightweight cross-encoder model to rerank initial vector search results.
The cross-encoder sees (query, candidate) pairs together, making it far better
at distinguishing semantically similar but functionally different code than
cosine similarity on independent embeddings.

Expected improvement: +0.15-0.25 on adversarial discrimination score.
"""

import os
import logging
from typing import Optional

import numpy as np

from synsc.config import get_config

logger = logging.getLogger(__name__)

# Default cross-encoder model — small (~22MB), fast (~10ms/pair on CPU)
DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class Reranker:
    """Cross-encoder reranker for search result quality improvement.

    Loads a small cross-encoder model that scores (query, passage) pairs.
    Unlike bi-encoder embeddings (which encode query and passage independently),
    cross-encoders attend to both simultaneously — much better at subtle
    distinctions like "implementation vs test" or "v1 vs v2 API".

    Memory: ~90MB additional on top of existing models.
    Latency: ~10ms per (query, candidate) pair on CPU.
    """

    def __init__(self, model_name: str | None = None):
        """Initialize the reranker.

        Tries the configured code-aware model first (BAAI/bge-reranker-base
        by default — works well on code+text pairs), then falls back to the
        ms-marco model. The fallback prevents an offline/CDN-blocked
        environment from disabling rerank entirely.

        Args:
            model_name: HuggingFace cross-encoder model name.
                        Defaults to config (RERANKER_MODEL env var) or
                        the code-aware bge-reranker-base.
        """
        from sentence_transformers import CrossEncoder

        config = get_config()

        # Build the candidate list: explicit override → code-aware →
        # plain text fallback. De-dup while preserving order.
        candidates: list[str] = []
        if model_name:
            candidates.append(model_name)
        else:
            if config.search.use_code_reranker:
                candidates.append(config.search.code_reranker_model)
            candidates.append(config.search.reranker_model)
            candidates.append(DEFAULT_RERANKER_MODEL)

        seen: set[str] = set()
        ordered: list[str] = []
        for c in candidates:
            if c and c not in seen:
                ordered.append(c)
                seen.add(c)

        last_err: Exception | None = None
        for cand in ordered:
            try:
                logger.info("Loading cross-encoder reranker: %s", cand)
                self.model = CrossEncoder(cand)
                self.model_name = cand
                logger.info("Reranker ready: %s", cand)
                break
            except Exception as e:
                last_err = e
                logger.warning(
                    "Reranker load failed for %s: %s — trying next.", cand, e
                )
        else:
            # Loop completed without break: every candidate failed.
            raise RuntimeError(
                f"All reranker models failed to load: last error {last_err}"
            )

    def rerank(
        self,
        query: str,
        results: list[dict],
        top_k: int | None = None,
        content_key: str = "content",
        score_key: str = "similarity",
        blend_alpha: float = 0.4,
    ) -> list[dict]:
        """Rerank search results using blended cross-encoder + vector scores.

        Instead of replacing vector similarity scores entirely, blends them
        with cross-encoder scores. This preserves the domain-specific signal
        from code embeddings while adding the cross-encoder's discrimination.

        final_score = α * cross_encoder + (1-α) * vector_similarity

        Args:
            query: The original search query.
            results: Search results (must have content_key and score_key).
            top_k: Number of results to return (None = return all, re-sorted).
            content_key: Key for the text content in result dicts.
            score_key: Key for the similarity score to update.
            blend_alpha: Weight for cross-encoder score (0=vector only, 1=CE only).

        Returns:
            Results reranked by blended score, with updated score_key.
        """
        if not results:
            return results

        # Build (query, passage) pairs for the cross-encoder
        pairs = [(query, r[content_key]) for r in results]

        # Score all pairs at once (batched for efficiency)
        scores = self.model.predict(pairs)

        # Normalize cross-encoder scores to 0-1 range using sigmoid
        # ms-marco models output raw logits; sigmoid maps them to probabilities
        normalized = 1 / (1 + np.exp(-np.array(scores)))

        # Blend cross-encoder with original vector similarity
        for r, ce_score in zip(results, normalized):
            original_score = r[score_key]
            r[score_key] = blend_alpha * float(ce_score) + (1 - blend_alpha) * original_score

        # Sort by blended scores (descending)
        results.sort(key=lambda r: r[score_key], reverse=True)

        if top_k is not None:
            results = results[:top_k]

        return results


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Singleton
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_reranker: Optional[Reranker] = None


def get_reranker() -> Reranker:
    """Get the global reranker instance (lazy-loaded on first use)."""
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker
