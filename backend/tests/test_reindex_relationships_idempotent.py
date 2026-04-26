"""Regression test for the idempotency of `_build_chunk_relationships`.

Diff-aware reindex preserves unchanged chunks and their edges. A subsequent
unconditional call to `_build_chunk_relationships` would otherwise re-INSERT
those preserved edges and trip the `unique_chunk_relationship` constraint,
rolling back the entire batch and silently losing relationships for
new/modified chunks.

Fix: insert via ``pg_insert(...).on_conflict_do_nothing(constraint=...)``
keyed on the existing UNIQUE constraint, so duplicates are quietly skipped
server-side without aborting the batch.

These tests assert at the SQL-build boundary rather than against a real
database (the project's test infra mocks the DB layer per
``backend/tests/conftest.py``).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.dialects.postgresql.dml import (
    Insert as PGInsert,
    OnConflictDoNothing,
)

from synsc.database.models import ChunkRelationship
from synsc.services.indexing_service import _build_chunk_relationships


def _chunk_row(chunk_id: str, file_id: str, idx: int, start: int, end: int):
    return SimpleNamespace(
        chunk_id=chunk_id,
        file_id=file_id,
        chunk_index=idx,
        start_line=start,
        end_line=end,
    )


def _wire_query(session: MagicMock, chunks: list, class_symbols: list):
    """Wire ``session.query(...).join(...).filter(...).order_by(...).all()``
    to return ``chunks`` first (the chunks query) and ``class_symbols`` second
    (the symbols query).
    """
    query_result = MagicMock()
    query_result.join.return_value = query_result
    query_result.filter.return_value = query_result
    query_result.order_by.return_value = query_result
    query_result.all.side_effect = [chunks, class_symbols]
    session.query.return_value = query_result


def test_insert_uses_on_conflict_do_nothing_with_named_constraint():
    """The bulk insert must be a Postgres ON CONFLICT DO NOTHING keyed on
    the existing ``unique_chunk_relationship`` constraint."""
    session = MagicMock()

    chunks = [
        _chunk_row("c1", "f1", 0, 1, 10),
        _chunk_row("c2", "f1", 1, 11, 20),
    ]
    _wire_query(session, chunks, [])

    captured: list = []
    session.execute.side_effect = lambda stmt, *args, **kwargs: captured.append(stmt)

    count = _build_chunk_relationships(session, repo_id="repo-uuid")

    assert count == 1, "two adjacent chunks → exactly one adjacent edge"
    assert len(captured) == 1, "expected exactly one INSERT statement"

    stmt = captured[0]
    assert isinstance(stmt, PGInsert), "must use postgres dialect Insert (pg_insert)"
    assert stmt.table is ChunkRelationship.__table__

    on_conflict = stmt._post_values_clause
    assert isinstance(on_conflict, OnConflictDoNothing), (
        "must be DO NOTHING, not DO UPDATE — relationship rows are immutable"
    )
    assert on_conflict.constraint_target == "unique_chunk_relationship"


def test_no_insert_when_repo_has_no_chunks():
    """Empty-chunk fast path must skip the SQL emission entirely."""
    session = MagicMock()
    _wire_query(session, [], [])

    count = _build_chunk_relationships(session, repo_id="repo-uuid")

    assert count == 0
    assert not session.execute.called, "no chunks → no INSERT"


def test_in_batch_dedup_still_runs_for_overlapping_class_edges():
    """Two overlapping class symbols can produce duplicate same_class edges
    within a single call. The in-memory ``seen`` set must dedup before the
    INSERT — duplicate rows in a single ON CONFLICT batch are server-handled
    but pointless to send."""
    session = MagicMock()

    chunks = [
        _chunk_row("c1", "f1", 0, 1, 100),
        _chunk_row("c2", "f1", 1, 101, 200),
    ]
    # Two class symbols, each spanning both chunks → naive emission would
    # yield two (c1, c2, same_class) edges; dedup must collapse to one.
    class_symbols = [
        SimpleNamespace(file_id="f1", start_line=1, end_line=200),
        SimpleNamespace(file_id="f1", start_line=10, end_line=180),
    ]
    _wire_query(session, chunks, class_symbols)

    captured: list = []
    session.execute.side_effect = lambda stmt, *args, **kwargs: captured.append(stmt)

    count = _build_chunk_relationships(session, repo_id="repo-uuid")

    # 1 adjacent (c1 → c2) + 1 same_class (c1 → c2 deduped from two symbols).
    assert count == 2

    stmt = captured[0]
    rows = stmt.compile().params  # bind params reflect the values list
    # Spot-check: same_class edge appears exactly once in the batch.
    same_class_count = sum(
        1 for k, v in rows.items()
        if k.startswith("relationship_type_") and v == "same_class"
    )
    assert same_class_count == 1, "same_class duplicate must be deduped pre-INSERT"
