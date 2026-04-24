"""Code chunking for semantic search."""

import hashlib
import re
from dataclasses import dataclass

import structlog
import tiktoken

from synsc.config import get_config

logger = structlog.get_logger(__name__)


@dataclass
class CodeChunk:
    """A chunk of code for indexing."""
    
    content: str
    start_line: int
    end_line: int
    chunk_type: str  # code, docstring, comment, import
    token_count: int


class CodeChunker:
    """Chunk code files for semantic search."""

    def __init__(self):
        """Initialize the chunker."""
        config = get_config()
        self.max_tokens = config.chunking.max_tokens
        self.overlap_tokens = config.chunking.overlap_tokens
        self.min_chunk_tokens = config.chunking.min_chunk_tokens
        self.respect_boundaries = config.chunking.respect_boundaries
        
        # Use cl100k_base tokenizer (GPT-4 tokenizer)
        self._tokenizer = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self._tokenizer.encode(text))

    def chunk_file(
        self,
        content: str,
        language: str | None = None,
        symbol_boundaries: list[tuple[int, int]] | None = None,
    ) -> list[CodeChunk]:
        """Chunk a file's content.

        Args:
            content: File content
            language: Programming language
            symbol_boundaries: Optional list of (start_line, end_line) tuples
                from tree-sitter symbol extraction. When provided, the chunker
                prefers splitting at symbol boundaries instead of arbitrary lines.

        Returns:
            List of CodeChunk objects
        """
        lines = content.split("\n")

        if not lines:
            return []

        # Build a set of lines where symbols START (1-indexed).
        # These are preferred split points — the line just before a new
        # function/class definition is a natural chunk boundary.
        boundary_lines: set[int] = set()
        if symbol_boundaries:
            for start_line, _end_line in symbol_boundaries:
                if start_line > 1:
                    boundary_lines.add(start_line)

        # Token-based chunking that prefers symbol boundaries
        chunks = []
        current_chunk_lines: list[str] = []
        current_start_line = 1
        current_tokens = 0

        # When we pass this threshold, start looking for a boundary to split at.
        # This gives a ~25% window to find a good boundary before hard-splitting.
        soft_limit = int(self.max_tokens * 0.75)
        seeking_boundary = False

        for i, line in enumerate(lines, start=1):
            line_tokens = self.count_tokens(line + "\n")

            # Hard limit — must split now regardless of boundaries
            if current_tokens + line_tokens > self.max_tokens and current_chunk_lines:
                chunk_content = "\n".join(current_chunk_lines)
                if current_tokens >= self.min_chunk_tokens:
                    chunks.append(CodeChunk(
                        content=chunk_content,
                        start_line=current_start_line,
                        end_line=i - 1,
                        chunk_type=self._detect_chunk_type(chunk_content, language),
                        token_count=current_tokens,
                    ))

                overlap_lines = self._get_overlap_lines(current_chunk_lines)
                current_chunk_lines = overlap_lines
                current_tokens = self.count_tokens("\n".join(overlap_lines))
                current_start_line = i - len(overlap_lines)
                seeking_boundary = False

            # Soft limit — if we hit a symbol boundary, split here
            elif (
                seeking_boundary
                and i in boundary_lines
                and current_tokens >= self.min_chunk_tokens
            ):
                chunk_content = "\n".join(current_chunk_lines)
                chunks.append(CodeChunk(
                    content=chunk_content,
                    start_line=current_start_line,
                    end_line=i - 1,
                    chunk_type=self._detect_chunk_type(chunk_content, language),
                    token_count=current_tokens,
                ))

                overlap_lines = self._get_overlap_lines(current_chunk_lines)
                current_chunk_lines = overlap_lines
                current_tokens = self.count_tokens("\n".join(overlap_lines))
                current_start_line = i - len(overlap_lines)
                seeking_boundary = False

            current_chunk_lines.append(line)
            current_tokens += line_tokens

            # Start looking for a boundary once we pass the soft limit
            if not seeking_boundary and current_tokens >= soft_limit and boundary_lines:
                seeking_boundary = True

        # Don't forget the last chunk
        if current_chunk_lines:
            chunk_content = "\n".join(current_chunk_lines)
            if self.count_tokens(chunk_content) >= self.min_chunk_tokens:
                chunks.append(CodeChunk(
                    content=chunk_content,
                    start_line=current_start_line,
                    end_line=len(lines),
                    chunk_type=self._detect_chunk_type(chunk_content, language),
                    token_count=self.count_tokens(chunk_content),
                ))

        logger.debug(
            "Chunked file",
            total_lines=len(lines),
            chunks=len(chunks),
            boundary_aware=bool(boundary_lines),
        )

        return chunks

    def _get_overlap_lines(self, lines: list[str]) -> list[str]:
        """Get lines for overlap."""
        if not lines:
            return []
        
        overlap_tokens = 0
        overlap_lines = []
        
        for line in reversed(lines):
            line_tokens = self.count_tokens(line + "\n")
            if overlap_tokens + line_tokens > self.overlap_tokens:
                break
            overlap_lines.insert(0, line)
            overlap_tokens += line_tokens
        
        return overlap_lines

    def _detect_chunk_type(self, content: str, language: str | None) -> str:
        """Detect the type of a chunk."""
        content_stripped = content.strip()
        
        # Check for imports
        import_patterns = [
            r"^import\s+",
            r"^from\s+\w+\s+import",
            r"^const\s+\w+\s*=\s*require\(",
            r'^import\s+.*\s+from\s+["\']',
            r"^use\s+",  # Rust
            r"^#include\s*[<\"]",  # C/C++
        ]
        for pattern in import_patterns:
            if re.match(pattern, content_stripped, re.MULTILINE):
                return "import"
        
        # Check for docstrings
        if language == "python" and (
            content_stripped.startswith('"""') or content_stripped.startswith("'''")
        ):
            return "docstring"
        
        # Check for comments
        comment_patterns = [
            r"^\s*/\*",  # Block comment
            r"^\s*//",  # Line comment
            r"^\s*#",  # Hash comment
        ]
        lines = content_stripped.split("\n")
        comment_lines = sum(
            1 for line in lines
            if any(re.match(p, line) for p in comment_patterns)
        )
        if comment_lines > len(lines) * 0.7:
            return "comment"
        
        return "code"

    def compute_hash(self, content: str) -> str:
        """Compute SHA-256 hash of content."""
        return hashlib.sha256(content.encode()).hexdigest()


