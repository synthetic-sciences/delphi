"""Listwise reranking of the retrieved head by a small language model.

A cross-encoder scores each candidate against the query in isolation, so it
can tell you that a chunk is *about* authentication but not that it is the
better of two authentication files for this particular question. Ranking is
comparative, and a listwise model gets to make the comparison: it sees the
candidates together and orders them.

This runs on the head of an already-good list. Retrieval and fusion decide
what is on the page; this decides what is at the top of it, which is where
Recall@5 and MRR live.

Failure is always silent and always falls back to the incoming order, because
a reranker that can 500 a search is worse than no reranker.
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx
import structlog

from synsc.config import get_config

logger = structlog.get_logger(__name__)

_ENDPOINT = "https://api.openai.com/v1/chat/completions"

_SYSTEM_PROMPT = (
    "You rank candidate source files by how directly each one answers a "
    "developer's request about a codebase.\n"
    "You are given a request and a numbered list of candidates, each with its "
    "repository path and an excerpt.\n"
    "Return the candidate numbers ordered best first, as a JSON array of "
    "integers, and nothing else. Example: [4,1,9,2]\n"
    "Include every candidate number exactly once.\n"
    "Judge by what the request actually asks for. If it asks which test covers "
    "some behaviour, a test file is the answer and the implementation is not. "
    "If it asks where something is implemented, the reverse holds. Prefer the "
    "file that would have to be opened or edited to satisfy the request over "
    "one that merely mentions the same words."
)

_INT = re.compile(r"-?\d+")


def _excerpt(text: str, limit: int) -> str:
    """One-line-per-newline excerpt, bounded, so prompts stay predictable."""
    collapsed = " ".join((text or "").split())
    return collapsed[:limit]


def build_prompt(
    query: str, candidates: list[dict[str, Any]], excerpt_chars: int
) -> str:
    lines = [f"Request:\n{_excerpt(query, 1200)}\n", "Candidates:"]
    for index, candidate in enumerate(candidates, start=1):
        path = candidate.get("file_path") or "(unknown path)"
        lines.append(
            f"{index}. {path}\n   {_excerpt(candidate.get('content', ''), excerpt_chars)}"
        )
    return "\n".join(lines)


def parse_order(reply: str, count: int) -> list[int] | None:
    """Read the model's ranking into 0-based indices.

    Tolerant of a model that wraps the array in prose or fences, strict about
    the result being a usable permutation: unknown or duplicate numbers are
    dropped, and anything the model omitted is appended in its original order
    so no candidate is ever lost to a formatting slip.
    """
    numbers = [int(match) for match in _INT.findall(reply or "")]
    order: list[int] = []
    seen: set[int] = set()
    for number in numbers:
        index = number - 1
        if 0 <= index < count and index not in seen:
            seen.add(index)
            order.append(index)
    if not order:
        return None
    order.extend(index for index in range(count) if index not in seen)
    return order


def listwise_rerank(
    query: str, results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Reorder the head of ``results`` with a listwise model.

    Returns the input unchanged when disabled, unavailable, or on any error.
    """
    config = get_config()
    if not config.search.enable_listwise_rerank:
        return results

    depth = max(0, config.search.listwise_rerank_k)
    if depth < 2 or len(results) < 2:
        return results

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        logger.warning("listwise rerank enabled but OPENAI_API_KEY is unset")
        return results

    head = results[:depth]
    tail = results[depth:]
    prompt = build_prompt(query, head, config.search.listwise_excerpt_chars)

    try:
        response = httpx.post(
            _ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.search.listwise_rerank_model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_completion_tokens": 300,
                "temperature": 0.0,
            },
            timeout=config.search.listwise_timeout_seconds,
        )
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001 - ranking must never fail a search
        logger.warning("listwise rerank failed", error=str(exc)[:200])
        return results

    order = parse_order(reply, len(head))
    if order is None:
        logger.warning("listwise rerank returned no usable order")
        return results

    reordered = [head[index] for index in order]

    # Keep ``similarity`` monotone with the new order. Downstream code sorts,
    # thresholds, and reports on that field, so leaving the old scores behind
    # would let a later step undo this ranking.
    if reordered:
        top = float(reordered[0].get("similarity", 1.0)) or 1.0
        step = top / (len(reordered) + 1)
        for position, item in enumerate(reordered):
            item["similarity"] = top - position * step
            item["listwise_rank"] = position + 1

    return reordered + tail
