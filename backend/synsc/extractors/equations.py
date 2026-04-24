"""Equation extraction from LaTeX in research papers."""

import re
from typing import Any

from synsc.extractors.base import BaseExtractor


class EquationExtractor(BaseExtractor):
    """Extracts LaTeX equations from paper text."""

    def get_extractor_name(self) -> str:
        return "equation"

    def extract(self, text: str, **kwargs) -> list[dict[str, Any]]:
        """Extract equations from text."""
        equations = []

        # 1. Display equations: $$...$$ or \[...\]
        equations.extend(self._extract_display_equations(text))

        # 2. Numbered equations: \begin{equation}...\end{equation}
        equations.extend(self._extract_numbered_equations(text))

        # 3. Inline equations: $...$
        equations.extend(self._extract_inline_equations(text))

        return equations

    def _extract_display_equations(self, text: str) -> list[dict[str, Any]]:
        r"""Extract display equations $$...$$ and \[...\]."""
        equations = []

        # Pattern: $$...$$
        for match in re.finditer(r"\$\$(.*?)\$\$", text, re.DOTALL):
            eq_text = match.group(1).strip()
            context = self._get_context(text, match.start(), match.end())

            equations.append(
                {
                    "equation_text": eq_text,
                    "equation_type": "display",
                    "context": context,
                }
            )

        # Pattern: \[...\]
        for match in re.finditer(r"\\\[(.*?)\\\]", text, re.DOTALL):
            eq_text = match.group(1).strip()
            context = self._get_context(text, match.start(), match.end())

            equations.append(
                {
                    "equation_text": eq_text,
                    "equation_type": "display",
                    "context": context,
                }
            )

        return equations

    def _extract_numbered_equations(self, text: str) -> list[dict[str, Any]]:
        """Extract numbered equations from equation environment."""
        equations = []

        pattern = r"\\begin\{equation\}(.*?)\\end\{equation\}"
        for match in re.finditer(pattern, text, re.DOTALL):
            eq_text = match.group(1).strip()
            context = self._get_context(text, match.start(), match.end())

            # Try to find equation number (1), (2), etc. nearby
            eq_num = self._find_equation_number(text, match.end())

            equations.append(
                {
                    "equation_text": eq_text,
                    "equation_type": "numbered",
                    "equation_number": eq_num,
                    "context": context,
                }
            )

        return equations

    def _extract_inline_equations(self, text: str) -> list[dict[str, Any]]:
        """Extract inline equations $...$."""
        equations = []

        # Match $...$ but not $$...$$
        pattern = r"(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)"

        for match in re.finditer(pattern, text):
            eq_text = match.group(1).strip()

            # Skip if too short (likely not a real equation)
            if len(eq_text) < 2:
                continue

            context = self._get_context(text, match.start(), match.end())

            equations.append(
                {
                    "equation_text": eq_text,
                    "equation_type": "inline",
                    "context": context,
                }
            )

        return equations

    def _get_context(self, text: str, start: int, end: int, window: int = 100) -> str:
        """Get context around equation."""
        ctx_start = max(0, start - window)
        ctx_end = min(len(text), end + window)
        context = text[ctx_start:ctx_end].strip()
        return re.sub(r"\s+", " ", context)

    def _find_equation_number(
        self, text: str, pos: int, search_window: int = 100
    ) -> str | None:
        """Find equation number like (1), (2.1) near position."""
        search_text = text[pos : pos + search_window]
        match = re.search(r"\((\d+(?:\.\d+)?)\)", search_text)
        return match.group(1) if match else None
