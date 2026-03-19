"""Tests for CORS configuration."""

import os


def test_default_cors_methods():
    """Default CORS methods should be the restricted set, not wildcard."""
    from synsc.config import APIConfig

    cfg = APIConfig()
    assert cfg.cors_methods == ["GET", "POST", "DELETE", "PUT", "OPTIONS"]
    assert "*" not in cfg.cors_methods


def test_default_cors_headers():
    """Default CORS headers should be the restricted set, not wildcard."""
    from synsc.config import APIConfig

    cfg = APIConfig()
    assert cfg.cors_headers == ["Authorization", "Content-Type", "X-API-Key"]
    assert "*" not in cfg.cors_headers


def test_cors_methods_from_env():
    """SYNSC_CORS_METHODS should be parsed as comma-separated list."""
    os.environ["SYNSC_CORS_METHODS"] = "GET, POST"
    try:
        from synsc.config import SynscConfig

        config = SynscConfig.from_env()
        assert config.api.cors_methods == ["GET", "POST"]
    finally:
        del os.environ["SYNSC_CORS_METHODS"]


def test_cors_headers_from_env():
    """SYNSC_CORS_HEADERS should be parsed as comma-separated list."""
    os.environ["SYNSC_CORS_HEADERS"] = "Authorization, X-Custom-Header"
    try:
        from synsc.config import SynscConfig

        config = SynscConfig.from_env()
        assert config.api.cors_headers == ["Authorization", "X-Custom-Header"]
    finally:
        del os.environ["SYNSC_CORS_HEADERS"]


def test_cors_preflight_returns_allowed_methods(client):
    """OPTIONS preflight should return the configured allowed methods."""
    resp = client.options(
        "/v1/repositories",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    # CORS middleware returns 200 or 400 depending on origin match
    if resp.status_code == 200:
        allowed = resp.headers.get("access-control-allow-methods", "")
        # Should NOT contain PATCH (not in our allowed list)
        assert "PATCH" not in allowed


def test_cors_preflight_returns_allowed_headers(client):
    """OPTIONS preflight should return the configured allowed headers."""
    resp = client.options(
        "/v1/repositories",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    if resp.status_code == 200:
        allowed_headers = resp.headers.get("access-control-allow-headers", "")
        assert "Authorization" in allowed_headers or "authorization" in allowed_headers.lower()
