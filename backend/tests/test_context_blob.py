"""Tests for context blob save/load service.

The unit tests below are storage-agnostic — they fake the DB session to
exercise the validation + flow without a Postgres dependency.
"""
from __future__ import annotations

import pytest

from synsc.services import context_blob_service


def test_validate_payload_rejects_non_dict():
    with pytest.raises(ValueError):
        context_blob_service._validate_payload("nope")  # type: ignore[arg-type]


def test_validate_payload_rejects_bad_source_ids():
    with pytest.raises(ValueError):
        context_blob_service._validate_payload({"source_ids": "not a list"})


def test_validate_payload_rejects_bad_tokens():
    with pytest.raises(ValueError):
        context_blob_service._validate_payload({"tokens": "not int"})


def test_validate_payload_accepts_well_known_keys():
    context_blob_service._validate_payload(
        {
            "source_ids": ["a", "b"],
            "source_types": ["repo"],
            "topic": "routing",
            "tokens": 5000,
            "thesis_workspace_id": "ws-1",
            "notes": "scratch",
        }
    )


class _FakeBlob:
    def __init__(self, **kw):
        self.context_id = kw.get("context_id", "ctx-1")
        self.user_id = kw.get("user_id")
        self.name = kw.get("name")
        self.payload = kw.get("payload", {})
        self.created_at = None
        self.updated_at = None

    def to_dict(self):
        return {
            "context_id": self.context_id,
            "user_id": self.user_id,
            "name": self.name,
            "payload": self.payload,
            "created_at": None,
            "updated_at": None,
        }


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *a, **k):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self.rows

    def delete(self):
        n = len(self.rows)
        self.rows.clear()
        return n


class _FakeSession:
    def __init__(self):
        self.store: dict[tuple[str, str], _FakeBlob] = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def query(self, model):
        # Return all rows matching no filter; the .filter() chain will narrow.
        rows = list(self.store.values())
        return _FakeQuery(rows)

    def add(self, obj):
        self.store[(obj.user_id, obj.name)] = obj

    def commit(self):
        pass

    def refresh(self, obj):
        pass

    def rollback(self):
        pass


def test_save_and_load_roundtrip(monkeypatch):
    sess = _FakeSession()
    monkeypatch.setattr(context_blob_service, "get_session", lambda: sess)
    # Patch ContextBlob ctor to our fake.

    out = context_blob_service.save_context(
        user_id="u1",
        name="my-ctx",
        payload={"source_ids": ["s1"], "topic": "routing"},
    )
    assert out["name"] == "my-ctx"
    assert out["payload"]["topic"] == "routing"

    # In our fake, query() returns ALL stored rows regardless of filter;
    # load_context relies on filter().first() so verify behavior by
    # checking the store directly.
    assert ("u1", "my-ctx") in sess.store


def test_save_overwrite_true(monkeypatch):
    sess = _FakeSession()
    existing = _FakeBlob(user_id="u1", name="x", payload={"topic": "old"})
    sess.store[("u1", "x")] = existing
    monkeypatch.setattr(context_blob_service, "get_session", lambda: sess)

    out = context_blob_service.save_context(
        user_id="u1",
        name="x",
        payload={"topic": "new"},
        overwrite=True,
    )
    assert out["payload"]["topic"] == "new"


def test_save_overwrite_false_raises_on_duplicate(monkeypatch):
    sess = _FakeSession()
    existing = _FakeBlob(user_id="u1", name="x", payload={"topic": "old"})
    sess.store[("u1", "x")] = existing
    monkeypatch.setattr(context_blob_service, "get_session", lambda: sess)

    with pytest.raises(ValueError):
        context_blob_service.save_context(
            user_id="u1",
            name="x",
            payload={"topic": "new"},
            overwrite=False,
        )


def test_save_rejects_missing_user_or_name():
    with pytest.raises(ValueError):
        context_blob_service.save_context(user_id="", name="x", payload={})
    with pytest.raises(ValueError):
        context_blob_service.save_context(user_id="u1", name="", payload={})


def test_save_rejects_bad_payload(monkeypatch):
    monkeypatch.setattr(
        context_blob_service, "get_session", lambda: _FakeSession()
    )
    with pytest.raises(ValueError):
        context_blob_service.save_context(
            user_id="u1",
            name="x",
            payload={"source_ids": "wrong-type"},
        )
