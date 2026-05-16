"""Named context blob save/load — portable agent context across IDEs.

Nia parity: a user can save a named context (indexed source set +
preferences) on one machine and load it on another. The MCP server is the
canonical store, so any client (Cursor / Claude Code / Windsurf / Claude
Desktop) sees the same context once the agent authenticates with the
same API key.

Payload shape is intentionally open — agents can stash arbitrary keys for
their workflow. We validate a small set of well-known fields when present
and warn on anything else but don't reject.
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.exc import IntegrityError

from synsc.database.connection import get_session
from synsc.database.models import ContextBlob

logger = structlog.get_logger(__name__)


_WELL_KNOWN_KEYS = {
    "source_ids",
    "source_types",
    "topic",
    "tokens",
    "thesis_workspace_id",
    "mcp_profile",
    "notes",
}


def _validate_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    if "source_ids" in payload and not isinstance(payload["source_ids"], list):
        raise ValueError("source_ids must be a list")
    if "source_types" in payload and not isinstance(payload["source_types"], list):
        raise ValueError("source_types must be a list")
    if "tokens" in payload and not isinstance(payload["tokens"], int):
        raise ValueError("tokens must be an integer")


def save_context(
    user_id: str,
    name: str,
    payload: dict[str, Any],
    *,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Save (or upsert) a named context for ``user_id``.

    Returns the persisted blob. Raises ``ValueError`` on invalid payload
    or duplicate name when overwrite=False.
    """
    if not user_id:
        raise ValueError("user_id required")
    if not name or len(name) > 255:
        raise ValueError("name must be 1..255 chars")
    _validate_payload(payload)

    extras = set(payload.keys()) - _WELL_KNOWN_KEYS
    if extras:
        logger.debug("context: payload has extra keys", extras=sorted(extras))

    with get_session() as session:
        existing = (
            session.query(ContextBlob)
            .filter(
                ContextBlob.user_id == str(user_id),
                ContextBlob.name == name,
            )
            .first()
        )
        if existing is not None:
            if not overwrite:
                raise ValueError(f"context name already exists: {name}")
            existing.payload = payload
            session.commit()
            session.refresh(existing)
            return existing.to_dict()
        blob = ContextBlob(user_id=str(user_id), name=name, payload=payload)
        session.add(blob)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("context name conflict") from exc
        session.refresh(blob)
        return blob.to_dict()


def load_context(user_id: str, name: str) -> dict[str, Any] | None:
    """Load a context by name. Returns None if not found."""
    if not user_id:
        return None
    with get_session() as session:
        blob = (
            session.query(ContextBlob)
            .filter(
                ContextBlob.user_id == str(user_id),
                ContextBlob.name == name,
            )
            .first()
        )
        return blob.to_dict() if blob else None


def list_contexts(user_id: str) -> list[dict[str, Any]]:
    """List all contexts for a user, newest first."""
    if not user_id:
        return []
    with get_session() as session:
        blobs = (
            session.query(ContextBlob)
            .filter(ContextBlob.user_id == str(user_id))
            .order_by(ContextBlob.updated_at.desc())
            .all()
        )
        return [b.to_dict() for b in blobs]


def delete_context(user_id: str, name: str) -> bool:
    """Delete a named context. Returns True if a row was removed."""
    if not user_id:
        return False
    with get_session() as session:
        n = (
            session.query(ContextBlob)
            .filter(
                ContextBlob.user_id == str(user_id),
                ContextBlob.name == name,
            )
            .delete()
        )
        session.commit()
        return bool(n)
