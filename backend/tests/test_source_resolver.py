"""Unit tests for canonical source_id resolver + legacy alias backfill."""
from __future__ import annotations

import pytest


_VALID_UUID = "12345678-1234-1234-1234-123456789abc"


def test_resolve_uuid_detected_as_repo(monkeypatch):
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service, "_lookup_source_type_by_uuid", lambda uid: "repo"
    )
    sid, stype = source_service.resolve_source_id(_VALID_UUID, user_id="u1")
    assert sid == _VALID_UUID
    assert stype == "repo"


def test_resolve_uuid_unknown_type_raises(monkeypatch):
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service, "_lookup_source_type_by_uuid", lambda uid: None
    )
    with pytest.raises(ValueError, match="could not resolve"):
        source_service.resolve_source_id(_VALID_UUID, user_id="u1")


def test_resolve_arxiv_prefix(monkeypatch):
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "_lookup_paper_by_arxiv",
        lambda arxiv_id: "paper-uuid" if arxiv_id == "2301.12345" else None,
    )
    sid, stype = source_service.resolve_source_id("arxiv:2301.12345", user_id="u1")
    assert sid == "paper-uuid"
    assert stype == "paper"


def test_resolve_bare_arxiv_id(monkeypatch):
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "_lookup_paper_by_arxiv",
        lambda arxiv_id: "paper-uuid" if arxiv_id == "2301.12345" else None,
    )
    sid, stype = source_service.resolve_source_id("2301.12345", user_id="u1")
    assert sid == "paper-uuid"
    assert stype == "paper"


def test_resolve_hf_dataset(monkeypatch):
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "_lookup_dataset_by_hf_id",
        lambda hf_id: "ds-uuid" if hf_id == "openai/gsm8k" else None,
    )
    sid, stype = source_service.resolve_source_id("hf:openai/gsm8k", user_id="u1")
    assert sid == "ds-uuid"
    assert stype == "dataset"


def test_resolve_owner_repo(monkeypatch):
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "_lookup_repo_by_owner_name",
        lambda owner, name, user_id: (
            "repo-uuid" if owner == "facebook" and name == "react" else None
        ),
    )
    sid, stype = source_service.resolve_source_id("facebook/react", user_id="u1")
    assert sid == "repo-uuid"
    assert stype == "repo"


def test_resolve_github_url(monkeypatch):
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "_lookup_repo_by_owner_name",
        lambda owner, name, user_id: "repo-uuid",
    )
    sid, stype = source_service.resolve_source_id(
        "https://github.com/facebook/react", user_id="u1"
    )
    assert sid == "repo-uuid"
    assert stype == "repo"


def test_resolve_github_url_strips_dot_git(monkeypatch):
    from synsc.services import source_service

    captured: dict = {}

    def fake(owner, name, user_id):
        captured["owner"] = owner
        captured["name"] = name
        return "uuid"

    monkeypatch.setattr(source_service, "_lookup_repo_by_owner_name", fake)
    source_service.resolve_source_id(
        "https://github.com/facebook/react.git", user_id="u1"
    )
    assert captured["name"] == "react"


def test_resolve_docs_url(monkeypatch):
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "_lookup_docs_by_url",
        lambda url: "docs-uuid" if "example.com" in url else None,
    )
    sid, stype = source_service.resolve_source_id(
        "https://docs.example.com", user_id="u1"
    )
    assert sid == "docs-uuid"
    assert stype == "docs"


def test_resolve_unknown_string_raises():
    from synsc.services.source_service import resolve_source_id

    with pytest.raises(ValueError, match="could not resolve"):
        resolve_source_id("not_a_known_alias", user_id="u1")


def test_resolve_empty_string_raises():
    from synsc.services.source_service import resolve_source_id

    with pytest.raises(ValueError, match="could not resolve"):
        resolve_source_id("", user_id="u1")


def test_unified_search_resolves_aliases_in_source_ids(monkeypatch):
    """Aliases (arxiv:..., owner/repo, ...) in source_ids must be canonicalised
    before retrieval. Unresolvable entries are dropped, not fatal."""
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "resolve_source_id",
        lambda raw, user_id=None: {
            "arxiv:2301.12345": ("paper-uuid", "paper"),
            "facebook/react": ("repo-uuid", "repo"),
        }.get(raw) or (_ for _ in ()).throw(ValueError("unknown")),
    )

    captured: dict = {}

    def fake_retrieve(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(source_service, "unified_retrieve", fake_retrieve)

    source_service.unified_search(
        query="q",
        source_ids=["arxiv:2301.12345", "facebook/react", "garbage"],
        user_id="u1",
    )

    # Only the two resolvable ids reach the retriever — the third is dropped.
    assert captured["source_ids"] == ["paper-uuid", "repo-uuid"]
