"""Git clone contracts for reproducible source indexing."""

from __future__ import annotations

import subprocess
from pathlib import Path

from synsc.core.git_client import GitClient


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_clone_accepts_a_full_commit_sha(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Break caught: historical revisions are passed to Dulwich as branch names
    # and rejected before a reproducible repository snapshot can be indexed.
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "--initial-branch=main")
    _git(remote, "config", "user.name", "Test User")
    _git(remote, "config", "user.email", "test@example.com")
    tracked = remote / "version.txt"
    tracked.write_text("old revision\n")
    _git(remote, "add", "version.txt")
    _git(remote, "commit", "-m", "old")
    old_commit = _git(remote, "rev-parse", "HEAD")
    tracked.write_text("new revision\n")
    _git(remote, "commit", "-am", "new")

    client = GitClient(repos_dir=tmp_path / "clones")
    monkeypatch.setattr(
        client,
        "parse_github_url",
        lambda _url: (str(remote), "owner", "repo"),
    )

    checkout, owner, name, commit = client.clone("owner/repo", old_commit)

    assert (owner, name, commit) == ("owner", "repo", old_commit)
    assert (checkout / "version.txt").read_text() == "old revision\n"
