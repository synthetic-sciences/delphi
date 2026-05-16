"""Unit tests for the token-budget + topic-filter helpers."""
from __future__ import annotations

from synsc.services.budget import (
    budget_results,
    chars_to_tokens,
    filter_results_by_topic,
    topic_matches,
    tokens_to_chars,
    truncate_to_tokens,
)


def test_tokens_chars_roundtrip():
    assert tokens_to_chars(100) == 400
    assert chars_to_tokens(400) == 100


def test_truncate_passthrough_when_budget_none():
    assert truncate_to_tokens("hello", None) == "hello"
    assert truncate_to_tokens("hello", 0) == "hello"


def test_truncate_caps_long_text():
    text = "a" * 1000
    out = truncate_to_tokens(text, 10)  # 10 tokens = 40 chars
    assert len(out) <= 50  # 40 chars + "..."
    assert out.endswith("...")


def test_truncate_snaps_to_sentence_end():
    text = "First sentence. Second sentence. Third sentence." * 5
    out = truncate_to_tokens(text, 20)  # 80 chars budget
    # Should land on a sentence boundary (ends with '. ' + '...' or similar)
    assert out.endswith("...")
    assert "First sentence" in out


def test_topic_matches_any_token():
    assert topic_matches("FastAPI routing guide", "routing") is True
    assert topic_matches("FastAPI routing guide", "hooks/react") is False
    assert topic_matches("FastAPI routing guide", "guide,hooks") is True


def test_topic_matches_no_topic_passes():
    assert topic_matches("anything", None) is True
    assert topic_matches("anything", "") is True


def test_filter_results_by_topic_keeps_matching():
    results = [
        {"content": "Authentication flow", "section": "Security"},
        {"content": "Router setup", "section": "Routing"},
        {"content": "Misc tips", "section": "Misc"},
    ]
    out = filter_results_by_topic(results, "routing", text_keys=("content", "section"))
    assert len(out) == 1
    assert out[0]["section"] == "Routing"


def test_filter_results_by_topic_none_passes_through():
    results = [{"content": "a"}, {"content": "b"}]
    assert filter_results_by_topic(results, None) == results


def test_budget_results_drops_after_cap():
    # Each result is 40 chars = 10 tokens; budget 25 tokens = 100 chars.
    results = [{"content": "x" * 40} for _ in range(5)]
    out = budget_results(results, tokens=25, text_key="content")
    # First 2 fit fully (80 chars), third truncated to remaining 20 chars,
    # last two dropped.
    assert out[0]["content"] == "x" * 40
    assert out[1]["content"] == "x" * 40
    assert out[2].get("_truncated") is True
    assert out[3].get("_dropped") is True
    assert out[4].get("_dropped") is True


def test_budget_results_zero_or_none_passthrough():
    results = [{"content": "abc"}]
    assert budget_results(results, None, text_key="content") == results
    assert budget_results(results, 0, text_key="content") == results
