"""Unit contracts for repository index purge ordering and behavior."""

from __future__ import annotations

from sqlalchemy import text

from synsc.services.indexing_service import IndexingService


def test_purge_repository_index_disables_timeouts_before_child_deletes() -> None:
    """Purge must lift statement timeouts before bulk child DELETEs."""
    service = IndexingService()
    repo_id = "repo-under-test"
    calls: list[str] = []

    class _RecordingSession:
        def execute(self, statement: object, params: object | None = None) -> None:
            sql = str(getattr(statement, "text", statement))
            calls.append(sql)

    service._purge_repository_index(_RecordingSession(), repo_id)

    timeout_positions = [
        index
        for index, sql in enumerate(calls)
        if "SET LOCAL statement_timeout" in sql
        or "SET LOCAL idle_in_transaction_session_timeout" in sql
    ]
    delete_positions = [
        index for index, sql in enumerate(calls) if sql.strip().upper().startswith("DELETE")
    ]

    assert len(timeout_positions) == 2
    assert len(delete_positions) == 5
    assert max(timeout_positions) < min(delete_positions)


def test_purge_repository_index_executes_expected_delete_order() -> None:
    service = IndexingService()
    repo_id = "repo-under-test"
    calls: list[str] = []

    class _RecordingSession:
        def execute(self, statement: object, params: object | None = None) -> None:
            sql = str(getattr(statement, "text", statement))
            calls.append(sql)

    service._purge_repository_index(_RecordingSession(), repo_id)

    delete_tables = [
        text(sql).text.split("FROM ", 1)[1].split(" WHERE", 1)[0]
        for sql in calls
        if sql.strip().upper().startswith("DELETE")
    ]
    assert delete_tables == [
        "symbol_references",
        "chunk_embeddings",
        "symbols",
        "code_chunks",
        "repository_files",
    ]
