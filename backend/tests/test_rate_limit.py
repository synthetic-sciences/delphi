"""Tests for rate limiting configuration and key extraction."""

import os
from unittest.mock import MagicMock, patch


def test_rate_limit_module_imports():
    """Rate limit module should import without errors."""
    from synsc.api.rate_limit import limiter, AUTH_LIMIT, INDEX_LIMIT, SEARCH_LIMIT

    assert AUTH_LIMIT == "10/minute"
    assert INDEX_LIMIT == "5/minute"
    assert SEARCH_LIMIT == "30/minute"


def test_rate_limit_key_uses_ip_when_no_user():
    """Anonymous requests should be keyed by IP address."""
    from synsc.api.rate_limit import _get_rate_limit_key

    mock_request = MagicMock()
    mock_request.state = MagicMock(spec=[])  # no user_id attribute
    mock_request.client.host = "192.168.1.1"

    key = _get_rate_limit_key(mock_request)
    # Should fall back to IP address
    assert "user:" not in key


def test_rate_limit_key_uses_user_id_when_present():
    """Authenticated requests should be keyed by user_id."""
    from synsc.api.rate_limit import _get_rate_limit_key

    mock_request = MagicMock()
    mock_request.state.user_id = "abc-123"

    key = _get_rate_limit_key(mock_request)
    assert key == "user:abc-123"


def test_rate_limit_exceeded_handler_returns_429():
    """The custom handler should return 429 with JSON body."""
    from synsc.api.rate_limit import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    mock_request = MagicMock()
    # RateLimitExceeded expects a Limit object; mock it
    mock_limit = MagicMock()
    mock_limit.error_message = None
    exc = RateLimitExceeded(mock_limit)
    exc.detail = "5 per 1 minute"

    response = _rate_limit_exceeded_handler(mock_request, exc)
    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_rate_limiting_enabled_by_default():
    """Rate limiting should be enabled by default."""
    os.environ.pop("SYNSC_RATE_LIMIT_ENABLED", None)
    from synsc.api.rate_limit import is_rate_limiting_enabled

    assert is_rate_limiting_enabled() is True


def test_rate_limiting_can_be_disabled():
    """SYNSC_RATE_LIMIT_ENABLED=false should disable rate limiting."""
    os.environ["SYNSC_RATE_LIMIT_ENABLED"] = "false"
    try:
        from synsc.api.rate_limit import is_rate_limiting_enabled

        assert is_rate_limiting_enabled() is False
    finally:
        os.environ.pop("SYNSC_RATE_LIMIT_ENABLED", None)


def test_rate_limit_env_overrides():
    """Rate limit tier values should be overridable via env vars."""
    os.environ["SYNSC_RATE_LIMIT_AUTH"] = "20/minute"
    os.environ["SYNSC_RATE_LIMIT_INDEX"] = "10/minute"
    os.environ["SYNSC_RATE_LIMIT_SEARCH"] = "50/minute"
    os.environ["SYNSC_RATE_LIMIT_DEFAULT"] = "100/minute"
    try:
        # Need to reimport to pick up env vars (module-level reads)
        import importlib
        import synsc.api.rate_limit as rl
        importlib.reload(rl)

        assert rl.AUTH_LIMIT == "20/minute"
        assert rl.INDEX_LIMIT == "10/minute"
        assert rl.SEARCH_LIMIT == "50/minute"
    finally:
        os.environ.pop("SYNSC_RATE_LIMIT_AUTH", None)
        os.environ.pop("SYNSC_RATE_LIMIT_INDEX", None)
        os.environ.pop("SYNSC_RATE_LIMIT_SEARCH", None)
        os.environ.pop("SYNSC_RATE_LIMIT_DEFAULT", None)
        # Reload with defaults restored
        import importlib
        import synsc.api.rate_limit as rl
        importlib.reload(rl)


def test_limiter_is_configured():
    """The limiter instance should be properly configured."""
    from synsc.api.rate_limit import limiter

    assert limiter is not None
    # Limiter wraps default limits in LimitGroup objects
    assert len(limiter._default_limits) == 1
