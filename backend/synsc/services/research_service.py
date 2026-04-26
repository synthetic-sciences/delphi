"""Retrieval-augmented synthesis across indexed sources.

Uses a pluggable `ResearchProvider` (default: Gemini via google.genai) and
a pluggable `retrieve_fn` so unit tests can stub out both.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Literal

import structlog

from synsc.config import get_config
from synsc.services.research_providers.base import ResearchProvider

logger = structlog.get_logger(__name__)

ResearchMode = Literal["quick", "deep", "oracle"]

RetrieveFn = Callable[..., list[dict[str, Any]]]

_REFINE_PREFIX = "REFINE:"


class ResearchService:
    def __init__(
        self,
        provider: ResearchProvider | None = None,
        retrieve_fn: RetrieveFn | None = None,
    ):
        self.config = get_config()
        self._provider = provider
        self._retrieve = retrieve_fn

    @property
    def provider(self) -> ResearchProvider:
        if self._provider is not None:
            return self._provider
        cfg = self.config.research
        if cfg.provider == "gemini":
            from synsc.services.research_providers.gemini import GeminiResearchProvider
            return GeminiResearchProvider(api_key=cfg.api_key)
        raise ValueError(f"Unknown research provider: {cfg.provider}")

    @property
    def retrieve(self) -> RetrieveFn:
        if self._retrieve is not None:
            return self._retrieve
        from synsc.services.source_service import unified_retrieve
        return unified_retrieve

    def run(
        self,
        query: str,
        mode: ResearchMode = "quick",
        source_ids: list[str] | None = None,
        source_types: list[str] | None = None,
        k: int | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        t0 = time.monotonic()
        cfg = self.config.research

        if mode == "quick":
            model = cfg.model_quick
            top_k = k or cfg.quick_top_k
            max_hops = 1
        elif mode in ("deep", "oracle"):
            model = cfg.model_deep
            top_k = k or cfg.deep_top_k
            max_hops = cfg.deep_max_hops
        else:
            raise ValueError(f"Unknown mode: {mode}")

        current_query = query
        all_citations: dict[str, dict] = {}
        tokens_in = 0
        tokens_out = 0
        answer_text = ""

        for hop in range(max_hops):
            hits = self.retrieve(
                query=current_query,
                source_ids=source_ids,
                source_types=source_types,
                k=top_k,
                user_id=user_id,
            )
            for h in hits:
                key = f"{h.get('source_id')}:{h.get('chunk_id')}"
                if key not in all_citations:
                    all_citations[key] = h

            ans = self.provider.generate(
                prompt=current_query if hop == 0 else self._refine_prompt(query, answer_text),
                context_blocks=list(all_citations.values()),
                model=model,
            )
            tokens_in += ans.tokens_in
            tokens_out += ans.tokens_out
            answer_text = ans.text

            if mode == "quick" or not ans.text.startswith(_REFINE_PREFIX):
                break
            current_query = ans.text[len(_REFINE_PREFIX):].strip() or query

        latency_ms = int((time.monotonic() - t0) * 1000)
        return {
            "answer_markdown": answer_text,
            "citations": [
                {
                    "source_id": c.get("source_id"),
                    "chunk_id": c.get("chunk_id"),
                    "text": c.get("text", "")[:1500],
                    "score": c.get("score", 0.0),
                    "path": c.get("path"),
                    "line_no": c.get("line_no"),
                }
                for c in all_citations.values()
            ],
            "usage": {
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "mode": mode,
                "latency_ms": latency_ms,
            },
        }

    @staticmethod
    def _refine_prompt(original: str, partial_answer: str) -> str:
        return (
            f"Original question: {original}\n\n"
            f"Prior partial answer: {partial_answer}\n\n"
            "Produce a final Markdown answer grounded in the context below. "
            "Do not start with 'REFINE:'."
        )
