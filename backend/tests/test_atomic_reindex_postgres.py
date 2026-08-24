"""Loss-safety contracts for repository replacement on real PostgreSQL."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import text


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


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="No real Postgres at DATABASE_URL — skipping atomic reindex tests.",
)


def test_chunk_relationship_insert_infers_bootstrap_unique_constraint() -> None:
    """setup_local.sql gives the relationship UNIQUE constraint an anonymous
    PostgreSQL name, so idempotency must target its columns rather than the
    different name declared by the SQLAlchemy model."""
    from synsc.database.connection import get_session
    from synsc.services.indexing_service import _build_chunk_relationships

    repo_id = str(uuid.uuid4())
    file_id = str(uuid.uuid4())
    first_chunk_id = str(uuid.uuid4())
    second_chunk_id = str(uuid.uuid4())
    url = f"https://github.com/acme/relationships-{repo_id}"

    try:
        with get_session() as session:
            session.execute(
                text(
                    """
                    INSERT INTO repositories
                        (repo_id, url, owner, name, branch, commit_sha,
                         is_public, files_count, chunks_count)
                    VALUES
                        (:repo_id, :url, 'acme', 'relationships', 'main',
                         'test-sha', TRUE, 1, 2)
                    """
                ),
                {"repo_id": repo_id, "url": url},
            )
            session.execute(
                text(
                    """
                    INSERT INTO repository_files
                        (file_id, repo_id, file_path, file_name, content_hash)
                    VALUES
                        (:file_id, :repo_id, 'sample.py', 'sample.py',
                         'test-hash')
                    """
                ),
                {"file_id": file_id, "repo_id": repo_id},
            )
            session.execute(
                text(
                    """
                    INSERT INTO code_chunks
                        (chunk_id, repo_id, file_id, chunk_index, content,
                         start_line, end_line)
                    VALUES
                        (:first_chunk_id, :repo_id, :file_id, 0, 'first', 1, 1),
                        (:second_chunk_id, :repo_id, :file_id, 1, 'second', 2, 2)
                    """
                ),
                {
                    "first_chunk_id": first_chunk_id,
                    "second_chunk_id": second_chunk_id,
                    "repo_id": repo_id,
                    "file_id": file_id,
                },
            )

            assert _build_chunk_relationships(session, repo_id) == 1
            assert _build_chunk_relationships(session, repo_id) == 1
            relationship_count = session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM chunk_relationships
                    WHERE source_chunk_id = :first_chunk_id
                      AND target_chunk_id = :second_chunk_id
                      AND relationship_type = 'adjacent'
                    """
                ),
                {
                    "first_chunk_id": first_chunk_id,
                    "second_chunk_id": second_chunk_id,
                },
            ).scalar_one()
            assert relationship_count == 1
    finally:
        with get_session() as session:
            session.execute(
                text("DELETE FROM repositories WHERE repo_id = :repo_id"),
                {"repo_id": repo_id},
            )


@pytest.fixture
def seeded_repository():
    from synsc.database.connection import get_session

    repo_id = str(uuid.uuid4())
    file_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    url = f"https://github.com/acme/atomic-{repo_id}"

    with get_session() as session:
        session.execute(
            text(
                """
                INSERT INTO repositories
                    (repo_id, url, owner, name, branch, commit_sha, is_public,
                     files_count, chunks_count)
                VALUES
                    (:repo_id, :url, 'acme', 'atomic', 'main', 'old-sha', TRUE, 1, 1)
                """
            ),
            {"repo_id": repo_id, "url": url},
        )
        session.execute(
            text(
                """
                INSERT INTO repository_files
                    (file_id, repo_id, file_path, file_name, content_hash)
                VALUES
                    (:file_id, :repo_id, 'old.py', 'old.py', 'old-hash')
                """
            ),
            {"file_id": file_id, "repo_id": repo_id},
        )
        session.execute(
            text(
                """
                INSERT INTO code_chunks
                    (chunk_id, repo_id, file_id, chunk_index, content,
                     start_line, end_line)
                VALUES
                    (:chunk_id, :repo_id, :file_id, 0, 'old index', 1, 1)
                """
            ),
            {
                "chunk_id": chunk_id,
                "repo_id": repo_id,
                "file_id": file_id,
            },
        )
        session.execute(
            text(
                """
                UPDATE repositories
                SET file_okapi_index_version = 'v1',
                    file_okapi_documents_count = 1
                WHERE repo_id = :repo_id
                """
            ),
            {"repo_id": repo_id},
        )
        session.execute(
            text(
                """
                INSERT INTO repository_file_lexical_documents
                    (file_id, repo_id, document_length, content_hash, index_version)
                VALUES
                    (:file_id, :repo_id, 3, 'old-hash', 'v1')
                """
            ),
            {"file_id": file_id, "repo_id": repo_id},
        )
        session.execute(
            text(
                """
                INSERT INTO repository_file_lexical_terms
                    (file_id, repo_id, term, term_frequency)
                VALUES
                    (:file_id, :repo_id, 'old', 2),
                    (:file_id, :repo_id, 'index', 1)
                """
            ),
            {"file_id": file_id, "repo_id": repo_id},
        )
        session.execute(
            text(
                """
                INSERT INTO user_repositories (user_id, repo_id)
                VALUES (:user_id, :repo_id)
                """
            ),
            {"user_id": user_id, "repo_id": repo_id},
        )

    yield {
        "repo_id": repo_id,
        "file_id": file_id,
        "chunk_id": chunk_id,
        "user_id": user_id,
        "url": url,
    }

    with get_session() as session:
        session.execute(
            text("DELETE FROM repositories WHERE repo_id = :repo_id"),
            {"repo_id": repo_id},
        )


