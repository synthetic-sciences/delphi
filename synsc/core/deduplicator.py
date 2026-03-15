"""
Global deduplication for research papers (Trynia-style).

Implements hash-based deduplication where one paper = one database entry,
shared across all users. Users get instant access to already-indexed papers.
"""

from typing import Any

from synsc.core.pdf_processor import calculate_pdf_hash


class DeduplicationResult:
    """Result of deduplication check."""

    def __init__(
        self,
        is_duplicate: bool,
        paper_id: str | None = None,
        title: str | None = None,
        message: str | None = None,
    ):
        """Initialize deduplication result.

        Args:
            is_duplicate: Whether paper is already indexed
            paper_id: Existing paper ID if duplicate
            title: Title of existing paper
            message: Human-readable message
        """
        self.is_duplicate = is_duplicate
        self.paper_id = paper_id
        self.title = title
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "is_duplicate": self.is_duplicate,
            "paper_id": self.paper_id,
            "title": self.title,
            "message": self.message,
        }


def check_duplicate_by_hash(pdf_hash: str, paper_repository) -> DeduplicationResult:
    """Check if paper with given hash already exists.

    This is the core of Trynia-style deduplication: one paper = one entry
    in the database, shared across all users.

    Args:
        pdf_hash: SHA-256 hash of PDF file
        paper_repository: Repository to check against

    Returns:
        DeduplicationResult indicating if paper exists
    """
    # Query database for existing paper with this hash
    existing_paper = paper_repository.get_by_pdf_hash(pdf_hash)

    if existing_paper:
        return DeduplicationResult(
            is_duplicate=True,
            paper_id=existing_paper.paper_id,
            title=existing_paper.title,
            message=f"Paper already indexed: {existing_paper.title}",
        )

    return DeduplicationResult(
        is_duplicate=False,
        message="Paper not found in index, ready to index",
    )


def check_duplicate_by_arxiv_id(arxiv_id: str, paper_repository) -> DeduplicationResult:
    """Check if paper with given arXiv ID already exists.

    Args:
        arxiv_id: arXiv identifier
        paper_repository: Repository to check against

    Returns:
        DeduplicationResult indicating if paper exists
    """
    existing_paper = paper_repository.get_by_arxiv_id(arxiv_id)

    if existing_paper:
        return DeduplicationResult(
            is_duplicate=True,
            paper_id=existing_paper.paper_id,
            title=existing_paper.title,
            message=f"arXiv paper already indexed: {existing_paper.title}",
        )

    return DeduplicationResult(
        is_duplicate=False,
        message="arXiv paper not found in index, ready to index",
    )


def get_or_create_paper_id(
    pdf_path: str,
    arxiv_id: str | None,
    paper_repository,
    user_paper_repository,
    user_id: str,
) -> tuple[str, bool]:
    """Get existing paper ID or indicate need to create new one.

    This implements the Trynia workflow:
    1. Check if paper exists (by hash or arXiv ID)
    2. If exists: Grant user access, return existing paper_id
    3. If new: Indicate needs indexing

    Args:
        pdf_path: Path to PDF file
        arxiv_id: arXiv ID if applicable
        paper_repository: Paper repository
        user_paper_repository: User-paper access repository
        user_id: User requesting access

    Returns:
        Tuple of (paper_id, is_new)
        - is_new=True: Paper needs to be indexed
        - is_new=False: Paper exists, user access granted
    """
    # First check by arXiv ID if available
    if arxiv_id:
        result = check_duplicate_by_arxiv_id(arxiv_id, paper_repository)
        if result.is_duplicate:
            # Grant user access
            user_paper_repository.grant_access(
                user_id=user_id,
                paper_id=result.paper_id,
                access_level="viewer",
            )
            return result.paper_id, False

    # Check by PDF hash
    pdf_hash = calculate_pdf_hash(pdf_path)
    result = check_duplicate_by_hash(pdf_hash, paper_repository)

    if result.is_duplicate:
        # Grant user access
        user_paper_repository.grant_access(
            user_id=user_id,
            paper_id=result.paper_id,
            access_level="viewer",
        )
        return result.paper_id, False

    # Paper is new, needs indexing
    return None, True
