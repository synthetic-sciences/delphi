"""
Code parsing module using tree-sitter.

Provides AST-based code understanding for:
- Symbol extraction (functions, classes, methods)
- AST-aware code chunking
- Language-specific parsing
"""

from synsc.parsing.models import CodeRegion, ExtractedSymbol
from synsc.parsing.registry import ParserRegistry, get_parser_registry

__all__ = [
    "ExtractedSymbol",
    "CodeRegion",
    "ParserRegistry",
    "get_parser_registry",
]
