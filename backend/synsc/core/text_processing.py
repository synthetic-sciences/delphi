"""
Advanced text processing and normalization for research papers.

This module contains sophisticated text normalization functions ported from
the paper_index implementation, which handles PDF extraction artifacts,
ligatures, special characters, and more.
"""

import re
from typing import Any


def normalize_pdf_text(text: str) -> str:
    """Fix common PDF extraction artifacts and encoding issues.

    Handles:
    - Ligature substitutions (fi, fl, ff, ffi, ffl)
    - Special character misreadings
    - Mathematical symbol corruption
    - Copyright and trademark symbols
    - Control characters
    - Hyphenation at line breaks

    Args:
        text: Raw text extracted from PDF

    Returns:
        Cleaned and normalized text
    """
    # Remove control characters first
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Fix common ligature issues (order matters - do longer patterns first)
    # These are specific word patterns that are known to be corrupted
    word_fixes = [
        # Multi-character ligature patterns - specific words
        (r"di\$erential", "differential"),
        (r"di4erential", "differential"),
        (r"\$nite", "finite"),
        (r"\$xed", "fixed"),
        (r"\$eld", "field"),
        (r"\$elds", "fields"),
        (r"\$lter", "filter"),
        (r"\$rst", "first"),
        (r"\$gure", "figure"),
        (r"\$nd", "find"),
        (r"\$rm", "firm"),
        (r"\$le", "file"),
        (r"\$ll", "fill"),
        (r"\$nal", "final"),
        (r"\$ne", "fine"),
        (r"8nite", "finite"),  # Another common corruption of 'finite'
        (r"8eld", "field"),  # Another common corruption of 'field'
        (r"con\$rm", "confirm"),
        (r"con\$rms", "confirms"),
        (r"de\$ne", "define"),
        (r"de\$ned", "defined"),
        (r"de\$nes", "defines"),
        (r"modi\$ed", "modified"),
        (r"satis\$ed", "satisfied"),
        (r"speci\$c", "specific"),
        (r"veri\$ed", "verified"),
        (r"signi\$cant", "significant"),
        # 'fl' ligature corruptions (4 is often misread as fl)
        (r"4ow", "flow"),
        (r"4uid", "fluid"),
        (r"4oat", "float"),
        (r"in4uence", "influence"),
        (r"con4ict", "conflict"),
        (r"re4ect", "reflect"),
        (r"brie4y", "briefly"),
        # Common 'ff' ligature corruptions (K is often misread as ff)
        (r"e4ect", "effect"),
        (r"di4erent", "different"),
        (r"coe\$cient", "coefficient"),
        (r"e\$cient", "efficient"),
        (r"su\$cient", "sufficient"),
        (r"insu\$cient", "insufficient"),
        (r"diKusion", "diffusion"),
        (r"diKerential", "differential"),
        (r"eKect", "effect"),
        (r"eKective", "effective"),
        (r"coeKicient", "coefficient"),
        (r"aKect", "affect"),
        (r"oKer", "offer"),
        # FEM/FEA patterns
        (r"fiEM", "FEM"),
        (r"fiFE", "FIFE"),
        # Keywords corruption
        (r"ffeywords", "Keywords"),
        (r"ffieywords", "Keywords"),
        (r"Keyfiords", "Keywords"),
        # Author name fixes (common patterns)
        (r"M\+uller", "Müller"),
        (r"M\\\+uller", "Müller"),
        (r"Muller", "Müller"),  # Fix missing umlaut
    ]

    for pattern, replacement in word_fixes:
        # Use word boundaries where appropriate
        text = re.sub(pattern, replacement, text)

    # More aggressive: fix remaining $X patterns that are likely 'fi' ligatures
    # Only do this in word contexts (surrounded by letters)
    text = re.sub(r"(\w)\$(\w)", r"\1fi\2", text)

    # Fix copyright and special symbols
    symbol_fixes = [
        ("c⃝", "©"),
        ("⃝c", "©"),
        ("∗", "*"),
    ]

    for old, new in symbol_fixes:
        text = text.replace(old, new)

    # Fix known PDF artifacts with equality sign
    text = re.sub(r"velocity=pressure", "velocity/pressure", text, flags=re.IGNORECASE)

    # Fix hyphenated words at line breaks (common in multi-column PDFs)
    # Pattern: word- \nword -> wordword
    text = re.sub(r"(\w+)-\s*\n\s*(\w+)", r"\1\2", text)

    # Also fix inline hyphenation like "incom- pressible" but preserve real hyphens
    # Only join if both parts are long enough to be word fragments
    def fix_hyphenation(m):
        p1, p2 = m.group(1), m.group(2)
        # Common suffix patterns that indicate hyphenation
        if p2.lower() in [
            "tion",
            "ment",
            "able",
            "ible",
            "ness",
            "less",
            "sible",
            "pressible",
            "ing",
            "ive",
            "ity",
        ]:
            return p1 + p2
        # If second part starts lowercase and is part of a common word
        if len(p1) >= 3 and len(p2) >= 4 and p2[0].islower():
            return p1 + p2
        return m.group(0)

    text = re.sub(r"(\w+)-\s+(\w+)", fix_hyphenation, text)

    # Clean up excessive whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)

    return text


