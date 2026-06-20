"""Tests for local-folder indexing (the DB-free validation + file-gather paths).

The full index path needs Postgres, so here we cover the early-return branches
(bad path, no indexable files) and the on-disk file walk that feeds the
pipeline.
"""
from __future__ import annotations

from pathlib import Path

from synsc.core.git_client import GitClient
from synsc.services.indexing_service import IndexingService


def test_index_local_folder_rejects_missing_path() -> None:
    service = IndexingService()
    result = service.index_local_folder("/no/such/folder/abc123", user_id="u1")
    assert result["success"] is False
    assert result["error"].startswith("not_a_directory")


def test_index_local_folder_rejects_file_path(tmp_path: Path) -> None:
    f = tmp_path / "file.py"
    f.write_text("print('hi')\n")
    service = IndexingService()
    result = service.index_local_folder(str(f), user_id="u1")
    assert result["success"] is False
    assert result["error"].startswith("not_a_directory")


def test_index_local_folder_no_indexable_files(tmp_path: Path) -> None:
    # Only a file with an extension that isn't in include patterns.
    (tmp_path / "blob.xyz").write_text("not code")
    service = IndexingService()
    result = service.index_local_folder(str(tmp_path), user_id="u1")
    assert result["success"] is False
    assert result["error"] == "no_indexable_files"


def test_git_client_lists_local_directory_files(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("def main():\n    return 1\n")
    (tmp_path / "util.go").write_text("package util\nfunc Add(a int) int { return a }\n")
    sub = tmp_path / "pkg"
    sub.mkdir()
    (sub / "mod.rs").write_text("fn helper() {}\n")

    files = GitClient().list_files(tmp_path, include_content=True)
    paths = {f["path"] for f in files}
    assert "main.py" in paths
    assert "util.go" in paths
    assert str(Path("pkg") / "mod.rs") in paths
    # Content is read off disk.
    py = next(f for f in files if f["path"] == "main.py")
    assert "def main" in py["content"]
