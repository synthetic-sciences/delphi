"""Prose queries over a code index need a vocabulary bridge, precise ones do not."""
from __future__ import annotations

import json
from types import SimpleNamespace

from synsc.services import query_expansion as expansion_module
from synsc.services.query_expansion import (
    embedding_text,
    expand_query,
    looks_like_prose,
    structured_prose_view,
)


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


def test_prose_view_pulls_human_fields_out_of_an_envelope():
    envelope = json.dumps({
        "diff_hunk_context": "@@ -1,3 +1,5 @@ def handle():",
        "given_file": "tests/cover/test_seed_printing.py",
        "pr_title": "Print the seed when shrinking is slow",
        "review_comment": "let's assert seed appears exactly once in output",
    })
    view = structured_prose_view(envelope)
    assert view is not None
    assert "Print the seed" in view
    assert "exactly once" in view
    assert "diff_hunk_context" not in view
    assert "test_seed_printing" not in view


def test_prose_view_is_none_for_free_text_and_non_objects():
    assert structured_prose_view("plain question about retries") is None
    assert structured_prose_view(json.dumps([1, 2, 3])) is None


def test_review_envelope_prose_passes_the_gate_where_raw_json_fails():
    envelope_view = structured_prose_view(json.dumps({
        "review_comment": (
            "should we also test the case where the parent class provides "
            "the constructor and the child only inherits it"
        ),
        "pr_title": "Treat custom enum values as dynamic",
        "path": "crates/ty_python_semantic/resources/mdtest/enums.md",
    }))
    assert envelope_view is not None
    assert looks_like_prose(envelope_view)


def test_query_expansion_uses_singleflight_cache(monkeypatch):
    config = SimpleNamespace(
        search=SimpleNamespace(
            enable_query_expansion=True,
            query_expansion_model="model",
            llm_cache_entries=4,
            llm_cache_db="/tmp/search-stage-cache.sqlite3",
            llm_seed=7,
        )
    )

    class SingleflightOnlyCache:
        calls = 0

        def get_or_compute(self, _key, _compute):
            self.calls += 1
            return "def retry_until_timeout(): pass"

    cache = SingleflightOnlyCache()
    cache_options = {}

    def fake_get_cache(*_args, **kwargs):
        cache_options.update(kwargs)
        return cache

    monkeypatch.setattr(expansion_module, "get_config", lambda: config)
    monkeypatch.setattr(expansion_module, "get_cache", fake_get_cache)
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    result = expand_query(
        "why does the retry loop give up before the timeout is reached"
    )

    assert result == "def retry_until_timeout(): pass"
    assert cache.calls == 1
    assert cache_options == {
        "persistent_path": "/tmp/search-stage-cache.sqlite3"
    }
