"""Gemini text-generation provider for research synthesis.

Uses the unified ``google.genai`` SDK. Do not pull in the legacy
``google-generativeai`` package.
"""
from __future__ import annotations

from google import genai

from synsc.services.research_providers.base import GeneratedAnswer


class GeminiResearchProvider:
    """Synthesize an answer from retrieved context with Gemini."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("GeminiResearchProvider requires a non-empty api_key")
        self._client = genai.Client(api_key=api_key)

    def generate(
        self,
        prompt: str,
        context_blocks: list[dict],
        model: str,
    ) -> GeneratedAnswer:
        """Synchronous one-shot generation. Caller assembles the prompt."""
        rendered = self._render_prompt(prompt, context_blocks)
        resp = self._client.models.generate_content(
            model=model,
            contents=rendered,
        )
        usage = getattr(resp, "usage_metadata", None)
        return GeneratedAnswer(
            text=resp.text or "",
            tokens_in=getattr(usage, "prompt_token_count", 0) or 0,
            tokens_out=getattr(usage, "candidates_token_count", 0) or 0,
            raw=resp,
        )

    @staticmethod
    def _render_prompt(question: str, blocks: list[dict]) -> str:
        parts = [
            "You are a research assistant answering questions grounded in the provided context.",
            "Cite sources inline as [chunk:<chunk_id>]. Answer in Markdown.",
            "",
            f"Question: {question}",
            "",
            "Context:",
        ]
        for i, b in enumerate(blocks, 1):
            parts.append(
                f"[{i}] source={b.get('source_id')} chunk={b.get('chunk_id')}\n{b.get('text','')}"
            )
        parts.append("\nAnswer:")
        return "\n".join(parts)
