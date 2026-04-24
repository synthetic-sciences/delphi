"""Data models for code parsing."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedSymbol:
    """A symbol extracted from source code.
    
    Represents a function, class, method, or other named code construct.
    """
    
    name: str
    """Simple name of the symbol (e.g., 'my_function')."""
    
    qualified_name: str
    """Fully qualified name (e.g., 'MyClass.my_method')."""
    
    symbol_type: str
    """Type of symbol: 'function', 'class', 'method', 'variable', 'constant', 'type', 'interface'."""
    
    start_line: int
    """Starting line number (1-indexed)."""
    
    end_line: int
    """Ending line number (1-indexed)."""
    
    signature: str | None = None
    """Function/class signature (declaration line(s))."""
    
    docstring: str | None = None
    """Documentation string if present."""
    
    is_exported: bool = False
    """Whether this symbol is exported/public."""
    
    is_async: bool = False
    """Whether this is an async function/method."""
    
    parameters: list[dict[str, Any]] | None = None
    """Function parameters: [{'name': str, 'type': str|None, 'default': str|None}]."""
    
    return_type: str | None = None
    """Return type annotation if present."""
    
    decorators: list[str] | None = None
    """List of decorator names/expressions."""
    
    children: list["ExtractedSymbol"] = field(default_factory=list)
    """Child symbols (methods in a class)."""
    
    parent_name: str | None = None
    """Name of parent symbol (class name for methods)."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "symbol_type": self.symbol_type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signature": self.signature,
            "docstring": self.docstring,
            "is_exported": self.is_exported,
            "is_async": self.is_async,
            "parameters": self.parameters,
            "return_type": self.return_type,
            "decorators": self.decorators,
            "parent_name": self.parent_name,
        }


@dataclass
class CodeRegion:
    """A semantic region of code for AST-aware chunking.
    
    Represents a logical unit of code that should be kept together
    when chunking (e.g., a complete function or class).
    """
    
    content: str
    """The source code content of this region."""
    
    start_line: int
    """Starting line number (1-indexed)."""
    
    end_line: int
    """Ending line number (1-indexed)."""
    
    region_type: str
    """Type of region: 'imports', 'function', 'class', 'module_docstring', 'code'."""
    
    symbols: list[str] = field(default_factory=list)
    """Names of symbols contained in this region."""
    
    token_count: int | None = None
    """Token count for this region (set during chunking)."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "start_line": self.start_line,
            "end_line": self.end_line,
            "region_type": self.region_type,
            "symbols": self.symbols,
            "token_count": self.token_count,
        }
