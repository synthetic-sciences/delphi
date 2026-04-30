"""Tests for ``synsc.core.git_client.GitClient``.

Focused unit tests for the ``clone`` retry-on-branch-not-found behavior added
in PR #17. ``porcelain.clone`` and the GitHub default-branch lookup are stubbed
so the tests run offline.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def git_client(tmp_path: Path):
    from synsc.core.git_client import GitClient

    return GitClient(repos_dir=tmp_path / "repos")


def _branch_not_found_exc(branch: str = "main") -> Exception:
    """Mirror the dulwich error message for a missing branch."""
    return Exception(f"b'{branch}' is not a valid branch or tag")


def test_clone_falls_back_to_default_branch_on_branch_not_found(git_client):
    """First clone attempt fails with branch-not-found → retry on default."""

    fake_repo = MagicMock()
    fake_repo.head.return_value = b"deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

    # First call: branch-not-found. Second: success on the fallback.
    clone_side_effect = [_branch_not_found_exc("main"), fake_repo]

    with patch(
        "synsc.core.git_client.porcelain.clone",
        side_effect=clone_side_effect,
    ) as mock_clone, patch.object(
        git_client, "_get_default_branch", return_value="master"
    ) as mock_default:
        repo_dir, owner, name, commit_sha = git_client.clone(
            "octocat/hello", branch="main"
        )

    assert owner == "octocat"
    assert name == "hello"
    assert commit_sha == "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    # Exactly one fallback lookup and exactly one retry — not a loop.
    assert mock_default.call_count == 1
    assert mock_clone.call_count == 2
    # The retry used the fallback branch.
    second_call_kwargs = mock_clone.call_args_list[1].kwargs
    assert second_call_kwargs.get("branch") == b"master"


def test_clone_does_not_retry_on_unrelated_error(git_client):
    """A non-branch-not-found error must propagate on the first attempt."""

    with patch(
        "synsc.core.git_client.porcelain.clone",
        side_effect=Exception("network unreachable"),
    ) as mock_clone, patch.object(
        git_client, "_get_default_branch"
    ) as mock_default:
        with pytest.raises(Exception, match="network unreachable"):
            git_client.clone("octocat/hello", branch="main")

    # No fallback API lookup, no retry.
    mock_default.assert_not_called()
    assert mock_clone.call_count == 1


def test_clone_does_not_retry_when_fallback_equals_requested(git_client):
    """If the API reports the same branch we already tried, surface the
    original error instead of looping.
    """

    with patch(
        "synsc.core.git_client.porcelain.clone",
        side_effect=_branch_not_found_exc("main"),
    ) as mock_clone, patch.object(
        git_client, "_get_default_branch", return_value="main"
    ) as mock_default:
        with pytest.raises(Exception, match="is not a valid branch or tag"):
            git_client.clone("octocat/hello", branch="main")

    assert mock_default.call_count == 1
    # Only one clone attempt — no pointless retry on the same branch.
    assert mock_clone.call_count == 1
