"""Anthropic Claude text-generation provider for research synthesis.

Streams under the hood per Anthropic SDK guidance so long inputs/outputs
do not hit non-streaming HTTP timeouts. Public shape mirrors
GeminiResearchProvider.
"""
from __future__ import annotations

from anthropic import Anthropic

from synsc.services.research_providers.base import GeneratedAnswer

DEFAULT_MAX_TOKENS = 16384


class AnthropicResearchProvider:
    """Synthesize an answer from retrieved context with Anthropic Claude."""

    def __init__(self, api_key: str, max_tokens: int = DEFAULT_MAX_TOKENS):
        if not api_key:
            raise ValueError("AnthropicResearchProvider requires a non-empty api_key")
        self._client = Anthropic(api_key=api_key)
        self._max_tokens = max_tokens

    def generate(
        self,
        prompt: str,
        context_blocks: list[dict],
        model: str,
    ) -> GeneratedAnswer:
        """Synchronous one-shot generation. Caller assembles the prompt."""
        rendered = self._render_prompt(prompt, context_blocks)
        with self._client.messages.stream(
            model=model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": rendered}],
        ) as stream:
            final = stream.get_final_message()

        text = "".join(
            block.text for block in final.content if getattr(block, "type", None) == "text"
        )
        usage = getattr(final, "usage", None)
        return GeneratedAnswer(
            text=text,
            tokens_in=getattr(usage, "input_tokens", 0) or 0,
            tokens_out=getattr(usage, "output_tokens", 0) or 0,
            raw=final,
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
