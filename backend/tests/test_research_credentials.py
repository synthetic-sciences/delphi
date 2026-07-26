"""Per-user research credential storage and HTTP contract tests."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError


class _Rows:
    def __init__(self, *, first=None, all_rows=None):
        self._first = first
        self._all = all_rows if all_rows is not None else ([] if first is None else [first])

    def mappings(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._all


class _FakeSession:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []
        self.commits = 0

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return next(self.results)

    def commit(self):
        self.commits += 1


class _FailingSession:
    def execute(self, statement, params=None):
        raise SQLAlchemyError("database unavailable")


def _session_factory(session):
    @contextmanager
    def factory():
        yield session

    return factory


def test_store_research_api_key_encrypts_and_upserts(monkeypatch):
    from synsc.services import research_credentials as credentials

    session = _FakeSession([SimpleNamespace(rowcount=1)])
    monkeypatch.setattr(credentials, "get_session", _session_factory(session))
    encrypt = MagicMock(return_value="ciphertext")
    monkeypatch.setattr(credentials, "encrypt_token", encrypt)

    credentials.store_user_research_api_key("user-1", "gemini", "secret-key")

    encrypt.assert_called_once_with("secret-key")
    sql, params = session.calls[0]
    assert "ON CONFLICT (user_id, provider) DO UPDATE" in sql
    assert params == {
        "user_id": "user-1",
        "provider": "gemini",
        "encrypted_key": "ciphertext",
    }
    assert session.commits == 1


def test_get_research_api_key_is_user_and_provider_scoped(monkeypatch):
    from synsc.services import research_credentials as credentials

    session = _FakeSession([_Rows(first={"encrypted_key": "ciphertext"})])
    monkeypatch.setattr(credentials, "get_session", _session_factory(session))
    decrypt = MagicMock(return_value="plaintext-key")
    monkeypatch.setattr(credentials, "decrypt_token", decrypt)

    value = credentials.get_user_research_api_key("user-2", "gemini")

    assert value == "plaintext-key"
    assert session.calls[0][1] == {"user_id": "user-2", "provider": "gemini"}
    decrypt.assert_called_once_with("ciphertext")


def test_get_research_api_key_returns_none_when_absent(monkeypatch):
    from synsc.services import research_credentials as credentials

    session = _FakeSession([_Rows(first=None)])
    monkeypatch.setattr(credentials, "get_session", _session_factory(session))

    assert credentials.get_user_research_api_key("user-3", "gemini") is None


def test_get_research_api_key_fails_closed_when_lookup_is_unavailable(monkeypatch):
    from synsc.services import research_credentials as credentials

    monkeypatch.setattr(
        credentials,
        "get_session",
        _session_factory(_FailingSession()),
    )

    with pytest.raises(credentials.ResearchCredentialLookupError) as exc_info:
        credentials.get_user_research_api_key("user-3", "gemini")

    assert exc_info.value.provider == "gemini"


def test_delete_research_api_key_is_scoped(monkeypatch):
    from synsc.services import research_credentials as credentials

    session = _FakeSession([SimpleNamespace(rowcount=1)])
    monkeypatch.setattr(credentials, "get_session", _session_factory(session))

    assert credentials.delete_user_research_api_key("user-4", "gemini") is True
    assert session.calls[0][1] == {"user_id": "user-4", "provider": "gemini"}
    assert session.commits == 1


def test_research_key_status_never_returns_secret(client, monkeypatch):
    from synsc.services import research_credentials as credentials

    monkeypatch.setattr(
        credentials,
        "get_user_research_credential_status",
        lambda user_id, provider: {
            "configured": True,
            "provider": provider,
            "created_at": "2026-07-27T00:00:00+00:00",
            "updated_at": "2026-07-27T00:00:00+00:00",
        },
    )

    response = client.get("/v1/keys/research?provider=gemini")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["provider"] == "gemini"
    assert "api_key" not in body
    assert "encrypted_key" not in body


def test_store_research_key_passes_secret_only_to_storage_service(client, monkeypatch):
    from synsc.services import research_credentials as credentials

    store = MagicMock()
    monkeypatch.setattr(credentials, "store_user_research_api_key", store)

    response = client.put(
        "/v1/keys/research",
        json={"provider": "gemini", "api_key": "private-user-key"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "success": True,
        "configured": True,
        "provider": "gemini",
    }
    store.assert_called_once_with(
        "00000000-0000-0000-0000-000000000000",
        "gemini",
        "private-user-key",
    )
    assert "private-user-key" not in response.text


def test_research_key_api_rejects_unimplemented_providers(client):
    response = client.put(
        "/v1/keys/research",
        json={"provider": "anthropic", "api_key": "private-user-key"},
    )

    assert response.status_code == 422