def extract_title_from_text(text: str) -> str | None:
    """Extract paper title from first page text.

    Uses sophisticated heuristics to identify the title by skipping
    common header patterns and author lines.

    Args:
        text: First page text from PDF

    Returns:
        Extracted title or None if not found
    """
    lines = text.split("\n")

    # Skip common header patterns
    skip_patterns = [
        r"journal of",
        r"www\.",
        r"elsevier",
        r"springer",
        r"arxiv",
        r"received",
        r"accepted",
        r"@",
        r"^\d+$",
        r"^\d+[–-]\d+$",
        r"^\d{4}",  # Years
        # Copyright and permission notices
        r"permission",
        r"copyright",
        r"©",
        r"hereby grants",
        r"attribution",
        r"licensed under",
        r"creative commons",
        r"all rights reserved",
        r"reproduced",
        r"journalistic",
        r"scholarly works",
        # Conference/proceedings headers
        r"proceedings of",
        r"conference on",
        r"published in",
        r"preprint",
        r"technical report",
        r"working paper",
    ]

    # Author indicators - line contains these = probably author line
    author_indicators = [
        r"\*",  # Asterisk for corresponding author
        r"∗",  # Special asterisk
        r"university",
        r"institute",
        r"department",
        r"fakultat",
        r"@",
        r"\d{5}",  # Zip codes
    ]

    title_lines = []
    started = False

    for line in lines[:25]:
        line = line.strip()

        if not line:
            if title_lines:
                break  # Empty line after title = end of title
            continue

        # Skip header lines
        skip = False
        for pattern in skip_patterns:
            if re.search(pattern, line.lower()):
                skip = True
                break
        if skip:
            continue

        # Check if this is an author line
        is_author = False
        for pattern in author_indicators:
            if re.search(pattern, line.lower()):
                is_author = True
                break

        if is_author:
            if title_lines:
                break  # Author line after title = end of title
            continue

        # Title line: reasonable length, has multiple words
        if 15 < len(line) < 250 and len(line.split()) > 3:
            title_lines.append(line)
            started = True
        elif started and len(line) > 10:
            # Continuation of title
            title_lines.append(line)

    if title_lines:
        title = " ".join(title_lines)
        # Clean up special characters
        title = re.sub(r"\s+", " ", title)
        return title.strip()

    return None


def extract_authors_from_text(text: str) -> list[str]:
    """Extract author names from first page text.

    Args:
        text: First page text from PDF

    Returns:
        List of author names
    """
    lines = text.split("\n")

    for i, line in enumerate(lines[:20]):
        line = line.strip()
        # Author lines often contain asterisks or are followed by affiliation
        if (
            "∗" in line
            or "*" in line
            or (i < 15 and re.search(r"[A-Z]\.\s*[A-Z]", line))
        ):
            # Split by common separators
            names = re.split(r"[,;]|\s+and\s+", line)
            authors = []
            for name in names:
                # Clean up author name - remove asterisks and other markers
                name = name.strip()
                name = re.sub(r"[\*∗†‡§¶]", "", name)  # Remove common footnote markers
                name = name.strip()
                if name and len(name) > 3 and not any(c.isdigit() for c in name):
                    authors.append(name)
            if authors:
                return authors

    return []


