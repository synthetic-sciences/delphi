"""PostgreSQL contracts for snapshot idempotency and immutability."""

from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from synsc.snapshots.service import (
    SnapshotAccessDeniedError,
    SnapshotError,
)


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
    reason="No real Postgres at DATABASE_URL — skipping snapshot contracts.",
)


def _vector() -> str:
    return "[" + ",".join(["1.0", *(["0.0"] * 767)]) + "]"


def _alternate_vector() -> str:
    return "[" + ",".join(["0.0", "1.0", *(["0.0"] * 766)]) + "]"


def test_repository_snapshots_preserve_old_content_and_vectors() -> None:
    from synsc.database.connection import get_session
    from synsc.snapshots.contracts import SnapshotSourceType
    from synsc.snapshots.service import SnapshotService

    repo_id = str(uuid.uuid4())
    file_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    url = f"https://example.invalid/{repo_id}"
    snapshot_ids: list[str] = []

    try:
        with get_session() as session:
            session.execute(
                text(
                    """
                    INSERT INTO repositories (
                        repo_id, url, owner, name, branch, commit_sha,
                        is_public, visibility, indexed_by, embedding_model
                    ) VALUES (
                        :repo_id, :url, 'example', 'snapshot', 'main', 'sha-a',
                        TRUE, 'public', :user_id, 'local-model'
                    )
                    """
                ),
                {"repo_id": repo_id, "url": url, "user_id": user_id},
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
            session.execute(
                text(
                    """
                    INSERT INTO repository_files (
                        file_id, repo_id, file_path, file_name
                    ) VALUES (:file_id, :repo_id, 'app.py', 'app.py')
                    """
                ),
                {"file_id": file_id, "repo_id": repo_id},
            )
            session.execute(
                text(
                    """
                    INSERT INTO code_chunks (
                        chunk_id, repo_id, file_id, chunk_index, content,
                        start_line, end_line, token_count
                    ) VALUES (
                        :chunk_id, :repo_id, :file_id, 0, 'alpha', 1, 1, 1
                    )
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
                    INSERT INTO chunk_embeddings (
                        chunk_id, repo_id, embedding
                    ) VALUES (:chunk_id, :repo_id, :embedding)
                    """
                ),
                {
                    "chunk_id": chunk_id,
                    "repo_id": repo_id,
                    "embedding": _vector(),
                },
            )

        service = SnapshotService()
        first = service.publish(
            SnapshotSourceType.REPOSITORY,
            repo_id,
            user_id=user_id,
        )
        snapshot_ids.append(first.snapshot_id)
        repeated = service.publish(
            SnapshotSourceType.REPOSITORY,
            repo_id,
            user_id=user_id,
        )
        assert repeated.snapshot_id == first.snapshot_id
        assert first.vector_count == 1
        assert first.vectors_complete is True
        assert first.sealed_at is not None
        assert (
            service.get(first.snapshot_id, user_id=None)["snapshot_id"]
            == first.snapshot_id
        )

        with get_session() as session:
            session.execute(
                text(
                    """
                    UPDATE repositories
                    SET is_public = FALSE, visibility = 'private'
                    WHERE repo_id = :repo_id
                    """
                ),
                {"repo_id": repo_id},
            )

        with pytest.raises(SnapshotAccessDeniedError):
            service.get(first.snapshot_id, user_id=None)
        assert (
            service.list(
                user_id=None,
                source_type=SnapshotSourceType.REPOSITORY,
                source_id=repo_id,
            )
            == []
        )
        assert len(
            service.list(
                user_id=user_id,
                source_type=SnapshotSourceType.REPOSITORY,
                source_id=repo_id,
            )
        ) == 1
        assert (
            service.list(
                user_id=str(uuid.uuid4()),
                source_type=SnapshotSourceType.REPOSITORY,
                source_id=repo_id,
            )
            == []
        )

        with get_session() as session:
            session.execute(
                text(
                    """
                    UPDATE chunk_embeddings SET embedding = :embedding
                    WHERE chunk_id = :chunk_id
                    """
                ),
                {
                    "chunk_id": chunk_id,
                    "embedding": _alternate_vector(),
                },
            )

        reembedded = service.publish(
            SnapshotSourceType.REPOSITORY,
            repo_id,
            user_id=user_id,
        )
        snapshot_ids.append(reembedded.snapshot_id)
        assert reembedded.snapshot_id != first.snapshot_id
        assert reembedded.version == first.version
        assert reembedded.content_hash == first.content_hash
        assert (
            reembedded.embedding_fingerprint
            != first.embedding_fingerprint
        )

        with get_session() as session:
            session.execute(
                text(
                    """
                    UPDATE repositories SET commit_sha = 'sha-b'
                    WHERE repo_id = :repo_id
                    """
                ),
                {"repo_id": repo_id},
            )
            session.execute(
                text(
                    """
                    UPDATE code_chunks SET content = 'beta'
                    WHERE chunk_id = :chunk_id
                    """
                ),
                {"chunk_id": chunk_id},
            )

        second = service.publish(
            SnapshotSourceType.REPOSITORY,
            repo_id,
            user_id=user_id,
        )
        snapshot_ids.append(second.snapshot_id)

        assert second.snapshot_id != first.snapshot_id
        with get_session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT snapshot_id, content
                    FROM source_snapshot_items
                    WHERE snapshot_id IN (:first, :reembedded, :second)
                    ORDER BY snapshot_id
                    """
                ),
                {
                    "first": first.snapshot_id,
                    "reembedded": reembedded.snapshot_id,
                    "second": second.snapshot_id,
                },
            ).all()
            by_snapshot = {row.snapshot_id: row.content for row in rows}
            vector_count = session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM source_snapshot_item_embeddings
                    WHERE snapshot_id IN (:first, :reembedded, :second)
                    """
                ),
                {
                    "first": first.snapshot_id,
                    "reembedded": reembedded.snapshot_id,
                    "second": second.snapshot_id,
                },
            ).scalar_one()
            head = session.execute(
                text(
                    """
                    SELECT snapshot_id FROM source_snapshot_heads
                    WHERE source_type = 'repo' AND source_id = :repo_id
                    """
                ),
                {"repo_id": repo_id},
            ).scalar_one()

        assert by_snapshot[first.snapshot_id] == "alpha"
        assert by_snapshot[reembedded.snapshot_id] == "alpha"
        assert by_snapshot[second.snapshot_id] == "beta"
        assert vector_count == 3
        assert head == second.snapshot_id

        with pytest.raises(DBAPIError), get_session() as session:
            session.execute(
                text(
                    """
                    UPDATE source_snapshots SET version = 'mutated'
                    WHERE snapshot_id = :snapshot_id
                    """
                ),
                {"snapshot_id": first.snapshot_id},
            )

        with pytest.raises(DBAPIError), get_session() as session:
            session.execute(
                text(
                    """
                    INSERT INTO source_snapshot_items (
                        snapshot_id, ordinal, origin_item_id, locator,
                        content_hash, content, metadata
                    ) VALUES (
                        :snapshot_id, 99, :chunk_id, 'late',
                        :content_hash, 'late', '{}'::jsonb
                    )
                    """
                ),
                {
                    "snapshot_id": first.snapshot_id,
                    "chunk_id": chunk_id,
                    "content_hash": "f" * 64,
                },
            )

        with pytest.raises(DBAPIError), get_session() as session:
            session.execute(
                text(
                    """
                    DELETE FROM source_snapshot_items
                    WHERE snapshot_id = :snapshot_id
                    """
                ),
                {"snapshot_id": first.snapshot_id},
            )

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            with get_session() as session:
                session.execute(
                    text(
                        """
                        UPDATE repositories SET commit_sha = 'sha-c'
                        WHERE repo_id = :repo_id
                        """
                    ),
                    {"repo_id": repo_id},
                )
                session.execute(
                    text(
                        """
                        UPDATE code_chunks SET content = 'gamma'
                        WHERE chunk_id = :chunk_id
                        """
                    ),
                    {"chunk_id": chunk_id},
                )
                future = executor.submit(
                    service.publish,
                    SnapshotSourceType.REPOSITORY,
                    repo_id,
                    user_id=user_id,
                )
                time.sleep(0.1)
                assert future.done() is False
            raced = future.result(timeout=5)
        finally:
            executor.shutdown(wait=True)

        snapshot_ids.append(raced.snapshot_id)
        assert raced.version == "sha-c"
        detail = service.get(
            raced.snapshot_id,
            user_id=user_id,
            include_items=True,
        )
        assert detail["items"][0]["content"] == "gamma"
        assert (
            service.resolve(
                SnapshotSourceType.REPOSITORY,
                repo_id,
                user_id=user_id,
            )["snapshot_id"]
            == raced.snapshot_id
        )
    finally:
        with get_session() as session:
            session.execute(
                text(
                    """
                    DELETE FROM source_snapshot_heads
                    WHERE source_type = 'repo' AND source_id = :repo_id
                    """
                ),
                {"repo_id": repo_id},
            )
            if snapshot_ids:
                session.execute(
                    text(
                        """
                        DELETE FROM source_snapshots
                        WHERE snapshot_id = ANY(:snapshot_ids)
                        """
                    ),
                    {"snapshot_ids": snapshot_ids},
                )
            session.execute(
                text("DELETE FROM repositories WHERE repo_id = :repo_id"),
                {"repo_id": repo_id},
            )


