"""An index built by another embedding model must not fail silently."""
from __future__ import annotations

from synsc.services.embedding_consistency import (
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
    def __init__(self, rows):
        self._rows = rows
        self.params = None

    def execute(self, _statement, params):
        self.params = params
        return _Rows(self._rows)


def test_reports_repository_indexed_by_another_model():
    session = _Session([
        {
            "repo_id": "r1",
            "repo_name": "etcd-io/etcd",
            "embedding_model": "text-embedding-3-small",
        }
    ])
    found = find_embedding_mismatches(session, "gemini-embedding-001")
    assert len(found) == 1
    assert found[0].indexed_with == "text-embedding-3-small"
    assert found[0].querying_with == "gemini-embedding-001"


def test_scopes_the_check_to_requested_repositories():
    session = _Session([])
    find_embedding_mismatches(session, "model-a", repo_ids=["r1", "r2"])
    assert session.params["rid_0"] == "r1"
    assert session.params["rid_1"] == "r2"


def test_no_active_model_means_nothing_to_compare():
    session = _Session([{"repo_id": "r1", "repo_name": "x", "embedding_model": "m"}])
    assert find_embedding_mismatches(session, "") == []


def test_a_failing_check_never_breaks_search():
    class _Broken:
        def execute(self, *a, **k):
            raise RuntimeError("database is down")

    assert find_embedding_mismatches(_Broken(), "model-a") == []


def test_message_names_both_models_and_the_remedy():
    message = EmbeddingMismatch("r1", "etcd-io/etcd", "openai-x", "gemini-y").message()
    assert "openai-x" in message
    assert "gemini-y" in message
    assert "re-index" in message
