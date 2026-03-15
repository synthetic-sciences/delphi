"""Tests for API key authentication and hashing."""

from unittest.mock import patch


# ---------------------------------------------------------------------------
# Auth-disabled mode (default for local development)
# ---------------------------------------------------------------------------

def test_auth_disabled_returns_dev_context(client):
    """When SYNSC_REQUIRE_AUTH=false, endpoints get a dev-mode AuthContext."""
    # /v1/keys requires auth — should work without a key in dev mode
    resp = client.get("/v1/keys")
    # Should not be 401; the exact response depends on DB but shouldn't be auth failure
    assert resp.status_code != 401


# ---------------------------------------------------------------------------
# Auth-enabled mode
# ---------------------------------------------------------------------------

def test_missing_key_returns_401(auth_client):
    """Requests without an API key should be rejected with 401."""
    resp = auth_client.get("/v1/keys")
    assert resp.status_code == 401
    assert "Missing API key" in resp.json()["detail"]


def test_invalid_key_returns_401(auth_client):
    """An unrecognised API key should be rejected with 401."""
    # validate_api_key_hybrid is the name http_server.py imports
    with patch(
        "synsc.supabase_auth.validate_api_key_hybrid",
        return_value=(False, None),
    ):
        resp = auth_client.get(
            "/v1/keys",
            headers={"X-API-Key": "synsc_invalid_key_12345"},
        )
    assert resp.status_code == 401


def test_valid_key_via_x_api_key_header(auth_client):
    """A valid key passed via X-API-Key header should authenticate."""
    with patch(
        "synsc.supabase_auth.validate_api_key_hybrid",
        return_value=(True, "user-123"),
    ):
        resp = auth_client.get(
            "/v1/keys",
            headers={"X-API-Key": "synsc_valid_test_key"},
        )
    # Should not be 401 (may be 500 if DB mock is missing, but not an auth error)
    assert resp.status_code != 401


def test_valid_key_via_bearer_header(auth_client):
    """A valid key passed via Authorization: Bearer should authenticate."""
    with patch(
        "synsc.supabase_auth.validate_api_key_hybrid",
        return_value=(True, "user-123"),
    ):
        resp = auth_client.get(
            "/v1/keys",
            headers={"Authorization": "Bearer synsc_valid_test_key"},
        )
    assert resp.status_code != 401


# ---------------------------------------------------------------------------
# SHA-256 hashing
# ---------------------------------------------------------------------------

def test_hash_api_key_deterministic():
    """_hash_api_key should return the same SHA-256 hex digest for the same input."""
    from synsc.supabase_auth import _hash_api_key

    key = "synsc_abc123456789"
    h1 = _hash_api_key(key)
    h2 = _hash_api_key(key)

    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex is 64 chars
    assert key not in h1  # Hash must NOT contain the raw key


def test_hash_api_key_different_keys_differ():
    """Different keys must produce different hashes."""
    from synsc.supabase_auth import _hash_api_key

    assert _hash_api_key("synsc_key_one") != _hash_api_key("synsc_key_two")


def test_hash_matches_python_hashlib():
    """The helper should produce a standard SHA-256 digest."""
    import hashlib

    from synsc.supabase_auth import _hash_api_key

    raw = "synsc_test_key_for_verification"
    expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    assert _hash_api_key(raw) == expected