def extract_abstract_from_text(text: str) -> str | None:
    """Extract abstract from paper text.

    Args:
        text: Full paper text or first page

    Returns:
        Extracted abstract or None if not found
    """
    # Pattern 1: Explicit "Abstract" label
    patterns = [
        r"(?i)abstract\s*\n+(.*?)(?=\n\s*(?:keywords|1\.?\s*introduction|©|\n\s*\n\s*1\.))",
        r"(?i)abstract\s*\n+(.*?)(?=\n\s*\n\s*\n)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            abstract = match.group(1).strip()
            # Clean up
            abstract = re.sub(r"\s+", " ", abstract)
            abstract = re.sub(r"\$[^$]*\$", "", abstract)  # Remove LaTeX math
            if len(abstract) > 100:
                return abstract[:1500]

    return None


def detect_sections(text: str) -> list[dict[str, Any]]:
    """Detect section headers in paper text.

    Finds numbered sections like:
    - Arabic: "1. Introduction", "2.1 Methods"
    - Roman: "I. INTRODUCTION", "II. RELATED WORK"

    Args:
        text: Full paper text

    Returns:
        List of dicts with 'title', 'number', 'start_pos', 'end_pos', 'content'
    """
    # Multiple patterns to match different section styles
    patterns = [
        # Arabic numerals: "1. Introduction", "2.1 Methods"
        r"\n\s*(\d+\.?\d*\.?\s+[A-Z][A-Za-z\s\-–]{3,80})(?=\n)",
        # Roman numerals: "I. INTRODUCTION", "II. RELATED WORK"
        r"\n\s*((?:I{1,3}|IV|V|VI{0,3}|IX|X{1,3})\.?\s+[A-Z][A-Za-z\s\-–]{3,80})(?=\n)",
        # All caps section headers: "INTRODUCTION", "METHODS"
        r"\n\s*([A-Z]{4,30}(?:\s+[A-Z]{3,20})?)(?=\n)",
    ]

    all_matches = []
    
    for pattern in patterns:
        matches = list(re.finditer(pattern, text))
        for match in matches:
            all_matches.append({
                "match": match,
                "title": match.group(1).strip(),
                "pos": match.start()
            })

    # Sort by position and deduplicate overlapping matches
    all_matches.sort(key=lambda x: x["pos"])
    
    # Remove duplicates (matches at same position)
    seen_positions = set()
    unique_matches = []
    for m in all_matches:
        # Skip if within 50 chars of a previous match
        is_duplicate = any(abs(m["pos"] - p) < 50 for p in seen_positions)
        if not is_duplicate:
            unique_matches.append(m)
            seen_positions.add(m["pos"])

    sections = []
    for i, m in enumerate(unique_matches):
        title = m["title"]
        start = m["match"].end()

        # End is start of next section or end of text
        if i + 1 < len(unique_matches):
            end = unique_matches[i + 1]["pos"]
        else:
            end = len(text)

        content = text[start:end].strip()
        
        # Skip sections with very little content
        if len(content) < 50:
            continue

        sections.append({
            "title": title,
            "number": title.split()[0] if title else None,
            "start_pos": start,
            "end_pos": end,
            "content": content,
        })

    return sections


def clean_text_for_search(text: str) -> str:
    """Clean text for indexing and search.

    Removes excessive whitespace, normalizes characters, and prepares
    text for vectorization.

    Args:
        text: Text to clean

    Returns:
        Cleaned text suitable for embedding/indexing
    """
    # First apply full normalization
    text = normalize_pdf_text(text)

    # Remove remaining special characters that don't add meaning
    text = re.sub(r"[^\w\s\-.,;:?!()\[\]{}]", " ", text)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)
    text = text.strip()

    return text
