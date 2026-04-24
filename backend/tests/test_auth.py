"""Tests for API key authentication."""

import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch


@contextmanager
def _mock_db_session():
    """Mock session that returns empty results for any query."""
    mock_session = MagicMock()
    mock_session.execute.return_value.mappings.return_value.first.return_value = None
    mock_session.execute.return_value.fetchall.return_value = []
    yield mock_session


# ---------------------------------------------------------------------------
# Auth-disabled mode (default for local development)
# ---------------------------------------------------------------------------


def test_auth_disabled_returns_dev_context(client):
    """When SYNSC_REQUIRE_AUTH=false, endpoints get a local AuthContext."""
    with patch("synsc.api.http_server.get_session", _mock_db_session):
        resp = client.get("/v1/user/profile")
    assert resp.status_code != 401
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Auth-enabled mode
# ---------------------------------------------------------------------------


def test_missing_key_returns_401(auth_client):
    """Requests without an API key should be rejected with 401."""
    resp = auth_client.get(
        "/v1/user/profile",
        headers={},
    )
    assert resp.status_code == 401


def test_invalid_key_returns_401(auth_client):
    """An unrecognised API key should be rejected with 401."""
    resp = auth_client.get(
        "/v1/user/profile",
        headers={"X-API-Key": "wrong-token"},
    )
    assert resp.status_code == 401


def test_valid_key_via_x_api_key_header(auth_client):
    """A valid SYSTEM_PASSWORD passed via X-API-Key header should authenticate."""
    with patch("synsc.api.http_server.get_session", _mock_db_session):
        resp = auth_client.get(
            "/v1/user/profile",
            headers={"X-API-Key": "test-password-123"},
        )
    assert resp.status_code != 401
    assert resp.status_code == 200


def test_valid_key_via_bearer_header(auth_client):
    """A valid SYSTEM_PASSWORD passed via Authorization: Bearer should authenticate."""
    with patch("synsc.api.http_server.get_session", _mock_db_session):
        resp = auth_client.get(
            "/v1/user/profile",
            headers={"Authorization": "Bearer test-password-123"},
        )
    assert resp.status_code != 401
    assert resp.status_code == 200
