"""Regex-based fallback parser for languages without a tree-sitter grammar.

This will never be as accurate as an AST parser, but it gives Delphi *some*
symbol-level recall (function/class names, line ranges) for ecosystems we don't
ship a grammar for — Kotlin, Swift, Scala, and friends. That's the difference
between "search returns nothing useful for this language" and "search can jump
to the right symbol", which is the whole point.

Each language is a :class:`RegexLanguageSpec` of compiled patterns. The parser
walks lines, matches definitions, and infers end lines from brace/indentation
balance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from synsc.parsing.base import BaseParser
from synsc.parsing.models import CodeRegion, ExtractedSymbol


@dataclass
class _Pattern:
    regex: re.Pattern[str]
    symbol_type: str


@dataclass
class RegexLanguageSpec:
    language: str
    extensions: tuple[str, ...]
    patterns: list[_Pattern]
    class_types: frozenset[str] = field(
        default_factory=lambda: frozenset({"class", "struct", "interface", "trait", "enum", "object", "protocol", "actor"})
    )
    block_style: str = "brace"  # "brace" or "indent"


def _p(pattern: str, symbol_type: str) -> _Pattern:
    return _Pattern(re.compile(pattern), symbol_type)


# Identifier fragment reused across patterns.
_ID = r"[A-Za-z_][A-Za-z0-9_]*"

REGEX_SPECS: dict[str, RegexLanguageSpec] = {
    "kotlin": RegexLanguageSpec(
        language="kotlin",
        extensions=(".kt", ".kts"),
        patterns=[
            _p(rf"^\s*(?:[\w@]+\s+)*fun\s+(?:<[^>]+>\s*)?(?:{_ID}\.)?(?P<name>{_ID})\s*\(", "function"),
            _p(rf"^\s*(?:[\w@]+\s+)*class\s+(?P<name>{_ID})", "class"),
            _p(rf"^\s*(?:[\w@]+\s+)*interface\s+(?P<name>{_ID})", "interface"),
            _p(rf"^\s*(?:[\w@]+\s+)*object\s+(?P<name>{_ID})", "object"),
            _p(rf"^\s*(?:[\w@]+\s+)*enum\s+class\s+(?P<name>{_ID})", "enum"),
        ],
    ),
    "swift": RegexLanguageSpec(
        language="swift",
        extensions=(".swift",),
        patterns=[
            _p(rf"^\s*(?:[\w@]+\s+)*func\s+(?P<name>{_ID})\s*[(<]", "function"),
            _p(rf"^\s*(?:[\w@]+\s+)*class\s+(?P<name>{_ID})", "class"),
            _p(rf"^\s*(?:[\w@]+\s+)*struct\s+(?P<name>{_ID})", "struct"),
            _p(rf"^\s*(?:[\w@]+\s+)*protocol\s+(?P<name>{_ID})", "protocol"),
            _p(rf"^\s*(?:[\w@]+\s+)*enum\s+(?P<name>{_ID})", "enum"),
            _p(rf"^\s*(?:[\w@]+\s+)*actor\s+(?P<name>{_ID})", "actor"),
            _p(rf"^\s*(?:[\w@]+\s+)*extension\s+(?P<name>{_ID})", "class"),
        ],
    ),
    "scala": RegexLanguageSpec(
        language="scala",
        extensions=(".scala", ".sc"),
        patterns=[
            _p(rf"^\s*(?:[\w@]+\s+)*def\s+(?P<name>{_ID})", "function"),
            _p(rf"^\s*(?:[\w@]+\s+)*class\s+(?P<name>{_ID})", "class"),
            _p(rf"^\s*(?:[\w@]+\s+)*trait\s+(?P<name>{_ID})", "trait"),
            _p(rf"^\s*(?:[\w@]+\s+)*object\s+(?P<name>{_ID})", "object"),
            _p(rf"^\s*(?:[\w@]+\s+)*case\s+class\s+(?P<name>{_ID})", "class"),
        ],
    ),
    "lua": RegexLanguageSpec(
        language="lua",
        extensions=(".lua",),
        block_style="indent",
        patterns=[
            _p(rf"^\s*(?:local\s+)?function\s+(?:{_ID}[.:])?(?P<name>{_ID})\s*\(", "function"),
            _p(rf"^\s*(?:local\s+)?(?P<name>{_ID})\s*=\s*function\s*\(", "function"),
        ],
    ),
    "elixir": RegexLanguageSpec(
        language="elixir",
        extensions=(".ex", ".exs"),
        block_style="indent",
        patterns=[
            _p(rf"^\s*defp?\s+(?P<name>{_ID}[!?]?)", "function"),
            _p(r"^\s*defmodule\s+(?P<name>[A-Za-z_][\w.]*)", "module"),
        ],
    ),
    "shell": RegexLanguageSpec(
        language="shell",
        extensions=(".sh", ".bash", ".zsh"),
        block_style="brace",
        patterns=[
            _p(rf"^\s*(?:function\s+)?(?P<name>{_ID})\s*\(\s*\)\s*\{{", "function"),
        ],
    ),
}


class RegexParser(BaseParser):
    """Best-effort symbol extraction for languages without an AST grammar."""

    def __init__(self, spec: RegexLanguageSpec) -> None:
        self.spec = spec

    @property
    def language(self) -> str:
        return self.spec.language

    @property
    def supported_extensions(self) -> list[str]:
        return list(self.spec.extensions)

    def parse(self, content: str) -> list[str]:
        return content.split("\n")

    def extract_symbols(self, content: str) -> list[ExtractedSymbol]:
        lines = content.split("\n")
        symbols: list[ExtractedSymbol] = []
        for idx, line in enumerate(lines):
            for pattern in self.spec.patterns:
                match = pattern.regex.match(line)
                if not match:
                    continue
                name = match.group("name")
                if not name:
                    continue
                end_line = self._find_end(lines, idx)
                symbols.append(
                    ExtractedSymbol(
                        name=name,
                        qualified_name=name,
                        symbol_type=pattern.symbol_type,
                        signature=line.strip()[:400],
                        docstring=None,
                        start_line=idx + 1,
                        end_line=end_line + 1,
                        is_exported=not name.startswith("_"),
                    )
                )
                break
        return symbols

    def _find_end(self, lines: list[str], start: int) -> int:
        if self.spec.block_style == "brace":
            return self._find_end_brace(lines, start)
        return self._find_end_indent(lines, start)

    def _find_end_brace(self, lines: list[str], start: int) -> int:
        depth = 0
        seen_open = False
        for i in range(start, len(lines)):
            for ch in lines[i]:
                if ch == "{":
                    depth += 1
                    seen_open = True
                elif ch == "}":
                    depth -= 1
                    if seen_open and depth <= 0:
                        return i
            if seen_open and depth <= 0 and i > start:
                return i
        return min(start, len(lines) - 1) if lines else start

    def _find_end_indent(self, lines: list[str], start: int) -> int:
        base_indent = len(lines[start]) - len(lines[start].lstrip())
        for i in range(start + 1, len(lines)):
            stripped = lines[i].strip()
            if not stripped:
                continue
            indent = len(lines[i]) - len(lines[i].lstrip())
            if indent <= base_indent:
                return i - 1
        return len(lines) - 1

    def create_code_regions(self, content: str) -> list[CodeRegion]:
        lines = content.split("\n")
        symbols = self.extract_symbols(content)
        regions: list[CodeRegion] = []
        for sym in symbols:
            start = sym.start_line - 1
            end = min(sym.end_line - 1, len(lines) - 1)
            regions.append(
                CodeRegion(
                    content="\n".join(lines[start : end + 1]),
                    start_line=sym.start_line,
                    end_line=sym.end_line,
                    region_type="class" if sym.symbol_type in self.spec.class_types else "function",
                    symbols=[sym.name],
                )
            )
        if not regions and lines:
            regions.append(
                CodeRegion(
                    content=content,
                    start_line=1,
                    end_line=len(lines),
                    region_type="code",
                    symbols=[],
                )
            )
        return regions
