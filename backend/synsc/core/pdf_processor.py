"""
Advanced PDF processing for research papers.

Extracts:
- Title, authors, abstract
- Sections with structure
- Figures and tables
- Full text for chunking
"""

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


class PDFProcessingError(Exception):
    """Base exception for PDF processing errors."""
    pass


class PDFSection:
    """Represents a section of a research paper."""

    def __init__(
        self,
        title: str,
        content: str,
        level: int = 1,
        page: int | None = None,
        section_number: str | None = None,
    ):
        self.title = title
        self.content = content
        self.level = level
        self.page = page
        self.section_number = section_number
        self.subsections: list["PDFSection"] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "level": self.level,
            "page": self.page,
            "section_number": self.section_number,
            "subsections": [sub.to_dict() for sub in self.subsections],
        }


class ExtractedPaper:
    """Represents extracted content from a research paper PDF."""

    def __init__(self):
        self.title: str | None = None
        self.authors: list[str] = []
        self.abstract: str | None = None
        self.sections: list[PDFSection] = []
        self.figures: list[dict[str, Any]] = []
        self.tables: list[dict[str, Any]] = []
        self.references: list[str] = []
        self.full_text: str = ""
        self.normalized_text: str = ""
        self.metadata: dict[str, Any] = {}
        self.page_count: int = 0
        self.pdf_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "sections": [section.to_dict() for section in self.sections],
            "figures": self.figures,
            "tables": self.tables,
            "references": self.references,
            "full_text": self.full_text,
            "normalized_text": self.normalized_text,
            "metadata": self.metadata,
            "page_count": self.page_count,
            "pdf_hash": self.pdf_hash,
        }


def calculate_pdf_hash(pdf_path: Path | str) -> str:
    """Calculate SHA-256 hash of a PDF file."""
    sha256_hash = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def _strip_nul_chars(text: str) -> str:
    """Remove NUL (0x00) bytes from a string.

    Postgres rejects NUL in ``text`` columns ("A string literal cannot
    contain NUL (0x00) characters."), and PyMuPDF text extraction does
    occasionally emit them on malformed PDFs. Strip them at the boundary
    so downstream chunkers, normalizers, and DB writers all see clean
    text. Logs a warning when any were removed so the truncation isn't
    silent.
    """
    if not text or "\x00" not in text:
        return text
    cleaned = text.replace("\x00", "")
    removed = len(text) - len(cleaned)
    logger.warning(
        "Stripped %d NUL byte(s) from extracted PDF text", removed,
    )
    return cleaned


def normalize_pdf_text(text: str) -> str:
    """Normalize text extracted from PDF.

    - Strip NUL (0x00) bytes (Postgres text columns reject these)
    - Fix hyphenation at line breaks
    - Normalize whitespace
    - Fix common PDF extraction artifacts
    """
    if not text:
        return ""

    # Strip NUL bytes first so the rest of the pipeline (and any DB
    # insert downstream) doesn't have to worry about them.
    text = _strip_nul_chars(text)

    # Fix hyphenation at line breaks (word- \n continuation)
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    
    # Normalize line breaks
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    # Normalize spaces
    text = re.sub(r"[ \t]+", " ", text)
    
    # Fix ligatures
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl")
    text = text.replace("ﬀ", "ff").replace("ﬃ", "ffi").replace("ﬄ", "ffl")
    
    return text.strip()


def extract_title_from_text(text: str) -> str | None:
    """Extract title from paper's first page text."""
    lines = text.split("\n")
    
    # Usually the title is in the first few lines, often the longest non-trivial line
    candidates = []
    for i, line in enumerate(lines[:20]):
        line = line.strip()
        if len(line) > 20 and len(line) < 300:
            # Title lines are usually not all lowercase and don't start with numbers
            if not line[0].isdigit() and not line.islower():
                candidates.append((i, line, len(line)))
    
    if candidates:
        # Return the longest candidate in the first few lines
        candidates.sort(key=lambda x: (-x[2], x[0]))
        return candidates[0][1]
    
    return None


