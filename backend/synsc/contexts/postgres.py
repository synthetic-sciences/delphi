"""PostgreSQL persistence for immutable context sessions and revisions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from synsc.contexts.service import (
    ContextRevisionConflictError,
    ContextSessionNotFoundError,
)
from synsc.database.connection import get_session


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _session_public(
    row: Mapping[str, Any] | RowMapping,
) -> dict[str, Any]:
    return {
        "session_id": str(row["session_id"]),
        "name": str(row["name"]),
        "objective": str(row["objective"]),
        "status": str(row["status"]),
        "sharing_policy": str(row["sharing_policy"]),
        "expires_at": _iso(row.get("expires_at")),
        "parent_session_id": (
            str(row["parent_session_id"])
            if row.get("parent_session_id") is not None
            else None
        ),
        "parent_revision_id": (
            str(row["parent_revision_id"])
            if row.get("parent_revision_id") is not None
            else None
        ),
        "handoff_note": (
            str(row["handoff_note"])
            if row.get("handoff_note") is not None
            else None
        ),
        "current_revision_id": (
            str(row["current_revision_id"])
            if row.get("current_revision_id") is not None
            else None
        ),
        "current_revision": int(row.get("current_revision") or 0),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _revision_public(
    row: Mapping[str, Any] | RowMapping,
) -> dict[str, Any]:
    return {
        "revision_id": str(row["revision_id"]),
        "session_id": str(row["session_id"]),
        "revision_number": int(row["revision_number"]),
        "parent_revision_id": (
            str(row["parent_revision_id"])
            if row.get("parent_revision_id") is not None
            else None
        ),
        "token_budget": int(row["token_budget"]),
        "tokens_used": int(row["tokens_used"]),
        "state": row.get("state") or {},
        "pinned_snapshots": row.get("pinned_snapshots") or [],
        "context_manifest": row.get("context_manifest") or {},
        "content_hash": str(row["content_hash"]),
        "summary_model": (
            str(row["summary_model"])
            if row.get("summary_model") is not None
            else None
        ),
        "summary_version": (
            str(row["summary_version"])
            if row.get("summary_version") is not None
            else None
        ),
        "created_at": _iso(row.get("created_at")),
    }


class PostgresContextSessionStore:
    """Atomically append revisions and advance one fenced session head."""

    @staticmethod
    def _insert_revision(
        database: Session,
        revision: Mapping[str, Any],
        *,
        user_id: str,
    ) -> None:
        database.execute(
            text(
                """
                INSERT INTO context_revisions (
                    revision_id, session_id, revision_number,
                    parent_revision_id, token_budget, tokens_used,
                    state, pinned_snapshots, context_manifest,
                    content_hash, summary_model, summary_version,
                    created_by
                ) VALUES (
                    :revision_id, :session_id, :revision_number,
                    :parent_revision_id, :token_budget, :tokens_used,
                    CAST(:state AS JSONB),
                    CAST(:pinned_snapshots AS JSONB),
                    CAST(:context_manifest AS JSONB),
                    :content_hash, :summary_model, :summary_version,
                    :created_by
                )
                """
            ),
            {
                "revision_id": revision["revision_id"],
                "session_id": revision["session_id"],
                "revision_number": revision["revision_number"],
                "parent_revision_id": revision.get("parent_revision_id"),
                "token_budget": revision["token_budget"],
                "tokens_used": revision["tokens_used"],
                "state": json.dumps(
                    revision["state"],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                "pinned_snapshots": json.dumps(
                    revision["pinned_snapshots"],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                "context_manifest": json.dumps(
                    revision["context_manifest"],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                "content_hash": revision["content_hash"],
                "summary_model": revision.get("summary_model"),
                "summary_version": revision.get("summary_version"),
                "created_by": user_id,
            },
        )

    @staticmethod
    def _get_in_session(
        database: Session,
        session_id: str,
        *,
        user_id: str,
        revision_number: int | None = None,
    ) -> dict[str, Any]:
        session_row = database.execute(
            text(
                """
                SELECT *
                FROM context_sessions
                WHERE session_id = :session_id
                  AND user_id = :user_id
                """
            ),
            {"session_id": session_id, "user_id": user_id},
        ).mappings().first()
        if session_row is None:
            raise ContextSessionNotFoundError(
                "Context session not found."
            )
        selected_revision = (
            int(revision_number)
            if revision_number is not None
            else int(session_row["current_revision"])
        )
        revision_row = database.execute(
            text(
                """
                SELECT *
                FROM context_revisions
                WHERE session_id = :session_id
                  AND revision_number = :revision_number
                """
            ),
            {
                "session_id": session_id,
                "revision_number": selected_revision,
            },
        ).mappings().first()
        if revision_row is None:
            raise ContextSessionNotFoundError(
                "Context revision not found."
            )
        return {
            "session": _session_public(session_row),
            "revision": _revision_public(revision_row),
        }

    def create(
        self,
        *,
        session: dict[str, Any],
        revision: dict[str, Any],
    ) -> dict[str, Any]:
        if revision["session_id"] != session["session_id"]:
            raise ValueError("revision session_id must match the session")
        if int(revision["revision_number"]) != 1:
            raise ValueError("initial context revision must be revision 1")
        try:
            with get_session() as database:
                database.execute(
                    text(
                        """
                        INSERT INTO context_sessions (
                            session_id, user_id, name, objective, status,
                            sharing_policy, expires_at, parent_session_id,
                            parent_revision_id, handoff_note,
                            current_revision
                        ) VALUES (
                            :session_id, :user_id, :name, :objective,
                            :status, :sharing_policy, :expires_at,
                            :parent_session_id, :parent_revision_id,
                            :handoff_note, 0
                        )
                        """
                    ),
                    session,
                )
                self._insert_revision(
                    database,
                    revision,
                    user_id=str(session["user_id"]),
                )
                database.execute(
                    text(
                        """
                        UPDATE context_sessions
                        SET current_revision = 1,
                            current_revision_id = :revision_id,
                            updated_at = NOW()
                        WHERE session_id = :session_id
                        """
                    ),
                    {
                        "session_id": session["session_id"],
                        "revision_id": revision["revision_id"],
                    },
                )
                return self._get_in_session(
                    database,
                    str(session["session_id"]),
                    user_id=str(session["user_id"]),
                )
        except IntegrityError as exc:
            raise ValueError(
                "Context name, parent, or revision conflicts with existing data."
            ) from exc

    def append(
        self,
        session_id: str,
        *,
        user_id: str,
        expected_revision: int,
        revision: dict[str, Any],
    ) -> dict[str, Any]:
        if revision["session_id"] != session_id:
            raise ValueError("revision session_id must match the session")
        if int(revision["revision_number"]) != expected_revision + 1:
            raise ValueError("revision_number must follow expected_revision")
        with get_session() as database:
            row = database.execute(
                text(
                    """
                    SELECT current_revision
                    FROM context_sessions
                    WHERE session_id = :session_id
                      AND user_id = :user_id
                    FOR UPDATE
                    """
                ),
                {"session_id": session_id, "user_id": user_id},
            ).mappings().first()
            if row is None:
                raise ContextSessionNotFoundError(
                    "Context session not found."
                )
            if int(row["current_revision"]) != expected_revision:
                raise ContextRevisionConflictError(
                    "Context revision changed."
                )
            self._insert_revision(
                database,
                revision,
                user_id=user_id,
            )
            database.execute(
                text(
                    """
                    UPDATE context_sessions
                    SET current_revision = :revision_number,
                        current_revision_id = :revision_id,
                        updated_at = NOW()
                    WHERE session_id = :session_id
                      AND user_id = :user_id
                    """
                ),
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "revision_number": revision["revision_number"],
                    "revision_id": revision["revision_id"],
                },
            )
            return self._get_in_session(
                database,
                session_id,
                user_id=user_id,
            )

    def get(
        self,
        session_id: str,
        *,
        user_id: str,
        revision_number: int | None = None,
    ) -> dict[str, Any]:
        with get_session() as database:
            return self._get_in_session(
                database,
                session_id,
                user_id=user_id,
                revision_number=revision_number,
            )

    def list(
        self,
        *,
        user_id: str,
        limit: int,
        include_expired: bool,
    ) -> list[dict[str, Any]]:
        expiry_clause = ""
        if not include_expired:
            expiry_clause = """
              AND (expires_at IS NULL OR expires_at > NOW())
              AND status <> 'archived'
            """
        with get_session() as database:
            rows = database.execute(
                text(
                    f"""
                    SELECT *
                    FROM context_sessions
                    WHERE user_id = :user_id
                    {expiry_clause}
                    ORDER BY updated_at DESC, session_id
                    LIMIT :limit
                    """
                ),
                {"user_id": user_id, "limit": limit},
            ).mappings().all()
        return [_session_public(row) for row in rows]

    def update_policy(
        self,
        session_id: str,
        *,
        user_id: str,
        expected_revision: int,
        sharing_policy: str,
        expires_at: datetime | None,
        status: str,
    ) -> dict[str, Any]:
        with get_session() as database:
            row = database.execute(
                text(
                    """
                    SELECT current_revision
                    FROM context_sessions
                    WHERE session_id = :session_id
                      AND user_id = :user_id
                    FOR UPDATE
                    """
                ),
                {"session_id": session_id, "user_id": user_id},
            ).mappings().first()
            if row is None:
                raise ContextSessionNotFoundError(
                    "Context session not found."
                )
            if int(row["current_revision"]) != expected_revision:
                raise ContextRevisionConflictError(
                    "Context revision changed."
                )
            updated = database.execute(
                text(
                    """
                    UPDATE context_sessions
                    SET sharing_policy = :sharing_policy,
                        expires_at = :expires_at,
                        status = :status,
                        updated_at = NOW()
                    WHERE session_id = :session_id
                      AND user_id = :user_id
                    RETURNING *
                    """
                ),
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "sharing_policy": sharing_policy,
                    "expires_at": expires_at,
                    "status": status,
                },
            ).mappings().one()
            return _session_public(updated)
