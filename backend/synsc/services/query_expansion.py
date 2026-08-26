"""Hypothetical-document expansion for prose queries over code.

A code index is written in code. A question about it is often written in
English — "this should probably be extracted into a helper", "why does the
retry loop give up early". Those two vocabularies barely overlap, so the
embedding of the question lands nowhere near the embedding of the answer, and
the vector branch contributes noise on exactly the queries that need it most.

The fix is the HyDE construction: ask a small model to write the code it
thinks the answer looks like, and embed *that* instead of the question. The
hypothetical snippet does not have to be correct. It only has to be written in
the same vocabulary as the corpus, which is enough to put the query vector in
the right neighbourhood.

Only the vector branch uses the expansion. BM25, symbol, path, and trigram
still see the caller's literal text, because those branches are exact-match
machinery and inventing terms for them would manufacture false precision.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
import structlog

from synsc.config import get_config
from synsc.core.llm_cache import BoundedCache, get_cache

logger = structlog.get_logger(__name__)

_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_PROMPT_REV = "hyde-v1"

_SYSTEM_PROMPT = (
    "You write short, plausible code snippets that would answer a developer's "
    "question about an unfamiliar codebase. Reply with code only: no prose, no "
    "explanation, no fences. Invent idiomatic function, class, and variable "
    "names for the language implied by the question. Being wrong about the "
    "specifics is fine; using the vocabulary real code would use is what "
    "matters. Keep it under 15 lines."
)

# Identifier-shaped tokens: snake_case, camelCase, dotted paths, file paths.
_CODEY_TOKEN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:[._/][A-Za-z0-9_]+)+|[a-z]+[A-Z][A-Za-z0-9]*|\w+_\w+"
)
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def looks_like_prose(query: str, threshold: float = 0.12) -> bool:
    """True when a query is mostly English rather than mostly identifiers.

    Expansion is worth its latency only where the vocabularies actually
    diverge. A query that is already full of symbol names does not need a
    hypothetical document — the lexical branches will find those symbols
    directly, and expanding would only blur a precise query.
    """
    words = _WORD.findall(query)
    if len(words) < 6:
        return False
    codey = len(set(_CODEY_TOKEN.findall(query)))
    return (codey / len(words)) < threshold


_PROSE_FIELD_TOKENS = {
    "comment",
    "review",
    "title",
    "intent",
    "goal",
    "task",
    "question",
    "request",
    "description",
    "summary",
    "objective",
    "message",
    "body",
}


def structured_prose_view(query: str) -> str | None:
    """The human sentences inside a structured developer envelope.

    A review comment arrives wrapped in JSON alongside paths, diff hunks, and
    line numbers. Judged as one string, that envelope looks like code — full
    of identifiers — so the prose gate skips expansion on exactly the queries
    whose English most needs the vocabulary bridge. Pull out just the fields
    a person wrote (comment, title, intent, question) and let the gate and
    the expansion prompt see those.
    """
    try:
        payload = json.loads(query)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    pieces: list[str] = []

    def collect(key: str, value: Any) -> None:
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                collect(str(nested_key), nested_value)
            return
        if isinstance(value, list):
            for item in value:
                collect(key, item)
            return
        if not isinstance(value, str) or not value.strip():
            return
        key_tokens = set(re.sub(r"[^a-z0-9]+", "_", key.lower()).split("_"))
        if key_tokens & _PROSE_FIELD_TOKENS:
            pieces.append(" ".join(value.split()))

    for field, field_value in payload.items():
        collect(str(field), field_value)
    joined = " ".join(dict.fromkeys(pieces)).strip()
    return joined or None


def expand_query(
    query: str, *, timeout: float = 10.0, prose: str | None = None
) -> str | None:
    """Return a hypothetical code snippet for ``query``, or None.

    ``prose`` overrides both the gate and the prompt when the caller has a
    cleaner view of the human-written part of the query (see
    ``structured_prose_view``). Returns None whenever expansion is disabled,
    unnecessary, or unavailable. A failure here must never fail the search:
    the caller falls back to embedding the original query, which is exactly
    today's behaviour.
    """
    config = get_config()
    if not config.search.enable_query_expansion:
        return None
    gate_text = prose if prose is not None else query
    if not looks_like_prose(gate_text):
        return None

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        logger.warning("query expansion enabled but OPENAI_API_KEY is unset")
        return None

    # A long pasted trace is already full of code vocabulary; only the leading
    # request is worth expanding, and it keeps the prompt cheap.
    prompt = (prose if prose is not None else query)[:2000]

    # Chat models resample even at temperature 0, and the expansion feeds the
    # query embedding, so an uncached expansion makes the whole vector branch
    # non-repeatable. First answer wins for the lifetime of the process.
    cache = get_cache(
        "query-expansion",
        config.search.llm_cache_entries,
        persistent_path=config.search.llm_cache_db,
    )
    cache_key = BoundedCache.key(
        _PROMPT_REV,
        config.search.query_expansion_model,
        str(config.search.llm_seed),
        prompt,
    )

    def fetch_expansion() -> str | None:
        try:
            response = httpx.post(
                _ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.search.query_expansion_model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "max_completion_tokens": 220,
                    "temperature": 0.0,
                    "seed": config.search.llm_seed,
                },
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - expansion is strictly optional
            logger.warning("query expansion failed", error=str(exc)[:200])
            return None

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            return None
        return content.strip() if isinstance(content, str) else None

    content = cache.get_or_compute(cache_key, fetch_expansion)
    return content or None


def embedding_text(query: str, *, raw_query: str | None = None) -> tuple[str, bool]:
    """Text the vector branch should embed, and whether it was expanded.

    The original query is kept alongside the hypothetical snippet rather than
    replaced by it. Pure HyDE throws away the caller's own words, and when the
    model guesses the domain wrong that is the only signal left.

    ``raw_query`` is the caller's pre-compaction request. When it is a
    structured envelope, the human-written fields inside it gate and seed the
    expansion, so a review comment buried in JSON still gets its vocabulary
    bridge.
    """
    prose = structured_prose_view(raw_query) if raw_query else None
    expansion = expand_query(query, prose=prose)
    if not expansion:
        return query, False
    return f"{query}\n\n{expansion}", True
