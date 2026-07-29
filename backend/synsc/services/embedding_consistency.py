"""Detect indexes that were built with a different embedding model.

Two embedding models can produce vectors of the same width. pgvector will
happily compute a cosine between them, the query will succeed, and every
score will be meaningless — the two spaces are unrelated, so the ranking is
noise. Nothing raises, nothing logs, and the failure is invisible from the
outside because results still come back and still look plausible.

This module makes that mismatch observable. ``repositories.embedding_model``
already records which model indexed each repository; it simply was never
compared against the model answering queries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EmbeddingMismatch:
    """One repository whose index does not match the query-time model."""

    repo_id: str
    repo_name: str
    indexed_with: str
    querying_with: str

    def as_dict(self) -> dict[str, str]:
        return {
            "repo_id": self.repo_id,
            "repo_name": self.repo_name,
            "indexed_with": self.indexed_with,
            "querying_with": self.querying_with,
        }

    def message(self) -> str:
        return (
            f"{self.repo_name or self.repo_id} was indexed with "
            f"'{self.indexed_with}' but is being queried with "
            f"'{self.querying_with}'. Vector scores against this repository "
            f"are not meaningful until it is re-indexed or the query-time "
            f"embedding model is changed to match."
        )


def find_embedding_mismatches(
    session: Session,
    active_model: str,
    repo_ids: list[str] | None = None,
) -> list[EmbeddingMismatch]:
    """Return repositories indexed with a model other than ``active_model``.

    Repositories with no recorded model are skipped rather than reported:
    they predate the column being populated, so their state is unknown and
    flagging them would be a guess.
    """
    if not active_model:
        return []

    params: dict[str, Any] = {"active": active_model}
    clause = ""
    if repo_ids:
        placeholders = ", ".join(f":rid_{i}" for i in range(len(repo_ids)))
        clause = f"AND repo_id IN ({placeholders})"
        for index, repo_id in enumerate(repo_ids):
            params[f"rid_{index}"] = repo_id

    sql = text(
        f"""
        SELECT repo_id, owner || '/' || name AS repo_name, embedding_model
        FROM repositories
        WHERE embedding_model IS NOT NULL
          AND embedding_model <> ''
          AND embedding_model <> :active
          {clause}
        """
    )

    try:
        rows = session.execute(sql, params).mappings().all()
    except Exception as exc:  # noqa: BLE001 - a diagnostic must never break search
        logger.warning("embedding consistency check failed", error=str(exc))
        return []

    return [
        EmbeddingMismatch(
            repo_id=str(row["repo_id"]),
            repo_name=row["repo_name"] or "",
            indexed_with=row["embedding_model"],
            querying_with=active_model,
        )
        for row in rows
    ]


def active_embedding_model() -> str:
    """Model name the query path will actually embed with."""
    try:
        from synsc.embeddings.generator import get_embedding_generator

        return getattr(get_embedding_generator(), "model_name", "") or ""
    except Exception as exc:  # noqa: BLE001 - diagnostics are best-effort
        logger.warning("could not resolve active embedding model", error=str(exc))
        return ""
