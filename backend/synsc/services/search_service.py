"""Search service for semantic code search.

Uses pgvector for semantic search with smart deduplication:
- Public repos are shared, but users only search repos in their collection
- Private repos are only accessible by the indexer

Post-retrieval quality pipeline:
1. Symbol-aware score boosting (exact symbol name matches)
2. Agent mode: stable file diversity that preserves fused high-recall rank
3. Other modes: metadata scoring, optional reranking, a dynamic threshold,
   and content-based MMR
"""

import json
import re
import time
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from synsc.config import get_config
from synsc.database.connection import get_session
from synsc.database.models import (
    CodeChunk,
    Repository,
    RepositoryFile,
    UserRepository,
)
from synsc.embeddings.generator import EmbeddingProvider, get_embedding_generator
from synsc.indexing.vector_store import VectorStore, get_vector_store
from synsc.providers.contracts import CancellationToken

logger = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Post-retrieval quality functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_DIAGNOSTIC_SIGNAL_PATTERN = re.compile(
    r"(?:"
    r"\bfail(?:ed|ure)?\b|"
    r"\berror\b|"
    r"\bexception\b|"
    r"\bpanic\b|"
    r"\bundefined\b|"
    r"\bcannot\b|"
    r"\bassert(?:ion)?\b|"
    r"\bexpected\b|"
    r"\bactual\b|"
    r"\bgot\b|"
    r"\bwant\b|"
    r"\btraceback\b|"
    r"\bsegmentation fault\b|"
    r"\btimeout\b"
    r")",
    re.IGNORECASE,
)

_DIAGNOSTIC_LOCATION_PATTERN = re.compile(
    r"(?:^|[\s(/])"
    r"[\w.@+~-]+(?:/[\w.@+~-]+)*"
    r"\.(?:c|cc|cpp|cs|go|java|js|jsx|php|py|rb|rs|swift|ts|tsx)"
    r":\d+(?::\d+)?\b",
    re.IGNORECASE,
)

_DIAGNOSTIC_NOISE_PATTERN = re.compile(
    r"^(?:"
    r"go:\s+downloading\b|"
    r"downloading\b|"
    r"compiling\b|"
    r"collected\s+\d+\s+items?\b|"
    r"fail(?:\s+\S+\s+\[build failed\])?$|"
    r"\[notice\]|"
    r"test\s+\S+\s+\.\.\.\s+ok$"
    r")",
    re.IGNORECASE,
)

_DIAGNOSTIC_IDENTIFIER_STOPWORDS = {
    "actual",
    "assertionerror",
    "diff",
    "disconnected",
    "empty",
    "err",
    "error",
    "expected",
    "fail",
    "failed",
    "false",
    "for",
    "none",
    "not",
    "strings",
    "test",
    "the",
    "trace",
    "true",
    "typeerror",
}

_DIAGNOSTIC_SNAKE_STOPWORDS = {
    "after",
    "all",
    "and",
    "be",
    "before",
    "correctly",
    "is",
    "of",
    "should",
    "when",
    "with",
}

_RELATED_PATH_SUFFIXES = {
    ".c", ".cc", ".cfg", ".cpp", ".cs", ".go", ".h", ".hpp", ".java",
    ".js", ".json", ".jsx", ".kt", ".md", ".php", ".py", ".rb", ".rs",
    ".rst", ".swift", ".toml", ".ts", ".tsx", ".vue", ".yaml", ".yml",
}

_RELATED_PATH_GENERIC_TOKENS = {
    "core", "index", "init", "lib", "main", "mod", "src", "test", "tests",
    "type", "types", "util", "utils",
}


def _structured_query_priority(key: str) -> int:
    """Rank generic structured fields by retrieval value."""
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    tokens = normalized.split("_")
    terminal = tokens[-1] if tokens else ""
    if set(tokens) & {
        "goal",
        "intent",
        "issue",
        "objective",
        "query",
        "question",
        "request",
        "task",
    }:
        return 0
    if terminal in {"headline", "subject", "title"}:
        return 1
    if terminal in {
        "directory",
        "directories",
        "file",
        "filename",
        "filenames",
        "files",
        "path",
        "paths",
    }:
        return 2
    if terminal in {"body", "comment", "diagnostic", "error", "message"}:
        return 3
    if terminal in {
        "context",
        "description",
        "excerpt",
        "log",
        "logs",
        "output",
        "summary",
        "trace",
    }:
        return 4
    if terminal in {"diff", "patch"}:
        return 5
    return 6


def _is_structured_developer_query(payload: dict[str, Any]) -> bool:
    """Conservatively distinguish developer envelopes from literal JSON.

    JSON itself can be the user's exact search expression, so generic keys
    such as ``error`` and ``message`` are not enough to justify removing its
    syntax. Developer envelopes carry stronger structural signals:
    developer-specific field or wrapper names, an explicit intent paired with
    a file, or multiple useful fields nested beneath a context wrapper.
    """
    leaf_keys: list[str] = []
    container_keys: list[str] = []

    def collect(value: Any) -> None:
        if not isinstance(value, dict):
            return
        for raw_key, nested_value in value.items():
            key = re.sub(
                r"[^a-z0-9]+",
                "_",
                str(raw_key).lower(),
            ).strip("_")
            if isinstance(nested_value, dict):
                container_keys.append(key)
                collect(nested_value)
            elif isinstance(nested_value, list):
                if any(isinstance(item, (str, int, float)) for item in nested_value):
                    leaf_keys.append(key)
                for item in nested_value:
                    collect(item)
            elif isinstance(nested_value, (str, int, float)):
                leaf_keys.append(key)

    collect(payload)
    priorities = {
        _structured_query_priority(key)
        for key in leaf_keys
        if _structured_query_priority(key) < 6
    }
    if len(priorities) < 2:
        return False

    tokenized_keys = [set(key.split("_")) for key in leaf_keys]
    tokenized_containers = [set(key.split("_")) for key in container_keys]
    developer_tokens = {
        "anchor",
        "changed",
        "code",
        "commit",
        "developer",
        "implementation",
        "pr",
        "pull",
        "target",
        "test",
    }
    if any(
        tokens & developer_tokens
        for tokens in (*tokenized_keys, *tokenized_containers)
    ):
        return True

    has_explicit_intent = any(
        tokens & {"goal", "intent", "objective", "request", "task"}
        for tokens in tokenized_keys
    )
    has_file = 2 in priorities
    if has_explicit_intent and has_file:
        return True

    context_wrappers = {"context", "developer_context", "request_context"}
    return bool(set(container_keys) & context_wrappers and priorities & {1, 2})


