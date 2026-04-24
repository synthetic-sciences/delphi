"""ArXiv paper integration for downloading and fetching metadata."""

import re
import time
from pathlib import Path
from typing import Any

import arxiv
import httpx

from synsc.config import get_config


class ArxivError(Exception):
    """Base exception for ArXiv-related errors."""
    pass


class ArxivNotFoundError(ArxivError):
    """Raised when an ArXiv paper is not found."""
    pass


class ArxivDownloadError(ArxivError):
    """Raised when PDF download fails."""
    pass


def parse_arxiv_id(arxiv_input: str) -> str:
    """Parse ArXiv ID from various input formats.

    Accepts:
    - Plain ID: "2301.07041"
    - ArXiv URL: "https://arxiv.org/abs/2301.07041"
    - PDF URL: "https://arxiv.org/pdf/2301.07041.pdf"

    Args:
        arxiv_input: ArXiv ID or URL

    Returns:
        Normalized ArXiv ID

    Raises:
        ArxivError: If input format is invalid
    """
    # Remove whitespace
    arxiv_input = arxiv_input.strip()

    # Check if it's a URL
    if arxiv_input.startswith(("http://", "https://")):
        # Extract ID from URL
        # Pattern matches: arxiv.org/abs/ID or arxiv.org/pdf/ID.pdf
        match = re.search(r"arxiv\.org/(abs|pdf)/([0-9.]+)", arxiv_input)
        if match:
            return match.group(2)
        else:
            raise ArxivError(f"Invalid ArXiv URL format: {arxiv_input}")

    # Check if it's a valid ArXiv ID format
    # ArXiv IDs are either YYMM.NNNNN or archive/YYMMNNN format
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", arxiv_input) or re.match(
        r"^[a-z\-]+/\d{7}(v\d+)?$", arxiv_input
    ):
        return arxiv_input

    raise ArxivError(f"Invalid ArXiv ID format: {arxiv_input}")


def get_arxiv_metadata(arxiv_id: str) -> dict[str, Any]:
    """Fetch metadata for an ArXiv paper.

    Args:
        arxiv_id: ArXiv paper ID

    Returns:
        Dictionary containing paper metadata:
        - title: Paper title
        - authors: List of author names
        - abstract: Paper abstract
        - published_date: Publication date (ISO format)
        - arxiv_url: URL to ArXiv page
        - pdf_url: URL to PDF
        - categories: List of ArXiv categories
        - doi: DOI if available

    Raises:
        ArxivNotFoundError: If paper not found
        ArxivError: If metadata fetch fails
    """
    try:
        # Use arxiv library to fetch metadata
        search = arxiv.Search(id_list=[arxiv_id], max_results=1)
        result = next(search.results(), None)

        if result is None:
            raise ArxivNotFoundError(f"ArXiv paper not found: {arxiv_id}")

        # Extract metadata
        metadata = {
            "title": result.title,
            "authors": [author.name for author in result.authors],
            "abstract": result.summary,
            "published_date": result.published.isoformat(),
            "arxiv_url": result.entry_id,
            "pdf_url": result.pdf_url,
            "categories": result.categories,
            "doi": result.doi if hasattr(result, "doi") else None,
            "primary_category": result.primary_category,
            "comment": result.comment if hasattr(result, "comment") else None,
            "journal_ref": result.journal_ref if hasattr(result, "journal_ref") else None,
        }

        return metadata

    except StopIteration:
        raise ArxivNotFoundError(f"ArXiv paper not found: {arxiv_id}")
    except Exception as e:
        if isinstance(e, (ArxivNotFoundError, ArxivError)):
            raise
        raise ArxivError(f"Failed to fetch ArXiv metadata: {str(e)}") from e


def download_arxiv_pdf(
    arxiv_id: str, output_path: Path | str, max_retries: int = 3
) -> Path:
    """Download PDF for an ArXiv paper.

    Args:
        arxiv_id: ArXiv paper ID
        output_path: Path to save PDF
        max_retries: Maximum number of retry attempts

    Returns:
        Path to downloaded PDF

    Raises:
        ArxivDownloadError: If download fails
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    retry_delay = 2.0
    timeout = 60.0

    # Construct PDF URL
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    # Try downloading with retries
    last_error = None
    for attempt in range(max_retries):
        try:
            # Download PDF
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.get(pdf_url)
                response.raise_for_status()

                # Write to file
                with open(output_path, "wb") as f:
                    f.write(response.content)

                return output_path

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ArxivDownloadError(f"PDF not found for ArXiv ID: {arxiv_id}")
            last_error = e
        except Exception as e:
            last_error = e

        # Wait before retrying (except on last attempt)
        if attempt < max_retries - 1:
            time.sleep(retry_delay)

    # All retries failed
    raise ArxivDownloadError(
        f"Failed to download PDF after {max_retries} attempts: {str(last_error)}"
    ) from last_error


class ArxivPaper:
    """Convenience class for ArXiv paper operations."""

    def __init__(self, arxiv_input: str):
        """Initialize with ArXiv ID or URL.

        Args:
            arxiv_input: ArXiv ID or URL
        """
        self.arxiv_id = parse_arxiv_id(arxiv_input)
        self._metadata: dict[str, Any] | None = None

    @property
    def metadata(self) -> dict[str, Any]:
        """Get paper metadata (cached after first fetch).

        Returns:
            Metadata dictionary
        """
        if self._metadata is None:
            self._metadata = get_arxiv_metadata(self.arxiv_id)
        return self._metadata

    def download_pdf(self, output_path: Path | str) -> Path:
        """Download paper PDF.

        Args:
            output_path: Path to save PDF

        Returns:
            Path to downloaded PDF
        """
        return download_arxiv_pdf(self.arxiv_id, output_path)

    def __repr__(self) -> str:
        """String representation."""
        return f"ArxivPaper(arxiv_id='{self.arxiv_id}')"
