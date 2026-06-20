"""Index freshness & drift detection — "is this index stale?"

An index is a snapshot. Code keeps moving after you index it, and an agent that
trusts a stale index reasons about code that no longer exists. This service
tells you when an index has drifted from its source:

- **GitHub repos**: compare the indexed commit SHA against the current remote
  HEAD of the indexed branch. Stale if the remote moved forward.
- **Local folders**: re-hash the folder's files and diff against the per-file
  content hashes captured at index time. Reports added / modified / deleted.

The result is recorded on the repository so the dashboard and ``list_stale``
can answer "what needs re-indexing?" cheaply.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog

from synsc.core.chunker import CodeChunker
from synsc.core.git_client import GitClient
from synsc.database.connection import get_session
from synsc.database.models import Repository, RepositoryFile, utc_now

logger = structlog.get_logger(__name__)

_LOCAL_PREFIX = "local://"
_DRIFT_SAMPLE = 25


class FreshnessService:
    """Check whether a repository's index has drifted from its source."""

    def __init__(self, user_id: str | None = None) -> None:
        self.user_id = user_id
        self.git_client = GitClient()
        self.chunker = CodeChunker()

    # ------------------------------------------------------------------
    # Pure helpers (DB-free, unit-testable)
    # ------------------------------------------------------------------
    @staticmethod
    def compute_hash_drift(
        current_files: list[dict[str, Any]],
        existing_hashes: dict[str, str | None],
        hash_fn: Callable[[str], str],
    ) -> tuple[list[str], list[str], list[str]]:
        """Diff current on-disk files against stored per-file content hashes.

        Returns ``(added, modified, deleted)`` lists of file paths.
        """
        added: list[str] = []
        modified: list[str] = []
        seen: set[str] = set()
        for file_info in current_files:
            path = file_info["path"]
            content = file_info.get("content", "")
            seen.add(path)
            if not content:
                continue
            digest = hash_fn(content)
            if path not in existing_hashes:
                added.append(path)
            elif existing_hashes[path] != digest:
                modified.append(path)
        deleted = [p for p in existing_hashes if p not in seen]
        return added, modified, deleted

    @staticmethod
    def is_stale_sha(indexed_sha: str | None, current_sha: str | None) -> bool:
        """A git index is stale when both SHAs are known and differ."""
        return bool(indexed_sha and current_sha and indexed_sha != current_sha)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def check_repository(self, repo_id: str, user_id: str | None = None) -> dict[str, Any]:
        uid = user_id or self.user_id
        with get_session() as session:
            repo = (
                session.query(Repository)
                .filter(Repository.repo_id == repo_id)
                .first()
            )
            if repo is None:
                return {"success": False, "error": "not_found", "repo_id": repo_id}
            if not repo.can_user_access(uid):
                return {"success": False, "error": "forbidden", "repo_id": repo_id}

            if (repo.url or "").startswith(_LOCAL_PREFIX):
                result = self._check_local(session, repo)
            else:
                result = self._check_remote(session, repo)

            # Persist a lightweight freshness marker for cheap dashboards / list.
            meta = repo.get_metadata()
            meta["freshness"] = {
                "checked_at": utc_now().isoformat(),
                "is_stale": result.get("is_stale", False),
                "source_type": result.get("source_type"),
            }
            repo.set_metadata(meta)
            session.commit()
            return result

    def list_stale(self, user_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Check every repo in the user's collection and return the stale ones."""
        uid = user_id or self.user_id
        with get_session() as session:
            query = session.query(Repository)
            if uid:
                query = query.filter(Repository.indexed_by == uid)
            repos = query.limit(limit).all()
            repo_ids = [r.repo_id for r in repos]

        stale: list[dict[str, Any]] = []
        checked = 0
        for repo_id in repo_ids:
            res = self.check_repository(repo_id, user_id=uid)
            checked += 1
            if res.get("is_stale"):
                stale.append(res)
        return {
            "success": True,
            "checked": checked,
            "stale_count": len(stale),
            "stale": stale,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _check_remote(self, session: Any, repo: Repository) -> dict[str, Any]:
        token = self._github_token(session, repo.indexed_by)
        current_sha = self.git_client.get_remote_commit_sha(
            repo.owner, repo.name, repo.branch, github_token=token
        )
        is_stale = self.is_stale_sha(repo.commit_sha, current_sha)
        return {
            "success": True,
            "repo_id": repo.repo_id,
            "source_type": "git",
            "branch": repo.branch,
            "indexed_sha": repo.commit_sha,
            "current_sha": current_sha,
            "is_stale": is_stale,
            "indexed_at": repo.indexed_at.isoformat() if repo.indexed_at else None,
            "message": (
                "Index is behind the remote — re-index to refresh."
                if is_stale
                else (
                    "Index is up to date."
                    if current_sha
                    else "Could not reach the remote to compare."
                )
            ),
        }

    def _check_local(self, session: Any, repo: Repository) -> dict[str, Any]:
        path = Path(repo.url[len(_LOCAL_PREFIX):])
        if not path.exists() or not path.is_dir():
            return {
                "success": True,
                "repo_id": repo.repo_id,
                "source_type": "local",
                "is_stale": True,
                "source_missing": True,
                "path": str(path),
                "message": "Source folder no longer exists — index is orphaned.",
            }

        files = self.git_client.list_files(path, include_content=True)
        existing = (
            session.query(RepositoryFile.file_path, RepositoryFile.content_hash)
            .filter(RepositoryFile.repo_id == repo.repo_id)
            .all()
        )
        existing_hashes = dict(existing)
        added, modified, deleted = self.compute_hash_drift(
            files, existing_hashes, self.chunker.compute_hash
        )
        is_stale = bool(added or modified or deleted)
        return {
            "success": True,
            "repo_id": repo.repo_id,
            "source_type": "local",
            "path": str(path),
            "is_stale": is_stale,
            "drift": {
                "added": len(added),
                "modified": len(modified),
                "deleted": len(deleted),
                "added_sample": added[:_DRIFT_SAMPLE],
                "modified_sample": modified[:_DRIFT_SAMPLE],
                "deleted_sample": deleted[:_DRIFT_SAMPLE],
            },
            "indexed_at": repo.indexed_at.isoformat() if repo.indexed_at else None,
            "message": (
                f"Folder drifted: +{len(added)} ~{len(modified)} -{len(deleted)} files."
                if is_stale
                else "Index matches the folder on disk."
            ),
        }

    def _github_token(self, session: Any, user_id: str | None) -> str | None:
        """Best-effort decrypt of the user's stored GitHub token for private repos."""
        if not user_id:
            return None
        try:
            from synsc.database.models import GitHubToken
            from synsc.services.token_encryption import decrypt_token

            row = (
                session.query(GitHubToken)
                .filter(GitHubToken.user_id == user_id)
                .first()
            )
            if row and row.encrypted_token:
                return decrypt_token(row.encrypted_token)
        except Exception:
            return None
        return None