def _service_for_reindex(monkeypatch, seeded_repository):
    from synsc.services.indexing_service import IndexingService

    service = IndexingService()
    service.git_client = SimpleNamespace(
        set_quality_mode=lambda _mode: None,
        parse_github_url=lambda _url: (
            seeded_repository["url"],
            "acme",
            "atomic",
        ),
        clone=lambda *_args, **_kwargs: (
            Path("/tmp/atomic-reindex"),
            "acme",
            "atomic",
            "new-sha",
        ),
        list_files=lambda *_args, **_kwargs: [
            {
                "path": "new.py",
                "content": "print('new')",
                "size_bytes": 12,
            }
        ],
        last_skip_reasons={},
        last_total_seen=1,
    )
    monkeypatch.setattr(service, "_build_code_graph_safe", lambda *_args: None)
    return service


def test_failed_full_reindex_restores_last_good_index(
    monkeypatch,
    seeded_repository,
):
    from synsc.database.connection import get_session

    service = _service_for_reindex(monkeypatch, seeded_repository)

    def fail_after_atomic_purge(*, session, **_kwargs):
        assert _kwargs["existing_repo_id"] == seeded_repository["repo_id"]
        remaining = session.execute(
            text("SELECT COUNT(*) FROM code_chunks WHERE repo_id = :repo_id"),
            {"repo_id": seeded_repository["repo_id"]},
        ).scalar_one()
        assert remaining == 0
        replacement_file_id = str(uuid.uuid4())
        session.execute(
            text(
                "UPDATE repositories SET commit_sha = 'partial-sha' "
                "WHERE repo_id = :repo_id"
            ),
            {"repo_id": seeded_repository["repo_id"]},
        )
        session.execute(
            text(
                """
                INSERT INTO repository_files
                    (file_id, repo_id, file_path, file_name, content_hash)
                VALUES
                    (:file_id, :repo_id, 'partial.py', 'partial.py', 'partial-hash')
                """
            ),
            {
                "file_id": replacement_file_id,
                "repo_id": seeded_repository["repo_id"],
            },
        )
        session.execute(
            text(
                """
                INSERT INTO code_chunks
                    (repo_id, file_id, chunk_index, content, start_line, end_line)
                VALUES
                    (:repo_id, :file_id, 0, 'partial index', 1, 1)
                """
            ),
            {
                "repo_id": seeded_repository["repo_id"],
                "file_id": replacement_file_id,
            },
        )
        raise RuntimeError("embedding provider unavailable")

    monkeypatch.setattr(service, "_index_files", fail_after_atomic_purge)

    result = service.index_repository(
        seeded_repository["url"],
        branch="main",
        user_id=seeded_repository["user_id"],
        is_public=True,
        force_reindex=True,
    )

    assert result["success"] is False
    assert "embedding provider unavailable" in result["error"]
    with get_session() as session:
        row = session.execute(
            text(
                """
                SELECT r.commit_sha,
                       r.file_okapi_index_version,
                       r.file_okapi_documents_count,
                       COUNT(DISTINCT f.file_id) AS files,
                       COUNT(DISTINCT c.chunk_id) AS chunks,
                       COUNT(DISTINCT ur.id) AS user_links,
                       MIN(f.file_path) AS file_path,
                       MIN(c.content) AS content,
                       COUNT(DISTINCT d.file_id) AS lexical_docs,
                       COUNT(DISTINCT t.file_id || ':' || t.term) AS lexical_terms
                FROM repositories r
                LEFT JOIN repository_files f ON f.repo_id = r.repo_id
                LEFT JOIN code_chunks c ON c.repo_id = r.repo_id
                LEFT JOIN user_repositories ur ON ur.repo_id = r.repo_id
                LEFT JOIN repository_file_lexical_documents d
                    ON d.repo_id = r.repo_id
                LEFT JOIN repository_file_lexical_terms t
                    ON t.repo_id = r.repo_id
                WHERE r.repo_id = :repo_id
                GROUP BY r.commit_sha,
                         r.file_okapi_index_version,
                         r.file_okapi_documents_count
                """
            ),
            {"repo_id": seeded_repository["repo_id"]},
        ).one()

    assert row.commit_sha == "old-sha"
    assert row.files == 1
    assert row.chunks == 1
    assert row.user_links == 1
    assert row.file_path == "old.py"
    assert row.content == "old index"
    assert row.file_okapi_index_version == "v1"
    assert row.file_okapi_documents_count == 1
    assert row.lexical_docs == 1
    assert row.lexical_terms == 2


