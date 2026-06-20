"""Password hashing and verification helpers."""

import hashlib
import hmac
import os


def hash_password(plaintext: str, salt: bytes | None = None) -> str:
    """Derive a salted PBKDF2 hash suitable for storage."""
    salt = salt or os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", plaintext.encode(), salt, 100_000)
    return salt.hex() + ":" + derived.hex()


def verify_password(plaintext: str, stored: str) -> bool:
    """Constant-time comparison of a candidate password against the stored hash."""
    salt_hex, hash_hex = stored.split(":", 1)
    salt = bytes.fromhex(salt_hex)
    candidate = hashlib.pbkdf2_hmac("sha256", plaintext.encode(), salt, 100_000)
    return hmac.compare_digest(candidate.hex(), hash_hex)
