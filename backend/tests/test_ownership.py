"""Tests for source visibility / ownership service."""
from __future__ import annotations

import pytest

from synsc.services import ownership_service


class _FakeRow:
    def __init__(self, indexed_by, **kw):
        self.indexed_by = indexed_by
        self.visibility = kw.get("visibility", "public")
        self.is_public = kw.get("is_public", True)
        self.repo_id = kw.get("repo_id", "r-1")
        self.paper_id = kw.get("paper_id", "p-1")
        self.docs_id = kw.get("docs_id", "d-1")


class _FakeQ:
    def __init__(self, row):
        self.row = row

    def filter(self, *a):
        return self

    def first(self):
        return self.row


class _FakeSession:
    def __init__(self, row):
        self.row = row
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def query(self, model):
        return _FakeQ(self.row)

    def execute(self, *a, **k):
        class _R:
            def first(self_inner):
                return self.row
        return _R()

    def commit(self):
        self.committed = True


def test_set_visibility_rejects_invalid_tier():
    with pytest.raises(ValueError, match="invalid visibility"):
        ownership_service.set_visibility("repo", "r1", "bogus", "u1")


def test_set_visibility_rejects_unknown_source_type():
    with pytest.raises(ValueError, match="unsupported"):
        ownership_service.set_visibility("nope", "x", "public", "u1")


def test_set_visibility_requires_owner(monkeypatch):
    row = _FakeRow(indexed_by="someone-else")
    sess = _FakeSession(row)
    monkeypatch.setattr(ownership_service, "get_session", lambda: sess)
    with pytest.raises(PermissionError):
        ownership_service.set_visibility("repo", "r1", "public", "u1")


def test_set_visibility_changes_value(monkeypatch):
    row = _FakeRow(indexed_by="u1", visibility="public", is_public=True)
    sess = _FakeSession(row)
    monkeypatch.setattr(ownership_service, "get_session", lambda: sess)
    out = ownership_service.set_visibility("repo", "r-1", "unlisted", "u1")
    assert out["visibility"] == "unlisted"
    assert out["is_public"] is False
    assert sess.committed


def test_transfer_ownership_requires_owner(monkeypatch):
    row = _FakeRow(indexed_by="someone-else")
    sess = _FakeSession(row)
    monkeypatch.setattr(ownership_service, "get_session", lambda: sess)
    with pytest.raises(PermissionError):
        ownership_service.transfer_ownership("repo", "r1", "u2", "u1")


def test_transfer_ownership_changes_indexed_by(monkeypatch):
    row = _FakeRow(indexed_by="u1")
    sess = _FakeSession(row)
    monkeypatch.setattr(ownership_service, "get_session", lambda: sess)
    out = ownership_service.transfer_ownership("repo", "r-1", "u2", "u1")
    assert out["indexed_by"] == "u2"
    assert sess.committed
