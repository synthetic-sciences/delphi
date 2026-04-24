"""
Citation extraction from research papers.

Extracts various citation formats:
- Numbered: [1], [2], [3-5]
- Author-year: (Smith et al., 2020), (Jones and Brown, 2019)
- Superscript numbers: ¹, ², ³
"""

import re
from typing import Any

from synsc.extractors.base import BaseExtractor


class CitationExtractor(BaseExtractor):
    """Extracts citations from research paper text."""

    def get_extractor_name(self) -> str:
        """Get extractor name."""
        return "citation"

    def extract(self, text: str, **kwargs) -> list[dict[str, Any]]:
        """Extract citations from text.

        Args:
            text: Full paper text
            **kwargs: Additional parameters

        Returns:
            List of citation dictionaries with:
            - citation_text: The citation marker
            - citation_context: Surrounding text
            - citation_number: Numeric identifier if available
            - citation_type: 'numbered', 'author_year', 'superscript'
        """
        citations = []

        # 1. Extract numbered citations [1], [2], [3-5]
        citations.extend(self._extract_numbered_citations(text))

        # 2. Extract author-year citations (Smith et al., 2020)
        citations.extend(self._extract_author_year_citations(text))

        # 3. Extract superscript citations¹ ² ³
        citations.extend(self._extract_superscript_citations(text))

        # Deduplicate by citation_text
        seen = set()
        unique_citations = []
        for cit in citations:
            key = (cit["citation_text"], cit["citation_type"])
            if key not in seen:
                seen.add(key)
                unique_citations.append(cit)

        return unique_citations

    def _extract_numbered_citations(self, text: str) -> list[dict[str, Any]]:
        """Extract numbered citations like [1], [2], [3-5]."""
        citations = []

        # Multiple patterns to handle different PDF extraction quirks
        patterns = [
            r"\[(\d+(?:\s*[-–]\s*\d+)?)\]",           # Standard: [1], [3-5], [3–5]
            r"\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]",         # Comma-separated: [1, 2, 3]
            r"[\uff3b](\d+(?:-\d+)?)[\uff3d]",         # Unicode fullwidth brackets ［1］
        ]

        seen = set()
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                citation_text = match.group(0)
                citation_num = match.group(1).strip()

                # Skip if likely a table cell, list index, or footnote marker
                # by checking if it's at the start of a line (reference list entry)
                pos = match.start()
                line_start = text.rfind('\n', 0, pos) + 1
                prefix = text[line_start:pos].strip()

                # Deduplicate by position
                if pos in seen:
                    continue
                seen.add(pos)

                # Get context (80 chars before and after)
                start = max(0, match.start() - 80)
                end = min(len(text), match.end() + 80)
                context = text[start:end].strip()

                citations.append(
                    {
                        "citation_text": citation_text,
                        "citation_number": citation_num,
                        "citation_context": context,
                        "citation_type": "numbered",
                    }
                )

        return citations

    def _extract_author_year_citations(self, text: str) -> list[dict[str, Any]]:
        """Extract author-year citations like (Smith et al., 2020)."""
        citations = []

        # Pattern: (Author(s) et al., YEAR) or (Author and Author, YEAR)
        patterns = [
            r"\(([A-Z][a-z]+(?:\s+et\s+al\.?)?),?\s+(\d{4}[a-z]?)\)",  # (Smith et al., 2020)
            r"\(([A-Z][a-z]+\s+and\s+[A-Z][a-z]+),?\s+(\d{4}[a-z]?)\)",  # (Smith and Jones, 2020)
            r"\(([A-Z][a-z]+),?\s+(\d{4}[a-z]?)\)",  # (Smith, 2020)
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text):
                citation_text = match.group(0)
                author = match.group(1)
                year = match.group(2)

                # Get context
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context = text[start:end].strip()

                citations.append(
                    {
                        "citation_text": citation_text,
                        "citation_number": None,
                        "citation_context": context,
                        "citation_type": "author_year",
                        "author": author,
                        "year": year,
                    }
                )

        return citations

    def _extract_superscript_citations(self, text: str) -> list[dict[str, Any]]:
        """Extract superscript number citations¹ ² ³."""
        citations = []

        # Superscript number characters
        superscript_map = {
            "¹": "1",
            "²": "2",
            "³": "3",
            "⁴": "4",
            "⁵": "5",
            "⁶": "6",
            "⁷": "7",
            "⁸": "8",
            "⁹": "9",
            "⁰": "0",
        }

        pattern = r"[¹²³⁴⁵⁶⁷⁸⁹⁰]+"

        for match in re.finditer(pattern, text):
            citation_text = match.group(0)

            # Convert superscript to regular numbers
            citation_num = "".join(superscript_map.get(c, c) for c in citation_text)

            # Get context
            start = max(0, match.start() - 50)
            end = min(len(text), match.end() + 50)
            context = text[start:end].strip()

            citations.append(
                {
                    "citation_text": citation_text,
                    "citation_number": citation_num,
                    "citation_context": context,
                    "citation_type": "superscript",
                }
            )

        return citations

    def extract_references_section(self, text: str) -> list[dict[str, Any]]:
        """Extract full reference list from References section.

        Args:
            text: Full paper text

        Returns:
            List of reference dictionaries
        """
        references = []

        # Find References section
        ref_pattern = (
            r"(?i)\n\s*(references|bibliography)\s*\n+(.*?)(?=\n\s*(?:appendix|$))"
        )
        match = re.search(ref_pattern, text, re.DOTALL)

        if not match:
            return references

        ref_section = match.group(2)

        # Split by numbered references [1], [2], etc or line-based
        # Pattern 1: [number] Author. Title. ...
        numbered_pattern = r"\[(\d+)\]\s*([^\n]+(?:\n(?!\[\d+\])[^\n]+)*)"

        for ref_match in re.finditer(numbered_pattern, ref_section):
            ref_num = ref_match.group(1)
            ref_text = ref_match.group(2).strip()
            ref_text = re.sub(r"\s+", " ", ref_text)  # Normalize whitespace

            # Try to parse reference components
            ref_data = self._parse_reference(ref_text)
            ref_data["citation_number"] = ref_num

            references.append(ref_data)

        return references

    def _parse_reference(self, ref_text: str) -> dict[str, Any]:
        """Parse a reference string into components.

        Attempts to extract: authors, title, year, journal/conference, etc.

        Args:
            ref_text: Reference text

        Returns:
            Dictionary with extracted components
        """
        result = {"raw_text": ref_text}

        # Try to extract year (4 digits)
        year_match = re.search(r"\b(19|20)\d{2}\b", ref_text)
        if year_match:
            result["year"] = year_match.group(0)

        # Try to extract DOI
        doi_match = re.search(r"doi:\s*(10\.\d+/[^\s]+)", ref_text, re.IGNORECASE)
        if doi_match:
            result["doi"] = doi_match.group(1)

        # Try to extract arXiv ID
        arxiv_match = re.search(r"arXiv:(\d{4}\.\d{4,5})", ref_text)
        if arxiv_match:
            result["arxiv_id"] = arxiv_match.group(1)

        # First sentence-like part is often the title (ends with period)
        # Authors usually come before title
        # This is a simple heuristic - more sophisticated parsing would use ML
        parts = ref_text.split(".")
        if len(parts) >= 2:
            # Assume first part has authors, second part is title
            result["potential_authors"] = parts[0].strip()
            result["potential_title"] = parts[1].strip()

        return result


# Convenience function
def extract_citations(text: str) -> list[dict[str, Any]]:
    """Extract citations from text using default extractor.

    Args:
        text: Paper text

    Returns:
        List of citations
    """
    extractor = CitationExtractor()
    return extractor.extract(text)
