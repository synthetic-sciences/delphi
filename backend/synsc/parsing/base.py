"""Base classes for language parsers."""

from abc import ABC, abstractmethod
from typing import Any

from synsc.parsing.models import CodeRegion, ExtractedSymbol


class BaseParser(ABC):
    """Abstract base class for language parsers.
    
    Each language parser implements tree-sitter based parsing
    to extract symbols and create semantic code regions.
    """
    
    @property
    @abstractmethod
    def language(self) -> str:
        """Get the language this parser handles.
        
        Returns:
            Language identifier (e.g., 'python', 'javascript')
        """
        pass
    
    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """Get file extensions this parser handles.
        
        Returns:
            List of extensions including dot (e.g., ['.py', '.pyi'])
        """
        pass
    
    @abstractmethod
    def parse(self, content: str) -> Any:
        """Parse source code into AST.
        
        Args:
            content: Source code string
            
        Returns:
            Parsed AST (tree-sitter Tree object)
        """
        pass
    
    @abstractmethod
    def extract_symbols(self, content: str) -> list[ExtractedSymbol]:
        """Extract all symbols from source code.
        
        Extracts functions, classes, methods, and other named
        constructs from the source code.
        
        Args:
            content: Source code string
            
        Returns:
            List of extracted symbols
        """
        pass
    
    @abstractmethod
    def create_code_regions(self, content: str) -> list[CodeRegion]:
        """Split code into semantic regions for chunking.
        
        Creates logical regions that respect code boundaries
        (function/class definitions, import blocks, etc.).
        
        Args:
            content: Source code string
            
        Returns:
            List of code regions
        """
        pass
    
    def is_supported_file(self, file_path: str) -> bool:
        """Check if this parser supports a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            True if this parser can handle the file
        """
        from pathlib import Path
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions
