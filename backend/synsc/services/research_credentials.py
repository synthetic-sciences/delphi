"""Encrypted, per-user credentials for research synthesis providers."""

from __future__ import annotations

from typing import Any, cast

import structlog
from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError

from synsc.database.connection import get_session
from synsc.services.token_encryption import decrypt_token, encrypt_token

logger = structlog.get_logger(__name__)


class ResearchCredentialLookupError(RuntimeError):
    """Raised when user-scoped credentials cannot be checked safely."""

    def __init__(self, provider: str):
        self.provider = provider
        super().__init__(f"Credential lookup for research provider '{provider}' is unavailable")


def store_user_research_api_key(
    user_id: str,
    provider: str,
    api_key: str,
) -> None:
    """Encrypt and upsert one provider credential for one user."""
    encrypted_key = encrypt_token(api_key)
    with get_session() as session:
        session.execute(
            text(
                """
                INSERT INTO user_research_credentials
                    (user_id, provider, encrypted_key)
                VALUES
                    (:user_id, :provider, :encrypted_key)
                ON CONFLICT (user_id, provider) DO UPDATE
                SET encrypted_key = EXCLUDED.encrypted_key,
                    updated_at = now()
                """
            ),
            {
                "user_id": user_id,
                "provider": provider,
                "encrypted_key": encrypted_key,
            },
        )
        session.commit()


def get_user_research_api_key(user_id: str | None, provider: str) -> str | None:
    """Return a decrypted user credential, scoped by user and provider."""
    if not user_id:
        return None
    try:
        with get_session() as session:
            row = (
                session.execute(
                    text(
                        """
                        SELECT encrypted_key
                        FROM user_research_credentials
                        WHERE user_id = :user_id AND provider = :provider
                        """
                    ),
                    {"user_id": user_id, "provider": provider},
                )
                .mappings()
                .first()
            )
    except SQLAlchemyError as exc:
        # Never silently fall back to an operator-owned key when the caller's
        # credential could not be checked.
        logger.error(
            "User research credential lookup unavailable",
            provider=provider,
            error=type(exc).__name__,
        )
        raise ResearchCredentialLookupError(provider) from exc
    if row is None:
        return None
    return decrypt_token(row["encrypted_key"])


def get_user_research_credential_status(
    user_id: str,
    provider: str,
) -> dict[str, Any]:
    """Return non-secret metadata for one user's provider credential."""
    with get_session() as session:
        row = (
            session.execute(
                text(
                    """
                    SELECT created_at, updated_at
                    FROM user_research_credentials
                    WHERE user_id = :user_id AND provider = :provider
                    """
                ),
                {"user_id": user_id, "provider": provider},
            )
            .mappings()
            .first()
        )
    if row is None:
        return {"configured": False, "provider": provider}
    return {
        "configured": True,
        "provider": provider,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def delete_user_research_api_key(user_id: str, provider: str) -> bool:
    """Delete one user's credential without affecting any other user/provider."""
    with get_session() as session:
        result = session.execute(
            text(
                """
                DELETE FROM user_research_credentials
                WHERE user_id = :user_id AND provider = :provider
                """
            ),
            {"user_id": user_id, "provider": provider},
        )
        session.commit()
    return cast(CursorResult[Any], result).rowcount > 0
