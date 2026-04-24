"""Fernet encryption for GitHub Personal Access Tokens.

Tokens are encrypted before storage and decrypted only in-memory at clone time.
The encryption key is loaded from the TOKEN_ENCRYPTION_KEY environment variable.

Generate a key once:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import os

import structlog
from cryptography.fernet import Fernet, InvalidToken

logger = structlog.get_logger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.environ.get("TOKEN_ENCRYPTION_KEY")
        if not key:
            raise RuntimeError(
                "TOKEN_ENCRYPTION_KEY environment variable is not set. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        _fernet = Fernet(key.encode())
    return _fernet


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token string. Returns base64-encoded ciphertext."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a token string. Returns plaintext.

    Raises:
        InvalidToken: If the ciphertext is invalid or the key is wrong.
    """
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt token — key mismatch or corrupted ciphertext")
        raise
