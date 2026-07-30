"""Prose queries over a code index need a vocabulary bridge, precise ones do not."""
from __future__ import annotations

from synsc.services.query_expansion import embedding_text, expand_query, looks_like_prose


def test_prose_question_is_detected():
    assert looks_like_prose(
        "why does the retry loop give up before the timeout is reached"
    )


def test_identifier_heavy_query_is_not_prose():
    # Already in the corpus vocabulary — expanding would blur a precise query.
    assert not looks_like_prose(
        "handleAuthCallback token_store.refresh auth/tokens.py validate_jwt"
    )


def test_short_query_is_left_alone():
    # Too little signal to classify, and too cheap to be worth a model call.
    assert not looks_like_prose("retry loop")


def test_expansion_is_off_by_default():
    assert expand_query("why does the retry loop give up early") is None


def test_embedding_text_falls_back_to_the_original_query():
    text, expanded = embedding_text("why does the retry loop give up early")
    assert text == "why does the retry loop give up early"
    assert expanded is False
