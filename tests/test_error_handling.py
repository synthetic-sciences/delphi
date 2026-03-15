"""Tests that API error responses never leak internal details."""

from unittest.mock import patch, MagicMock


def test_create_key_error_is_generic(client):
    """POST /v1/keys should return a generic error, not str(e)."""
    with patch("synsc.supabase_auth.get_supabase_client") as mock_client:
        mock_client.return_value.insert.side_effect = RuntimeError(
            "connection to server at 'db.xxx.supabase.co' refused"
        )
        resp = client.post("/v1/keys", json={"name": "test key"})

    # The response should NOT contain the internal error message
    body = resp.json()
    assert "connection to server" not in str(body)
    assert "refused" not in str(body)
    # Should contain a generic message
    assert "Failed to create API key" in body.get("error", "")


def test_search_code_error_is_generic(client):
    """POST /v1/search/code should return a generic error on failure."""
    with patch(
        "synsc.services.search_service.SearchService.search_code",
        side_effect=RuntimeError("pgvector index corrupt"),
    ):
        resp = client.post("/v1/search/code", json={"query": "hello"})

    body = resp.json()
    assert "pgvector" not in str(body)
    assert resp.status_code == 500
    assert "Code search failed" in body.get("error", "")


def test_revoke_key_error_is_generic(client):
    """POST /v1/keys/{id}/revoke should return a generic error on failure."""
    with patch("synsc.supabase_auth.get_supabase_client") as mock_client:
        mock_client.return_value.update.side_effect = RuntimeError("DB timeout")
        resp = client.post("/v1/keys/fake-uuid/revoke")

    body = resp.json()
    assert "DB timeout" not in str(body)
    assert resp.status_code == 500


def test_delete_key_error_is_generic(client):
    """DELETE /v1/keys/{id} should return a generic error on failure."""
    with patch("synsc.supabase_auth.get_supabase_client") as mock_client:
        mock_client.return_value.delete.side_effect = RuntimeError("permission denied")
        resp = client.delete("/v1/keys/fake-uuid")

    body = resp.json()
    assert "permission denied" not in str(body)
    assert resp.status_code == 500
