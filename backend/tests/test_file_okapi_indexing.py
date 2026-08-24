"""Unit and integration tests for persisted file-level Okapi indexing."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from synsc.database.models import (
    RepositoryFile,
    RepositoryFileLexicalDocument,
    RepositoryFileLexicalTerm,
)
from synsc.services import file_okapi
from synsc.services.file_okapi import FILE_OKAPI_INDEX_VERSION, build_file_okapi_document
from synsc.services.indexing_service import IndexingService


def _postgres_reachable() -> bool:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        return False
    try:
        import psycopg2

        connection = psycopg2.connect(url, connect_timeout=2)
        connection.close()
        return True
    except Exception:
        return False


class RecordingSession:
    """Minimal session fake that records SQLAlchemy add() calls."""

    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


def test_add_file_okapi_rows_persists_document_and_exact_terms() -> None:
    service = IndexingService()
    session = RecordingSession()
    db_file = RepositoryFile(
        file_id="file-1",
        repo_id="repo-1",
        file_path="src/user_service.py",
        file_name="user_service.py",
        content_hash="abc123",
    )
    content = "class UserService:\n    user = UserService()\n"
    expected = build_file_okapi_document("src/user_service.py", content)

    count = service._add_file_okapi_rows(
        session,
        repo_id="repo-1",
        repository_file=db_file,
        file_path="src/user_service.py",
        content=content,
        content_hash="abc123",
    )

    assert count == 1
    documents = [
        obj for obj in session.added if isinstance(obj, RepositoryFileLexicalDocument)
    ]
    terms = [obj for obj in session.added if isinstance(obj, RepositoryFileLexicalTerm)]
    assert len(documents) == 1
    document = documents[0]
    assert document.file_id == "file-1"
    assert document.repo_id == "repo-1"
    assert document.document_length == expected.document_length
    assert document.content_hash == "abc123"
    assert document.index_version == FILE_OKAPI_INDEX_VERSION
    assert {(term.term, term.term_frequency) for term in terms} == set(
        expected.term_frequencies.items()
    )
    assert all(term.file_id == "file-1" and term.repo_id == "repo-1" for term in terms)


def test_add_file_okapi_rows_rejects_over_cap_without_partial_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = IndexingService()
    session = RecordingSession()
    db_file = RepositoryFile(
        file_id="file-1",
        repo_id="repo-1",
        file_path="big.py",
        file_name="big.py",
        content_hash="hash",
    )
    monkeypatch.setattr(file_okapi, "FILE_OKAPI_DOCUMENT_TOKEN_CAP", 3)

    count = service._add_file_okapi_rows(
        session,
        repo_id="repo-1",
        repository_file=db_file,
        file_path="big.py",
        content="one two three four",
        content_hash="hash",
    )

    assert count == 0
    assert session.added == []


def test_full_index_sets_repository_okapi_version_and_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if not _postgres_reachable():
        pytest.skip("No real Postgres at DATABASE_URL — skipping full index test.")

    from sqlalchemy import text

    from synsc.database.connection import get_session

    content = "def answer():\n    return 42\n"
    (tmp_path / "answer.py").write_text(content)

    service = IndexingService()
    service.git_client = SimpleNamespace(
        set_quality_mode=lambda _mode: None,
        list_files=lambda *_args, **_kwargs: [
            {
                "path": "answer.py",
                "name": "answer.py",
                "size_bytes": len(content),
                "content": content,
            }
        ],
        last_skip_reasons={},
        last_total_seen=1,
    )

    class FixedEmbeddingGenerator:
        batch_size = 64
        model_name = "test-fixed-768"

        def generate(self, texts: list[str]) -> np.ndarray:
            vectors = np.zeros((len(texts), 768), dtype=np.float32)
            vectors[:, 0] = 1.0
            return vectors

    service._embedding_generator = FixedEmbeddingGenerator()
    monkeypatch.setattr(service, "_build_code_graph_safe", lambda *_args: None)

    result: dict[str, object] = {}
    try:
        result = service.index_local_folder(
            str(tmp_path),
            user_id=str(uuid.uuid4()),
            quality_mode="agent",
        )

        assert result["success"] is True
        assert result["file_okapi_documents_count"] == 1

        with get_session() as session:
            repo = session.execute(
                text(
                    """
                    SELECT file_okapi_index_version, file_okapi_documents_count
                    FROM repositories
                    WHERE repo_id = :repo_id
                    """
                ),
                {"repo_id": result["repo_id"]},
            ).one()
            doc_count = session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM repository_file_lexical_documents
                    WHERE repo_id = :repo_id
                    """
                ),
                {"repo_id": result["repo_id"]},
            ).scalar_one()
            term_count = session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM repository_file_lexical_terms
                    WHERE repo_id = :repo_id
                    """
                ),
                {"repo_id": result["repo_id"]},
            ).scalar_one()

        assert repo.file_okapi_index_version == FILE_OKAPI_INDEX_VERSION
        assert repo.file_okapi_documents_count == 1
        assert doc_count == 1
        assert term_count >= 1
    finally:
        repo_id = result.get("repo_id")
        if repo_id:
            with get_session() as session:
                session.execute(
                    text("DELETE FROM repositories WHERE repo_id = :repo_id"),
                    {"repo_id": repo_id},
                )