def test_snapshot_seal_rejects_mismatched_source_vector() -> None:
    from synsc.database.connection import get_session
    from synsc.snapshots.contracts import SnapshotSourceType
    from synsc.snapshots.service import SnapshotService

    source_repo_id = str(uuid.uuid4())
    other_repo_id = str(uuid.uuid4())
    source_file_id = str(uuid.uuid4())
    other_file_id = str(uuid.uuid4())
    source_chunk_id = str(uuid.uuid4())
    other_chunk_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    try:
        with get_session() as session:
            for repo_id, url, name in (
                (
                    source_repo_id,
                    f"https://example.invalid/{source_repo_id}",
                    "source",
                ),
                (
                    other_repo_id,
                    f"https://example.invalid/{other_repo_id}",
                    "other",
                ),
            ):
                session.execute(
                    text(
                        """
                        INSERT INTO repositories (
                            repo_id, url, owner, name, branch, commit_sha,
                            is_public, visibility, indexed_by, embedding_model
                        ) VALUES (
                            :repo_id, :url, 'example', :name, 'main', 'sha',
                            FALSE, 'private', :user_id, 'local-model'
                        )
                        """
                    ),
                    {
                        "repo_id": repo_id,
                        "url": url,
                        "name": name,
                        "user_id": user_id,
                    },
                )
            session.execute(
                text(
                    """
                    INSERT INTO user_repositories (user_id, repo_id)
                    VALUES (:user_id, :repo_id)
                    """
                ),
                {"user_id": user_id, "repo_id": source_repo_id},
            )
            for repo_id, file_id, chunk_id, path in (
                (
                    source_repo_id,
                    source_file_id,
                    source_chunk_id,
                    "source.py",
                ),
                (
                    other_repo_id,
                    other_file_id,
                    other_chunk_id,
                    "other.py",
                ),
            ):
                session.execute(
                    text(
                        """
                        INSERT INTO repository_files (
                            file_id, repo_id, file_path, file_name
                        ) VALUES (:file_id, :repo_id, :path, :path)
                        """
                    ),
                    {
                        "file_id": file_id,
                        "repo_id": repo_id,
                        "path": path,
                    },
                )
                session.execute(
                    text(
                        """
                        INSERT INTO code_chunks (
                            chunk_id, repo_id, file_id, chunk_index, content,
                            start_line, end_line, token_count
                        ) VALUES (
                            :chunk_id, :repo_id, :file_id, 0, :path, 1, 1, 1
                        )
                        """
                    ),
                    {
                        "chunk_id": chunk_id,
                        "repo_id": repo_id,
                        "file_id": file_id,
                        "path": path,
                    },
                )
            session.execute(
                text(
                    """
                    INSERT INTO chunk_embeddings (
                        chunk_id, repo_id, embedding
                    ) VALUES (:chunk_id, :repo_id, :embedding)
                    """
                ),
                {
                    "chunk_id": other_chunk_id,
                    "repo_id": source_repo_id,
                    "embedding": _vector(),
                },
            )

        with pytest.raises(SnapshotError, match="copy verification"):
            SnapshotService().publish(
                SnapshotSourceType.REPOSITORY,
                source_repo_id,
                user_id=user_id,
            )

        with get_session() as session:
            snapshot_count = session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM source_snapshots
                    WHERE source_type = 'repo' AND source_id = :source_id
                    """
                ),
                {"source_id": source_repo_id},
            ).scalar_one()
            head_count = session.execute(
                text(
                    """
                    SELECT COUNT(*) FROM source_snapshot_heads
                    WHERE source_type = 'repo' AND source_id = :source_id
                    """
                ),
                {"source_id": source_repo_id},
            ).scalar_one()
        assert snapshot_count == 0
        assert head_count == 0
    finally:
        with get_session() as session:
            session.execute(
                text(
                    """
                    DELETE FROM chunk_embeddings
                    WHERE chunk_id = :chunk_id
                    """
                ),
                {"chunk_id": other_chunk_id},
            )
            session.execute(
                text(
                    """
                    DELETE FROM repositories
                    WHERE repo_id IN (:source_repo_id, :other_repo_id)
                    """
                ),
                {
                    "source_repo_id": source_repo_id,
                    "other_repo_id": other_repo_id,
                },
            )
