"""
Base classes for content extractors.

Provides abstract interfaces for extracting structured content
from research papers (citations, equations, code, etc.).
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseExtractor(ABC):
    """Abstract base class for content extractors."""

    @abstractmethod
    def extract(self, text: str, **kwargs) -> list[dict[str, Any]]:
        """Extract structured content from text.

        Args:
            text: Input text to extract from
            **kwargs: Additional extraction parameters

        Returns:
            List of extracted items as dictionaries
        """
        pass

    @abstractmethod
    def get_extractor_name(self) -> str:
        """Get the name of this extractor.

        Returns:
            Extractor name
        """
        pass

    def extract_from_paper(self, paper_dict: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract from a structured paper dictionary.

        Args:
            paper_dict: Paper data with full_text, sections, etc.

        Returns:
            List of extracted items
        """
        # Default implementation uses full_text
        full_text = paper_dict.get("normalized_text") or paper_dict.get("full_text", "")
        return self.extract(full_text)


class ExtractionResult:
    """Result of an extraction operation."""

    def __init__(
        self,
        extractor_name: str,
        items: list[dict[str, Any]],
        success: bool = True,
        error: str | None = None,
    ):
        """Initialize extraction result.

        Args:
            extractor_name: Name of extractor
            items: Extracted items
            success: Whether extraction succeeded
            error: Error message if failed
        """
        self.extractor_name = extractor_name
        self.items = items
        self.success = success
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "extractor": self.extractor_name,
            "items": self.items,
            "count": len(self.items),
            "success": self.success,
            "error": self.error,
        }
