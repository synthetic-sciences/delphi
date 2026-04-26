"""Research provider protocol — abstracts over Gemini / Anthropic / future."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class GeneratedAnswer:
    text: str
    tokens_in: int
    tokens_out: int
    raw: Any = None


class ResearchProvider(Protocol):
    def generate(
        self,
        prompt: str,
        context_blocks: list[dict],
        model: str,
    ) -> GeneratedAnswer: ...
