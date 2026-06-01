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
from synsc.services.research_providers.base import GeneratedAnswer, ResearchProvider

logger = structlog.get_logger(__name__)

ResearchMode = Literal["quick", "deep", "oracle"]

RetrieveFn = Callable[..., list[dict[str, Any]]]

_REFINE_PREFIX = "REFINE:"

_QUOTA_HINTS = (
    "429",
    "quota",
    "rate limit",
    "rate_limit",
    "resource_exhausted",
    "resource exhausted",
)


def _is_quota_error(err: BaseException) -> bool:
    """Heuristic: identify quota/rate-limit errors across provider SDKs."""
    code = getattr(err, "status_code", None) or getattr(err, "code", None)
    if code == 429:
        return True
    msg = str(err).lower()
    return any(hint in msg for hint in _QUOTA_HINTS)


class _FallbackProvider:
    """Wraps a primary ResearchProvider with a secondary one used on quota errors.

    Mirrors the ResearchProvider Protocol so callers do not need to know a
    fallback exists. Errors that are not quota-related propagate unchanged.
    """

    def __init__(
        self,
        primary: ResearchProvider,
        fallback: ResearchProvider,
        model_map: dict[str, str],
    ):
        self._primary = primary
        self._fallback = fallback
        self._model_map = model_map

    def generate(
        self,
        prompt: str,
        context_blocks: list[dict],
        model: str,
    ) -> GeneratedAnswer:
        try:
            return self._primary.generate(prompt, context_blocks, model)
        except Exception as err:
            if not _is_quota_error(err):
                raise
            fallback_model = self._model_map.get(model, model)
            logger.warning(
                "research.primary_quota_exhausted_falling_back",
                primary_model=model,
                fallback_model=fallback_model,
                error=str(err)[:200],
            )
            return self._fallback.generate(prompt, context_blocks, fallback_model)


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
        primary = self._build_provider(cfg.provider, cfg.api_key)

        if cfg.fallback_provider == "none" or not cfg.fallback_api_key:
            return primary

        fallback = self._build_provider(cfg.fallback_provider, cfg.fallback_api_key)
        model_map = {
            cfg.model_quick: cfg.fallback_model_quick,
            cfg.model_deep: cfg.fallback_model_deep,
        }
        return _FallbackProvider(primary, fallback, model_map)

    @staticmethod
    def _build_provider(name: str, api_key: str) -> ResearchProvider:
        if name == "gemini":
            from synsc.services.research_providers.gemini import GeminiResearchProvider
            return GeminiResearchProvider(api_key=api_key)
        if name == "anthropic":
            from synsc.services.research_providers.anthropic import (
                AnthropicResearchProvider,
            )
            return AnthropicResearchProvider(api_key=api_key)
        raise ValueError(f"Unknown research provider: {name}")

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