# =============================================================================
# Paper Chunking
# =============================================================================

@dataclass
class PaperChunk:
    """A chunk of paper text for indexing."""
    
    content: str
    chunk_index: int
    token_count: int
    page_numbers: list[int] | None = None


def chunk_paper(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[dict]:
    """Chunk paper text into overlapping segments.
    
    Args:
        text: Full text of the paper
        chunk_size: Target chunk size in characters
        chunk_overlap: Overlap between chunks in characters
        
    Returns:
        List of chunk dictionaries with 'content' and 'chunk_index' keys
    """
    if not text or not text.strip():
        return []
    
    chunks = []
    text = text.strip()
    
    # Split by paragraphs first for better semantic boundaries
    paragraphs = re.split(r'\n\s*\n', text)
    
    current_chunk = ""
    chunk_index = 0
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        # If adding this paragraph exceeds chunk size
        if len(current_chunk) + len(para) + 2 > chunk_size and current_chunk:
            # Save current chunk
            chunks.append({
                "content": current_chunk.strip(),
                "chunk_index": chunk_index,
            })
            chunk_index += 1
            
            # Start new chunk with overlap
            # Take last N characters as overlap
            if len(current_chunk) > chunk_overlap:
                # Find a good break point (sentence or word boundary)
                overlap_text = current_chunk[-chunk_overlap:]
                # Try to start at a sentence boundary
                sentence_match = re.search(r'[.!?]\s+', overlap_text)
                if sentence_match:
                    overlap_text = overlap_text[sentence_match.end():]
                current_chunk = overlap_text
            else:
                current_chunk = ""
        
        # Add paragraph to current chunk
        if current_chunk:
            current_chunk += "\n\n" + para
        else:
            current_chunk = para
    
    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append({
            "content": current_chunk.strip(),
            "chunk_index": chunk_index,
        })
    
    logger.debug(
        "Chunked paper",
        total_chars=len(text),
        chunks=len(chunks),
        avg_chunk_size=len(text) // max(len(chunks), 1),
    )
    
    return chunks
