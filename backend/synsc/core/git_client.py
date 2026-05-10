"""Git operations using dulwich."""

import contextlib
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

    def __init__(self, repos_dir: Path | None = None, quality_mode: str | None = None):
        """Initialize the Git client.

        Args:
            repos_dir: Directory for storing cloned repos (uses temp_dir by default)
            quality_mode: Override quality_mode for inclusion/exclusion decisions.
                None = use config.quality.quality_mode.
        """
        config = get_config()
        self.repos_dir = repos_dir or config.storage.temp_dir
        self.git_config = config.git
        self.quality_config = config.quality
        # Resolve effective quality mode at call time so per-request overrides
        # (passed by IndexingService) take effect without needing a fresh
        # GitClient instance.
        self._quality_mode_override = quality_mode
        self.repos_dir.mkdir(parents=True, exist_ok=True)

    @property
    def effective_quality_mode(self) -> str:
        return self._quality_mode_override or self.quality_config.quality_mode

    def set_quality_mode(self, quality_mode: str | None) -> None:
        """Override quality_mode for subsequent operations on this client."""
        self._quality_mode_override = quality_mode

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
            branch: Branch to clone (default: main)
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

        repo_dir = self.get_repo_dir(owner, name, branch)

        # If already cloned, refresh against the remote before returning the
        # cached SHA. The previous behavior trusted the on-disk HEAD, so
        # re-indexes silently used stale code when the remote moved forward.
        # We now fetch the remote tip and only fast-forward; if anything
        # diverges (force-pushed, branch deleted) we wipe and re-clone.
        if repo_dir.exists():
            logger.info(
                "Repository already exists, refreshing against remote",
                path=str(repo_dir),
                branch=branch,
            )
            try:
                repo = Repo(str(repo_dir))

                # Build the same authenticated remote URL used at clone time
                # so private repos refresh as well.
                refresh_url = full_url
                if github_token:
                    parsed = urlparse(full_url)
                    refresh_url = (
                        f"https://x-access-token:{github_token}@"
                        f"{parsed.netloc}{parsed.path}"
                    )

                # dulwich.porcelain.fetch updates remote refs without merging.
                with contextlib.suppress(Exception):
                    porcelain.fetch(
                        repo, refresh_url, depth=1, force=True,
                    )

                remote_ref = f"refs/remotes/origin/{branch}".encode()
                refs = repo.get_refs()
                remote_sha_bytes = refs.get(remote_ref)

                if remote_sha_bytes:
                    # Fast-forward HEAD to the remote tip so list_files reads
                    # the latest content.
                    repo.refs[b"HEAD"] = remote_sha_bytes
                    branch_ref = f"refs/heads/{branch}".encode()
                    repo.refs[branch_ref] = remote_sha_bytes
                    commit_sha = remote_sha_bytes.decode()
                    logger.info(
                        "Repository fast-forwarded to remote tip",
                        path=str(repo_dir),
                        sha=commit_sha[:8],
                    )
                else:
                    # Couldn't get remote tip — fall back to local HEAD but
                    # warn so re-indexers know they may be working with stale
                    # source.
                    commit_sha = repo.head().decode()
                    logger.warning(
                        "Could not refresh remote, using local HEAD",
                        sha=commit_sha[:8],
                    )

                # Materialize the working tree at the new HEAD so list_files
                # reads the refreshed content from disk.
                with contextlib.suppress(Exception):
                    porcelain.reset(repo, mode="hard", treeish=commit_sha.encode())

                return repo_dir, owner, name, commit_sha
            except Exception as e:
                logger.warning(
                    "Failed to refresh existing repo, re-cloning",
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
        self,
        repo_path: Path,
        include_content: bool = False,
        max_workers: int = 8,
    ) -> list[dict]:
        """List all indexable files in a repository.

        Uses parallel I/O for faster file reading when include_content=True.

        Aggregates skip reasons per category so we can answer "what got
        filtered and why" without spamming the log on every file.

        Args:
            repo_path: Path to the repository
            include_content: Whether to include file content
            max_workers: Max parallel threads for file reading (default: 8)

        Returns:
            List of file info dicts. ``self.last_skip_reasons`` is populated
            with a counter of skip reasons for the most recent call.
        """
        # Phase 1: Collect file paths (fast, single-threaded)
        file_paths = []
        skip_reasons: dict[str, int] = {}
        total_seen = 0

        def _bump(reason: str) -> None:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

        for root, dirs, filenames in os.walk(repo_path):
            # Skip excluded directories
            kept_dirs = []
            for d in dirs:
                if self._should_exclude(Path(root) / d, repo_path):
                    _bump("dir_excluded")
                else:
                    kept_dirs.append(d)
            dirs[:] = kept_dirs

            for filename in filenames:
                total_seen += 1
                file_path = Path(root) / filename
                rel_path = file_path.relative_to(repo_path)

                # Check exclusions
                if self._should_exclude(file_path, repo_path):
                    _bump("pattern_excluded")
                    continue

                # Check file extension / basename
                if not self._should_include(file_path):
                    _bump("extension_not_included")
                    continue

                # Check file size
                try:
                    size = file_path.stat().st_size
                    if size > self.git_config.max_file_size_mb * 1024 * 1024:
                        _bump("file_too_large")
                        logger.debug(
                            "Skipping large file",
                            path=str(rel_path),
                            size_mb=size / (1024 * 1024),
                        )
                        continue
                except OSError:
                    _bump("stat_error")
                    continue

                file_paths.append((file_path, rel_path, filename, size))

        # Stash for the caller (IndexingService) to consume / log later.
        self.last_skip_reasons = skip_reasons
        self.last_total_seen = total_seen
        
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
        """Check if a path should be excluded.

        In agent quality mode we keep tests/docs/examples/configs because they
        carry context an agent needs (test cases reveal contracts, examples
        show idiomatic usage, configs reveal env vars and feature flags).
        """
        rel_path = str(path.relative_to(repo_root))

        # Combine patterns
        patterns = list(self.git_config.exclude_patterns)

        # In agent mode, never apply fast_mode_skip_patterns even if fast_mode
        # is on globally — agent mode is opinionated about keeping tests/docs.
        if self.git_config.fast_mode and self.effective_quality_mode != "agent":
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
        """Check if a file should be included.

        Inclusion rules (in order):
        1. Exact basename match against config.git.include_basenames — covers
           Dockerfile, Makefile, go.mod, .env.example, Procfile, etc. that
           have no extension or unusual ones.
        2. Extension match against config.git.include_extensions.
        3. In agent quality mode only, basenames starting with "Dockerfile.",
           "Makefile.", or ending with ".dockerfile" are also included.
        """
        name = path.name
        if name in self.git_config.include_basenames:
            return True

        suffix = path.suffix.lower()
        if suffix in self.git_config.include_extensions:
            return True

        if self.effective_quality_mode == "agent":
            # Common variants that don't show up in include_basenames literally.
            if name.startswith("Dockerfile.") or name.endswith(".dockerfile"):
                return True
            if name.startswith("Makefile.") or name.endswith(".mk"):
                return True
            # Bazel files — BUILD.foo, foo.bzl
            if suffix == ".bzl":
                return True
            # IaC / infra
            if suffix in {".tf", ".tfvars", ".hcl", ".bicep", ".nomad"}:
                return True

        return False
