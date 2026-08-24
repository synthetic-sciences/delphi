"""Unit tests: local force reindex must reuse repository rows atomically."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from synsc.database.models import Repository
from synsc.services.indexing_service import IndexingService


def _local_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    abs_path: Path,
    files: list[dict[str, Any]],
    existing: Repository | None,
) -> tuple[IndexingService, dict[str, Any]]:
    """Build an IndexingService with a fake DB session for local reindex."""
    service = IndexingService()
    service.git_client = SimpleNamespace(
        set_quality_mode=lambda _mode: None,
        list_files=lambda *_args, **_kwargs: files,
    )
    monkeypatch.setattr(service, "_build_code_graph_safe", lambda *_args: None)
    monkeypatch.setattr(service.vector_store, "save", lambda: None)

    calls: dict[str, Any] = {
        "purge_repo_ids": [],
        "lock_calls": [],
        "index_files_kwargs": None,
        "deleted_objects": [],
    }

    class _RepoQuery:
        def __init__(self, repo: Repository | None) -> None:
            self._repo = repo

        def filter(self, *_args: object, **_kwargs: object) -> _RepoQuery:
            return self

        def first(self) -> Repository | None:
            return self._repo

    class _FakeSession:
        def __init__(self) -> None:
            self.committed = False

        def query(self, model: type[object]) -> _RepoQuery:
            assert model is Repository
            return _RepoQuery(existing)

        def delete(self, obj: object) -> None:
            calls["deleted_objects"].append(obj)

        def flush(self) -> None:
            return None

        def commit(self) -> None:
            self.committed = True

        def execute(self, *_args: object, **_kwargs: object) -> None:
            return None

    fake_session = _FakeSession()

    @contextmanager
    def _fake_get_session():
        yield fake_session

    monkeypatch.setattr(
        "synsc.services.indexing_service.get_session",
        _fake_get_session,
    )
    monkeypatch.setattr(
        "synsc.database.connection.get_engine",
        lambda: SimpleNamespace(dispose=lambda: None),
    )
    monkeypatch.setattr(
        "synsc.services.indexing_service._build_chunk_relationships",
        lambda *_args, **_kwargs: 0,
    )

    def _record_purge(_session: object, repo_id: str) -> None:
        calls["purge_repo_ids"].append(repo_id)

    def _record_lock(
        _session: object,
        repo_id: str,
        expected_commit_sha: str | None,
    ) -> Repository:
        calls["lock_calls"].append((repo_id, expected_commit_sha))
        assert existing is not None
        return existing

    def _record_index_files(*, session: object, **kwargs: Any) -> dict[str, Any]:
        calls["index_files_kwargs"] = kwargs
        repo_id = kwargs.get("existing_repo_id") or str(uuid.uuid4())
        return {
            "repo_id": repo_id,
            "files_count": len(files),
            "chunks_count": 1,
            "symbols_count": 0,
            "file_okapi_documents_count": 0,
        }

    monkeypatch.setattr(service, "_purge_repository_index", _record_purge)
    monkeypatch.setattr(service, "_lock_repository_for_reindex", _record_lock)
    monkeypatch.setattr(service, "_index_files", _record_index_files)
    monkeypatch.setattr(
        service,
        "_add_repo_to_user_collection",
        lambda *_args, **_kwargs: None,
    )

    return service, calls


def test_local_force_reindex_purges_and_passes_existing_repo_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Force reindex must purge in-place and reuse repo_id, not delete the row."""
    content = "def answer():\n    return 42\n"
    (tmp_path / "answer.py").write_text(content)
    existing = Repository(
        repo_id="3b835c1d-aaaa-bbbb-cccc-ddddeeeeffff",
        url=f"local://{tmp_path.resolve()}",
        owner="local",
        name=tmp_path.name,
        branch="local",
        commit_sha="old-digest",
        files_count=1,
        chunks_count=1,
    )
    files = [
        {
            "path": "answer.py",
            "name": "answer.py",
            "size_bytes": len(content),
            "content": content,
        }
    ]

    service, calls = _local_service(
        monkeypatch,
        abs_path=tmp_path,
        files=files,
        existing=existing,
    )

    result = service.index_local_folder(
        str(tmp_path),
        user_id=str(uuid.uuid4()),
        force_reindex=True,
        quality_mode="agent",
    )

    assert result["success"] is True
    assert result["repo_id"] == existing.repo_id
    assert calls["deleted_objects"] == []
    assert calls["purge_repo_ids"] == [existing.repo_id]
    assert calls["lock_calls"] == [(existing.repo_id, "old-digest")]
    assert calls["index_files_kwargs"] is not None
    assert calls["index_files_kwargs"]["existing_repo_id"] == existing.repo_id


def test_local_changed_content_reindex_reuses_existing_repo_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Content change reindex must also reuse the repository row."""
    content = "def answer():\n    return 99\n"
    (tmp_path / "answer.py").write_text(content)
    existing = Repository(
        repo_id="20e1c9b0-1111-2222-3333-444455556666",
        url=f"local://{tmp_path.resolve()}",
        owner="local",
        name=tmp_path.name,
        branch="local",
        commit_sha="stale-digest",
        files_count=1,
        chunks_count=1,
    )
    files = [
        {
            "path": "answer.py",
            "name": "answer.py",
            "size_bytes": len(content),
            "content": content,
        }
    ]

    service, calls = _local_service(
        monkeypatch,
        abs_path=tmp_path,
        files=files,
        existing=existing,
    )

    result = service.index_local_folder(
        str(tmp_path),
        user_id=str(uuid.uuid4()),
        quality_mode="agent",
    )

    assert result["success"] is True
    assert result["repo_id"] == existing.repo_id
    assert calls["deleted_objects"] == []
    assert calls["purge_repo_ids"] == [existing.repo_id]
    assert calls["index_files_kwargs"]["existing_repo_id"] == existing.repo_id


def test_local_new_repo_skips_purge_and_existing_repo_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """First-time local indexing must not lock/purge or pass existing_repo_id."""
    content = "print('hello')\n"
    (tmp_path / "hello.py").write_text(content)
    files = [
        {
            "path": "hello.py",
            "name": "hello.py",
            "size_bytes": len(content),
            "content": content,
        }
    ]

    service, calls = _local_service(
        monkeypatch,
        abs_path=tmp_path,
        files=files,
        existing=None,
    )

    result = service.index_local_folder(
        str(tmp_path),
        user_id=str(uuid.uuid4()),
        quality_mode="agent",
    )

    assert result["success"] is True
    assert calls["purge_repo_ids"] == []
    assert calls["lock_calls"] == []
    assert calls["index_files_kwargs"]["existing_repo_id"] is None
    assert calls["deleted_objects"] == []
