"""JWT session management — issue and verify session tokens.

After GitHub OAuth login, a session JWT is issued containing the user_id.
It's stored as an httpOnly cookie or returned to the frontend.

Requires SERVER_SECRET env var for signing.
"""

import os
from datetime import datetime, timezone, timedelta

import jwt
import structlog

logger = structlog.get_logger(__name__)

_SESSION_ALGORITHM = "HS256"
_SESSION_EXPIRY_HOURS = 72  # 3 days


def _get_server_secret() -> str:
    secret = os.getenv("SERVER_SECRET", "")
    if not secret:
        raise RuntimeError(
            "SERVER_SECRET environment variable is required. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return secret


def create_session_token(user_id: str, email: str | None = None) -> str:
    """Create a signed JWT session token for a user."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": "session",
        "iat": now,
        "exp": now + timedelta(hours=_SESSION_EXPIRY_HOURS),
    }
    if email:
        payload["email"] = email
    return jwt.encode(payload, _get_server_secret(), algorithm=_SESSION_ALGORITHM)


def verify_session_token(token: str) -> str | None:
    """Verify a session JWT and return the user_id, or None if invalid."""
    try:
        payload = jwt.decode(token, _get_server_secret(), algorithms=[_SESSION_ALGORITHM])
        if payload.get("type") != "session":
            return None
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        logger.debug("Session token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug("Invalid session token", error=str(e))
        return None
