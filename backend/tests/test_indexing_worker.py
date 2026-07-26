"""Regression tests for the durable repository indexing worker."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from synsc.workers import indexing_worker


def _worker_with_fakes(tmp_path: Path, *, default_branch: str = "trunk"):
    worker = indexing_worker.IndexingWorker.__new__(indexing_worker.IndexingWorker)
    worker.job_queue = SimpleNamespace(
        update_progress=Mock(),
        complete_job=Mock(),
        fail_job=Mock(),
    )
    worker.git_client = SimpleNamespace(
        parse_github_url=Mock(
            return_value=("https://github.com/acme/widgets.git", "acme", "widgets")
        ),
        _get_default_branch=Mock(return_value=default_branch),
        clone=Mock(return_value=(tmp_path, "acme", "widgets", "abc123")),
        list_files=Mock(return_value=[]),
    )
    worker._process_files_parallel = Mock(
        return_value={
            "repo_id": "repo-1",
            "files_processed": 0,
            "chunks_created": 0,
            "symbols_extracted": 0,
        }
    )
    return worker


def test_process_job_consumes_git_client_clone_tuple(tmp_path: Path) -> None:
    """A successful clone tuple reaches processing instead of failing the job."""
    worker = _worker_with_fakes(tmp_path)
    job = SimpleNamespace(
        job_id="job-1",
        repo_url="acme/widgets",
        branch="develop",
        user_id="user-1",
    )

    worker._process_job(job)

    worker.git_client.clone.assert_called_once_with("acme/widgets", "develop")
    worker._process_files_parallel.assert_called_once()
    assert worker._process_files_parallel.call_args.kwargs["repo_path"] == tmp_path
    assert worker._process_files_parallel.call_args.kwargs["branch"] == "develop"
    worker.job_queue.complete_job.assert_called_once()
    worker.job_queue.fail_job.assert_not_called()


def test_process_job_resolves_missing_default_branch(tmp_path: Path) -> None:
    """An omitted branch is resolved before cloning and persisted repository setup."""
    worker = _worker_with_fakes(tmp_path, default_branch="stable")
    job = SimpleNamespace(
        job_id="job-2",
        repo_url="acme/widgets",
        branch=None,
        user_id="user-1",
    )

    worker._process_job(job)

    worker.git_client._get_default_branch.assert_called_once_with("acme", "widgets")
    worker.git_client.clone.assert_called_once_with("acme/widgets", "stable")
    assert worker._process_files_parallel.call_args.kwargs["branch"] == "stable"
    worker.job_queue.fail_job.assert_not_called()


def test_process_job_rejects_missing_repository_url(tmp_path: Path) -> None:
    """A malformed repository job fails before attempting a clone."""
    worker = _worker_with_fakes(tmp_path)
    job = SimpleNamespace(
        job_id="job-3",
        repo_url=None,
        branch="main",
        user_id="user-1",
    )

    worker._process_job(job)

    worker.git_client.clone.assert_not_called()
    worker.job_queue.complete_job.assert_not_called()
    worker.job_queue.fail_job.assert_called_once_with(
        "job-3",
        "Repository indexing job is missing repo_url",
    )


def test_read_repository_file_detects_language_from_path(tmp_path: Path) -> None:
    """Worker file reads use the current path-only language detector contract."""
    source = tmp_path / "src" / "widget.py"
    source.parent.mkdir()
    source.write_text("def widget():\n    return 1\n")

    result = indexing_worker._read_repository_file(
        tmp_path,
        {"path": "src/widget.py"},
    )

    assert result == {
        "file_path": "src/widget.py",
        "content": "def widget():\n    return 1\n",
        "language": "python",
        "size": 27,
        "lines": 3,
        "success": True,
    }


def test_create_repository_job_forwards_requested_branch(client, monkeypatch) -> None:
    """The job API preserves an explicitly requested non-main branch."""
    service = SimpleNamespace(create_job=Mock(return_value={"success": True}))
    monkeypatch.setattr(
        "synsc.services.job_queue_service.get_job_queue_service",
        lambda: service,
    )

    response = client.post(
        "/v1/jobs",
        json={
            "job_type": "repository",
            "target": "acme/widgets",
            "branch": "develop",
        },
    )

    assert response.status_code == 200
    service.create_job.assert_called_once_with(
        user_id="00000000-0000-0000-0000-000000000000",
        repo_url="acme/widgets",
        branch="develop",
    )


def test_create_repository_job_allows_default_branch_detection(client, monkeypatch) -> None:
    """An omitted branch stays unset so the worker can detect the repository default."""
    service = SimpleNamespace(create_job=Mock(return_value={"success": True}))
    monkeypatch.setattr(
        "synsc.services.job_queue_service.get_job_queue_service",
        lambda: service,
    )

    response = client.post(
        "/v1/jobs",
        json={"job_type": "repository", "target": "acme/widgets"},
    )

    assert response.status_code == 200
    service.create_job.assert_called_once_with(
        user_id="00000000-0000-0000-0000-000000000000",
        repo_url="acme/widgets",
        branch=None,
    )
