"""Per-source ownership + visibility management.

Lets the indexing user change the visibility of a source (public /
private / unlisted) and transfer ownership to another user. Mirrors the
admin surface that Context7 exposes on library claims.

Visibility tiers:
  public   — anyone can list and search this source.
  private  — only the owner sees it (default for papers, datasets).
  unlisted — not in public lists, but anyone with the source_id can add
             it to their collection (link-share semantics).
"""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

from synsc.database.connection import get_session
from synsc.database.models import (
    DocumentationSource,
    Paper,
    Repository,
)

logger = structlog.get_logger(__name__)


VISIBILITY_TIERS = {"public", "private", "unlisted"}


def _model_for(source_type: str):
    return {
        "repo": (Repository, "repo_id", "owner", "name"),
        "paper": (Paper, "paper_id", "title", None),
        "docs": (DocumentationSource, "docs_id", "display_name", None),
    }.get(source_type)


def _ensure_owner(session, model, source_id: str, user_id: str) -> Any:
    row = (
        session.query(model)
        .filter(getattr(model, _pk_col(model)) == source_id)
        .first()
    )
    if row is None:
        raise LookupError("source not found")
    if str(row.indexed_by or "").lower() != str(user_id).lower():
        raise PermissionError("only the indexer can change this")
    return row


def _pk_col(model) -> str:
    name = model.__tablename__
    return {
        "repositories": "repo_id",
        "papers": "paper_id",
        "documentation_sources": "docs_id",
    }[name]


def set_visibility(
    source_type: str,
    source_id: str,
    visibility: str,
    user_id: str,
) -> dict[str, Any]:
    """Change a source's visibility. Only the indexer can call this."""
    if visibility not in VISIBILITY_TIERS:
        raise ValueError(
            f"invalid visibility {visibility!r}; expected one of {sorted(VISIBILITY_TIERS)}"
        )

    if source_type == "dataset":
        return _set_dataset_visibility(source_id, visibility, user_id)

    spec = _model_for(source_type)
    if spec is None:
        raise ValueError(f"unsupported source_type: {source_type}")
    model = spec[0]

    with get_session() as session:
        row = _ensure_owner(session, model, source_id, user_id)
        row.visibility = visibility
        row.is_public = visibility == "public"
        session.commit()
        return {
            "source_id": source_id,
            "source_type": source_type,
            "visibility": visibility,
            "is_public": row.is_public,
        }


def _set_dataset_visibility(
    source_id: str, visibility: str, user_id: str
) -> dict[str, Any]:
    with get_session() as session:
        row = session.execute(
            text(
                "SELECT indexed_by FROM datasets WHERE dataset_id = :id LIMIT 1"
            ),
            {"id": source_id},
        ).first()
        if row is None:
            raise LookupError("dataset not found")
        if str(row.indexed_by or "").lower() != str(user_id).lower():
            raise PermissionError("only the indexer can change this")
        session.execute(
            text(
                "UPDATE datasets SET visibility = :v, is_public = :p "
                "WHERE dataset_id = :id"
            ),
            {
                "v": visibility,
                "p": visibility == "public",
                "id": source_id,
            },
        )
        session.commit()
    return {
        "source_id": source_id,
        "source_type": "dataset",
        "visibility": visibility,
        "is_public": visibility == "public",
    }


def transfer_ownership(
    source_type: str,
    source_id: str,
    new_owner_user_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Transfer indexer ownership of a source to another user."""
    if source_type == "dataset":
        with get_session() as session:
            row = session.execute(
                text(
                    "SELECT indexed_by FROM datasets WHERE dataset_id = :id "
                    "LIMIT 1"
                ),
                {"id": source_id},
            ).first()
            if row is None:
                raise LookupError("dataset not found")
            if str(row.indexed_by or "").lower() != str(user_id).lower():
                raise PermissionError("only the indexer can transfer ownership")
            session.execute(
                text(
                    "UPDATE datasets SET indexed_by = :new WHERE dataset_id = :id"
                ),
                {"new": new_owner_user_id, "id": source_id},
            )
            session.commit()
        return {
            "source_id": source_id,
            "source_type": "dataset",
            "indexed_by": new_owner_user_id,
        }

    spec = _model_for(source_type)
    if spec is None:
        raise ValueError(f"unsupported source_type: {source_type}")
    model = spec[0]
    with get_session() as session:
        row = _ensure_owner(session, model, source_id, user_id)
        row.indexed_by = new_owner_user_id
        session.commit()
        return {
            "source_id": source_id,
            "source_type": source_type,
            "indexed_by": new_owner_user_id,
        }
