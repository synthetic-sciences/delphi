"""Indexing service for GitHub repositories.

Supports multi-tenant operation with smart deduplication:
- PUBLIC repos: Indexed once, shared by all users who add them
- PRIVATE repos: Indexed once, accessible only by the indexer

This saves massive storage when multiple users index popular repos like react/next.js.
"""

import contextlib
import queue as _queue
import threading as _threading
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import numpy as np
import requests
import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from synsc.config import get_config
from synsc.core.chunker import CodeChunker
from synsc.core.context_enrichment import enrich_chunk_for_embedding, enrich_doc_chunk_for_embedding
from synsc.core.git_client import GitClient
from synsc.core.language_detector import detect_language
from synsc.database.connection import get_session
from synsc.database.models import (
    ChunkRelationship,
    CodeChunk,
    Repository,
    RepositoryFile,
    Symbol,
    UserRepository,
)
from synsc.embeddings.generator import EmbeddingGenerator, get_embedding_generator
from synsc.indexing.vector_store import get_vector_store
from synsc.parsing.registry import get_parser_registry

logger = structlog.get_logger(__name__)


def _build_chunk_relationships(session: Session, repo_id: str) -> int:
    """Build directed edges between chunks for relationship-aware search.

    Creates two types of relationships:
    - adjacent: consecutive chunks in the same file (chunk_index N → N+1)
    - same_class: chunks that fall within the same class symbol's line range

    Returns the number of relationships created.
    """
    # Only fetch columns needed for relationship building (skip content to avoid
    # transferring megabytes of code text).
    chunks = (
        session.query(
            CodeChunk.chunk_id,
            CodeChunk.file_id,
            CodeChunk.chunk_index,
            CodeChunk.start_line,
            CodeChunk.end_line,
        )
        .join(RepositoryFile, CodeChunk.file_id == RepositoryFile.file_id)
        .filter(RepositoryFile.repo_id == repo_id)
        .order_by(CodeChunk.file_id, CodeChunk.chunk_index)
        .all()
    )

    if not chunks:
        return 0

    relationships: list[ChunkRelationship] = []
    seen: set[tuple[str, str, str]] = set()

    def _add(src: str, tgt: str, rtype: str, weight: float = 1.0) -> None:
        key = (src, tgt, rtype)
        if key not in seen:
            seen.add(key)
            relationships.append(
                ChunkRelationship(
                    source_chunk_id=src,
                    target_chunk_id=tgt,
                    relationship_type=rtype,
                    weight=weight,
                )
            )

    # Group chunks by file
    chunks_by_file: dict[str, list[CodeChunk]] = {}
    for c in chunks:
        chunks_by_file.setdefault(c.file_id, []).append(c)

    # 1. Adjacent edges
    for file_chunks in chunks_by_file.values():
        for i in range(len(file_chunks) - 1):
            _add(file_chunks[i].chunk_id, file_chunks[i + 1].chunk_id, "adjacent")

    # 2. Same-class edges: chunks overlapping a class symbol's line range
    file_ids = list(chunks_by_file.keys())
    class_symbols = (
        session.query(Symbol.file_id, Symbol.start_line, Symbol.end_line)
        .filter(Symbol.file_id.in_(file_ids), Symbol.symbol_type == "class")
        .all()
    )

    for sym in class_symbols:
        overlapping = [
            c
            for c in chunks_by_file.get(sym.file_id, [])
            if c.start_line is not None
            and c.end_line is not None
            and c.start_line <= sym.end_line
            and c.end_line >= sym.start_line
        ]
        # Cap at 10 chunks per class to avoid quadratic blowup
        overlapping = overlapping[:10]
        for i, a in enumerate(overlapping):
            for b in overlapping[i + 1 :]:
                _add(a.chunk_id, b.chunk_id, "same_class")

    if relationships:
        # Diff-aware reindex preserves unchanged chunks and their edges.
        # ON CONFLICT DO NOTHING lets us re-issue the full edge set without
        # rolling back the whole batch when a preserved edge is re-inserted.
        rows = [
            {
                "source_chunk_id": r.source_chunk_id,
                "target_chunk_id": r.target_chunk_id,
                "relationship_type": r.relationship_type,
                "weight": r.weight,
            }
            for r in relationships
        ]
        stmt = pg_insert(ChunkRelationship.__table__).values(rows)
        stmt = stmt.on_conflict_do_nothing(constraint="unique_chunk_relationship")
        session.execute(stmt)
        session.flush()

    logger.info(
        "Built chunk relationships",
        repo_id=repo_id,
        total=len(relationships),
        adjacent=sum(1 for r in relationships if r.relationship_type == "adjacent"),
        same_class=sum(1 for r in relationships if r.relationship_type == "same_class"),
    )

    return len(relationships)


