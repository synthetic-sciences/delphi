"""Tests for security headers middleware."""

import os
from unittest.mock import patch, MagicMock


def test_security_headers_on_health(client):
    """GET /health should include all required security headers."""
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.count.return_value = 0

    with patch("synsc.database.connection.get_session", return_value=mock_session):
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert resp.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert "default-src 'self'" in resp.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["x-xss-protection"] == "0"


def test_security_headers_on_root(client):
    """GET / should also have security headers."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_no_hsts_by_default(client):
    """HSTS should NOT be present unless explicitly enabled."""
    resp = client.get("/")
    assert "strict-transport-security" not in resp.headers


def test_hsts_when_enabled():
    """HSTS header should appear when SYNSC_ENABLE_HSTS=true."""
    os.environ["SYNSC_ENABLE_HSTS"] = "true"
    try:
        from synsc.api.http_server import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        with TestClient(app) as c:
            resp = c.get("/")
        assert resp.status_code == 200
        assert "strict-transport-security" in resp.headers
        assert "max-age=63072000" in resp.headers["strict-transport-security"]
    finally:
        os.environ.pop("SYNSC_ENABLE_HSTS", None)


def test_csp_header_value(client):
    """CSP header should have default-src 'self' and frame-ancestors 'none'."""
    resp = client.get("/")
    csp = resp.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
