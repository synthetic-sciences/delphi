"""Token-budget + topic filtering helpers for fetch/search results.

Context7 exposes ``tokens`` and ``topic`` on every doc fetch — agents pay per
token and rarely need a whole library's docs. These helpers let every Delphi
fetch/search tool offer the same two parameters with consistent semantics.

Token estimate: 1 token ~= 4 characters (English ASCII). We keep the
heuristic; precise tokenization would require pulling tiktoken, which adds a
large dep for a budgeter that's already only a soft cap.
"""
from __future__ import annotations

import re
from typing import Any

_CHARS_PER_TOKEN = 4
_DEFAULT_BUDGET_TOKENS = 5000


def tokens_to_chars(tokens: int) -> int:
    return max(1, int(tokens) * _CHARS_PER_TOKEN)


def chars_to_tokens(chars: int) -> int:
    return max(0, int(chars) // _CHARS_PER_TOKEN)


def truncate_to_tokens(text: str | None, max_tokens: int | None) -> str:
    """Hard-cap ``text`` to ``max_tokens``. None / non-positive → unchanged."""
    if not text or not max_tokens or max_tokens <= 0:
        return text or ""
    cap = tokens_to_chars(max_tokens)
    if len(text) <= cap:
        return text
    # Snap to the nearest paragraph / sentence end to avoid mid-word cutoffs.
    head = text[:cap]
    for sep in ("\n\n", ". ", "\n", ".", " "):
        idx = head.rfind(sep)
        if idx >= cap * 0.85:
            return head[: idx + len(sep)] + "..."
    return head + "..."


def _tokenize_topic(topic: str) -> list[str]:
    return [t for t in re.split(r"[\s,/_\-]+", topic.lower()) if t]


def topic_matches(text: str | None, topic: str | None) -> bool:
    """True if any topic token appears in ``text`` (case-insensitive)."""
    if not topic:
        return True
    if not text:
        return False
    haystack = text.lower()
    for tok in _tokenize_topic(topic):
        if tok in haystack:
            return True
    return False


def filter_results_by_topic(
    results: list[dict[str, Any]],
    topic: str | None,
    *,
    text_keys: tuple[str, ...] = ("content", "text", "heading", "section"),
) -> list[dict[str, Any]]:
    """Filter result dicts whose joined text-keys match the topic."""
    if not topic:
        return results
    out = []
    for r in results:
        haystack = " ".join(
            str(r.get(k) or "") for k in text_keys if r.get(k)
        )
        if topic_matches(haystack, topic):
            out.append(r)
    return out


def budget_results(
    results: list[dict[str, Any]],
    tokens: int | None,
    *,
    text_key: str = "content",
) -> list[dict[str, Any]]:
    """Pack ``results`` into a ``tokens`` budget, truncating the last one.

    Returns a new list. Preserves order. If ``tokens`` is None / non-positive
    the list passes through. Adds ``_truncated: True`` to the last item that
    gets cut and ``_dropped: True`` to anything that didn't fit at all.
    """
    if not tokens or tokens <= 0:
        return results

    cap = tokens_to_chars(tokens)
    used = 0
    out: list[dict[str, Any]] = []
    for r in results:
        body = r.get(text_key) or ""
        if used >= cap:
            new_r = dict(r)
            new_r["_dropped"] = True
            new_r[text_key] = ""
            out.append(new_r)
            continue
        remaining = cap - used
        if len(body) <= remaining:
            out.append(r)
            used += len(body)
        else:
            new_r = dict(r)
            new_r[text_key] = truncate_to_tokens(body, chars_to_tokens(remaining))
            new_r["_truncated"] = True
            out.append(new_r)
            used = cap
    return out


def default_budget() -> int:
    """Default token budget when caller didn't pass one."""
    return _DEFAULT_BUDGET_TOKENS
