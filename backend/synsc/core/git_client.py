"""Git operations using dulwich."""

import fnmatch
import hashlib
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests as _requests
import structlog
from dulwich import porcelain
from dulwich.repo import Repo

from synsc.config import get_config

logger = structlog.get_logger(__name__)


class GitClient:
    """Handle Git operations for cloning and managing repositories."""

    def __init__(self, repos_dir: Path | None = None):
        """Initialize the Git client.
        
        Args:
            repos_dir: Directory for storing cloned repos (uses temp_dir by default)
        """
        config = get_config()
        self.repos_dir = repos_dir or config.storage.temp_dir
        self.git_config = config.git
        self.repos_dir.mkdir(parents=True, exist_ok=True)

    def parse_github_url(self, url: str) -> tuple[str, str, str]:
        """Parse a GitHub URL or shorthand into (url, owner, name).
        
        Args:
            url: GitHub URL or shorthand (owner/repo)
            
        Returns:
            Tuple of (full_url, owner, repo_name)
        """
        # Handle shorthand: owner/repo
        if re.match(r"^[\w.-]+/[\w.-]+$", url):
            owner, name = url.split("/")
            full_url = f"https://github.com/{owner}/{name}.git"
            return full_url, owner, name
        
        # Handle full URL
        parsed = urlparse(url)
        
        if not parsed.netloc:
            raise ValueError(f"Invalid URL: {url}")
        
        # Extract path parts
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) < 2:
            raise ValueError(f"Invalid GitHub URL: {url}")
        
        owner = path_parts[0]
        name = path_parts[1].replace(".git", "")
        
        # Normalize URL
        full_url = f"https://{parsed.netloc}/{owner}/{name}.git"
        
        return full_url, owner, name

    def _get_default_branch(
        self, owner: str, name: str, github_token: str | None = None
    ) -> str:
        """Query GitHub API for the repo's default branch.

        Falls back to config default (usually 'main') on any error.
        """
        try:
            headers = {"Accept": "application/vnd.github+json"}
            if github_token:
                headers["Authorization"] = f"Bearer {github_token}"
            resp = _requests.get(
                f"https://api.github.com/repos/{owner}/{name}",
                headers=headers,
                timeout=5,
            )
            if resp.status_code == 200:
                branch = resp.json().get("default_branch")
                if branch:
                    logger.debug("Auto-detected default branch", owner=owner, name=name, branch=branch)
                    return branch
        except Exception:
            pass
        return self.git_config.default_branch

    def get_repo_dir(self, owner: str, name: str, branch: str) -> Path:
        """Get the local directory for a repository.
        
        Args:
            owner: Repository owner
            name: Repository name
            branch: Branch name
            
        Returns:
            Path to the repository directory
        """
        # Use hash to handle long names and special characters
        repo_hash = hashlib.sha256(f"{owner}/{name}/{branch}".encode()).hexdigest()[:12]
        return self.repos_dir / f"{owner}_{name}_{repo_hash}"

    def clone(
        self,
        url: str,
        branch: str | None = None,
        github_token: str | None = None,
    ) -> tuple[Path, str, str, str]:
        """Clone a repository.

        Args:
            url: GitHub URL or shorthand
            branch: Branch to clone. If not specified — or if the requested
                branch isn't found on the remote — the repo's default branch
                is used when it can be determined via the GitHub API. If that
                lookup fails (rate limit, network error, or non-200 response),
                falls back to the configured ``git.default_branch``. This
                handles repos whose default isn't the configured
                ``git.default_branch`` (e.g. ``master``) when the API lookup
                succeeds.
            github_token: GitHub PAT for authenticated cloning of private repos.
                          If provided, injected as x-access-token in the clone URL.
                          NEVER logged or persisted — used only for this clone operation.

        Returns:
            Tuple of (local_path, owner, name, commit_sha)
        """
        full_url, owner, name = self.parse_github_url(url)

        # Auto-detect default branch from GitHub API if not specified
        if not branch:
            branch = self._get_default_branch(owner, name, github_token)

        try:
            # Suppress the error-level log on the first attempt: a
            # branch-not-found here is an expected/recoverable case and
            # we'll log it ourselves below if the fallback also fails.
            return self._clone_branch(
                full_url, owner, name, branch, github_token,
                log_errors=False,
            )
        except Exception as e:
            # On "branch not found" style errors, retry once against the
            # repo's GitHub-reported default branch. Dulwich surfaces these
            # as a generic Exception with the message
            # "b'<branch>' is not a valid branch or tag".
            err_msg_lower = str(e).lower()
            looks_like_bad_branch = (
                "is not a valid branch or tag" in err_msg_lower
                or "ref refs/heads/" in err_msg_lower
                or "remote ref" in err_msg_lower
            )
            if not looks_like_bad_branch:
                # Real failure on the first attempt — surface it now since
                # _clone_branch swallowed the error log.
                logger.error(
                    "Failed to clone repository",
                    url=full_url,
                    error=str(e),
                )
                raise

            fallback = self._get_default_branch(owner, name, github_token)
            if not fallback or fallback == branch:
                logger.error(
                    "Failed to clone repository (no usable fallback branch)",
                    url=full_url,
                    requested=branch,
                    fallback=fallback,
                    error=str(e),
                )
                raise

            logger.info(
                "Requested branch not found, retrying with default branch",
                owner=owner,
                name=name,
                requested=branch,
                fallback=fallback,
            )
            return self._clone_branch(
                full_url, owner, name, fallback, github_token,
            )

    def _clone_branch(
        self,
        full_url: str,
        owner: str,
        name: str,
        branch: str,
        github_token: str | None,
        log_errors: bool = True,
    ) -> tuple[Path, str, str, str]:
        """Clone a specific branch. Extracted from ``clone`` so the outer
        method can retry against the default branch on a "branch not found"
        error without duplicating dedup/auth logic.

        ``log_errors=False`` lets the outer ``clone`` suppress the error log
        on the first attempt of a fallback-eligible call; it logs once,
        with full context, after deciding whether to retry.
        """
        repo_dir = self.get_repo_dir(owner, name, branch)

        # If already cloned, pull latest
        if repo_dir.exists():
            logger.info(
                "Repository already exists, pulling latest",
                path=str(repo_dir),
                branch=branch,
            )
            try:
                repo = Repo(str(repo_dir))
                # Get current commit
                commit_sha = repo.head().decode()
                return repo_dir, owner, name, commit_sha
            except Exception as e:
                logger.warning(
                    "Failed to open existing repo, re-cloning",
                    error=str(e),
                )
                shutil.rmtree(repo_dir)

        # Build clone URL — inject token for authenticated access to private repos
        clone_url = full_url
        if github_token:
            parsed = urlparse(full_url)
            clone_url = f"https://x-access-token:{github_token}@{parsed.netloc}{parsed.path}"

        # Log the clean URL only (never the authenticated URL)
        logger.info(
            "Cloning repository",
            url=full_url,
            branch=branch,
            target=str(repo_dir),
            authenticated=bool(github_token),
        )

        try:
            # Clone with dulwich
            repo = porcelain.clone(
                clone_url,
                str(repo_dir),
                branch=branch.encode() if branch else None,
                depth=1,  # Shallow clone for speed
            )

            commit_sha = repo.head().decode()

            logger.info(
                "Repository cloned successfully",
                owner=owner,
                name=name,
                commit=commit_sha[:8],
            )

            return repo_dir, owner, name, commit_sha

        except Exception as e:
            if log_errors:
                logger.error(
                    "Failed to clone repository",
                    url=full_url,
                    error=str(e),
                )
            # Clean up partial clone
            if repo_dir.exists():
                shutil.rmtree(repo_dir)
            raise

    def delete_repo(self, owner: str, name: str, branch: str) -> bool:
        """Delete a cloned repository.
        
        Args:
            owner: Repository owner
            name: Repository name
            branch: Branch name
            
        Returns:
            True if deleted, False if not found
        """
        repo_dir = self.get_repo_dir(owner, name, branch)
        
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
            logger.info("Deleted repository", path=str(repo_dir))
            return True
        
        return False

    def list_files(
        self, repo_path: Path, include_content: bool = False, max_workers: int = 8
    ) -> list[dict]:
        """List all indexable files in a repository.
        
        Uses parallel I/O for faster file reading when include_content=True.
        
        Args:
            repo_path: Path to the repository
            include_content: Whether to include file content
            max_workers: Max parallel threads for file reading (default: 8)
            
        Returns:
            List of file info dicts
        """
        # Phase 1: Collect file paths (fast, single-threaded)
        file_paths = []
        
        for root, dirs, filenames in os.walk(repo_path):
            # Skip excluded directories
            dirs[:] = [
                d for d in dirs
                if not self._should_exclude(Path(root) / d, repo_path)
            ]
            
            for filename in filenames:
                file_path = Path(root) / filename
                rel_path = file_path.relative_to(repo_path)
                
                # Check exclusions
                if self._should_exclude(file_path, repo_path):
                    continue
                
                # Check file extension
                if not self._should_include(file_path):
                    continue
                
                # Check file size
                try:
                    size = file_path.stat().st_size
                    if size > self.git_config.max_file_size_mb * 1024 * 1024:
                        logger.debug(
                            "Skipping large file",
                            path=str(rel_path),
                            size_mb=size / (1024 * 1024),
                        )
                        continue
                except OSError:
                    continue
                
                file_paths.append((file_path, rel_path, filename, size))
        
        # Phase 2: Read file contents in parallel (if requested)
        if not include_content:
            # No content needed, just return metadata
            files = [
                {"path": str(rel_path), "name": filename, "size_bytes": size}
                for _, rel_path, filename, size in file_paths
            ]
            logger.info("Listed files", count=len(files))
            return files
        
        # Parallel file reading for content
        def read_file_content(args):
            """Read a single file's content."""
            file_path, rel_path, filename, size = args
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                return {
                    "path": str(rel_path),
                    "name": filename,
                    "size_bytes": size,
                    "content": content,
                }
            except Exception as e:
                logger.debug(
                    "Failed to read file",
                    path=str(rel_path),
                    error=str(e),
                )
                return None
        
        files = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(read_file_content, fp): fp for fp in file_paths}
            
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    files.append(result)
        
        logger.info("Listed files with content (parallel)", count=len(files))
        return files

    def _should_exclude(self, path: Path, repo_root: Path) -> bool:
        """Check if a path should be excluded."""
        rel_path = str(path.relative_to(repo_root))
        
        # Combine patterns
        patterns = list(self.git_config.exclude_patterns)
        
        # Add fast mode patterns if enabled
        if self.git_config.fast_mode:
            patterns.extend(self.git_config.fast_mode_skip_patterns)
        
        for pattern in patterns:
            # Handle directory patterns (ending with /)
            if pattern.endswith("/"):
                if pattern[:-1] in rel_path.split(os.sep):
                    return True
            # Handle glob patterns
            elif "*" in pattern:
                if fnmatch.fnmatch(path.name, pattern):
                    return True
                if fnmatch.fnmatch(rel_path, pattern):
                    return True
            # Handle exact matches
            elif pattern in rel_path:
                return True
        
        return False

    def _should_include(self, path: Path) -> bool:
        """Check if a file should be included based on extension."""
        suffix = path.suffix.lower()
        return suffix in self.git_config.include_extensions
