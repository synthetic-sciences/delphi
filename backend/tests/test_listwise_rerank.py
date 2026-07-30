"""Listwise reranking must reorder usefully and never lose a candidate."""
from __future__ import annotations

from synsc.services.listwise_rerank import build_prompt, listwise_rerank, parse_order


def test_parse_order_reads_a_plain_array():
    assert parse_order("[3,1,2]", 3) == [2, 0, 1]


def test_parse_order_tolerates_prose_and_fences():
    assert parse_order("Here you go:\n```json\n[2, 1]\n```", 2) == [1, 0]


def test_parse_order_appends_anything_the_model_omitted():
    # A formatting slip must never silently drop a candidate.
    assert parse_order("[3]", 4) == [2, 0, 1, 3]


def test_parse_order_ignores_out_of_range_and_duplicates():
    assert parse_order("[2,2,99,-1,1]", 3) == [1, 0, 2]


def test_parse_order_rejects_a_reply_with_no_numbers():
    assert parse_order("I cannot rank these", 3) is None


def test_prompt_carries_paths_and_excerpts():
    prompt = build_prompt(
        "which test covers the proxy",
        [{"file_path": "tests/proxy_test.go", "content": "func TestProxy() {}"}],
        excerpt_chars=100,
    )
    assert "tests/proxy_test.go" in prompt
    assert "func TestProxy() {}" in prompt
    assert "which test covers the proxy" in prompt


def test_disabled_by_default_returns_input_untouched():
    results = [{"file_path": "a.py", "content": "x", "similarity": 0.9}]
    assert listwise_rerank("q", results) == results


def test_single_result_is_never_sent_to_the_model():
    # Nothing to compare, so nothing to spend a model call on.
    results = [{"file_path": "a.py", "content": "x", "similarity": 0.9}]
    assert listwise_rerank("q", results) is results
