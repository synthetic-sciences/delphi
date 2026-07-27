"""Rate limiting for the Synsc Context API.

Uses slowapi (built on limits) with per-user or per-IP key extraction.
"""

import os
from typing import Any, cast

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse


def _get_rate_limit_key(request: Request) -> str:
    """Extract rate limit key: user_id from JWT if available, else IP address."""
    # The auth middleware stores user info in request.state
    user_id = getattr(getattr(request, "state", None), "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return get_remote_address(request)


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a JSON 429 response with Retry-After header."""
    retry_after = getattr(exc, "retry_after", 60)
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": f"Rate limit exceeded: {exc.detail}",
        },
        headers={"Retry-After": str(retry_after)},
    )


def is_rate_limiting_enabled() -> bool:
    """Check if rate limiting is enabled via config."""
    return os.getenv("SYNSC_RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")


# Default limits are applied per-key (user or IP)
_default_limit = os.getenv("SYNSC_RATE_LIMIT_DEFAULT", "60/minute")

limiter = Limiter(
    key_func=_get_rate_limit_key,
    default_limits=[_default_limit],
    enabled=is_rate_limiting_enabled(),
    storage_uri="memory://",
)


def reset_route_limit_definitions() -> None:
    """Reset factory-registered rules without clearing live request counters.

    SlowAPI keys route definitions by ``module.function`` and appends a new
    rule every time a decorated function is defined. Our FastAPI application
    factory intentionally defines routes inside ``create_app``; without this
    reset, constructing another app multiplies each request's rate-limit cost.
    All factory instances expose the same route names and limits, so replacing
    the definitions is safe while preserving the backing limiter's counters.
    """
    internal = cast(Any, limiter)
    internal._route_limits.clear()
    internal._dynamic_route_limits.clear()
    internal._Limiter__marked_for_limiting.clear()

# Tier-specific limit strings (importable by endpoints)
AUTH_LIMIT = os.getenv("SYNSC_RATE_LIMIT_AUTH", "10/minute")
INDEX_LIMIT = os.getenv("SYNSC_RATE_LIMIT_INDEX", "5/minute")
SEARCH_LIMIT = os.getenv("SYNSC_RATE_LIMIT_SEARCH", "30/minute")
