"""Code-aware lexical documents for file-level Okapi BM25 retrieval."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

FILE_OKAPI_INDEX_VERSION = "v1"
FILE_OKAPI_K1 = 1.2
FILE_OKAPI_B = 0.75
FILE_OKAPI_QUERY_TERM_CAP = 256
FILE_OKAPI_DOCUMENT_TOKEN_CAP = 250_000

_MIN_TERM_LENGTH = 1
_MAX_TERM_LENGTH = 128

_ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
_SEGMENT_SPLIT_RE = re.compile(r"[/._\W]+")
_ALNUM_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_NUMERIC_ONLY_RE = re.compile(r"^\d+$")


@dataclass(frozen=True)
class FileOkapiDocument:
    document_length: int
    term_frequencies: dict[str, int]


def _split_identifier(value: str) -> list[str]:
    value = _ACRONYM_BOUNDARY_RE.sub(r"\1 \2", value)
    value = _CAMEL_BOUNDARY_RE.sub(r"\1 \2", value)
    parts: list[str] = []
    for piece in value.split("_"):
        piece = piece.strip()
        if not piece:
            continue
        parts.extend(_ALNUM_TOKEN_RE.findall(piece))
    return parts


def _is_valid_term(token: str) -> bool:
    if len(token) < _MIN_TERM_LENGTH or len(token) > _MAX_TERM_LENGTH:
        return False
    return _NUMERIC_ONLY_RE.fullmatch(token) is None


def tokenize_file_okapi(value: str, *, limit: int | None = None) -> list[str]:
    """Tokenize paths and source text for file-level Okapi indexing."""
    tokens: list[str] = []

    for segment in _SEGMENT_SPLIT_RE.split(value):
        if not segment:
            continue
        for raw in _split_identifier(segment):
            term = raw.lower()
            if not _is_valid_term(term):
                continue
            tokens.append(term)

    if limit is None:
        return tokens

    truncated: list[str] = []
    seen: set[str] = set()
    for term in tokens:
        if term in seen:
            continue
        if len(seen) >= limit:
            break
        seen.add(term)
        truncated.append(term)
    return truncated


def build_file_okapi_document(file_path: str, content: str) -> FileOkapiDocument:
    """Build a lexical document with path terms prepended once."""
    path_tokens = tokenize_file_okapi(file_path)
    content_tokens = tokenize_file_okapi(content)

    frequencies: Counter[str] = Counter(content_tokens)
    for term in path_tokens:
        frequencies[term] += 1

    document_length = sum(frequencies.values())
    if document_length == 0:
        msg = "document has no retained terms"
        raise ValueError(msg)
    if document_length > FILE_OKAPI_DOCUMENT_TOKEN_CAP:
        msg = f"document exceeds token cap ({FILE_OKAPI_DOCUMENT_TOKEN_CAP})"
        raise ValueError(msg)

    return FileOkapiDocument(
        document_length=document_length,
        term_frequencies=dict(frequencies),
    )


def bm25_term_score(
    *,
    term_frequency: int,
    document_length: int,
    document_count: int,
    document_frequency: int,
    average_document_length: float,
    k1: float = FILE_OKAPI_K1,
    b: float = FILE_OKAPI_B,
) -> float:
    """Canonical Okapi BM25 contribution for one query term."""
    idf = math.log(
        1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
    )
    length_norm = 1 - b + b * (document_length / average_document_length)
    tf_num = term_frequency * (k1 + 1)
    tf_den = term_frequency + k1 * length_norm
    return idf * (tf_num / tf_den)
