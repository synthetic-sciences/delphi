"""An index built by another embedding model must not fail silently."""
from __future__ import annotations

from synsc.services.embedding_consistency import (
    SOURCE_TABLES,
    EmbeddingMismatch,
    find_embedding_mismatches,
)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Session:
    """Returns rows for one named table and nothing for the others."""

    def __init__(self, rows_by_table=None):
        self._rows_by_table = rows_by_table or {}
        self.calls: list[tuple[str, dict]] = []

    def execute(self, statement, params):
        sql = str(statement)
        table = next(
            (t for t, _, _ in SOURCE_TABLES if f"FROM {t}" in sql), "unknown"
        )
        self.calls.append((table, params))
        return _Rows(self._rows_by_table.get(table, []))


def test_reports_a_repository_indexed_by_another_model():
    session = _Session({
        "repositories": [{
            "source_id": "r1",
            "source_name": "etcd-io/etcd",
            "embedding_model": "text-embedding-3-small",
        }]
    })
    found = find_embedding_mismatches(session, "gemini-embedding-001")
    assert len(found) == 1
    assert found[0].source_type == "repositories"
    assert found[0].indexed_with == "text-embedding-3-small"


def test_reports_a_documentation_source_too():
    """A docs corpus in the wrong space is just as invisible as a repo."""
    session = _Session({
        "documentation_sources": [{
            "source_id": "d1",
            "source_name": "numpy docs",
            "embedding_model": "gemini-embedding-001",
        }]
    })
    found = find_embedding_mismatches(session, "text-embedding-3-small")
    assert [m.source_type for m in found] == ["documentation_sources"]


def test_checks_every_source_table():
    session = _Session()
    find_embedding_mismatches(session, "model-a")
    assert {table for table, _ in session.calls} == {t for t, _, _ in SOURCE_TABLES}


def test_repo_ids_scope_only_the_repository_check():
    # Other source types are not named by repository id, so scoping them
    # would silently skip the very sources a search still touches.
    session = _Session()
    find_embedding_mismatches(session, "model-a", repo_ids=["r1", "r2"])
    by_table = dict(session.calls)
    assert by_table["repositories"]["rid_0"] == "r1"
    assert "rid_0" not in by_table["documentation_sources"]


def test_a_missing_table_does_not_break_the_check():
    class _PartlyBroken(_Session):
        def execute(self, statement, params):
            if "FROM papers" in str(statement):
                raise RuntimeError('relation "papers" does not exist')
            return super().execute(statement, params)

    session = _PartlyBroken({
        "repositories": [{
            "source_id": "r1", "source_name": "x", "embedding_model": "other",
        }]
    })
    assert len(find_embedding_mismatches(session, "model-a")) == 1


def test_no_active_model_means_nothing_to_compare():
    session = _Session({"repositories": [
        {"source_id": "r1", "source_name": "x", "embedding_model": "m"}
    ]})
    assert find_embedding_mismatches(session, "") == []


def test_message_names_the_source_type_and_both_models():
    message = EmbeddingMismatch(
        "d1", "numpy docs", "openai-x", "gemini-y", "documentation_sources"
    ).message()
    assert "documentation_sources" in message
    assert "openai-x" in message and "gemini-y" in message
    assert "re-index" in message
