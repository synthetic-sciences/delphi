"""Tests for the health and info endpoints."""

from unittest.mock import patch, MagicMock


def test_root_returns_api_info(client):
    """GET / should return API name, version, and doc links."""
    resp = client.get("/")
    assert resp.status_code == 200

    data = resp.json()
    assert data["name"] == "Synsc Context API"
    assert data["version"] == "1.0.0"
    assert data["docs"] == "/docs"
    assert data["health"] == "/health"


def test_health_returns_healthy(client):
    """GET /health should return status=healthy with correct backend info."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.count.return_value = 0

    with patch("synsc.database.connection.get_session", return_value=mock_session):
        resp = client.get("/health")

    assert resp.status_code == 200

    data = resp.json()
    assert data["status"] == "healthy"
    assert data["version"] == "1.0.0"
    assert data["database_backend"] == "postgresql"
    assert data["vector_backend"] == "pgvector"
    assert data["auth_backend"] == "supabase"
    assert isinstance(data["uptime_seconds"], float)


def test_health_endpoint_is_public(auth_client):
    """GET /health should work without authentication even when auth is required."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.count.return_value = 0

    with patch("synsc.database.connection.get_session", return_value=mock_session):
        resp = auth_client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"
