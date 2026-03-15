"""Tests for API key authentication."""

import os


# ---------------------------------------------------------------------------
# Auth-disabled mode (default for local development)
# ---------------------------------------------------------------------------

def test_auth_disabled_returns_dev_context(client):
    """When SYNSC_REQUIRE_AUTH=false, endpoints get a local AuthContext."""
    resp = client.get("/v1/user/profile")
    assert resp.status_code != 401


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
    """A valid key passed via X-API-Key header should authenticate."""
    resp = auth_client.get(
        "/v1/user/profile",
        headers={"X-API-Key": "test-token-123"},
    )
    assert resp.status_code != 401


def test_valid_key_via_bearer_header(auth_client):
    """A valid key passed via Authorization: Bearer should authenticate."""
    resp = auth_client.get(
        "/v1/user/profile",
        headers={"Authorization": "Bearer test-token-123"},
    )
    assert resp.status_code != 401
