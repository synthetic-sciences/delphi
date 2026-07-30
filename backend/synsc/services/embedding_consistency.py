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

import logging
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)


# Every table that stores its own embeddings and records which model made
# them. A mismatch is equally meaningless in any of them, so the check cannot
# be repository-only: a documentation corpus indexed by a different model
# returns the same confident noise a repository would.
SOURCE_TABLES: tuple[tuple[str, str, str], ...] = (
    ("repositories", "repo_id", "owner || '/' || name"),
    ("documentation_sources", "docs_id", "coalesce(display_name, url)"),
    ("papers", "paper_id", "title"),
    ("datasets", "dataset_id", "name"),
)


@dataclass(frozen=True)
class EmbeddingMismatch:
    """One indexed source whose vectors do not match the query-time model."""

    repo_id: str
    repo_name: str
    indexed_with: str
    querying_with: str
    source_type: str = "repositories"

    def as_dict(self) -> dict[str, str]:
        return {
            "repo_id": self.repo_id,
            "repo_name": self.repo_name,
            "source_type": self.source_type,
            "indexed_with": self.indexed_with,
            "querying_with": self.querying_with,
        }

    def message(self) -> str:
        return (
            f"{self.source_type}: {self.repo_name or self.repo_id} was indexed with "
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
    """Return indexed sources built by a model other than ``active_model``.

    Covers every table that stores embeddings, not just repositories: a
    documentation corpus indexed by a different model returns exactly the same
    confident noise, and is just as invisible.

    Sources with no recorded model are skipped rather than reported. They
    predate the column being populated, so their state is unknown and flagging
    them would be a guess. ``repo_ids`` scopes the repository check only —
    other source types are always checked in full, since a search that touches
    them does not name them by repository id.
    """
    if not active_model:
        return []

    found: list[EmbeddingMismatch] = []
    for table, id_column, name_expr in SOURCE_TABLES:
        params: dict[str, Any] = {"active": active_model}
        clause = ""
        if repo_ids and table == "repositories":
            placeholders = ", ".join(f":rid_{i}" for i in range(len(repo_ids)))
            clause = f"AND {id_column} IN ({placeholders})"
            for index, repo_id in enumerate(repo_ids):
                params[f"rid_{index}"] = repo_id

        sql = text(
            f"""
            SELECT {id_column} AS source_id, {name_expr} AS source_name,
                   embedding_model
            FROM {table}
            WHERE embedding_model IS NOT NULL
              AND embedding_model <> ''
              AND embedding_model <> :active
              {clause}
            """
        )
        try:
            rows = session.execute(sql, params).mappings().all()
        except Exception as exc:  # noqa: BLE001 - a diagnostic must not break search
            # A table can legitimately be absent on an older schema. Anything
            # else means this check is silently not checking, which is the
            # exact failure mode it exists to prevent, so it is logged loudly.
            message = str(exc)
            missing = "does not exist" in message or "UndefinedTable" in message
            logger.log(
                logging.DEBUG if missing else logging.ERROR,
                "embedding consistency check could not read %s: %s",
                table,
                message[:160],
            )
            continue

        found.extend(
            EmbeddingMismatch(
                repo_id=str(row["source_id"]),
                repo_name=row["source_name"] or "",
                indexed_with=row["embedding_model"],
                querying_with=active_model,
                source_type=table,
            )
            for row in rows
        )
    return found


def active_embedding_model() -> str:
    """Model name the query path will actually embed with."""
    try:
        from synsc.embeddings.generator import get_embedding_generator

        return getattr(get_embedding_generator(), "model_name", "") or ""
    except Exception as exc:  # noqa: BLE001 - diagnostics are best-effort
        logger.warning("could not resolve active embedding model", error=str(exc))
        return ""
