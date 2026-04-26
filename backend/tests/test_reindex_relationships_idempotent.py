"""Regression test for the idempotency of `_build_chunk_relationships`.

Diff-aware reindex preserves unchanged chunks and their edges. A subsequent
unconditional call to `_build_chunk_relationships` would otherwise re-INSERT
those preserved edges and trip the `unique_chunk_relationship` constraint,
rolling back the entire batch and silently losing relationships for
new/modified chunks.

The fix pre-loads the existing (source_chunk_id, target_chunk_id,
relationship_type) keys for the repo into the in-memory `seen` set before
iterating, so the dedup helper skips already-persisted edges.

This test patches the SQLAlchemy session boundaries to verify that:
1. A pre-load query against `chunk_relationships` runs before edges are added.
2. Edges returned by that pre-load are NOT included in `session.add_all`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from synsc.services.indexing_service import _build_chunk_relationships


def _chunk_row(chunk_id: str, file_id: str, idx: int, start: int, end: int):
    return SimpleNamespace(
        chunk_id=chunk_id,
        file_id=file_id,
        chunk_index=idx,
        start_line=start,
        end_line=end,
    )


def test_preserved_edges_are_not_reinserted():
    """Edges already in chunk_relationships must not be added again."""
    session = MagicMock()

    # Two adjacent chunks in one file → would naturally produce one
    # `adjacent` edge: (c1 → c2).
    chunks = [
        _chunk_row("c1", "f1", 0, 1, 10),
        _chunk_row("c2", "f1", 1, 11, 20),
    ]

    # session.query(CodeChunk...) returns chunks; session.query(Symbol...)
    # returns no class symbols (so no same_class edges).
    query_result = MagicMock()
    query_result.join.return_value = query_result
    query_result.filter.return_value = query_result
    query_result.order_by.return_value = query_result
    query_result.all.side_effect = [chunks, []]
    session.query.return_value = query_result

    # Pre-load existing edges: pretend (c1 → c2, adjacent) already exists.
    existing = [("c1", "c2", "adjacent")]
    execute_result = MagicMock()
    execute_result.all.return_value = existing
    session.execute.return_value = execute_result

    captured: list = []
    session.add_all.side_effect = lambda rels: captured.extend(rels)

    count = _build_chunk_relationships(session, repo_id="repo-uuid")

    # Pre-load query must have been issued.
    assert session.execute.called, "expected pre-load SELECT against chunk_relationships"

    # The duplicate edge must NOT be added.
    keys = [(r.source_chunk_id, r.target_chunk_id, r.relationship_type) for r in captured]
    assert ("c1", "c2", "adjacent") not in keys
    assert count == 0


def test_new_edges_still_added_when_some_preserved():
    """Edges absent from the pre-load are still inserted."""
    session = MagicMock()

    # Three adjacent chunks → two adjacent edges: (c1→c2), (c2→c3)
    chunks = [
        _chunk_row("c1", "f1", 0, 1, 10),
        _chunk_row("c2", "f1", 1, 11, 20),
        _chunk_row("c3", "f1", 2, 21, 30),
    ]

    query_result = MagicMock()
    query_result.join.return_value = query_result
    query_result.filter.return_value = query_result
    query_result.order_by.return_value = query_result
    query_result.all.side_effect = [chunks, []]
    session.query.return_value = query_result

    # Pre-load: only the first edge already persists.
    execute_result = MagicMock()
    execute_result.all.return_value = [("c1", "c2", "adjacent")]
    session.execute.return_value = execute_result

    captured: list = []
    session.add_all.side_effect = lambda rels: captured.extend(rels)

    count = _build_chunk_relationships(session, repo_id="repo-uuid")

    keys = [(r.source_chunk_id, r.target_chunk_id, r.relationship_type) for r in captured]
    assert ("c1", "c2", "adjacent") not in keys, "preserved edge should be skipped"
    assert ("c2", "c3", "adjacent") in keys, "new edge should be added"
    assert count == 1


def test_uuid_objects_compare_equal_to_string_keys():
    """Pre-load returns strings; `_add` may receive UUID objects.
    Casting both sides to str ensures dedup works regardless of representation.
    """
    import uuid as _uuid

    session = MagicMock()
    src_uuid = _uuid.UUID("00000000-0000-0000-0000-000000000001")
    tgt_uuid = _uuid.UUID("00000000-0000-0000-0000-000000000002")

    chunks = [
        _chunk_row(src_uuid, "f1", 0, 1, 10),
        _chunk_row(tgt_uuid, "f1", 1, 11, 20),
    ]

    query_result = MagicMock()
    query_result.join.return_value = query_result
    query_result.filter.return_value = query_result
    query_result.order_by.return_value = query_result
    query_result.all.side_effect = [chunks, []]
    session.query.return_value = query_result

    # Pre-load returns string form (matches DB ::text cast).
    execute_result = MagicMock()
    execute_result.all.return_value = [(str(src_uuid), str(tgt_uuid), "adjacent")]
    session.execute.return_value = execute_result

    captured: list = []
    session.add_all.side_effect = lambda rels: captured.extend(rels)

    count = _build_chunk_relationships(session, repo_id="repo-uuid")

    assert count == 0, "UUID-typed chunk_id must dedup against string-typed pre-load key"