def _related_path_pattern(query: str) -> str | None:
    """Build a loose sibling-file probe from explicit developer path hints.

    Given an implementation path such as ``src/core_model_loading.py``, agent
    search should also consider paths like ``tests/test_core_model_loading.py``.
    The wildcard probe is deliberately limited to structured developer
    envelopes and safe repository-relative paths; literal JSON searches and
    machine-local absolute paths remain untouched.
    """
    try:
        payload = json.loads(query)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or not _is_structured_developer_query(payload):
        return None

    paths: list[str] = []

    def collect(key: str, value: Any) -> None:
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                collect(str(nested_key), nested_value)
            return
        if isinstance(value, list):
            for item in value:
                collect(key, item)
            return
        if not isinstance(value, str) or _structured_query_priority(key) != 2:
            return
        candidate = value.strip().replace("\\", "/")
        if (
            "/" not in candidate
            or "://" in candidate
            or candidate.startswith(("/", "~"))
            or re.match(r"^[A-Za-z]:/", candidate) is not None
            or ".." in candidate.split("/")
            or Path(candidate).suffix.lower() not in _RELATED_PATH_SUFFIXES
        ):
            return
        paths.append(candidate)

    for field, field_value in payload.items():
        collect(str(field), field_value)
    if not paths:
        return None

    for path in paths:
        stem = Path(path).stem
        tokens = re.findall(
            r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+",
            stem.replace("-", "_"),
        )
        useful = [
            token.lower()
            for token in tokens
            if len(token) >= 2
            and token.lower() not in _RELATED_PATH_GENERIC_TOKENS
        ]
        if useful:
            return "*" + "*".join(useful) + "*"
    return None


def _compact_structured_query(
    payload: dict[str, Any],
    *,
    max_chars: int,
) -> str:
    """Flatten a JSON developer payload into bounded retrieval text."""
    components: list[tuple[int, int, str]] = []
    order = 0

    def collect(key: str, value: Any) -> None:
        nonlocal order
        if isinstance(value, str):
            text_value = " ".join(value.split())
            if text_value:
                components.append(
                    (_structured_query_priority(key), order, text_value)
                )
                order += 1
            return
        if isinstance(value, list):
            for item in value:
                collect(key, item)
            return
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                collect(str(nested_key), nested_value)

    for field, field_value in payload.items():
        collect(str(field), field_value)

    if not components:
        return ""
    components.sort(key=lambda item: (item[0], item[1]))
    unique_components: list[tuple[int, int, str]] = []
    seen_text: set[str] = set()
    for component in components:
        if component[2] in seen_text:
            continue
        seen_text.add(component[2])
        unique_components.append(component)

    if max_chars <= 0:
        return ""
    full_text = " ".join(item[2] for item in unique_components)
    if len(full_text) <= max_chars:
        return full_text

    intent_components = [item[2] for item in unique_components if item[0] == 0]
    title_components = [item[2] for item in unique_components if item[0] == 1]
    path_components = [item[2] for item in unique_components if item[0] == 2]
    supplemental = [item[2] for item in unique_components if item[0] > 2]
    if not (intent_components or title_components or path_components):
        return full_text[:max_chars].rstrip()

    def take_components(
        values: list[str],
        *,
        budget: int,
        whole_only: bool = False,
    ) -> str:
        selected: list[str] = []
        used = 0
        for value in values:
            separator = 1 if selected else 0
            available = budget - used - separator
            if available <= 0:
                break
            if len(value) <= available:
                selected.append(value)
                used += separator + len(value)
                continue
            if whole_only:
                continue
            piece = value[:available].rstrip()
            if piece:
                selected.append(piece)
            break
        return " ".join(selected)

    high_value_budget = max_chars if not (path_components or supplemental) else max(
        1,
        int(max_chars * 0.50),
    )
    if intent_components and title_components:
        intent_budget = max(1, int(max_chars * 0.30))
        title_budget = max(1, high_value_budget - intent_budget - 1)
    elif intent_components:
        intent_budget = high_value_budget
        title_budget = 0
    else:
        intent_budget = 0
        title_budget = high_value_budget
    intent_text = take_components(intent_components, budget=intent_budget)
    title_text = take_components(title_components, budget=title_budget)
    compacted = " ".join(part for part in (intent_text, title_text) if part)

    supplemental_reserve = int(max_chars * 0.20) if supplemental else 0
    path_separator = 1 if compacted and path_components else 0
    supplemental_separator = 1 if supplemental else 0
    path_budget = max(
        0,
        max_chars
        - len(compacted)
        - path_separator
        - supplemental_reserve
        - supplemental_separator,
    )
    path_text = take_components(
        path_components,
        budget=path_budget,
        whole_only=True,
    )
    if path_text:
        compacted = f"{compacted} {path_text}" if compacted else path_text

    for text_value in supplemental:
        separator = 1 if compacted else 0
        available = max_chars - len(compacted) - separator
        if available <= 0:
            break
        piece = text_value[:available].rstrip()
        if not piece:
            continue
        compacted = f"{compacted} {piece}" if compacted else piece
    return compacted[:max_chars].rstrip()


def _diagnostic_identifier_query(text: str, limit: int = 16) -> str:
    """Extract a short API/symbol query from diagnostic context."""
    text = re.sub(
        r"(?:(?:[A-Za-z]:)?/|~/)(?:[^\s:]+/)*[^\s:]*",
        " ",
        text,
    )
    identifiers: list[str] = []
    seen: set[str] = set()
    for raw_token in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", text):
        token = raw_token.strip(".")
        if len(token) == 1:
            continue
        lowered = token.lower()
        from_test_name = False
        if lowered.startswith("test_"):
            from_test_name = True
            token = token[5:]
            lowered = token.lower()
        if token.startswith("Test") and len(token) > 4 and token[4].isupper():
            from_test_name = True
            token = token[4:]
            lowered = token.lower()
        if re.search(
            r"\.(?:c|cc|cpp|cs|go|java|js|json|jsx|php|py|rb|rs|swift|"
            r"toml|ts|tsx|xml|yaml|yml)$",
            token,
            re.IGNORECASE,
        ):
            continue
        if (
            lowered in _DIAGNOSTIC_IDENTIFIER_STOPWORDS
            or lowered.startswith(("pytest.", "result.", "runner.", "testing."))
            or re.fullmatch(
                r"(?:[a-z0-9-]+\.)+(?:com|dev|io|net|org)",
                lowered,
            )
        ):
            continue
        identifier_like = (
            "_" in token
            or "." in token
            or token[0].isupper()
            or any(character.isupper() for character in token[1:])
        )
        if not identifier_like or lowered in seen:
            continue
        expanded = [token]
        if token.count("_") >= 2 and not token.isupper():
            parts = [
                part
                for part in token.split("_")
                if part and part.lower() not in _DIAGNOSTIC_SNAKE_STOPWORDS
            ]
            expanded = []
            if len(parts) >= 2:
                expanded.append(f"{parts[0]}_{parts[1]}")
                expanded.extend(parts[2:])
            else:
                expanded.extend(parts)
        elif from_test_name:
            expanded = re.findall(
                r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+",
                token,
            )
        for candidate in expanded:
            candidate_lowered = candidate.lower()
            if candidate_lowered in seen:
                continue
            seen.add(candidate_lowered)
            identifiers.append(candidate)
            if len(identifiers) >= limit:
                return " ".join(identifiers)
    return " ".join(identifiers)


