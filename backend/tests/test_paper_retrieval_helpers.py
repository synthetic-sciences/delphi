"""Unit tests for paper_retrieval helpers (section weights, sentence
splitter, quote scoring). DB-backed search is covered by the integration
suite.
"""
from __future__ import annotations

from synsc.services.paper_retrieval import (
    _section_weight,
    _split_sentences,
    _SECTION_WEIGHTS,
)


def test_methods_outranks_related_work():
    assert _section_weight("Methods") > _section_weight("Related Work")
    assert _section_weight("Results") > _section_weight("References")
    assert _section_weight("Methodology") > _section_weight("Acknowledgements")


def test_section_weight_unknown_defaults_to_one():
    assert _section_weight("Some Random Heading") == 1.0
    assert _section_weight(None) == 1.0
    assert _section_weight("") == 1.0


def test_section_weight_prefix_match_works():
    # 'Method' prefix should bump 'Method 1: ...' too.
    assert _section_weight("Method 1: Approach") > 1.0


def test_section_weight_case_insensitive():
    assert _section_weight("METHODS") == _section_weight("methods")
    assert _section_weight("Results") == _section_weight("results")


def test_section_weights_no_silly_high_values():
    """No section should outweigh ranking by more than 1.25x. Otherwise a
    weakly-matched chunk in 'Methods' could outrank a strong match in
    'Discussion'.
    """
    for sec, w in _SECTION_WEIGHTS.items():
        assert 0.4 <= w <= 1.25, f"{sec}: {w} out of range"


def test_split_sentences_basic():
    text = "This is one. This is two. This is three!"
    sents = _split_sentences(text)
    assert len(sents) == 3
    assert sents[0] == "This is one."


def test_split_sentences_handles_questions_and_exclamations():
    text = "Why does X work? Because of Y. The end!"
    sents = _split_sentences(text)
    assert len(sents) == 3


def test_split_sentences_empty_input():
    assert _split_sentences("") == []
    assert _split_sentences("   ") == []