def test_failed_diff_reindex_preserves_last_good_index_and_reports_failure(
    monkeypatch,
    seeded_repository,
):
    from synsc.database.connection import get_session

    service = _service_for_reindex(monkeypatch, seeded_repository)

    def fail_after_diff_delete(session, existing, *_args, **_kwargs):
        session.execute(
            text("DELETE FROM code_chunks WHERE repo_id = :repo_id"),
            {"repo_id": existing.repo_id},
        )
        raise RuntimeError("diff embedding failed")

    monkeypatch.setattr(service, "_diff_reindex", fail_after_diff_delete)

    result = service.index_repository(
        seeded_repository["url"],
        branch="main",
        user_id=str(uuid.uuid4()),
        is_public=True,
    )

    assert result["success"] is False
    assert "diff embedding failed" in result["error"]
    with get_session() as session:
        row = session.execute(
            text(
                """
                SELECT r.file_okapi_index_version,
                       r.file_okapi_documents_count,
                       COUNT(DISTINCT c.chunk_id) AS chunks,
                       COUNT(DISTINCT d.file_id) AS lexical_docs,
                       COUNT(DISTINCT t.file_id || ':' || t.term) AS lexical_terms
                FROM repositories r
                LEFT JOIN code_chunks c ON c.repo_id = r.repo_id
                LEFT JOIN repository_file_lexical_documents d
                    ON d.repo_id = r.repo_id
                LEFT JOIN repository_file_lexical_terms t
                    ON t.repo_id = r.repo_id
                WHERE r.repo_id = :repo_id
                GROUP BY r.file_okapi_index_version,
                         r.file_okapi_documents_count
                """
            ),
            {"repo_id": seeded_repository["repo_id"]},
        ).one()

    assert row.chunks == 1
    assert row.file_okapi_index_version == "v1"
    assert row.file_okapi_documents_count == 1
    assert row.lexical_docs == 1
    assert row.lexical_terms == 2


def test_stale_candidate_is_rejected_after_concurrent_commit(
    monkeypatch,
    seeded_repository,
):
    from synsc.database.connection import get_session

    service = _service_for_reindex(monkeypatch, seeded_repository)

    with get_session() as stale_session:
        baseline = stale_session.execute(
            text("SELECT commit_sha FROM repositories WHERE repo_id = :repo_id"),
            {"repo_id": seeded_repository["repo_id"]},
        ).scalar_one()

        with get_session() as winner_session:
            winner_session.execute(
                text(
                    "UPDATE repositories SET commit_sha = 'winner-sha' "
                    "WHERE repo_id = :repo_id"
                ),
                {"repo_id": seeded_repository["repo_id"]},
            )

        with pytest.raises(
            RuntimeError,
            match="changed while re-index was being prepared",
        ):
            service._lock_repository_for_reindex(
                stale_session,
                seeded_repository["repo_id"],
                baseline,
            )

    with get_session() as session:
        commit_sha = session.execute(
            text("SELECT commit_sha FROM repositories WHERE repo_id = :repo_id"),
            {"repo_id": seeded_repository["repo_id"]},
        ).scalar_one()
    assert commit_sha == "winner-sha"


def test_local_index_flushes_valid_files_when_final_input_is_skipped(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A skipped final file must not strand earlier valid files in the batch."""
    from synsc.database.connection import get_session
    from synsc.services.indexing_service import IndexingService

    valid_content = (
        "def answer(values):\n"
        "    total = 0\n"
        "    for value in values:\n"
        "        total += value\n"
        "    return total\n"
    )
    (tmp_path / "main.py").write_text(valid_content)
    (tmp_path / "empty.py").write_text("")

    service = IndexingService()
    service.git_client.list_files = lambda *_args, **_kwargs: [
        {
            "path": "main.py",
            "name": "main.py",
            "size_bytes": len(valid_content),
            "content": valid_content,
        },
        {
            "path": "empty.py",
            "name": "empty.py",
            "size_bytes": 0,
            "content": "",
        },
    ]

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
        assert int(result["chunks_created"]) >= 1
        with get_session() as session:
            counts = session.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT c.chunk_id) AS chunks,
                           COUNT(DISTINCT e.embedding_id) AS embeddings
                    FROM code_chunks c
                    LEFT JOIN chunk_embeddings e ON e.chunk_id = c.chunk_id
                    WHERE c.repo_id = :repo_id
                    """
                ),
                {"repo_id": result["repo_id"]},
            ).one()
        assert counts.chunks >= 1
        assert counts.embeddings == counts.chunks
    finally:
        repo_id = result.get("repo_id")
        if repo_id:
            with get_session() as session:
                session.execute(
                    text("DELETE FROM repositories WHERE repo_id = :repo_id"),
                    {"repo_id": repo_id},
                )