def _prepare_search_query(query: str, max_chars: int = 4000) -> str:
    """Compact structured build/test failures into high-signal retrieval text.

    Agent traces often arrive as JSON with a short command and a very long
    ``failure_excerpt``. Embedding the serialized object verbatim lets package
    downloads, successful tests, and compiler progress consume the model's
    useful input window. Preserve diagnostic lines and the tail fallback while
    leaving ordinary natural-language queries untouched.
    """
    try:
        payload = json.loads(query)
    except (json.JSONDecodeError, TypeError):
        return query
    if not isinstance(payload, dict):
        return query

    failure_excerpt = payload.get("failure_excerpt")
    if not isinstance(failure_excerpt, str) or not failure_excerpt.strip():
        if not _is_structured_developer_query(payload):
            return query
        if max_chars <= 0:
            return ""
        return _compact_structured_query(payload, max_chars=max_chars) or query
    command = payload.get("command")
    command_text = command.strip() if isinstance(command, str) else ""

    excerpt_lines = failure_excerpt.splitlines()
    signal_indices = {
        index
        for index, raw_line in enumerate(excerpt_lines)
        for line in [raw_line.strip()]
        if line
        and not _DIAGNOSTIC_NOISE_PATTERN.search(line)
        and (
            _DIAGNOSTIC_SIGNAL_PATTERN.search(line)
            or _DIAGNOSTIC_LOCATION_PATTERN.search(line)
        )
    }
    selected_indices = {
        nearby
        for index in signal_indices
        for nearby in range(max(0, index - 10), min(len(excerpt_lines), index + 2))
    }

    selected_lines: list[str] = []
    seen: set[str] = set()
    ordered_indices = sorted(signal_indices) + sorted(selected_indices - signal_indices)
    for index in ordered_indices:
        line = excerpt_lines[index].strip()
        if not line or _DIAGNOSTIC_NOISE_PATTERN.search(line):
            continue
        if line not in seen:
            seen.add(line)
            selected_lines.append(line)

    diagnostic_text = (
        " ".join(selected_lines) if selected_lines else failure_excerpt.strip()
    )
    focused_query = _diagnostic_identifier_query(diagnostic_text)
    if focused_query:
        prepared = focused_query
    else:
        parts = [part for part in (command_text, diagnostic_text) if part]
        prepared = " ".join(parts)
    if len(prepared) <= max_chars:
        return prepared

    if focused_query:
        return focused_query[:max_chars]
    if command_text:
        remaining = max(0, max_chars - len(command_text) - 1)
        if len(diagnostic_text) <= remaining:
            return f"{command_text} {diagnostic_text}"[:max_chars]
        head_size = max(0, (remaining * 2) // 3 - 3)
        tail_size = max(0, remaining - head_size - 3)
        compacted = (
            f"{diagnostic_text[:head_size]}..."
            f"{diagnostic_text[-tail_size:] if tail_size else ''}"
        )
        return f"{command_text} {compacted}"[:max_chars]
    head_size = max_chars * 2 // 3 - 3
    tail_size = max_chars - head_size - 3
    return f"{prepared[:head_size]}...{prepared[-tail_size:]}"


def _extract_query_symbols(query: str) -> set[str]:
    """Extract likely symbol names from a search query.

    Matches identifiers that look like function/class/variable names:
    camelCase, snake_case, PascalCase, UPPER_CASE, dotted.paths.
    """
    # Match word-like tokens that look like code identifiers
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", query)
    symbols = set()
    for token in tokens:
        # Skip common English words that aren't code identifiers
        if len(token) <= 2 or token.lower() in {
            "the", "and", "for", "how", "does", "what", "this", "that",
            "with", "from", "use", "get", "set", "not", "all", "any",
            "find", "list", "show", "code", "file", "function", "class",
            "method", "where", "which",
        }:
            continue
        symbols.add(token.lower())
        # Also add parts of dotted paths: "fastapi.routing" → {"fastapi", "routing"}
        if "." in token:
            symbols.update(part.lower() for part in token.split(".") if len(part) > 2)
    return symbols


def _apply_symbol_boost(
    results: list[dict[str, Any]],
    query_symbols: set[str],
    boost: float = 0.15,
) -> list[dict[str, Any]]:
    """Boost relevance score for chunks whose symbol_names match query symbols.

    Args:
        results: Search results with 'similarity' and 'symbol_names' keys.
        query_symbols: Lowercased symbol names extracted from query.
        boost: Score boost for a symbol match (added to similarity).

    Returns:
        Results with updated 'similarity' scores (capped at 1.0).
    """
    if not query_symbols:
        return results

    for r in results:
        raw_symbols = r.get("symbol_names")
        if not raw_symbols:
            continue

        # symbol_names is stored as JSON array or list
        if isinstance(raw_symbols, str):
            try:
                raw_symbols = json.loads(raw_symbols)
            except (json.JSONDecodeError, TypeError):
                continue

        chunk_symbols = {s.lower() for s in raw_symbols if isinstance(s, str)}

        if query_symbols & chunk_symbols:
            r["similarity"] = min(r["similarity"] + boost, 1.0)

    return results


# Patterns indicating non-production code (tests, docs, examples, fixtures)
_DEMOTE_PATTERNS = re.compile(
    r"(?:^|/)"
    r"(?:test_|tests/|__tests__/|spec/|specs/|"
    r"docs_src/|docs/|doc/|examples?/|"
    r"fixtures?/|mocks?/|__mocks__/|__snapshots__/|"
    r"storybook/|stories/|e2e/|cypress/|playwright/|"
    r"benchmarks?/|sandbox/|demo/)",
    re.IGNORECASE,
)

# Patterns indicating a test file by name
_TEST_FILE_PATTERN = re.compile(
    r"(?:^|/)(?:test_.*|.*_test|.*\.test|.*\.spec|conftest)\.(?:py|js|ts|tsx|jsx)$",
    re.IGNORECASE,
)


# Content patterns indicating test/assertion code (not implementation)
_TEST_CONTENT_PATTERN = re.compile(
    r"(?:"
    r"\bassert\s|"
    r"\bdef test_|"
    r"\bpytest\b|"
    r"\b(?:mock|patch|MagicMock|monkeypatch)\b|"
    r"\bdescribe\(|"
    r"\bit\(|"
    r"\bexpect\(|"
    r"\bshould\b.*\b(?:equal|be|have)\b"
    r")",
    re.IGNORECASE,
)


# Query signals that the caller is looking *for* tests, docs, or examples.
# When one fires, the matching demotion is suppressed: the whole point of
# "which test covers this?" is to return a test file.
_WANTS_TEST_PATTERN = re.compile(
    r"\b(?:tests?|testing|test-?case|test-?file|regression|spec|specs|"
    r"unit-?test|integration-?test|e2e|end-?to-?end|pytest|unittest|jest|"
    r"mocha|vitest|junit|rspec|testify|coverage|assertion|assertions)\b",
    re.IGNORECASE,
)

_WANTS_DOCS_PATTERN = re.compile(
    r"\b(?:docs?|documentation|guide|guides|tutorial|readme|changelog|"
    r"how-?to|reference|manual|docstring)\b",
    re.IGNORECASE,
)

_WANTS_EXAMPLE_PATTERN = re.compile(
    r"\b(?:examples?|samples?|demos?|usage|snippet|snippets|starter|"
    r"boilerplate|template|templates)\b",
    re.IGNORECASE,
)

# Path families each intent protects from demotion.
_TEST_PATH_PATTERN = re.compile(
    r"(?:^|/)(?:test_|tests?/|__tests__/|spec/|specs/|e2e/|cypress/|"
    r"playwright/|fixtures?/|mocks?/|__mocks__/|__snapshots__/)",
    re.IGNORECASE,
)

_DOCS_PATH_PATTERN = re.compile(
    r"(?:^|/)(?:docs_src/|docs?/)",
    re.IGNORECASE,
)

_EXAMPLE_PATH_PATTERN = re.compile(
    r"(?:^|/)(?:examples?/|storybook/|stories/|demo/|sandbox/|benchmarks?/)",
    re.IGNORECASE,
)


def _query_seeks(query: str | None) -> set[str]:
    """Which non-production file families the query is actually asking for."""
    if not query:
        return set()
    wanted: set[str] = set()
    if _WANTS_TEST_PATTERN.search(query):
        wanted.add("test")
    if _WANTS_DOCS_PATTERN.search(query):
        wanted.add("docs")
    if _WANTS_EXAMPLE_PATTERN.search(query):
        wanted.add("example")
    return wanted


def _demotion_is_suppressed(file_path: str, wanted: set[str]) -> bool:
    """True when this path belongs to a family the query explicitly wants."""
    if not wanted or not file_path:
        return False
    if "test" in wanted and _TEST_PATH_PATTERN.search(file_path):
        return True
    if "docs" in wanted and _DOCS_PATH_PATTERN.search(file_path):
        return True
    if "example" in wanted and _EXAMPLE_PATH_PATTERN.search(file_path):
        return True
    if "test" in wanted and _TEST_FILE_PATTERN.search(file_path):
        return True
    return False


def _apply_metadata_scoring(
    results: list[dict[str, Any]],
    path_penalty: float = 0.08,
    content_penalty: float = 0.04,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Adjust scores based on file path and content signals.

    Uses two layers:
    1. File path: demotes test dirs, doc dirs, example dirs
    2. Content: demotes chunks heavy on assert/mock/pytest patterns

    Penalties stack: a test file in tests/ with lots of asserts gets both.
    No boost for implementation — avoids false positives on similar_sig cases
    where both correct and decoy chunks contain definitions.

    The penalties are **conditional on what the query asked for**. Demoting
    tests is right for "where is this implemented?" and exactly backwards for
    "which test covers this?" — the same heuristic that sharpens one query
    buries the answer to the other. When the query names tests, docs, or
    examples, the matching penalty is suppressed for those paths.

    Args:
        results: Search results with 'file_path', 'content', 'similarity' keys.
        path_penalty: Score penalty for test/doc/example file paths.
        content_penalty: Score penalty for test-heavy content.
        query: The originating query, used to infer which families are wanted.

    Returns:
        Results with adjusted scores.
    """
    wanted = _query_seeks(query)

    for r in results:
        penalty = 0.0
        file_path = r.get("file_path", "")
        content = r.get("content", "")

        if _demotion_is_suppressed(file_path, wanted):
            continue

        # Path-based signals
        if file_path and (
            _DEMOTE_PATTERNS.search(file_path)
            or _TEST_FILE_PATTERN.search(file_path)
        ):
            penalty += path_penalty

        # Content-based signals (demote only, no boost)
        if content:
            num_lines = max(content.count("\n") + 1, 1)
            test_hits = len(_TEST_CONTENT_PATTERN.findall(content))
            if test_hits / num_lines > 0.15:
                penalty += content_penalty

        if penalty > 0:
            r["similarity"] = max(r["similarity"] - penalty, 0.0)

    return results


def _apply_dynamic_threshold(
    results: list[dict[str, Any]],
    min_absolute: float = 0.3,
    relative_factor: float = 0.6,
) -> list[dict[str, Any]]:
    """Filter results using a dynamic threshold relative to the top score.

    If the best result has similarity 0.92, the cutoff becomes
    max(0.3, 0.92 * 0.6) = 0.552 — dropping low-quality tail results
    that the fixed 0.3 threshold would have kept.

    Args:
        results: Search results sorted by similarity (descending).
        min_absolute: Hard floor — never drop above this threshold.
        relative_factor: Fraction of top score used as dynamic cutoff.

    Returns:
        Filtered results.
    """
    if not results:
        return results

    top_score = max(r["similarity"] for r in results)
    threshold = max(min_absolute, top_score * relative_factor)

    return [r for r in results if r["similarity"] >= threshold]


def _apply_mmr(
    results: list[dict[str, Any]],
    query_embedding: np.ndarray,
    embeddings: dict[str, np.ndarray] | None = None,
    top_k: int = 10,
    lambda_param: float = 0.7,
) -> list[dict[str, Any]]:
    """Apply Maximal Marginal Relevance to diversify results.

    MMR balances relevance to the query with diversity among selected results.
    score = λ * sim(candidate, query) - (1-λ) * max_sim(candidate, already_selected)

    Since we don't have chunk embeddings in-memory, we approximate inter-result
    similarity using content overlap (Jaccard on token sets). This avoids an
    extra DB round-trip and works well for catching near-duplicate chunks.

    Args:
        results: Candidate results (should be more than top_k for best effect).
        query_embedding: Not used in content-based mode, kept for future use.
        embeddings: Optional pre-fetched embeddings keyed by chunk_id.
        top_k: Number of results to select.
        lambda_param: Balance between relevance (1.0) and diversity (0.0).

    Returns:
        top_k results selected by MMR.
    """
    if len(results) <= top_k:
        return results

    # Tokenize content for Jaccard similarity
    def _tokenize(text: str) -> set[str]:
        return set(text.lower().split())

    token_sets = [_tokenize(r["content"]) for r in results]

    def _jaccard(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    selected_indices: list[int] = []
    remaining = list(range(len(results)))

    for _ in range(top_k):
        if not remaining:
            break

        best_idx = None
        best_score = -float("inf")

        for idx in remaining:
            relevance = results[idx]["similarity"]

            # Max similarity to any already-selected result
            max_sim = 0.0
            for sel_idx in selected_indices:
                sim = _jaccard(token_sets[idx], token_sets[sel_idx])
                if sim > max_sim:
                    max_sim = sim

            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim

            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx

        if best_idx is None:
            break
        selected_indices.append(best_idx)
        remaining.remove(best_idx)

    return [results[i] for i in selected_indices]


def _select_file_diverse_results(
    results: list[dict[str, Any]],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    """Preserve rank while preferring one chunk per file.

    Agent searches are context-acquisition calls: losing a relevant file is
    more expensive than returning a merely imperfect score. Content-based MMR
    can reorder or discard relevant candidates and is quadratic in the size of
    the candidate set. This stable selector admits the first hit from each
    file, then fills remaining slots with deferred same-file chunks in their
    original order.

    Results without a file path are keyed by chunk id so unrelated anonymous
    candidates do not collapse into one lane.
    """
    if top_k <= 0 or not results:
        return []

    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    seen_files: set[tuple[str, str]] = set()

    for result in results:
        file_id = str(result.get("file_id") or "")
        file_path = str(result.get("file_path") or "")
        repo_id = str(result.get("repo_id") or "")
        chunk_id = str(result.get("chunk_id") or id(result))
        if file_id:
            file_key = ("file_id", file_id)
        elif file_path:
            file_key = (repo_id, file_path)
        else:
            file_key = ("chunk_id", chunk_id)
        if file_key in seen_files:
            deferred.append(result)
            continue
        seen_files.add(file_key)
        selected.append(result)
        if len(selected) >= top_k:
            return selected

    remaining = top_k - len(selected)
    if remaining > 0:
        selected.extend(deferred[:remaining])
    return selected


def _select_source_diverse_results(
    results: list[dict[str, Any]],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    """Combine file diversity with coverage of successful retrieval branches.

    Weighted fusion can otherwise crowd a strong lexical-only recovery out
    with a full page of vector hits before reranking or agent selection. Start
    with ranked file diversity, then replace only a lowest-ranked result whose
    branch signals are already represented elsewhere. The final candidates
    retain their original relative order.
    """
    if top_k <= 0 or not results:
        return []
    if len(results) <= top_k:
        return list(results)

    selected = _select_file_diverse_results(results, top_k=top_k)

    original_rank = {id(result): index for index, result in enumerate(results)}
    selected_ids = {id(result) for result in selected}
    # Preserve the semantic baseline first, then the highest-precision
    # lexical branches. Trigram precedes broad BM25 so small result windows
    # still retain the only branch able to recover a misspelled identifier.
    for source in ("vector", "symbol", "path", "trigram", "bm25"):
        if any(
            source in (result.get("candidate_sources") or {})
            for result in selected
        ):
            continue

        candidate = next(
            (
                result
                for result in results
                if source in (result.get("candidate_sources") or {})
                and id(result) not in selected_ids
            ),
            None,
        )
        if candidate is None:
            continue

        source_counts: dict[str, int] = {}
        for result in selected:
            for result_source in (result.get("candidate_sources") or {}):
                source_counts[result_source] = (
                    source_counts.get(result_source, 0) + 1
                )
        replacement_index = next(
            (
                index
                for index in range(len(selected) - 1, -1, -1)
                if all(
                    source_counts.get(result_source, 0) > 1
                    for result_source in (
                        selected[index].get("candidate_sources") or {}
                    )
                )
            ),
            None,
        )
        if replacement_index is None:
            continue

        selected_ids.discard(id(selected[replacement_index]))
        selected[replacement_index] = candidate
        selected_ids.add(id(candidate))

    selected.sort(key=lambda result: original_rank[id(result)])
    return selected


def _enrich_results_with_context(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich search results with enclosing symbol docstrings/signatures and adjacent context.

    Post-retrieval enrichment: for each result, finds the tightest enclosing
    symbol (function/class) and prepends its signature and docstring to the
    chunk content. Also fetches the previous chunk for flow context.

    This runs after result selection, so operates on at most top_k results.
    Uses two batched SQL queries — expected latency ~10-30ms.
    """
    if not results:
        return results

    file_ids = list({r["file_id"] for r in results if r.get("file_id")})
    if not file_ids:
        return results

    try:
        with get_session() as session:
            # Batch query 1: all symbols for relevant files
            symbol_rows = session.execute(
                text("""
                    SELECT file_id, name, qualified_name, symbol_type,
                           signature, docstring, start_line, end_line
                    FROM symbols
                    WHERE file_id = ANY(CAST(:file_ids AS uuid[]))
                """),
                {"file_ids": file_ids},
            ).fetchall()

            # Group symbols by file_id
            symbols_by_file: dict[str, list[Any]] = {}
            for s in symbol_rows:
                symbols_by_file.setdefault(str(s.file_id), []).append(s)

            # Batch query 2: adjacent (previous) chunks
            prev_lookups = []
            for r in results:
                ci = r.get("chunk_index")
                if ci is not None and ci > 0:
                    prev_lookups.append({"fid": r["file_id"], "ci": ci - 1})

            adjacent_chunks: dict[tuple[str, int], str] = {}
            if prev_lookups:
                # Build values list for batch lookup
                fid_list = [p["fid"] for p in prev_lookups]
                ci_list = [p["ci"] for p in prev_lookups]
                adj_rows = session.execute(
                    text("""
                        SELECT file_id, chunk_index, content
                        FROM code_chunks
                        WHERE file_id = ANY(CAST(:fids AS uuid[])) AND chunk_index = ANY(:cis)
                    """),
                    {"fids": fid_list, "cis": ci_list},
                ).fetchall()
                for row in adj_rows:
                    adjacent_chunks[(str(row.file_id), row.chunk_index)] = row.content

            # Enrich each result
            for r in results:
                prefix_parts = []
                file_id = r.get("file_id")
                if not file_id:
                    continue

                # Find tightest enclosing symbol (smallest span containing chunk)
                file_symbols = symbols_by_file.get(file_id, [])
                best_symbol = None
                best_span = float("inf")
                for s in file_symbols:
                    if s.start_line <= r["start_line"] and s.end_line >= r["end_line"]:
                        span = s.end_line - s.start_line
                        if span < best_span:
                            best_span = span
                            best_symbol = s

                if best_symbol:
                    if best_symbol.signature:
                        prefix_parts.append(
                            f"# {best_symbol.symbol_type}: {best_symbol.signature}"
                        )
                    if best_symbol.docstring:
                        doc_lines = best_symbol.docstring.strip().split("\n")[:3]
                        truncated = "\n# ".join(doc_lines)
                        if len(truncated) > 200:
                            truncated = truncated[:200] + "..."
                        prefix_parts.append(f"# Docstring: {truncated}")

                # Previous chunk context (last 5 lines)
                ci = r.get("chunk_index")
                if ci is not None and ci > 0:
                    prev_content = adjacent_chunks.get((file_id, ci - 1))
                    if prev_content:
                        prev_lines = prev_content.strip().split("\n")[-5:]
                        prefix_parts.append(
                            "# preceding context:\n# " + "\n# ".join(prev_lines)
                        )

                if prefix_parts:
                    prefix = "\n".join(prefix_parts)
                    # Cap total prefix size
                    if len(prefix) > 500:
                        prefix = prefix[:500] + "\n# ..."
                    r["content"] = prefix + "\n\n" + r["content"]

    except Exception as e:
        # Enrichment is best-effort — don't fail the search
        logger.warning("Context enrichment failed, returning raw results", error=str(e))

    return results


class SearchService:
    """Service for semantic code search.
    
    ACCESS CONTROL:
    - Users can only search repos in their collection (user_repositories)
    - Public repos can be added to collection; private repos only by indexer
    """

    def __init__(self, user_id: str | None = None) -> None:
        """Initialize the search service.
        
        Args:
            user_id: User ID for access control.
        """
        self.config = get_config()
        self.user_id = user_id
        self._vector_store: VectorStore | None = None

    @property
    def embedding_generator(self) -> EmbeddingProvider:
        """Return the global singleton embedding generator."""
        return get_embedding_generator()
    
    @property
    def vector_store(self) -> VectorStore:
        """Lazy-load vector store."""
        if self._vector_store is None:
            self._vector_store = get_vector_store()
        return self._vector_store

    def search_code(
        self,
        query: str,
        repo_ids: list[str] | None = None,
        language: str | None = None,
        file_pattern: str | None = None,
        top_k: int = 10,
        user_id: str | None = None,
        quality_mode: str | None = None,
        timeout_ms: int = 120_000,
        cancellation: CancellationToken | None = None,
    ) -> dict[str, Any]:
        """Search code using semantic + hybrid retrieval.

        ACCESS CONTROL: Only searches repos in user's collection.

        In agent quality mode (default for MCP), runs five retrieval branches
        — vector, BM25, exact symbol, exact path, trigram — fuses them, and
        preserves high-recall rank with stable file-level diversity.
        Pure-vector search used to lose the identifier battle on queries like
        ``handleAuthCallback`` or ``go.mod``; hybrid recovers them.

        Args:
            query: Search query (natural language or keywords)
            repo_ids: Optional list of repository IDs to search (must be in collection)
            language: Filter by programming language
            file_pattern: Filter by file path pattern
            top_k: Number of results to return
            user_id: User ID for access control (overrides constructor user_id)
            quality_mode: 'fast', 'balanced', or 'agent'. None falls back to
                the global default. Agent mode forces high-recall hybrid
                retrieval; reranking remains an explicit deployment option.

        Returns:
            Dict with search results, including ``candidate_sources`` per
            result so agents (and humans) can see why something matched.
        """
        start_time = time.time()
        effective_user_id = user_id or self.user_id
        token = cancellation or CancellationToken()
        if not 1 <= timeout_ms <= 300_000:
            raise ValueError("timeout_ms must be between 1 and 300000")
        deadline_monotonic = time.monotonic() + timeout_ms / 1000

        def remaining_timeout_ms() -> int:
            return max(
                1,
                int(
                    (deadline_monotonic - time.monotonic()) * 1000
                ),
            )

        def stopped() -> bool:
            return (
                token.cancelled
                or time.monotonic() >= deadline_monotonic
            )

        # Require user_id
        if not effective_user_id:
            return {
                "success": False,
                "query": query,
                "error": "Authentication required",
                "message": "You must be authenticated to search",
            }
        if stopped():
            return {
                "success": False,
                "query": query,
                "error": "Search cancelled",
                "results": [],
            }

        # Resolve effective quality mode for this call.
        effective_mode = quality_mode or self.config.quality.quality_mode
        agent_mode = effective_mode == "agent"
        # Agent mode implies high-recall hybrid retrieval. Cross-encoder
        # reranking remains an explicit deployment choice: forcing it here
        # can erase exact test/doc/path candidates and adds model latency.
        use_hybrid = agent_mode or self.config.search.enable_hybrid
        use_rerank = self.config.search.enable_reranker
        effective_file_pattern = file_pattern
        if agent_mode and effective_file_pattern is None:
            effective_file_pattern = _related_path_pattern(query)

        try:
            retrieval_query = _prepare_search_query(query)
            # Generate query embedding
            t_embed = time.time()
            query_embedding = self.embedding_generator.generate_single(
                retrieval_query
            )
            embed_ms = (time.time() - t_embed) * 1000
            if stopped():
                return {
                    "success": False,
                    "query": query,
                    "error": "Search cancelled",
                    "results": [],
                }

            # Over-fetch for post-retrieval quality pipeline. Hybrid mode pulls
            # the wider window per branch so rerank has room to work.
            fetch_k = max(top_k * 3, 20)
            if use_hybrid:
                fetch_k = max(fetch_k, self.config.search.hybrid_candidates)

            db_ms = 0.0
            hybrid_meta: dict[str, Any] | None = None

            if use_hybrid:
                # Hybrid: vector + BM25 + symbol + path + trigram, fused.
                from synsc.services.hybrid_retrieval import hybrid_retrieve

                t_db = time.time()
                with get_session() as hsess:
                    hsess.execute(
                        text(
                            "SELECT set_config("
                            "'statement_timeout', :timeout, true)"
                        ),
                        {"timeout": f"{remaining_timeout_ms()}ms"},
                    )
                    fused = hybrid_retrieve(
                        session=hsess,
                        query=retrieval_query,
                        query_embedding=query_embedding,
                        vector_search_fn=lambda **kwargs: (
                            self.vector_store.search(
                                **kwargs,
                                timeout_ms=remaining_timeout_ms(),
                            )
                        ),
                        user_id=effective_user_id,
                        repo_ids=repo_ids,
                        language=language,
                        file_pattern=effective_file_pattern,
                        top_k=fetch_k,
                    )
                db_ms = (time.time() - t_db) * 1000
                raw_results = [c.to_dict() for c in fused]
                hybrid_meta = {
                    "candidates": len(fused),
                    "sources_hit": {
                        src: sum(1 for c in fused if src in c.sources)
                        for src in ("vector", "bm25", "symbol", "path", "trigram")
                    },
                }
                # Path filter is part of hybrid retrieval already, no need to
                # re-filter here (it would also throw away same-file siblings
                # the path branch surfaced).
            else:
                # Legacy pure-vector path
                t_db = time.time()
                raw_results = self.vector_store.search(
                    query_embedding=query_embedding,
                    user_id=effective_user_id,
                    repo_ids=repo_ids,
                    language=language,
                    top_k=fetch_k,
                    timeout_ms=remaining_timeout_ms(),
                )
                db_ms = (time.time() - t_db) * 1000

                # Apply file pattern filter early (before quality pipeline)
                if file_pattern:
                    import fnmatch
                    raw_results = [
                        r for r in raw_results
                        if fnmatch.fnmatch(r.get("file_path", ""), file_pattern)
                    ]

            # --- Quality pipeline ---
            if stopped():
                return {
                    "success": False,
                    "query": query,
                    "error": "Search cancelled",
                    "results": [],
                }

            # 1. Symbol-aware score boosting
            query_symbols = _extract_query_symbols(retrieval_query)
            if query_symbols:
                _apply_symbol_boost(raw_results, query_symbols)

            # 2. Metadata-aware scoring for implementation-focused modes.
            # Agent mode deliberately indexes tests/docs/examples as useful
            # context, so a blanket penalty contradicts that contract. The
            # other modes still demote, but only for families this query did
            # not ask for — "which test covers X" must not bury tests.
            if not agent_mode:
                _apply_metadata_scoring(raw_results, query=retrieval_query)

            # Re-sort after boosting + metadata adjustments
            raw_results.sort(key=lambda r: r["similarity"], reverse=True)

            # 3. Optional cross-encoder reranking (blended with fused/vector
            #    similarity), gated by SYNSC_ENABLE_RERANKER.
            #    Limit to hybrid_rerank_k candidates to bound latency.
            if (
                len(raw_results) > 1
                and use_rerank
                and not stopped()
                and deadline_monotonic - time.monotonic() >= 0.25
            ):
                try:
                    from synsc.services.reranker import get_reranker
                    reranker = get_reranker()
                    rerank_window = self.config.search.hybrid_rerank_k
                    if agent_mode:
                        head = _select_source_diverse_results(
                            raw_results,
                            top_k=rerank_window,
                        )
                        head_ids = {id(result) for result in head}
                        tail = [
                            result
                            for result in raw_results
                            if id(result) not in head_ids
                        ]
                    else:
                        head = raw_results[:rerank_window]
                        tail = raw_results[rerank_window:]
                    head = reranker.rerank(
                        query=retrieval_query,
                        results=head,
                        blend_alpha=self.config.search.reranker_blend_alpha,
                    )
                    raw_results = head + tail
                except Exception as e:
                    logger.warning(
                        "Reranker unavailable, falling back to fused similarity",
                        error=str(e),
                    )
            if stopped():
                return {
                    "success": False,
                    "query": query,
                    "error": "Search cancelled or timed out",
                    "results": [],
                }

            if agent_mode:
                # Keep high-recall branch candidates and avoid returning many
                # chunks from a single file without lossy thresholding or
                # quadratic content-MMR.
                raw_results = _select_source_diverse_results(
                    raw_results,
                    top_k=top_k,
                )
            else:
                # 4. Dynamic similarity threshold
                raw_results = _apply_dynamic_threshold(
                    raw_results,
                    min_absolute=self.config.search.min_similarity_score,
                )

                # 5. MMR diversification (select top_k from candidates)
                raw_results = _apply_mmr(
                    raw_results,
                    query_embedding=query_embedding,
                    top_k=top_k,
                )

            # 6. Context enrichment (attach docstrings/signatures)
            raw_results = _enrich_results_with_context(raw_results)

            # Format results — surface candidate_sources so agents can reason
            # about *why* a chunk matched (vector vs symbol vs path vs BM25).
            results = []
            for r in raw_results:
                results.append({
                    "repo_id": r["repo_id"],
                    "repo_name": r.get("repo_name", ""),
                    "file_path": r.get("file_path", ""),
                    "chunk_id": r["chunk_id"],
                    "content": r["content"],
                    "start_line": r["start_line"],
                    "end_line": r["end_line"],
                    "language": r.get("language"),
                    "relevance_score": r["similarity"],
                    "chunk_type": r.get("chunk_type", "code"),
                    "is_public": r.get("is_public", True),
                    "candidate_sources": r.get("candidate_sources"),
                })
            
            elapsed_time = (time.time() - start_time) * 1000

            logger.debug(
                "Search timing breakdown",
                embed_ms=round(embed_ms, 1),
                db_ms=round(db_ms, 1),
                total_ms=round(elapsed_time, 1),
                pipeline_ms=round(elapsed_time - embed_ms - db_ms, 1),
                results=len(results),
            )

            # Telemetry: which branches contributed, top scores, latency.
            # Best-effort — never break search if logging fails.
            try:
                from synsc.services.observability import log_search_telemetry
                log_search_telemetry(
                    user_id=effective_user_id,
                    query=retrieval_query,
                    quality_mode=effective_mode,
                    hybrid_meta=hybrid_meta,
                    top_results=results,
                    elapsed_ms=elapsed_time,
                )
            except Exception:
                pass

            # An index built by a different embedding model returns plausible
            # results with meaningless scores, and stays invisible unless it is
            # reported. Surface it on the response rather than only in logs.
            warnings: list[dict[str, str]] = []
            try:
                from synsc.services.embedding_consistency import (
                    active_embedding_model,
                    find_embedding_mismatches,
                )

                with get_session() as csess:
                    mismatches = find_embedding_mismatches(
                        csess, active_embedding_model(), repo_ids
                    )
                for mismatch in mismatches:
                    logger.error(
                        "embedding model mismatch — vector scores are not meaningful",
                        **mismatch.as_dict(),
                    )
                    warnings.append(
                        {"code": "embedding_model_mismatch", **mismatch.as_dict()}
                    )
            except Exception:
                pass

            payload = {
                "success": True,
                "query": query,
                "retrieval_query": retrieval_query,
                "query_compacted": retrieval_query != query,
                "results": results,
                "count": len(results),
                "search_time_ms": elapsed_time,
                "quality_mode": effective_mode,
                "hybrid": hybrid_meta,
                "timing": {
                    "embedding_ms": round(embed_ms, 1),
                    "db_search_ms": round(db_ms, 1),
                    "pipeline_ms": round(elapsed_time - embed_ms - db_ms, 1),
                },
            }
            if warnings:
                payload["warnings"] = warnings
            return payload
            
        except Exception as e:
            logger.error("Search failed", error=str(e), user_id=effective_user_id)
            return {
                "success": False,
                "query": query,
                "error": str(e),
                "message": f"Search failed: {e}",
            }

    def get_file(
        self,
        repo_id: str,
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Get file content from a repository.
        
        ACCESS CONTROL:
        - Public repos: User must have it in their collection
        - Private repos: Only the indexer can access
        
        Args:
            repo_id: Repository ID
            file_path: Path to file within repository
            start_line: Starting line (1-indexed)
            end_line: Ending line
            user_id: User ID for authorization
            
        Returns:
            Dict with file content
        """
        effective_user_id = user_id or self.user_id
        
        with get_session() as session:
            repo = session.query(Repository).filter(
                Repository.repo_id == repo_id
            ).first()
            
            if not repo:
                return {
                    "success": False,
                    "error": "Repository not found",
                }
            
            # Check access control
            if not repo.can_user_access(effective_user_id):
                return {
                    "success": False,
                    "error": "Access denied",
                    "message": "You don't have access to this private repository",
                }
            
            # Check if in user's collection (for public repos)
            if effective_user_id:
                user_repo = session.query(UserRepository).filter(
                    UserRepository.user_id == effective_user_id,
                    UserRepository.repo_id == repo_id,
                ).first()
                
                if not user_repo and repo.is_public:
                    return {
                        "success": False,
                        "error": "Not in collection",
                        "message": "Add this repository to your collection first",
                    }
            
            db_file = session.query(RepositoryFile).filter(
                RepositoryFile.repo_id == repo_id,
                RepositoryFile.file_path == file_path,
            ).first()
            
            if not db_file:
                return {
                    "success": False,
                    "error": "File not found",
                }
            
            content = None
            source = None
            
            # Try to read from local clone first (if available)
            if repo.local_path:
                full_path = Path(repo.local_path) / file_path
                if full_path.exists():
                    content = full_path.read_text(encoding="utf-8", errors="ignore")
                    source = "local"
            
            # Fall back to reconstructing from chunks (cloud mode)
            if content is None:
                content = self._reconstruct_file_from_chunks(session, db_file.file_id)
                if content is not None:
                    source = "chunks"
            
            if content is None:
                return {
                    "success": False,
                    "error": "File content not available",
                    "message": "Local clone not found and no chunks indexed for this file",
                }
            
            total_lines = content.count("\n") + 1
            
            # Apply line range
            if start_line or end_line:
                lines = content.split("\n")
                start = (start_line or 1) - 1
                end = end_line or len(lines)
                content = "\n".join(lines[start:end])

            # Observability: stamp every chunk in the requested range as
            # "used" so we can measure get_file-after-search_code rates.
            # Best-effort — never break the read on logging failure.
            try:
                from synsc.services.observability import log_chunk_used
                lo, hi = start_line or 1, end_line or total_lines
                used_chunks = session.execute(
                    text(
                        """
                        SELECT chunk_id FROM code_chunks
                        WHERE file_id = :fid
                          AND start_line <= :hi AND end_line >= :lo
                        LIMIT 25
                        """
                    ),
                    {"fid": db_file.file_id, "lo": lo, "hi": hi},
                ).fetchall()
                for row in used_chunks:
                    log_chunk_used(user_id=effective_user_id, chunk_id=str(row[0]))
            except Exception:
                pass

            return {
                "success": True,
                "repo_id": repo_id,
                "file_path": file_path,
                "content": content,
                "language": db_file.language,
                "total_lines": total_lines,
                "start_line": start_line or 1,
                "end_line": end_line or total_lines,
                "source": source,  # "local" or "chunks"
                "is_public": repo.is_public,
            }
    
    def _reconstruct_file_from_chunks(
        self,
        session: Session,
        file_id: str,
    ) -> str | None:
        """Reconstruct file content from indexed chunks.
        
        Chunks are ordered by chunk_index and concatenated.
        Note: This may not perfectly reproduce the original file due to
        overlap removal and chunking boundaries.
        
        Args:
            session: Database session
            file_id: File identifier
            
        Returns:
            Reconstructed file content, or None if no chunks found
        """
        chunks = session.query(CodeChunk).filter(
            CodeChunk.file_id == file_id
        ).order_by(CodeChunk.chunk_index).all()
        
        if not chunks:
            return None
        
        # Simple reconstruction: join chunks, removing overlap
        # This is approximate since chunk overlap means content duplication
        content_parts = []
        last_end_line = 0
        
        for chunk in chunks:
            if chunk.start_line > last_end_line:
                # No overlap with previous chunk
                content_parts.append(chunk.content)
            else:
                # Overlapping content - skip lines we've already added
                lines = chunk.content.split("\n")
                skip_lines = last_end_line - chunk.start_line + 1
                if skip_lines < len(lines):
                    content_parts.append("\n".join(lines[skip_lines:]))
            
            last_end_line = chunk.end_line
        
        return "\n".join(content_parts) if content_parts else None
