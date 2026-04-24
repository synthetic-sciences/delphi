"""Code snippet extraction from research papers."""

import re
from typing import Any

from synsc.extractors.base import BaseExtractor


class CodeSnippetExtractor(BaseExtractor):
    """Extracts code snippets from paper text."""

    def get_extractor_name(self) -> str:
        return "code_snippet"

    def extract(self, text: str, **kwargs) -> list[dict[str, Any]]:
        """Extract code snippets from text."""
        snippets = []

        # 1. Code blocks with verbatim/lstlisting
        snippets.extend(self._extract_latex_code_blocks(text))

        # 2. Indented code blocks (simple heuristic)
        snippets.extend(self._extract_indented_code(text))

        return snippets

    def _extract_latex_code_blocks(self, text: str) -> list[dict[str, Any]]:
        """Extract LaTeX code environments."""
        snippets = []

        # verbatim environment
        for match in re.finditer(
            r"\\begin\{verbatim\}(.*?)\\end\{verbatim\}", text, re.DOTALL
        ):
            code = match.group(1).strip()
            snippets.append(
                {
                    "code_text": code,
                    "language": None,
                    "source": "verbatim",
                }
            )

        # lstlisting environment (may have language)
        for match in re.finditer(
            r"\\begin\{lstlisting\}(?:\[.*?language=(\w+).*?\])?(.*?)\\end\{lstlisting\}",
            text,
            re.DOTALL,
        ):
            language = match.group(1)
            code = match.group(2).strip()
            snippets.append(
                {
                    "code_text": code,
                    "language": language,
                    "source": "lstlisting",
                }
            )

        return snippets

    def _extract_indented_code(self, text: str) -> list[dict[str, Any]]:
        """Extract code blocks based on indentation heuristics."""
        snippets = []
        lines = text.split("\n")

        in_code_block = False
        code_lines = []
        min_indent = float("inf")

        for line in lines:
            # Check if line looks like code (heavily indented)
            stripped = line.lstrip()
            if not stripped:
                if in_code_block:
                    code_lines.append(line)
                continue

            indent = len(line) - len(stripped)

            # Heuristic: code if indented >= 4 spaces or starts with common code patterns
            is_code_like = (
                indent >= 4
                or stripped.startswith(
                    (
                        "def ",
                        "class ",
                        "import ",
                        "from ",
                        "function ",
                        "var ",
                        "const ",
                        "let ",
                    )
                )
                or bool(re.match(r"^\w+\s*=\s*.+[;:]?$", stripped))  # assignments
                or bool(re.match(r"^for\s*\(", stripped))  # for loops
                or bool(re.match(r"^if\s*\(", stripped))  # if statements
            )

            if is_code_like:
                if not in_code_block:
                    in_code_block = True
                    code_lines = []
                    min_indent = indent
                code_lines.append(line)
                min_indent = min(min_indent, indent)
            else:
                if in_code_block and len(code_lines) >= 3:  # At least 3 lines
                    # Extract code block
                    code = "\n".join(code_lines)
                    # Detect language
                    language = self._detect_language(code)
                    snippets.append(
                        {
                            "code_text": code,
                            "language": language,
                            "source": "indented",
                        }
                    )
                in_code_block = False
                code_lines = []

        # Handle final code block
        if in_code_block and len(code_lines) >= 3:
            code = "\n".join(code_lines)
            language = self._detect_language(code)
            snippets.append(
                {
                    "code_text": code,
                    "language": language,
                    "source": "indented",
                }
            )

        return snippets

    def _detect_language(self, code: str) -> str | None:
        """Simple language detection based on keywords."""
        code_lower = code.lower()

        if any(
            kw in code_lower for kw in ["def ", "import ", "class ", "self.", "python"]
        ):
            return "python"
        elif any(
            kw in code_lower for kw in ["function ", "const ", "let ", "var ", "=>"]
        ):
            return "javascript"
        elif any(
            kw in code_lower
            for kw in ["public class", "private ", "void ", "public static"]
        ):
            return "java"
        elif any(kw in code_lower for kw in ["#include", "int main", "std::", "cout"]):
            return "cpp"
        elif any(kw in code_lower for kw in ["func ", "package ", "import fmt"]):
            return "go"

        return None