class IndexingService:
    """Service for indexing GitHub repositories.
    
    SMART DEDUPLICATION:
    - If a public repo is already indexed, just add to user's collection (instant!)
    - If it's new or private, perform full indexing
    
    This saves 90%+ storage for popular repos like react, next.js, etc.
    """

    def __init__(self, user_id: str | None = None):
        """Initialize the indexing service.
        
        Args:
            user_id: User ID for multi-tenant isolation. Required for cloud deployments.
        """
        self.config = get_config()
        self.user_id = user_id
        self.git_client = GitClient()
        self.chunker = CodeChunker()
        self._embedding_generator = None
        self._vector_store = None
    
    @property
    def embedding_generator(self):
        """Lazy-load embedding generator (dispatches by EMBEDDING_PROVIDER)."""
        if self._embedding_generator is None:
            self._embedding_generator = get_embedding_generator()
        return self._embedding_generator
    
    @property
    def vector_store(self):
        """Lazy-load vector store."""
        if self._vector_store is None:
            self._vector_store = get_vector_store()
        return self._vector_store

    def _check_repo_is_public(self, url: str) -> bool:
        """Check if a GitHub repository is public.
        
        Args:
            url: GitHub URL
            
        Returns:
            True if public (accessible without auth), False otherwise
        """
        try:
            # Try to access the repo without authentication
            # GitHub returns 200 for public repos, 404 for private ones
            response = requests.head(url, timeout=5, allow_redirects=True)
            return response.status_code == 200
        except Exception:
            # If we can't check, assume private for safety
            return False

    def _get_user_github_token(self, user_id: str) -> str | None:
        """Retrieve and decrypt a user's stored GitHub PAT.

        Returns the plaintext token or None if no token is stored.
        Never logs the token value.
        """
        try:
            from synsc.database.models import GitHubToken

            with get_session() as session:
                token_row = session.query(GitHubToken).filter(
                    GitHubToken.user_id == user_id
                ).first()
                if not token_row:
                    return None

                # Tokens stored in plaintext for local deployment
                token = token_row.encrypted_token

                # Update last_used_at (fire-and-forget)
                with contextlib.suppress(Exception):
                    from datetime import datetime, timezone
                    token_row.last_used_at = datetime.now(timezone.utc)

            return token
        except Exception as e:
            logger.error("Failed to retrieve GitHub token", error=str(e))
            return None

    def _verify_repo_access(self, github_token: str, owner: str, name: str) -> bool:
        """Verify that a GitHub token has read access to a specific repo.

        Args:
            github_token: Plaintext PAT
            owner: Repository owner
            name: Repository name

        Returns:
            True if the token can access the repo, False otherwise
        """
        try:
            response = requests.get(
                f"https://api.github.com/repos/{owner}/{name}",
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error("GitHub repo access check failed", error=str(e))
            return False

    def _add_repo_to_user_collection(
        self,
        session: Session,
        repo_id: str,
        user_id: str,
    ) -> None:
        """Add a repository to user's collection (junction table).
        
        Args:
            session: Database session
            repo_id: Repository ID
            user_id: User ID
        """
        # Check if already in collection
        existing = session.query(UserRepository).filter(
            UserRepository.user_id == user_id,
            UserRepository.repo_id == repo_id,
        ).first()
        
        if not existing:
            user_repo = UserRepository(
                user_id=user_id,
                repo_id=repo_id,
            )
            session.add(user_repo)
            logger.info(
                "Added repo to user collection",
                repo_id=repo_id,
                user_id=user_id,
            )

    def index_repository(
        self,
        url: str,
        branch: str | None = None,
        user_id: str | None = None,
        is_public: bool | None = None,
        progress_callback: Callable | None = None,
        deep_index: bool = False,
        force_reindex: bool = False,
    ) -> dict:
        """Index a GitHub repository with smart deduplication.
        
        DEDUPLICATION FLOW:
        1. Check if repo already exists globally (by url+branch)
        2. If exists AND public: Just add to user's collection (instant!)
        3. If exists AND private: Error (can't access another user's private repo)
        4. If new: Index it and add to user's collection
        
        Args:
            url: GitHub URL or shorthand (owner/repo)
            branch: Branch to index (default: main)
            user_id: User ID for multi-tenant isolation
            is_public: Override visibility detection (None = auto-detect)
            
        Returns:
            Dict with indexing results
        """
        start_time = time.time()
        branch = branch or self.config.git.default_branch
        
        # Use provided user_id or fall back to instance user_id
        effective_user_id = user_id or self.user_id
        
        # For local development without auth, use a default UUID
        if not effective_user_id:
            if not self.config.api.require_auth:
                # Use a consistent UUID for local development
                effective_user_id = "00000000-0000-0000-0000-000000000001"
                logger.info("Using default local user for indexing", user_id=effective_user_id)
            else:
                return {
                    "success": False,
                    "status": "error",
                    "error": "user_id required",
                    "message": "Authentication required to index repositories",
                }
        
        def report_progress(stage: str, message: str, progress: float = 0, **kwargs):
            """Report progress if callback is provided."""
            if progress_callback:
                with contextlib.suppress(Exception):
                    progress_callback(stage, message, progress, **kwargs)
        
        try:
            # Parse URL
            report_progress("parsing", "Parsing repository URL...", 5)
            full_url, owner, name = self.git_client.parse_github_url(url)
            
            # Check if repo already exists globally (DEDUPLICATION CHECK)
            report_progress("checking", f"Checking if {owner}/{name} is already indexed...", 10)
            with get_session() as session:
                existing = session.query(Repository).filter(
                    Repository.url == full_url,
                    Repository.branch == branch,
                ).first()
                
                if existing:
                    # Repo already indexed - check if it needs updating
                    if existing.is_public:
                        # PUBLIC: Check if repo is up-to-date
                        # Get current commit SHA to compare
                        try:
                            # Clone temporarily to check current commit
                            temp_path, _, _, current_sha = self.git_client.clone(url, branch)
                            needs_update = current_sha != existing.commit_sha

                            if not needs_update and not force_reindex:
                                # Up-to-date: Just add to collection (INSTANT!)
                                self._add_repo_to_user_collection(
                                    session, existing.repo_id, effective_user_id
                                )
                                session.commit()

                                logger.info(
                                    "Repo already indexed and up-to-date, added to user collection",
                                    repo_id=existing.repo_id,
                                    owner=owner,
                                    name=name,
                                    current_sha=current_sha,
                                    indexed_sha=existing.commit_sha,
                                    user_id=effective_user_id,
                                )

                                elapsed_time = (time.time() - start_time) * 1000
                                return {
                                    "success": True,
                                    "status": "already_indexed",
                                    "repo_id": str(existing.repo_id),
                                    "owner": owner,
                                    "name": name,
                                    "branch": branch,
                                    "commit_sha": existing.commit_sha,
                                    "files_indexed": existing.files_count,
                                    "chunks_created": existing.chunks_count,
                                    "is_public": True,
                                    "is_shared": True,
                                    "indexing_time_ms": elapsed_time,
                                    "message": "Repository already indexed and up-to-date - added to your collection!",
                                }
                            else:
                                # Outdated: Need to re-index (update the repo)
                                logger.info(
                                    "Public repo is outdated, re-indexing",
                                    repo_id=existing.repo_id,
                                    owner=owner,
                                    name=name,
                                    old_sha=existing.commit_sha,
                                    new_sha=current_sha,
                                )
                                report_progress(
                                    "updating",
                                    f"Repository has new commits, updating {owner}/{name}...",
                                    15,
                                )

                                if not force_reindex:
                                    # Diff-aware re-index: only process changed files
                                    diff_files = self.git_client.list_files(temp_path, include_content=True)
                                    diff_result = self._diff_reindex(
                                        session, existing, temp_path, diff_files,
                                        current_sha, progress_callback, deep_index,
                                    )
                                    if diff_result is not None:
                                        # Diff reindex succeeded
                                        self._add_repo_to_user_collection(
                                            session, existing.repo_id, effective_user_id
                                        )
                                        session.commit()

                                        # Rebuild chunk relationships for affected files
                                        try:
                                            report_progress("relationships", "Rebuilding chunk relationships...", 96)
                                            from synsc.database.connection import get_engine
                                            get_engine().dispose()
                                            with get_session() as rel_session:
                                                rel_count = _build_chunk_relationships(rel_session, existing.repo_id)
                                                rel_session.commit()
                                        except Exception:
                                            logger.warning("Failed to rebuild relationships (non-critical)", exc_info=True)

                                        elapsed_time = (time.time() - start_time) * 1000
                                        return {
                                            "success": True,
                                            "status": "updated",
                                            "repo_id": str(existing.repo_id),
                                            "owner": owner,
                                            "name": name,
                                            "branch": branch,
                                            "commit_sha": current_sha,
                                            "files_indexed": diff_result["files_count"],
                                            "chunks_created": diff_result["chunks_count"],
                                            "symbols_extracted": diff_result.get("symbols_count", 0),
                                            "is_public": True,
                                            "is_shared": True,
                                            "diff_stats": diff_result.get("diff_stats"),
                                            "indexing_time_ms": elapsed_time,
                                            "message": "Repository updated via diff-aware re-index",
                                        }
                                    # diff_result is None → threshold exceeded, fall through to full re-index
                                    logger.info("Diff threshold exceeded, performing full re-index")

                                # Full re-index: delete child data but KEEP the repo row
                                # so the repo_id is preserved and user_repositories links stay valid
                                session.execute(text("DELETE FROM chunk_embeddings WHERE repo_id = :rid"), {"rid": existing.repo_id})
                                session.execute(text("DELETE FROM symbols WHERE repo_id = :rid"), {"rid": existing.repo_id})
                                session.execute(text("DELETE FROM code_chunks WHERE repo_id = :rid"), {"rid": existing.repo_id})
                                session.execute(text("DELETE FROM repository_files WHERE repo_id = :rid"), {"rid": existing.repo_id})
                                session.commit()
                                # Fall through to re-index below (_index_files will reuse the repo row)
                        except Exception as e:
                            logger.warning(
                                "Failed to check if repo is up-to-date, treating as up-to-date",
                                error=str(e),
                            )
                            # On error, just add to collection without updating
                            self._add_repo_to_user_collection(
                                session, existing.repo_id, effective_user_id
                            )
                            session.commit()

                            elapsed_time = (time.time() - start_time) * 1000
                            return {
                                "success": True,
                                "status": "already_indexed",
                                "repo_id": str(existing.repo_id),
                                "owner": owner,
                                "name": name,
                                "branch": branch,
                                "commit_sha": existing.commit_sha,
                                "files_indexed": existing.files_count,
                                "chunks_created": existing.chunks_count,
                                "is_public": True,
                                "is_shared": True,
                                "indexing_time_ms": elapsed_time,
                                "message": "Repository already indexed - added to your collection!",
                            }
                    elif existing.indexed_by == effective_user_id:
                        if not force_reindex:
                            # PRIVATE + same user: Already in collection
                            # Make sure it's in their collection
                            self._add_repo_to_user_collection(
                                session, existing.repo_id, effective_user_id
                            )
                            session.commit()

                            return {
                                "success": True,
                                "status": "already_exists",
                                "repo_id": str(existing.repo_id),
                                "owner": owner,
                                "name": name,
                                "branch": branch,
                                "commit_sha": existing.commit_sha,
                                "files_indexed": existing.files_count,
                                "chunks_created": existing.chunks_count,
                                "is_public": False,
                                "is_shared": False,
                                "message": "Repository already indexed by you",
                            }
                        else:
                            # Force re-index: delete child data but KEEP the repo row
                            session.execute(text("DELETE FROM chunk_embeddings WHERE repo_id = :rid"), {"rid": existing.repo_id})
                            session.execute(text("DELETE FROM symbols WHERE repo_id = :rid"), {"rid": existing.repo_id})
                            session.execute(text("DELETE FROM code_chunks WHERE repo_id = :rid"), {"rid": existing.repo_id})
                            session.execute(text("DELETE FROM repository_files WHERE repo_id = :rid"), {"rid": existing.repo_id})
                            session.commit()
                    else:
                        # PRIVATE + different user: Don't reuse the existing
                        # entry — fall through to full indexing so this user
                        # gets their own isolated copy. The UNIQUE(url, branch)
                        # constraint doesn't apply because we'll use a
                        # disambiguated URL for private per-user entries.
                        pass
            
            # NEW REPO: Need to index it
            # Auto-detect visibility if not specified
            if is_public is None:
                is_public = self._check_repo_is_public(full_url)

            # For private repos: acquire GitHub token for authenticated clone
            github_token = None
            if not is_public:
                github_token = self._get_user_github_token(effective_user_id)
                if not github_token:
                    return {
                        "success": False,
                        "status": "github_token_required",
                        "error": "GitHub token required for private repositories",
                        "message": (
                            "This repository appears to be private. "
                            "Add a GitHub Personal Access Token in Settings to index private repos."
                        ),
                    }

                # Verify the token has access to this specific repo
                if not self._verify_repo_access(github_token, owner, name):
                    return {
                        "success": False,
                        "status": "repo_not_accessible",
                        "error": "Token cannot access this repository",
                        "message": (
                            f"Your GitHub token does not have access to {owner}/{name}. "
                            "Ensure your fine-grained PAT includes this repository with 'Contents: Read' permission."
                        ),
                    }

            # Clone repository
            report_progress("cloning", f"Cloning {owner}/{name}...", 15)
            repo_path, owner, name, commit_sha = self.git_client.clone(
                url, branch, github_token=github_token
            )
            report_progress("cloned", f"Cloned {owner}/{name} successfully", 25)

            # List files
            report_progress("listing", "Listing files...", 30)
            files = self.git_client.list_files(repo_path, include_content=True)
            report_progress("listed", f"Found {len(files)} files to process", 35, files_count=len(files))

            if not files:
                return {
                    "success": False,
                    "status": "error",
                    "error": "No indexable files found",
                    "message": "Repository has no files matching include patterns",
                }

            # For private repos, disambiguate the stored URL so the
            # UNIQUE(url, branch) constraint allows per-user copies.
            # This prevents cross-user deduplication of private repos.
            stored_url = full_url
            if not is_public:
                stored_url = f"{full_url}#user={effective_user_id}"

            # Index files
            report_progress("indexing", "Processing files and extracting symbols...", 40)
            with get_session() as session:
                result = self._index_files(
                    session=session,
                    url=stored_url,
                    owner=owner,
                    name=name,
                    branch=branch,
                    commit_sha=commit_sha,
                    repo_path=repo_path,
                    files=files,
                    user_id=effective_user_id,
                    is_public=is_public,
                    progress_callback=progress_callback,
                    deep_index=deep_index,
                )
                
                # Add to user's collection
                self._add_repo_to_user_collection(
                    session, result["repo_id"], effective_user_id
                )
                report_progress("committing", "Saving to database...", 95)
                session.commit()
            
            # Save vector store (no-op for pgvector)
            self.vector_store.save()

            # Build chunk relationships in a SEPARATE session (post-commit).
            # After long indexing transactions (20+ min), pooled connections are
            # stale (closed by PgBouncer/timeout). Dispose the pool to force
            # a fresh connection, then build relationships.
            try:
                report_progress("relationships", "Building chunk relationships...", 96)
                from synsc.database.connection import get_engine
                get_engine().dispose()  # Drop stale connections from pool
                with get_session() as rel_session:
                    rel_count = _build_chunk_relationships(rel_session, result["repo_id"])
                    rel_session.commit()
                    logger.info("Built chunk relationships", count=rel_count, repo_id=result["repo_id"])
            except Exception:
                logger.warning("Failed to build chunk relationships (non-critical)", exc_info=True)

            elapsed_time = (time.time() - start_time) * 1000

            logger.info(
                "Indexing complete",
                repo=f"{owner}/{name}",
                branch=branch,
                files=result["files_count"],
                chunks=result["chunks_count"],
                symbols=result.get("symbols_count", 0),
                time_ms=round(elapsed_time),
            )

            return {
                "success": True,
                "status": "indexed",
                "repo_id": str(result["repo_id"]),
                "owner": owner,
                "name": name,
                "branch": branch,
                "commit_sha": commit_sha,
                "files_indexed": result["files_count"],
                "chunks_created": result["chunks_count"],
                "symbols_extracted": result.get("symbols_count", 0),
                "is_public": is_public,
                "is_shared": False,
                "indexing_time_ms": elapsed_time,
                "message": f"Repository indexed successfully ({'public - can be shared' if is_public else 'private - only you can access'})",
            }
            
        except Exception as e:
            logger.error("Failed to index repository", error=str(e), user_id=effective_user_id)
            return {
                "success": False,
                "status": "error",
                "error": str(e),
                "message": f"Failed to index repository: {e}",
            }

    # ── Diff-aware re-indexing ─────────────────────────────────────────────

    def _compute_file_diff(
        self,
        session: Session,
        repo_id: str,
        new_files: list[dict],
    ) -> tuple[list[dict], list[dict], list[RepositoryFile]]:
        """Compare cloned files against DB to determine added/modified/deleted.

        Returns:
            (added_files, modified_files, deleted_db_files)
        """
        # Build lookup of existing files by path → RepositoryFile
        existing_files = (
            session.query(RepositoryFile)
            .filter(RepositoryFile.repo_id == repo_id)
            .all()
        )
        db_lookup: dict[str, RepositoryFile] = {f.file_path: f for f in existing_files}

        added: list[dict] = []
        modified: list[dict] = []
        seen_paths: set[str] = set()

        for file_info in new_files:
            path = file_info["path"]
            content = file_info.get("content", "")
            seen_paths.add(path)

            if not content:
                continue

            content_hash = self.chunker.compute_hash(content)
            db_file = db_lookup.get(path)

            if db_file is None:
                added.append(file_info)
            elif db_file.content_hash != content_hash:
                modified.append(file_info)
            # else: unchanged — skip

        # Files in DB but not in new clone → deleted
        deleted = [f for path, f in db_lookup.items() if path not in seen_paths]

        return added, modified, deleted

    def _delete_file_data(self, session: Session, file_id: str) -> None:
        """Delete all data for a single file.

        With ON DELETE CASCADE on chunk_embeddings and chunk_relationships,
        deleting code_chunks auto-cleans embeddings and relationships.
        """
        session.execute(
            text("DELETE FROM code_chunks WHERE file_id = :fid"), {"fid": file_id}
        )
        session.execute(
            text("DELETE FROM symbols WHERE file_id = :fid"), {"fid": file_id}
        )
        session.execute(
            text("DELETE FROM repository_files WHERE file_id = :fid"), {"fid": file_id}
        )

    def _diff_reindex(
        self,
        session: Session,
        existing: Repository,
        repo_path: Path,
        new_files: list[dict],
        new_commit_sha: str,
        progress_callback: Callable | None = None,
        deep_index: bool = False,
    ) -> dict | None:
        """Perform diff-aware re-indexing on an existing repository.

        Returns result dict on success, or None if >80% files changed
        (caller should fall back to full re-index).
        """
        def report_progress(stage: str, message: str, progress: float = 0, **kwargs):
            if progress_callback:
                with contextlib.suppress(Exception):
                    progress_callback(stage, message, progress, **kwargs)

        repo_id = existing.repo_id

        # 1. Compute diff
        report_progress("computing_diff", "Comparing files with previous index...", 15)
        added, modified, deleted = self._compute_file_diff(session, repo_id, new_files)
        total_changed = len(added) + len(modified) + len(deleted)
        total_files = len(new_files)

        logger.info(
            "Diff computed",
            repo_id=repo_id,
            added=len(added),
            modified=len(modified),
            deleted=len(deleted),
            unchanged=total_files - len(added) - len(modified),
        )

        # 2. Threshold check — if >80% changed, fall back to full re-index
        if total_files > 0 and total_changed / total_files > 0.8:
            logger.info(
                "Diff threshold exceeded, falling back to full re-index",
                changed_pct=round(total_changed / total_files * 100),
            )
            return None

        # Disable timeouts for reindex
        session.execute(text("SET LOCAL statement_timeout = '0'"))
        session.execute(text("SET LOCAL idle_in_transaction_session_timeout = '0'"))

        # 3. Purge deleted + modified files
        files_to_purge = [f for f in deleted] + [
            session.query(RepositoryFile)
            .filter(RepositoryFile.repo_id == repo_id, RepositoryFile.file_path == fi["path"])
            .first()
            for fi in modified
        ]
        if files_to_purge:
            report_progress(
                "removing_deleted",
                f"Removing {len(files_to_purge)} changed/deleted files...",
                20,
            )
            for db_file in files_to_purge:
                if db_file:
                    self._delete_file_data(session, db_file.file_id)
            session.flush()

        # 4. Index only new/changed files
        files_to_process = added + modified
        if not files_to_process:
            # Only deletions — just update metadata
            existing.commit_sha = new_commit_sha
            existing.last_diff_stats = {
                "added": 0, "modified": 0,
                "deleted": len(deleted),
                "unchanged": total_files,
            }
            existing.embedding_model = self.embedding_generator.model_name

            # Recalculate stats from remaining files
            remaining_files = (
                session.query(RepositoryFile)
                .filter(RepositoryFile.repo_id == repo_id)
                .count()
            )
            remaining_chunks = (
                session.query(CodeChunk)
                .filter(CodeChunk.repo_id == repo_id)
                .count()
            )
            remaining_symbols = (
                session.query(Symbol)
                .filter(Symbol.repo_id == repo_id)
                .count()
            )
            existing.files_count = remaining_files
            existing.chunks_count = remaining_chunks
            existing.symbols_count = remaining_symbols

            return {
                "repo_id": str(repo_id),
                "files_count": remaining_files,
                "chunks_count": remaining_chunks,
                "symbols_count": remaining_symbols,
                "diff_stats": existing.last_diff_stats,
            }

        report_progress(
            "reprocessing",
            f"Re-processing {len(files_to_process)} modified/added files...",
            30,
        )

        # Reuse the per-file processing logic from _index_files
        parser_registry = get_parser_registry()
        total_new_symbols = 0
        chunks_to_embed: list[tuple[CodeChunk, str]] = []

        for file_idx, file_info in enumerate(files_to_process):
            file_path = file_info["path"]
            content = file_info.get("content", "")
            if not content:
                continue

            language = detect_language(file_path)

            db_file = RepositoryFile(
                repo_id=repo_id,
                file_path=file_path,
                file_name=Path(file_path).name,
                language=language,
                line_count=content.count("\n") + 1,
                token_count=self.chunker.count_tokens(content),
                size_bytes=file_info["size_bytes"],
                content_hash=self.chunker.compute_hash(content),
            )
            session.add(db_file)

            if (file_idx + 1) % 50 == 0 or file_idx == len(files_to_process) - 1:
                pct = 30 + ((file_idx + 1) / len(files_to_process)) * 30
                report_progress(
                    "reprocessing",
                    f"Processing {file_idx + 1}/{len(files_to_process)} files...",
                    pct,
                )

        # Flush to get file_ids
        session.flush()

        # Now process chunks for all new/modified files
        for file_info in files_to_process:
            file_path = file_info["path"]
            content = file_info.get("content", "")
            if not content:
                continue

            language = detect_language(file_path)
            db_file = (
                session.query(RepositoryFile)
                .filter(
                    RepositoryFile.repo_id == repo_id,
                    RepositoryFile.file_path == file_path,
                )
                .first()
            )
            if not db_file:
                continue

            # Doc files
            is_doc_file = language in ("markdown", "restructuredtext") or (
                file_path.lower().endswith((".md", ".mdx", ".rst"))
            )

            if is_doc_file:
                chunks = self.chunker.chunk_file(content, language)
                for idx, chunk in enumerate(chunks):
                    db_chunk = CodeChunk(
                        repo_id=repo_id,
                        file_id=db_file.file_id,
                        chunk_index=idx,
                        content=chunk.content,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        chunk_type="documentation",
                        language=language,
                        token_count=chunk.token_count,
                    )
                    session.add(db_chunk)
                    enriched = enrich_doc_chunk_for_embedding(chunk.content, file_path)
                    chunks_to_embed.append((db_chunk, enriched))
                continue

            # Code files — symbol extraction + chunking
            turbo_mode = False if deep_index else self.config.git.turbo_mode
            parser = parser_registry.get_parser(language) if language else None
            use_ast_chunking = False
            symbol_boundaries: list[tuple[int, int]] = []
            extracted_symbols: list = []

            if parser:
                try:
                    extracted_symbols = parser.extract_symbols(content)
                    for ext_sym in extracted_symbols:
                        symbol_boundaries.append((ext_sym.start_line, ext_sym.end_line))

                    for ext_sym in extracted_symbols:
                        db_symbol = Symbol(
                            repo_id=repo_id,
                            file_id=db_file.file_id,
                            name=ext_sym.name,
                            qualified_name=ext_sym.qualified_name,
                            symbol_type=ext_sym.symbol_type,
                            signature=ext_sym.signature,
                            docstring=ext_sym.docstring,
                            start_line=ext_sym.start_line,
                            end_line=ext_sym.end_line,
                            is_exported=ext_sym.is_exported,
                            is_async=ext_sym.is_async,
                            language=language,
                        )
                        if ext_sym.parameters:
                            db_symbol.set_parameters(ext_sym.parameters)
                        if ext_sym.return_type:
                            db_symbol.return_type = ext_sym.return_type
                        if ext_sym.decorators:
                            db_symbol.set_decorators(ext_sym.decorators)
                        session.add(db_symbol)
                        total_new_symbols += 1

                    if not turbo_mode:
                        try:
                            regions = parser.create_code_regions(content)
                            if regions:
                                chunk_counter = 0
                                for region in regions:
                                    token_count = self.chunker.count_tokens(region.content)
                                    if token_count > self.chunker.max_tokens * 1.5:
                                        sub_chunks = self.chunker.chunk_file(region.content, language)
                                        for sub_chunk in sub_chunks:
                                            db_chunk = CodeChunk(
                                                repo_id=repo_id,
                                                file_id=db_file.file_id,
                                                chunk_index=chunk_counter,
                                                content=sub_chunk.content,
                                                start_line=region.start_line + sub_chunk.start_line - 1,
                                                end_line=region.start_line + sub_chunk.end_line - 1,
                                                chunk_type=region.region_type,
                                                language=language,
                                                token_count=sub_chunk.token_count,
                                            )
                                            if region.symbols:
                                                db_chunk.set_symbol_names(region.symbols)
                                            enriched = enrich_chunk_for_embedding(
                                                sub_chunk.content, file_path,
                                                region.start_line + sub_chunk.start_line - 1,
                                                region.start_line + sub_chunk.end_line - 1,
                                                extracted_symbols, content, language,
                                            )
                                            session.add(db_chunk)
                                            chunks_to_embed.append((db_chunk, enriched))
                                            chunk_counter += 1
                                    else:
                                        db_chunk = CodeChunk(
                                            repo_id=repo_id,
                                            file_id=db_file.file_id,
                                            chunk_index=chunk_counter,
                                            content=region.content,
                                            start_line=region.start_line,
                                            end_line=region.end_line,
                                            chunk_type=region.region_type,
                                            language=language,
                                            token_count=token_count,
                                        )
                                        if region.symbols:
                                            db_chunk.set_symbol_names(region.symbols)
                                        enriched = enrich_chunk_for_embedding(
                                            region.content, file_path,
                                            region.start_line, region.end_line,
                                            extracted_symbols, content, language,
                                        )
                                        session.add(db_chunk)
                                        chunks_to_embed.append((db_chunk, enriched))
                                        chunk_counter += 1
                                use_ast_chunking = True
                        except Exception:
                            use_ast_chunking = False
                except Exception:
                    pass

            if not use_ast_chunking:
                chunks = self.chunker.chunk_file(
                    content, language,
                    symbol_boundaries=symbol_boundaries or None,
                )
                for idx, chunk in enumerate(chunks):
                    db_chunk = CodeChunk(
                        repo_id=repo_id,
                        file_id=db_file.file_id,
                        chunk_index=idx,
                        content=chunk.content,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        chunk_type=chunk.chunk_type,
                        language=language,
                        token_count=chunk.token_count,
                    )
                    session.add(db_chunk)
                    enriched = enrich_chunk_for_embedding(
                        chunk.content, file_path,
                        chunk.start_line, chunk.end_line,
                        extracted_symbols, content, language,
                    )
                    chunks_to_embed.append((db_chunk, enriched))

        # Flush all new chunks + symbols
        session.flush()

        # 5. Generate embeddings for new chunks only
        if chunks_to_embed:
            report_progress(
                "generating_embeddings",
                f"Generating embeddings for {len(chunks_to_embed)} new chunks...",
                70,
            )
            contents = [c[1] for c in chunks_to_embed]
            batch_size = self.embedding_generator.batch_size
            total_batches = (len(contents) + batch_size - 1) // batch_size
            all_embeddings = []

            for batch_idx in range(0, len(contents), batch_size):
                batch = contents[batch_idx : batch_idx + batch_size]
                batch_embeddings = self.embedding_generator.generate(batch)
                all_embeddings.append(batch_embeddings)

                batch_num = batch_idx // batch_size + 1
                pct = 70 + (batch_num / total_batches) * 20
                report_progress(
                    "generating_embeddings",
                    f"Embedding batch {batch_num}/{total_batches}...",
                    pct,
                )

            embeddings = np.vstack(all_embeddings)
            chunk_ids = [db_chunk.chunk_id for db_chunk, _ in chunks_to_embed]
            self.vector_store.add(
                embeddings=embeddings,
                chunk_ids=chunk_ids,
                repo_id=repo_id,
                session=session,
            )

        # 6. Update repo metadata (same repo_id!)
        diff_stats = {
            "added": len(added),
            "modified": len(modified),
            "deleted": len(deleted),
            "unchanged": total_files - len(added) - len(modified),
        }
        existing.commit_sha = new_commit_sha
        existing.last_diff_stats = diff_stats
        existing.embedding_model = self.embedding_generator.model_name

        # Recalculate stats
        existing.files_count = (
            session.query(RepositoryFile)
            .filter(RepositoryFile.repo_id == repo_id)
            .count()
        )
        existing.chunks_count = (
            session.query(CodeChunk)
            .filter(CodeChunk.repo_id == repo_id)
            .count()
        )
        existing.symbols_count = (
            session.query(Symbol)
            .filter(Symbol.repo_id == repo_id)
            .count()
        )

        logger.info(
            "Diff-aware re-index complete",
            repo_id=repo_id,
            diff_stats=diff_stats,
            new_chunks=len(chunks_to_embed),
            new_symbols=total_new_symbols,
        )

        return {
            "repo_id": str(repo_id),
            "files_count": existing.files_count,
            "chunks_count": existing.chunks_count,
            "symbols_count": existing.symbols_count,
            "diff_stats": diff_stats,
        }

    def _index_files(
        self,
        session: Session,
        url: str,
        owner: str,
        name: str,
        branch: str,
        commit_sha: str,
        repo_path: Path,
        files: list[dict],
        user_id: str | None = None,
        is_public: bool = True,
        progress_callback: Callable | None = None,
        deep_index: bool = False,
    ) -> dict:
        """Index files from a repository.

        Extracts symbols using tree-sitter when available, and uses
        AST-aware chunking for supported languages.
        
        Args:
            session: Database session
            url: Repository URL
            owner: Repository owner
            name: Repository name
            branch: Branch name
            commit_sha: Commit SHA
            repo_path: Local path to cloned repo
            files: List of file info dicts
            user_id: User ID of who indexed (for private repos, this is the owner)
            is_public: Whether the repo is publicly accessible
        
        Returns:
            Dict with indexing stats
        """
        logger.info(
            "Starting _index_files",
            owner=owner, name=name, files=len(files),
        )

        # Disable statement timeout for indexing operations.
        # Large repos (pytorch, numpy) can have 30k+ files generating thousands of
        # INSERTs, flushes, and unique constraint checks that exceed any fixed timeout.
        # Indexing is authenticated and rate-limited, so runaway queries aren't a concern.
        # The Gunicorn worker timeout (300s) provides an outer safety net.
        session.execute(text("SET LOCAL statement_timeout = '0'"))
        session.execute(text("SET LOCAL idle_in_transaction_session_timeout = '0'"))
        logger.info("Statement and idle-in-transaction timeouts disabled for indexing")

        # Reuse existing repository record if one exists (force reindex case),
        # otherwise create a new one.
        repo = session.query(Repository).filter(
            Repository.url == url,
            Repository.branch == branch,
        ).first()

        if repo:
            # Update existing record
            repo.commit_sha = commit_sha
            repo.local_path = str(repo_path)
            if deep_index:
                repo.deep_indexed = True
            session.flush()
            logger.info("Reusing existing repository record", repo_id=repo.repo_id)
        else:
            repo = Repository(
                url=url,
                owner=owner,
                name=name,
                branch=branch,
                commit_sha=commit_sha,
                local_path=str(repo_path),
                indexed_by=user_id,
                is_public=is_public,
                deep_indexed=deep_index,
            )
            session.add(repo)
            logger.info("Flushing repository record to get repo_id")
            session.flush()  # Get repo_id
            logger.info("Repository record created", repo_id=repo.repo_id)
        
        # Get parser registry for symbol extraction
        parser_registry = get_parser_registry()
        
        # Track stats
        total_lines = 0
        total_tokens = 0
        total_symbols = 0
        language_lines: Counter = Counter()
        chunks_to_embed: list[tuple[CodeChunk, str]] = []  # (db_chunk, content)
        
        def report_progress(stage: str, message: str, progress: float = 0, **kwargs):
            """Report progress if callback is provided."""
            if progress_callback:
                with contextlib.suppress(Exception):
                    progress_callback(stage, message, progress, **kwargs)
        
        total_files = len(files)

        # OPTIMIZATION: Batch flush interval - flush every N files instead of every file
        # Larger batches = fewer DB round-trips
        # 500 files per flush: numpy (1430 files) = 3 flushes instead of 14
        FLUSH_BATCH_SIZE = 500

        # Track files in current batch for chunk processing after batch flush
        current_batch_files: list[tuple[RepositoryFile, dict, str]] = []  # (db_file, file_info, content)

        # ── Embedding pipeline: overlap file processing with embedding generation ──
        # Producer (main thread): chunks files, flushes to DB, enqueues texts
        # Consumer (embed thread): model.encode() releases GIL → true parallelism
        # The main thread also drains completed embeddings → pgvector between batches,
        # keeping the DB session active (prevents idle_in_transaction_session_timeout).
        embed_q: _queue.Queue = _queue.Queue()  # unbounded — items are just text strings (~128KB each)
        embed_results: _queue.Queue = _queue.Queue()
        embed_error: list[Exception] = []
        embed_batch_counter = 0
        embed_batches_written = 0
        last_enqueued_idx = 0  # tracks which chunks_to_embed entries have been enqueued

        def _embedding_worker():
            """Background thread: pull text batches from queue, generate embeddings."""
            try:
                while True:
                    item = embed_q.get()
                    if item is None:
                        break  # poison pill
                    batch_num, chunk_ids, texts = item
                    embeddings = self.embedding_generator.generate(texts)
                    embed_results.put((batch_num, chunk_ids, embeddings))
                    report_progress(
                        "generating_embeddings",
                        f"Embedding batch {batch_num}...",
                        min(90, 72 + batch_num * 0.3),
                        embedding_batch=batch_num,
                    )
            except Exception as e:
                embed_error.append(e)

        def _drain_embed_results():
            """Drain completed embeddings from result queue → pgvector.

            Called from the main thread between file batches to keep the
            DB session active and write embeddings progressively.
            """
            nonlocal embed_batches_written
            while not embed_results.empty():
                try:
                    batch_num, chunk_ids, embeddings = embed_results.get_nowait()
                except _queue.Empty:
                    break
                self.vector_store.add(
                    embeddings=embeddings,
                    chunk_ids=chunk_ids,
                    repo_id=repo.repo_id,
                    session=session,
                )
                embed_batches_written += 1
                logger.debug(
                    "Wrote embedding batch to pgvector",
                    batch_num=batch_num,
                    chunks=len(chunk_ids),
                    total_written=embed_batches_written,
                )

        embed_thread = _threading.Thread(
            target=_embedding_worker, daemon=True, name="embed-pipeline"
        )
        embed_thread.start()

        log_interval = max(1, total_files // 20)  # Log ~20 times during processing
        for file_idx, file_info in enumerate(files):
            file_path = file_info["path"]
            content = file_info.get("content", "")

            # Log progress periodically so we can see the loop is alive
            if (file_idx + 1) % log_interval == 0:
                logger.info(
                    "Processing files",
                    progress=f"{file_idx + 1}/{total_files}",
                    chunks_so_far=len(chunks_to_embed),
                )

            # Progress indicator — report frequently so the SSE stream stays alive.
            # Every 25 files (or at least every 10% of total) keeps the bar moving.
            report_interval = max(1, min(25, total_files // 10))
            if (file_idx + 1) % report_interval == 0 or file_idx == total_files - 1:
                file_progress = ((file_idx + 1) / total_files) * 100
                # Report progress: 40-70% is file processing range
                overall_progress = 40 + (file_progress * 0.3)
                report_progress(
                    "processing_files",
                    f"Processing {file_idx + 1}/{total_files} files...",
                    overall_progress,
                    files_processed=file_idx + 1,
                    total_files=total_files,
                )

            if not content:
                continue

            # Detect language
            language = detect_language(file_path)

            # Create file record
            db_file = RepositoryFile(
                repo_id=repo.repo_id,
                file_path=file_path,
                file_name=Path(file_path).name,
                language=language,
                line_count=content.count("\n") + 1,
                token_count=self.chunker.count_tokens(content),
                size_bytes=file_info["size_bytes"],
                content_hash=self.chunker.compute_hash(content),
            )
            session.add(db_file)

            # Track stats
            total_lines += db_file.line_count
            total_tokens += db_file.token_count
            if language:
                language_lines[language] += db_file.line_count

            # Add to batch for processing after flush
            current_batch_files.append((db_file, file_info, content))

            # OPTIMIZATION: Batch flush - flush files, then process chunks for the batch
            # This reduces database round-trips while ensuring file_id is set before chunks
            should_flush = (file_idx + 1) % FLUSH_BATCH_SIZE == 0 or file_idx == total_files - 1
            if should_flush:
                # Drain any completed embeddings before flushing — gives the
                # embed thread the full file-processing window to finish batches
                _drain_embed_results()

                batch_num = (file_idx + 1) // FLUSH_BATCH_SIZE or 1
                total_batches = (total_files + FLUSH_BATCH_SIZE - 1) // FLUSH_BATCH_SIZE
                logger.info(
                    "Flushing file batch to DB",
                    batch=f"{batch_num}/{total_batches}",
                    files_in_batch=len(current_batch_files),
                    files_done=file_idx + 1,
                    total_files=total_files,
                )
                flush_start = time.time()
                # Flush files to get file_id values
                session.flush()
                logger.info(
                    "File batch flushed",
                    batch=f"{batch_num}/{total_batches}",
                    flush_ms=round((time.time() - flush_start) * 1000),
                )

                # Now process chunks for all files in this batch
                for db_file, file_info, content in current_batch_files:
                    file_path = file_info["path"]
                    language = db_file.language

                    # Documentation files (markdown, rst) — paragraph-based chunking
                    is_doc_file = language in ("markdown", "restructuredtext") or (
                        file_path.lower().endswith((".md", ".mdx", ".rst"))
                    )

                    if is_doc_file:
                        chunks = self.chunker.chunk_file(content, language)
                        for idx, chunk in enumerate(chunks):
                            db_chunk = CodeChunk(
                                repo_id=repo.repo_id,
                                file_id=db_file.file_id,
                                chunk_index=idx,
                                content=chunk.content,
                                start_line=chunk.start_line,
                                end_line=chunk.end_line,
                                chunk_type="documentation",
                                language=language,
                                token_count=chunk.token_count,
                            )
                            session.add(db_chunk)
                            enriched = enrich_doc_chunk_for_embedding(
                                chunk.content, file_path,
                            )
                            chunks_to_embed.append((db_chunk, enriched))
                        continue

                    # Deep index disables turbo mode for full AST chunking
                    turbo_mode = False if deep_index else self.config.git.turbo_mode
                    parser = parser_registry.get_parser(language) if language else None

                    use_ast_chunking = False
                    symbol_boundaries: list[tuple[int, int]] = []
                    extracted_symbols: list = []

                    # Extract symbols if parser is available (always extract symbols, even in turbo mode)
                    if parser:
                        try:
                            extracted_symbols = parser.extract_symbols(content)

                            # Collect top-level symbol boundaries for boundary-aware chunking
                            for ext_sym in extracted_symbols:
                                symbol_boundaries.append((ext_sym.start_line, ext_sym.end_line))

                            for ext_sym in extracted_symbols:
                                db_symbol = Symbol(
                                    repo_id=repo.repo_id,
                                    file_id=db_file.file_id,
                                    name=ext_sym.name,
                                    qualified_name=ext_sym.qualified_name,
                                    symbol_type=ext_sym.symbol_type,
                                    signature=ext_sym.signature,
                                    docstring=ext_sym.docstring,
                                    start_line=ext_sym.start_line,
                                    end_line=ext_sym.end_line,
                                    is_exported=ext_sym.is_exported,
                                    is_async=ext_sym.is_async,
                                    language=language,
                                )
                                if ext_sym.parameters:
                                    db_symbol.set_parameters(ext_sym.parameters)
                                if ext_sym.return_type:
                                    db_symbol.return_type = ext_sym.return_type
                                if ext_sym.decorators:
                                    db_symbol.set_decorators(ext_sym.decorators)
                                session.add(db_symbol)
                                total_symbols += 1

                            # Try AST-aware chunking (skip in turbo mode for speed)
                            # Collect chunks first, only commit on success
                            if not turbo_mode:
                                try:
                                    regions = parser.create_code_regions(content)
                                    if regions:
                                        # Collect chunks temporarily, using running counter for indices
                                        temp_chunks = []
                                        chunk_counter = 0
                                        for region in regions:
                                            token_count = self.chunker.count_tokens(region.content)

                                            # If region is too large, fall back to line-based for this region
                                            if token_count > self.chunker.max_tokens * 1.5:
                                                # Chunk this large region with line-based chunker
                                                sub_chunks = self.chunker.chunk_file(region.content, language)
                                                for sub_chunk in sub_chunks:
                                                    db_chunk = CodeChunk(
                                                        repo_id=repo.repo_id,
                                                        file_id=db_file.file_id,
                                                        chunk_index=chunk_counter,
                                                        content=sub_chunk.content,
                                                        start_line=region.start_line + sub_chunk.start_line - 1,
                                                        end_line=region.start_line + sub_chunk.end_line - 1,
                                                        chunk_type=region.region_type,
                                                        language=language,
                                                        token_count=sub_chunk.token_count,
                                                    )
                                                    if region.symbols:
                                                        db_chunk.set_symbol_names(region.symbols)
                                                    enriched = enrich_chunk_for_embedding(
                                                        sub_chunk.content, file_path,
                                                        region.start_line + sub_chunk.start_line - 1,
                                                        region.start_line + sub_chunk.end_line - 1,
                                                        extracted_symbols, content, language,
                                                    )
                                                    temp_chunks.append((db_chunk, enriched))
                                                    chunk_counter += 1
                                            else:
                                                db_chunk = CodeChunk(
                                                    repo_id=repo.repo_id,
                                                    file_id=db_file.file_id,
                                                    chunk_index=chunk_counter,
                                                    content=region.content,
                                                    start_line=region.start_line,
                                                    end_line=region.end_line,
                                                    chunk_type=region.region_type,
                                                    language=language,
                                                    token_count=token_count,
                                                )
                                                if region.symbols:
                                                    db_chunk.set_symbol_names(region.symbols)
                                                enriched = enrich_chunk_for_embedding(
                                                    region.content, file_path,
                                                    region.start_line, region.end_line,
                                                    extracted_symbols, content, language,
                                                )
                                                temp_chunks.append((db_chunk, enriched))
                                                chunk_counter += 1

                                        # All chunks created successfully - commit them
                                        use_ast_chunking = True
                                        for db_chunk, content in temp_chunks:
                                            session.add(db_chunk)
                                            chunks_to_embed.append((db_chunk, content))
                                except Exception as e:
                                    logger.debug(
                                        "AST chunking failed, using line-based",
                                        file=file_path,
                                        error=str(e),
                                    )
                                    use_ast_chunking = False

                        except Exception as e:
                            logger.debug(
                                "Symbol extraction failed",
                                file=file_path,
                                error=str(e),
                            )

                    # Fall back to line-based chunking if no parser or AST chunking failed
                    # Pass symbol boundaries so the chunker prefers splitting at
                    # function/class boundaries instead of arbitrary lines.
                    if not use_ast_chunking:
                        chunks = self.chunker.chunk_file(
                            content, language,
                            symbol_boundaries=symbol_boundaries or None,
                        )

                        for idx, chunk in enumerate(chunks):
                            db_chunk = CodeChunk(
                                repo_id=repo.repo_id,
                                file_id=db_file.file_id,
                                chunk_index=idx,
                                content=chunk.content,
                                start_line=chunk.start_line,
                                end_line=chunk.end_line,
                                chunk_type=chunk.chunk_type,
                                language=language,
                                token_count=chunk.token_count,
                            )
                            session.add(db_chunk)
                            enriched = enrich_chunk_for_embedding(
                                chunk.content, file_path,
                                chunk.start_line, chunk.end_line,
                                extracted_symbols, content, language,
                            )
                            chunks_to_embed.append((db_chunk, enriched))

                # Flush chunks/symbols created for this batch immediately
                # instead of accumulating everything for one massive flush at the end.
                # This keeps memory bounded and avoids a single giant INSERT.
                logger.info(
                    "Flushing chunks/symbols for batch",
                    batch=f"{batch_num}/{total_batches}",
                    chunks_so_far=len(chunks_to_embed),
                    symbols_so_far=total_symbols,
                )
                chunk_flush_start = time.time()
                session.flush()
                logger.info(
                    "Chunks/symbols flushed",
                    batch=f"{batch_num}/{total_batches}",
                    flush_ms=round((time.time() - chunk_flush_start) * 1000),
                )

                # ── Enqueue newly-flushed chunks for background embedding ──
                # chunk_ids are now available after flush
                new_chunks = chunks_to_embed[last_enqueued_idx:]
                if new_chunks:
                    # Read current batch_size each time — it may shrink after CUDA OOM recovery
                    cur_embed_batch = self.embedding_generator.batch_size
                    for i in range(0, len(new_chunks), cur_embed_batch):
                        batch_slice = new_chunks[i : i + cur_embed_batch]
                        embed_batch_counter += 1
                        chunk_ids = [c[0].chunk_id for c in batch_slice]
                        texts = [c[1] for c in batch_slice]
                        embed_q.put((embed_batch_counter, chunk_ids, texts))
                    last_enqueued_idx = len(chunks_to_embed)
                    logger.info(
                        "Enqueued chunks for embedding",
                        new_chunks=len(new_chunks),
                        embed_batches_queued=embed_batch_counter,
                    )

                # ── Progressive drain: write completed embeddings to pgvector ──
                # This keeps the DB session active, preventing connection timeouts
                _drain_embed_results()

                # Clear batch after processing
                current_batch_files = []
        
        report_progress(
            "files_done",
            f"Processed {total_files} files → {len(chunks_to_embed)} chunks",
            70,
            files_processed=total_files,
            chunks_created=len(chunks_to_embed),
        )

        # ── Pipeline drain: wait for embedding thread, write remaining to pgvector ──
        embed_q.put(None)  # poison pill
        embed_thread.join()

        if embed_error:
            raise embed_error[0]

        # Write any remaining embeddings that completed after the last drain
        _drain_embed_results()

        if chunks_to_embed:
            report_progress("embeddings_done", "Embeddings generated!", 90)
            logger.info(
                "All embeddings written to pgvector",
                total_chunks=len(chunks_to_embed),
                embed_batches_produced=embed_batch_counter,
                embed_batches_written=embed_batches_written,
            )
        
        # NOTE: Chunk relationships are built AFTER commit in index_repository()
        # to avoid risking the main transaction on a non-critical operation.

        # Calculate language percentages
        total_lang_lines = sum(language_lines.values())
        if total_lang_lines > 0:
            languages = {
                lang: (count / total_lang_lines) * 100
                for lang, count in language_lines.most_common()
            }
        else:
            languages = {}
        
        # Update repository stats
        repo.files_count = len(files)
        repo.chunks_count = len(chunks_to_embed)
        repo.symbols_count = total_symbols
        repo.total_lines = total_lines
        repo.total_tokens = total_tokens
        repo.set_languages(languages)
        repo.embedding_model = self.embedding_generator.model_name
        if deep_index:
            repo.deep_indexed = True

        # NOTE: Do NOT commit here - let the outer transaction handle the commit
        # This ensures atomicity: if the server crashes before user_repositories
        # is created, the entire indexing operation rolls back (no orphaned repos)

        logger.info(
            "Indexed repository",
            repo_id=repo.repo_id,
            files=repo.files_count,
            chunks=repo.chunks_count,
            symbols=total_symbols,
            lines=total_lines,
        )

        return {
            "repo_id": str(repo.repo_id),
            "files_count": repo.files_count,
            "chunks_count": repo.chunks_count,
            "symbols_count": total_symbols,
            "total_lines": total_lines,
            "total_tokens": total_tokens,
            "languages": languages,
        }

    def delete_repository(self, repo_id: str, user_id: str | None = None) -> dict:
        """Delete a repository from the index.

        NEW BEHAVIOR:
        - Public repos: Just remove from YOUR collection (unmap only)
        - Private repos: Only the indexer can fully delete the data

        Args:
            repo_id: Repository ID
            user_id: User ID for authorization

        Returns:
            Dict with deletion results
        """
        effective_user_id = user_id or self.user_id

        if not effective_user_id:
            return {
                "success": False,
                "error": "Authentication required",
                "message": "You must be authenticated to delete repositories",
            }

        with get_session() as session:
            repo = session.query(Repository).filter(
                Repository.repo_id == repo_id
            ).first()

            if not repo:
                logger.warning(
                    "Delete failed: repository not found",
                    repo_id=repo_id,
                    user_id=effective_user_id,
                )
                return {
                    "success": False,
                    "error": "Repository not found",
                    "message": f"Repository '{repo_id}' not found. It may have been deleted or indexing failed.",
                }

            # NEW LOGIC: Public repos should only be unmapped, not deleted
            if repo.is_public:
                # Just remove from user's collection
                return self.remove_from_collection(repo_id, effective_user_id)

            # PRIVATE REPO: Check authorization and actually delete
            if not repo.can_user_delete(effective_user_id):
                logger.warning(
                    "Delete authorization failed",
                    repo_id=repo_id,
                    repo_indexed_by=repo.indexed_by,
                    requesting_user=effective_user_id,
                )
                return {
                    "success": False,
                    "error": "Not authorized",
                    "message": "Only the user who indexed this private repository can delete it.",
                }

            owner = repo.owner
            name = repo.name
            branch = repo.branch
            files_count = repo.files_count
            chunks_count = repo.chunks_count

            # Bulk-delete child tables with raw SQL (much faster than ORM
            # cascade over a network connection — avoids loading every row
            # into Python and issuing individual DELETEs).
            from sqlalchemy import text
            session.execute(text("DELETE FROM chunk_embeddings WHERE repo_id = :rid"), {"rid": repo_id})
            session.execute(text("DELETE FROM symbols WHERE repo_id = :rid"), {"rid": repo_id})
            session.execute(text("DELETE FROM code_chunks WHERE repo_id = :rid"), {"rid": repo_id})
            session.execute(text("DELETE FROM repository_files WHERE repo_id = :rid"), {"rid": repo_id})
            session.execute(text("DELETE FROM user_repositories WHERE repo_id = :rid"), {"rid": repo_id})
            session.execute(text("DELETE FROM repositories WHERE repo_id = :rid"), {"rid": repo_id})
            session.commit()

            # Delete local clone (if exists)
            self.git_client.delete_repo(owner, name, branch)

            logger.info(
                "Deleted private repository",
                repo_id=repo_id,
                owner=owner,
                name=name,
                user_id=effective_user_id,
            )

            return {
                "success": True,
                "repo_id": repo_id,
                "files_deleted": files_count,
                "chunks_deleted": chunks_count,
                "message": "Private repository deleted successfully",
            }
    
    def remove_from_collection(self, repo_id: str, user_id: str | None = None) -> dict:
        """Remove a repository from user's collection without deleting it.

        For public repos, this just removes the link to the user's collection.
        The actual data remains for other users.

        Args:
            repo_id: Repository ID
            user_id: User ID

        Returns:
            Dict with removal results
        """
        effective_user_id = user_id or self.user_id

        if not effective_user_id:
            return {
                "success": False,
                "error": "Authentication required",
                "message": "You must be authenticated",
            }

        with get_session() as session:
            user_repo = session.query(UserRepository).filter(
                UserRepository.user_id == effective_user_id,
                UserRepository.repo_id == repo_id,
            ).first()

            if not user_repo:
                return {
                    "success": True,
                    "repo_id": repo_id,
                    "repo_name": "unknown",
                    "message": "Repository is not in your collection (already removed)",
                }

            # Get repo info for response
            repo = session.query(Repository).filter(
                Repository.repo_id == repo_id
            ).first()

            is_public = repo.is_public if repo else False
            repo_name = f"{repo.owner}/{repo.name}" if repo else "unknown"

            # Remove from collection
            session.delete(user_repo)
            session.commit()

            logger.info(
                "Removed repo from user collection",
                repo_id=repo_id,
                repo_name=repo_name,
                user_id=effective_user_id,
                is_public=is_public,
            )

            message = "Repository removed from your collection"
            if is_public:
                message += " (data preserved for other users)"

            return {
                "success": True,
                "repo_id": repo_id,
                "repo_name": repo_name,
                "message": message,
            }

    def list_repositories(
        self,
        limit: int = 50,
        offset: int = 0,
        user_id: str | None = None,
    ) -> dict:
        """List repositories in user's collection.
        
        Returns repos that the user has added to their collection,
        including both:
        - Repos they indexed themselves
        - Public repos they've added (indexed by others)
        
        Args:
            limit: Max repositories to return
            offset: Pagination offset
            user_id: User ID for multi-tenant filtering
            
        Returns:
            Dict with repository list
        """
        effective_user_id = user_id or self.user_id
        
        if not effective_user_id:
            return {
                "success": False,
                "error": "Authentication required",
                "repositories": [],
                "total": 0,
            }
        
        with get_session() as session:
            # Join with user_repositories to get user's collection
            query = session.query(Repository, UserRepository).join(
                UserRepository,
                Repository.repo_id == UserRepository.repo_id
            ).filter(
                UserRepository.user_id == effective_user_id
            )
            
            total = query.count()
            
            results = query.order_by(
                UserRepository.added_at.desc()
            ).offset(offset).limit(limit).all()
            
            return {
                "success": True,
                "repositories": [
                    {
                        "repo_id": str(r.repo_id),
                        "owner": r.owner,
                        "name": r.name,
                        "url": r.url,
                        "branch": r.branch,
                        "commit_sha": r.commit_sha,
                        "indexed_at": r.indexed_at.isoformat() if r.indexed_at else None,
                        "files_count": r.files_count,
                        "chunks_count": r.chunks_count,
                        "languages": r.get_languages(),
                        # New fields for deduplication awareness
                        "is_public": r.is_public,
                        "is_owner": r.indexed_by == effective_user_id,
                        "added_at": ur.added_at.isoformat() if ur.added_at else None,
                        "is_favorite": ur.is_favorite,
                        "deep_indexed": getattr(r, "deep_indexed", False),
                    }
                    for r, ur in results
                ],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    def get_repository(self, repo_id: str, user_id: str | None = None) -> dict:
        """Get repository details.
        
        ACCESS RULES:
        - Public repos: Anyone with the repo in their collection
        - Private repos: Only the indexer
        
        Args:
            repo_id: Repository ID
            user_id: User ID for authorization
            
        Returns:
            Dict with repository details
        """
        effective_user_id = user_id or self.user_id
        
        with get_session() as session:
            repo = session.query(Repository).filter(
                Repository.repo_id == repo_id
            ).first()
            
            if not repo:
                return {
                    "success": False,
                    "error": "Repository not found",
                    "message": f"Repository with ID '{repo_id}' not found",
                }
            
            # Check access
            if not repo.can_user_access(effective_user_id):
                return {
                    "success": False,
                    "error": "Access denied",
                    "message": "You don't have access to this private repository",
                }
            
            # Check if in user's collection
            user_repo = None
            if effective_user_id:
                user_repo = session.query(UserRepository).filter(
                    UserRepository.user_id == effective_user_id,
                    UserRepository.repo_id == repo_id,
                ).first()
            
            return {
                "success": True,
                "repo_id": str(repo.repo_id),
                "owner": repo.owner,
                "name": repo.name,
                "url": repo.url,
                "branch": repo.branch,
                "commit_sha": repo.commit_sha,
                "indexed_at": repo.indexed_at.isoformat() if repo.indexed_at else None,
                "stats": {
                    "files_count": repo.files_count,
                    "chunks_count": repo.chunks_count,
                    "symbols_count": repo.symbols_count,
                    "total_lines": repo.total_lines,
                    "total_tokens": repo.total_tokens,
                },
                "languages": repo.get_languages(),
                # New fields for deduplication awareness
                "is_public": repo.is_public,
                "is_owner": repo.indexed_by == effective_user_id,
                "in_collection": user_repo is not None,
                "is_favorite": user_repo.is_favorite if user_repo else False,
            }
