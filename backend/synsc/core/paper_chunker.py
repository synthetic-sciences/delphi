"""
Smart text chunking for research papers.

Section-aware chunking that preserves semantic boundaries.
"""

import re
from dataclasses import dataclass
from typing import Any

import tiktoken

from synsc.core.pdf_processor import ExtractedPaper


@dataclass
class TextChunk:
    """Represents a chunk of text from a paper."""
    content: str
    chunk_index: int
    section_title: str | None = None
    chunk_type: str = "section"
    page_number: int | None = None
    token_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "chunk_index": self.chunk_index,
            "section_title": self.section_title,
            "chunk_type": self.chunk_type,
            "page_number": self.page_number,
            "token_count": self.token_count,
        }

    def get_text_with_context(self) -> str:
        """Get chunk text with section title as context."""
        if self.section_title:
            return f"Section: {self.section_title}\n\n{self.content}"
        return self.content


def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """Count tokens in text using tiktoken."""
    try:
        encoding = tiktoken.get_encoding(model)
        return len(encoding.encode(text))
    except Exception:
        # Fallback: rough estimate (1 token ≈ 0.75 words)
        return int(len(text.split()) * 1.3)


def split_text_by_tokens(
    text: str, max_tokens: int, overlap_tokens: int = 0
) -> list[str]:
    """Split text into chunks by token count."""
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)

    chunks = []
    start = 0

    while start < len(tokens):
        end = start + max_tokens
        chunk_tokens = tokens[start:end]
        chunk_text = encoding.decode(chunk_tokens)
        chunks.append(chunk_text)
        start = end - overlap_tokens

    return chunks


def split_by_paragraphs(
    text: str, max_tokens: int, overlap_tokens: int = 0
) -> list[str]:
    """Split text by paragraphs, respecting max token limit."""
    paragraphs = re.split(r"\n\s*\n", text)

    chunks = []
    current_chunk = []
    current_tokens = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        para_tokens = count_tokens(para)

        if para_tokens > max_tokens:
            # Save current chunk
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_tokens = 0

            # Split long paragraph
            para_chunks = split_text_by_tokens(para, max_tokens, overlap_tokens)
            chunks.extend(para_chunks)
            continue

        if current_tokens + para_tokens > max_tokens and current_chunk:
            # Save current chunk
            chunks.append("\n\n".join(current_chunk))
            current_chunk = []
            current_tokens = 0

        current_chunk.append(para)
        current_tokens += para_tokens

    # Add remaining chunk
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks


def chunk_markdown(
    markdown_text: str,
    max_tokens: int = 1024,
    overlap_tokens: int = 50,
    description: str | None = None,
) -> list[TextChunk]:
    """Chunk a markdown document into semantic units.

    Used for dataset cards and other markdown documentation.
    Splits by markdown headers, then by paragraphs within sections.

    Args:
        markdown_text: Raw markdown content
        max_tokens: Maximum tokens per chunk
        overlap_tokens: Token overlap between chunks
        description: Optional short description to include as chunk 0

    Returns:
        List of TextChunk objects
    """
    chunks: list[TextChunk] = []
    chunk_index = 0

    # Optional description as first chunk
    if description and description.strip():
        desc_text = description.strip()
        desc_tokens = count_tokens(desc_text)
        if desc_tokens > 0:
            chunks.append(
                TextChunk(
                    content=desc_text,
                    chunk_index=chunk_index,
                    section_title="Description",
                    chunk_type="description",
                    token_count=desc_tokens,
                )
            )
            chunk_index += 1

    if not markdown_text or not markdown_text.strip():
        return chunks

    # Strip YAML front matter
    text = re.sub(r"^---\s*\n.*?\n---\s*\n", "", markdown_text, flags=re.DOTALL).strip()
    if not text:
        return chunks

    # Split by markdown headers (##, ###, etc.)
    # This produces alternating [text_before, header, text_after, header, text_after, ...]
    parts = re.split(r"^(#{1,3}\s+.+)$", text, flags=re.MULTILINE)

    # Group into (title, content) pairs
    sections: list[tuple[str | None, str]] = []
    if parts[0].strip():
        # Text before any header
        sections.append((None, parts[0].strip()))

    i = 1
    while i < len(parts):
        title = parts[i].lstrip("#").strip() if i < len(parts) else None
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if content:
            sections.append((title, content))
        i += 2

    for title, content in sections:
        section_tokens = count_tokens(content)

        if section_tokens <= max_tokens:
            if section_tokens > 0:
                chunks.append(
                    TextChunk(
                        content=content,
                        chunk_index=chunk_index,
                        section_title=title,
                        chunk_type="section",
                        token_count=section_tokens,
                    )
                )
                chunk_index += 1
        else:
            # Split long section by paragraphs
            section_chunks = split_by_paragraphs(content, max_tokens, overlap_tokens)
            for part_text in section_chunks:
                part_tokens = count_tokens(part_text)
                if part_tokens > 0:
                    chunks.append(
                        TextChunk(
                            content=part_text,
                            chunk_index=chunk_index,
                            section_title=title,
                            chunk_type="section",
                            token_count=part_tokens,
                        )
                    )
                    chunk_index += 1

    return chunks