def extract_authors_from_text(text: str) -> list[str]:
    """Extract author names from paper's first page."""
    authors = []
    
    # Look for common author patterns
    # Pattern 1: Names separated by commas, possibly with affiliations
    author_section = re.search(
        r"(?i)(?:^|\n)([A-Z][a-z]+ [A-Z][a-z]+(?:,\s*[A-Z][a-z]+ [A-Z][a-z]+)*)",
        text[:2000]
    )
    
    if author_section:
        author_text = author_section.group(1)
        # Split by comma or "and"
        names = re.split(r",\s*|\s+and\s+", author_text)
        for name in names:
            name = name.strip()
            if name and len(name) > 3 and len(name.split()) >= 2:
                authors.append(name)
    
    return authors[:10]  # Limit to 10 authors


def extract_abstract_from_text(text: str) -> str | None:
    """Extract abstract from paper text."""
    # Look for "Abstract" section
    patterns = [
        r"(?i)\babstract\b[:\s]*\n?(.*?)(?=\n\s*(?:1\.?\s*)?introduction|\n\s*keywords|\n\s*\d+\.)",
        r"(?i)\babstract\b[:\s]*(.*?)(?=\n\n)",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text[:5000], re.DOTALL)
        if match:
            abstract = match.group(1).strip()
            # Clean up
            abstract = re.sub(r"\s+", " ", abstract)
            if len(abstract) > 50:
                return abstract[:2000]  # Limit length
    
    return None


def detect_sections(text: str) -> list[dict]:
    """Detect section structure in paper text."""
    sections = []
    
    # Common section heading patterns
    patterns = [
        # Numbered sections: "1. Introduction", "2.1 Methods"
        r"(?m)^(\d+(?:\.\d+)*)[.\s]+([A-Z][^\n]{3,50})\n",
        # Non-numbered sections: "Introduction", "Methods"
        r"(?m)^([A-Z][A-Z ]{2,30})\n",
    ]
    
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            if len(match.groups()) == 2:
                number, title = match.groups()
            else:
                number = None
                title = match.group(1)
            
            # Find content until next section
            start = match.end()
            next_match = re.search(pattern, text[start:])
            if next_match:
                end = start + next_match.start()
            else:
                end = len(text)
            
            content = text[start:end].strip()
            
            if content and len(content) > 50:
                sections.append({
                    "number": number,
                    "title": title.strip(),
                    "content": content,
                })
        
        if sections:
            break  # Use first pattern that matches
    
    return sections


def extract_figures_from_text(text: str) -> list[dict[str, str]]:
    """Extract figure captions from paper text."""
    figures = []
    
    patterns = [
        r"(?i)(?:figure|fig\.?)\s*(\d+)[:\.\s]+([^\n]+)",
        r"(?i)(?:figure|fig\.?)\s*(\d+)\s*[\(\[]([^\)\]]+)[\)\]]",
    ]
    
    seen_numbers = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            fig_num = match.group(1)
            if fig_num not in seen_numbers:
                caption = match.group(2).strip()
                caption = re.sub(r"\s+", " ", caption)
                if len(caption) > 10:
                    figures.append({
                        "number": fig_num,
                        "caption": caption[:500],
                    })
                    seen_numbers.add(fig_num)
    
    return sorted(figures, key=lambda x: int(x["number"]))


def extract_tables_from_text(text: str) -> list[dict[str, str]]:
    """Extract table captions from paper text."""
    tables = []
    
    patterns = [
        r"(?i)table\s*(\d+)[:\.\s]+([^\n]+)",
        r"(?i)table\s*(\d+)\s*[\(\[]([^\)\]]+)[\)\]]",
    ]
    
    seen_numbers = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            table_num = match.group(1)
            if table_num not in seen_numbers:
                caption = match.group(2).strip()
                caption = re.sub(r"\s+", " ", caption)
                if len(caption) > 10:
                    tables.append({
                        "number": table_num,
                        "caption": caption[:500],
                    })
                    seen_numbers.add(table_num)
    
    return sorted(tables, key=lambda x: int(x["number"]))


