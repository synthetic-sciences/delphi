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


def test_identifier_token_dominates_conceptual_phrase():
    """When an identifier is named explicitly, treat as identifier intent.

    Earlier iterations tried to force "with X to Y" phrasing to conceptual
    even when an identifier was present. Bench results showed that hurt
    more than helped — when the user names the exact class they want
    (``StreamingResponse``, ``OAuth2PasswordBearer``), code is the right
    answer, not the surrounding tutorial.
    """
    for q in (
        "Stream a response body with FastAPI StreamingResponse",
        "Mounting a httpx-based test client to a FastAPI app",
        "FastAPI OAuth2 password flow with httpx",
    ):
        assert source_service.classify_query_intent(q) == "identifier", q


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
