"""Parser registry for managing language parsers."""

from pathlib import Path

import structlog

from synsc.parsing.base import BaseParser

logger = structlog.get_logger(__name__)


class ParserRegistry:
    """Registry for language parsers.
    
    Singleton that manages parser instances and provides
    lookup by language or file extension.
    """
    
    _instance: "ParserRegistry | None" = None
    
    def __new__(cls) -> "ParserRegistry":
        """Create or return singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._parsers = {}
            cls._instance._extension_map = {}
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        """Initialize the registry (only runs once)."""
        if not self._initialized:
            self._initialize()
            self._initialized = True
    
    def _initialize(self) -> None:
        """Initialize available parsers."""
        # Import and register Python parser
        try:
            from synsc.parsing.python_parser import PythonParser
            self.register(PythonParser())
            logger.info("Python parser registered")
        except ImportError as e:
            logger.warning(
                "Python parser not available - install tree-sitter-python",
                error=str(e),
            )
        except Exception as e:
            logger.warning("Failed to initialize Python parser", error=str(e))
        
        # JavaScript parser
        try:
            from synsc.parsing.typescript_parser import JavaScriptParser
            self.register(JavaScriptParser())
            logger.info("JavaScript parser registered")
        except ImportError as e:
            logger.warning(
                "JavaScript parser not available - install tree-sitter-javascript",
                error=str(e),
            )
        except Exception as e:
            logger.warning("Failed to initialize JavaScript parser", error=str(e))
        
        # TypeScript parser
        try:
            from synsc.parsing.typescript_parser import TypeScriptParser
            self.register(TypeScriptParser())
            logger.info("TypeScript parser registered")
        except ImportError as e:
            logger.warning(
                "TypeScript parser not available - install tree-sitter-typescript",
                error=str(e),
            )
        except Exception as e:
            logger.warning("Failed to initialize TypeScript parser", error=str(e))
    
    def register(self, parser: BaseParser) -> None:
        """Register a parser.
        
        Args:
            parser: Parser instance to register
        """
        self._parsers[parser.language] = parser
        for ext in parser.supported_extensions:
            self._extension_map[ext.lower()] = parser.language
        logger.debug(
            "Registered parser",
            language=parser.language,
            extensions=parser.supported_extensions,
        )
    
    def get_parser(self, language: str) -> BaseParser | None:
        """Get parser for a language.
        
        Args:
            language: Language identifier (e.g., 'python')
            
        Returns:
            Parser instance or None if not available
        """
        return self._parsers.get(language)
    
    def get_parser_for_file(self, file_path: str) -> BaseParser | None:
        """Get parser for a file based on extension.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Parser instance or None if not available
        """
        ext = Path(file_path).suffix.lower()
        language = self._extension_map.get(ext)
        if language:
            return self._parsers.get(language)
        return None
    
    @property
    def supported_languages(self) -> list[str]:
        """Get list of supported languages.
        
        Returns:
            List of language identifiers
        """
        return list(self._parsers.keys())
    
    @property
    def supported_extensions(self) -> list[str]:
        """Get list of supported file extensions.
        
        Returns:
            List of extensions including dot
        """
        return list(self._extension_map.keys())
    
    def has_parser(self, language: str) -> bool:
        """Check if a parser is available for a language.
        
        Args:
            language: Language identifier
            
        Returns:
            True if parser is available
        """
        return language in self._parsers


# Global registry instance
_registry: ParserRegistry | None = None


def get_parser_registry() -> ParserRegistry:
    """Get the global parser registry.
    
    Returns:
        ParserRegistry singleton instance
    """
    global _registry
    if _registry is None:
        _registry = ParserRegistry()
    return _registry
