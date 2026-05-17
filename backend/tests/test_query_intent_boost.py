"""Tests for query-intent classification + docs/paper boost."""
from __future__ import annotations

from synsc.services import source_service


def test_conceptual_starters_detected():
    for q in (
        "how does FastAPI background tasks execute",
        "What happens when httpx times out?",
        "Why use AsyncClient over Client?",
        "Explain dependency injection",
        "compare Path vs Query parameters",
    ):
        assert source_service.classify_query_intent(q) == "conceptual", q


def test_identifier_queries_detected():
    for q in (
        "FastAPI.routing.APIRouter",
        "OAuth2PasswordBearer signature",
        "BaseModel.model_validate parameters",
    ):
        assert source_service.classify_query_intent(q) == "identifier", q


def test_conceptual_phrases_override_identifier_tokens():
    """A query with both an identifier-shaped token and a how-to phrase is conceptual."""
    for q in (
        "FastAPI OAuth2 password flow with httpx client to call token endpoint",
        "Use FastAPI middleware to handle CORS",
        "Configure FastAPI with HTTPS",
    ):
        assert source_service.classify_query_intent(q) == "conceptual", q


def test_gerund_opener_is_conceptual():
    """``Mounting``, ``Streaming``, ``Configuring`` — how-to-do-X queries."""
    for q in (
        "Mounting a httpx-based test client to a FastAPI app",
        "Streaming a response with StreamingResponse",
        "Configuring CORS middleware",
    ):
        assert source_service.classify_query_intent(q) == "conceptual", q


def test_neutral_queries():
    # No conceptual starter, no dotted identifier, no snake_case.
    assert source_service.classify_query_intent("middleware") == "neutral"
    assert source_service.classify_query_intent("") == "neutral"


def test_conceptual_boost_lifts_docs_above_code():
    hits = [
        {"source_type": "repo", "score": 0.85},
        {"source_type": "repo", "score": 0.80},
        {"source_type": "docs", "score": 0.75},
        {"source_type": "docs", "score": 0.70},
    ]
    source_service._apply_query_type_boost(
        "how does FastAPI dependency injection work", hits
    )
    # After +0.15 to docs, the top docs (0.90) outranks the top repo (0.85).
    docs_top = max(h["score"] for h in hits if h["source_type"] == "docs")
    repo_top = max(h["score"] for h in hits if h["source_type"] == "repo")
    assert docs_top > repo_top


def test_identifier_boost_keeps_code_on_top():
    hits = [
        {"source_type": "docs", "score": 0.85},
        {"source_type": "repo", "score": 0.80},
    ]
    source_service._apply_query_type_boost(
        "fastapi.routing.APIRouter.include_router", hits
    )
    # Repo gets +0.10 → 0.90, docs stays 0.85 → docs no longer wins.
    repo = next(h for h in hits if h["source_type"] == "repo")
    docs = next(h for h in hits if h["source_type"] == "docs")
    assert repo["score"] > docs["score"]


def test_neutral_intent_does_not_modify_scores():
    hits = [
        {"source_type": "docs", "score": 0.6},
        {"source_type": "repo", "score": 0.5},
    ]
    source_service._apply_query_type_boost("middleware", hits)
    assert hits[0]["score"] == 0.6
    assert hits[1]["score"] == 0.5