def chunk_paper(
    paper: ExtractedPaper,
    max_tokens: int = 1024,
    abstract_max_tokens: int = 512,
    overlap_tokens: int = 50,
    include_metadata: bool = True,
) -> list[TextChunk]:
    """Chunk a paper into semantic units.

    Args:
        paper: Extracted paper content
        max_tokens: Maximum tokens per section chunk
        abstract_max_tokens: Maximum tokens for abstract chunks
        overlap_tokens: Tokens to overlap
        include_metadata: Whether to include abstract/metadata chunks

    Returns:
        List of TextChunk objects
    """
    chunks = []
    chunk_index = 0

    # 1. Abstract as separate chunk (if exists and not too long)
    if include_metadata and paper.abstract:
        abstract_tokens = count_tokens(paper.abstract)
        if abstract_tokens <= abstract_max_tokens:
            chunks.append(
                TextChunk(
                    content=paper.abstract,
                    chunk_index=chunk_index,
                    section_title="Abstract",
                    chunk_type="abstract",
                    token_count=abstract_tokens,
                )
            )
            chunk_index += 1
        else:
            # Split long abstract
            for text in split_by_paragraphs(
                paper.abstract, abstract_max_tokens, overlap_tokens
            ):
                chunks.append(
                    TextChunk(
                        content=text,
                        chunk_index=chunk_index,
                        section_title="Abstract",
                        chunk_type="abstract",
                        token_count=count_tokens(text),
                    )
                )
                chunk_index += 1

    # 2. Chunk each section
    for section in paper.sections:
        section_tokens = count_tokens(section.content)

        if section_tokens <= max_tokens:
            # Section fits in one chunk
            chunks.append(
                TextChunk(
                    content=section.content,
                    chunk_index=chunk_index,
                    section_title=section.title,
                    chunk_type="section",
                    page_number=section.page,
                    token_count=section_tokens,
                )
            )
            chunk_index += 1
        else:
            # Split long section by paragraphs
            section_chunks = split_by_paragraphs(
                section.content, max_tokens, overlap_tokens
            )
            for text in section_chunks:
                chunks.append(
                    TextChunk(
                        content=text,
                        chunk_index=chunk_index,
                        section_title=section.title,
                        chunk_type="section",
                        page_number=section.page,
                        token_count=count_tokens(text),
                    )
                )
                chunk_index += 1

    # 3. Figure captions as separate small chunks (optional)
    if include_metadata:
        for fig in paper.figures:
            caption = f"Figure {fig['number']}: {fig['caption']}"
            fig_tokens = count_tokens(caption)
            if fig_tokens <= max_tokens:
                chunks.append(
                    TextChunk(
                        content=caption,
                        chunk_index=chunk_index,
                        section_title=f"Figure {fig['number']}",
                        chunk_type="figure",
                        token_count=fig_tokens,
                    )
                )
                chunk_index += 1

    return chunks