def process_pdf(
    pdf_path: Path | str,
    max_file_size_mb: float = 50.0,
) -> ExtractedPaper:
    """Process a PDF file and extract structured content.

    Args:
        pdf_path: Path to PDF file
        max_file_size_mb: Maximum file size in MB

    Returns:
        ExtractedPaper with extracted content

    Raises:
        PDFProcessingError: If processing fails
    """
    pdf_path = Path(pdf_path)

    # Check file exists
    if not pdf_path.exists():
        raise PDFProcessingError(f"PDF file not found: {pdf_path}")

    # Check file size
    file_size_mb = pdf_path.stat().st_size / (1024 * 1024)
    if file_size_mb > max_file_size_mb:
        raise PDFProcessingError(
            f"PDF file too large: {file_size_mb:.1f}MB (max: {max_file_size_mb}MB)"
        )

    extracted = ExtractedPaper()

    try:
        # Calculate hash for deduplication
        extracted.pdf_hash = calculate_pdf_hash(pdf_path)

        # Open PDF with PyMuPDF
        doc = fitz.open(pdf_path)
        
        # Extract metadata
        extracted.metadata = {
            "title": doc.metadata.get("title"),
            "author": doc.metadata.get("author"),
            "subject": doc.metadata.get("subject"),
            "creator": doc.metadata.get("creator"),
            "producer": doc.metadata.get("producer"),
            "page_count": doc.page_count,
        }
        extracted.page_count = doc.page_count

        # Extract text from all pages
        pages = []
        for page in doc:
            pages.append(page.get_text())
        
        doc.close()

        # Strip NUL bytes once at the extraction boundary — keeps
        # extracted.full_text safe for direct DB inserts (Postgres text
        # columns reject 0x00) and lets every downstream consumer trust
        # the field. normalize_pdf_text() also strips defensively for
        # callers who go straight from raw page text to the normalizer.
        full_text = _strip_nul_chars("\n\n".join(pages))
        extracted.full_text = full_text

        # Normalize text
        normalized_text = normalize_pdf_text(full_text)
        extracted.normalized_text = normalized_text

        # Get first page for title/author/abstract extraction
        first_page = normalize_pdf_text(pages[0]) if pages else ""

        # Extract title
        extracted.title = extract_title_from_text(first_page)
        if not extracted.title and extracted.metadata.get("title"):
            extracted.title = extracted.metadata["title"]
        if not extracted.title:
            extracted.title = "Untitled"

        # Extract authors
        extracted.authors = extract_authors_from_text(first_page)
        if not extracted.authors and extracted.metadata.get("author"):
            authors_str = extracted.metadata["author"]
            authors = re.split(r"[,;]|\s+and\s+", authors_str)
            extracted.authors = [a.strip() for a in authors if a.strip()]

        # Extract abstract
        first_two_pages = normalize_pdf_text("\n\n".join(pages[:2])) if len(pages) >= 2 else first_page
        extracted.abstract = extract_abstract_from_text(first_two_pages)

        # Detect sections
        sections_data = detect_sections(normalized_text)

        if sections_data:
            for section_info in sections_data:
                section = PDFSection(
                    title=section_info["title"],
                    content=section_info["content"],
                    level=1,
                    section_number=section_info.get("number"),
                )
                extracted.sections.append(section)
        else:
            # If no sections detected, create a single "Content" section
            max_section_chars = 50000
            
            if len(normalized_text) <= max_section_chars:
                section = PDFSection(
                    title="Content",
                    content=normalized_text,
                    level=1,
                )
                extracted.sections.append(section)
            else:
                # Split by paragraphs into sections
                paragraphs = normalized_text.split("\n\n")
                current_content = []
                current_length = 0
                section_num = 1
                
                for para in paragraphs:
                    if current_length + len(para) > max_section_chars and current_content:
                        section = PDFSection(
                            title=f"Content (Part {section_num})",
                            content="\n\n".join(current_content),
                            level=1,
                        )
                        extracted.sections.append(section)
                        section_num += 1
                        current_content = []
                        current_length = 0
                    
                    current_content.append(para)
                    current_length += len(para)
                
                if current_content:
                    section = PDFSection(
                        title=f"Content (Part {section_num})" if section_num > 1 else "Content",
                        content="\n\n".join(current_content),
                        level=1,
                    )
                    extracted.sections.append(section)

        # Extract figures and tables
        extracted.figures = extract_figures_from_text(normalized_text)
        extracted.tables = extract_tables_from_text(normalized_text)

        return extracted

    except PDFProcessingError:
        raise
    except Exception as e:
        raise PDFProcessingError(f"Failed to process PDF: {str(e)}") from e
