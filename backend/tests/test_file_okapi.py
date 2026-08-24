"""Unit tests for code-aware file-level Okapi document building."""
from __future__ import annotations

import math

import pytest

from synsc.services import file_okapi
from synsc.services.file_okapi import (
    bm25_term_score,
    build_file_okapi_document,
    tokenize_file_okapi,
)


def test_tokenizer_splits_snake_camel_acronym_and_path_boundaries():
    assert tokenize_file_okapi("src/HTTPServer/get_user.py") == [
        "src",
        "http",
        "server",
        "get",
        "user",
        "py",
    ]


def test_document_prepends_path_terms_once_and_counts_source_terms():
    document = build_file_okapi_document(
        "src/user_service.py",
        "class UserService:\n    user = UserService()\n",
    )
    assert document.term_frequencies["src"] == 1
    assert document.term_frequencies["user"] == 4
    assert document.term_frequencies["service"] == 3
    assert document.document_length == sum(document.term_frequencies.values())


def test_document_rejects_more_than_token_cap(monkeypatch):
    monkeypatch.setattr(file_okapi, "FILE_OKAPI_DOCUMENT_TOKEN_CAP", 3)
    with pytest.raises(ValueError, match="token cap"):
        build_file_okapi_document("a.py", "one two three four")


def test_bm25_term_score_matches_hand_calculated_reference():
    actual = bm25_term_score(
        term_frequency=3,
        document_length=100,
        document_count=10,
        document_frequency=2,
        average_document_length=80.0,
    )
    expected_idf = math.log(1 + (10 - 2 + 0.5) / (2 + 0.5))
    expected = expected_idf * (3 * 2.2) / (3 + 1.2 * (0.25 + 0.75 * 1.25))
    assert actual == pytest.approx(expected)


@pytest.mark.parametrize(
    ("value", "limit", "expected"),
    [
        ("foo foo", 1, ["foo"]),
        ("foo bar foo baz qux", 2, ["foo", "bar"]),
        ("alpha beta gamma", 256, ["alpha", "beta", "gamma"]),
    ],
)
def test_tokenizer_limit_deduplicates_and_caps_unique_terms(value, limit, expected):
    assert tokenize_file_okapi(value, limit=limit) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("123 abc 456", ["abc"]),
        ("a " + ("x" * 128), ["a", "x" * 128]),
        ("a " + ("y" * 129), ["a"]),
    ],
)
def test_tokenizer_rejects_numeric_only_and_overlong_terms(value, expected):
    assert tokenize_file_okapi(value) == expected


def test_document_accepts_exactly_at_token_cap(monkeypatch):
    monkeypatch.setattr(file_okapi, "FILE_OKAPI_DOCUMENT_TOKEN_CAP", 3)
    document = build_file_okapi_document("a.py", "one")
    assert document.document_length == 3
    assert document.term_frequencies == {"a": 1, "py": 1, "one": 1}
