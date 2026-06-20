"""Session token issuance and validation."""

import time
import hashlib
import secrets


class TokenExpired(Exception):
    """Raised when a token is presented after its expiry."""


def generate_token(user_id: str, ttl_seconds: int = 3600) -> dict:
    """Mint a signed session token for a user with a time-to-live."""
    raw = secrets.token_hex(16)
    issued_at = int(time.time())
    signature = hashlib.sha256(f"{user_id}:{raw}:{issued_at}".encode()).hexdigest()
    return {
        "token": raw,
        "user_id": user_id,
        "issued_at": issued_at,
        "expires_at": issued_at + ttl_seconds,
        "signature": signature,
    }


def validate_token(token: dict) -> str:
    """Verify a token's signature and expiry; return the user_id if valid."""
    now = int(time.time())
    if now > token["expires_at"]:
        raise TokenExpired("token has expired, re-authenticate")
    expected = hashlib.sha256(
        f"{token['user_id']}:{token['token']}:{token['issued_at']}".encode()
    ).hexdigest()
    if not secrets.compare_digest(expected, token["signature"]):
        raise ValueError("invalid token signature")
    return token["user_id"]
