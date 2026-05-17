"""Unit tests for resolve_source_name (Context7-style name lookup)."""
from __future__ import annotations

from synsc.services import source_service


def test_match_quality_exact():
    assert source_service._match_quality("fastapi", "fastapi") == 4


def test_match_quality_prefix():
    assert source_service._match_quality("fast", "fastapi") == 3


def test_match_quality_token_prefix_beats_substring():
    # 'fastapi' is a prefix of the 'fastapi' token inside 'tiangolo/fastapi'
    # → token-prefix=2; 'api' is only a mid-word substring → 1.
    assert source_service._match_quality("fastapi", "tiangolo/fastapi") == 2
    assert source_service._match_quality("api", "tiangolo/fastapi") == 1


def test_match_quality_full_prefix():
    assert source_service._match_quality("tia", "tiangolo/fastapi") == 3


def test_match_quality_miss():
    assert source_service._match_quality("redis", "fastapi") == 0


def test_trust_score_explicit_clamped():
    assert source_service._trust_score({"trust_score": 0.7}) == 0.7
    assert source_service._trust_score({"trust_score": 2.0}) == 1.0
    assert source_service._trust_score({"trust_score": -1.0}) == 0.0


def test_trust_score_stars_normalized():
    s_low = source_service._trust_score({"stars": 1})
    s_high = source_service._trust_score({"stars": 100000})
    assert 0.0 <= s_low < s_high <= 1.0


def test_trust_score_handles_string_json():
    assert source_service._trust_score('{"stars": 1000}') > 0


def test_trust_score_missing_returns_fallback():
    assert source_service._trust_score(None) == 0.0
    assert source_service._trust_score({}, fallback=0.3) == 0.3


def test_resolve_source_name_empty_returns_empty():
    assert source_service.resolve_source_name("") == []
    assert source_service.resolve_source_name(None) == []  # type: ignore[arg-type]


def test_resolve_source_name_ranks_higher_quality_above_lower(monkeypatch):
    def fake_repos(needle, user_id, limit):
        return [
            {
                "source_id": "uuid-best",
                "source_type": "repo",
                "display_name": "tiangolo/fastapi",
                "external_ref": "https://github.com/tiangolo/fastapi",
                "match_quality": 4,
                "trust_score": 0.5,
                "extra": {},
            },
            {
                "source_id": "uuid-worse",
                "source_type": "repo",
                "display_name": "someone/fastapi-utils",
                "external_ref": "",
                "match_quality": 2,
                "trust_score": 0.9,
                "extra": {},
            },
        ]

    monkeypatch.setattr(source_service, "_resolve_repos_by_name", fake_repos)
    out = source_service.resolve_source_name("fastapi")
    assert out[0]["source_id"] == "uuid-best"


def test_resolve_source_name_trust_score_breaks_ties(monkeypatch):
    def fake_repos(needle, user_id, limit):
        return [
            {
                "source_id": "uuid-low",
                "source_type": "repo",
                "display_name": "a/x",
                "external_ref": "",
                "match_quality": 3,
                "trust_score": 0.2,
                "extra": {},
            },
            {
                "source_id": "uuid-high",
                "source_type": "repo",
                "display_name": "b/x",
                "external_ref": "",
                "match_quality": 3,
                "trust_score": 0.9,
                "extra": {},
            },
        ]

    monkeypatch.setattr(source_service, "_resolve_repos_by_name", fake_repos)
    out = source_service.resolve_source_name("x")
    assert out[0]["source_id"] == "uuid-high"


def test_resolve_source_name_filters_by_source_types(monkeypatch):
    calls = {"repo": 0, "paper": 0}

    def fake_repos(needle, user_id, limit):
        calls["repo"] += 1
        return []

    def fake_papers(needle, user_id, limit):
        calls["paper"] += 1
        return []

    monkeypatch.setattr(source_service, "_resolve_repos_by_name", fake_repos)
    monkeypatch.setattr(source_service, "_resolve_papers_by_name", fake_papers)
    source_service.resolve_source_name(
        "anything", user_id="u1", source_types=["repo"]
    )
    assert calls["repo"] == 1
    assert calls["paper"] == 0
