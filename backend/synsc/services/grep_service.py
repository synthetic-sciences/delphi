"""Regex search within a single indexed source.

Supports source_type in {'repo', 'paper'}. For repos we prefer the on-disk
clone (fast); fall back to reconstruction from chunks. For papers we match
against paper_chunks.content with section_title as the synthetic path.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import structlog
from sqlalchemy.orm import Session

from synsc.database.connection import get_session
from synsc.database.models import CodeChunk, Repository, RepositoryFile

logger = structlog.get_logger(__name__)

_DEFAULT_MAX_MATCHES = 100
_DEFAULT_CONTEXT_LINES = 2


class GrepService:
    """Regex search within one indexed source."""

    def grep_source(
        self,
        source_id: str,
        source_type: str,
        pattern: str,
        path_prefix: str | None = None,
        max_matches: int = _DEFAULT_MAX_MATCHES,
        context_lines: int = _DEFAULT_CONTEXT_LINES,
        user_id: str | None = None,
    ) -> list[dict]:
        try:
            regex = re.compile(pattern)
        except re.error as e:
            raise ValueError(f"invalid regex: {e}") from e

        matches: list[dict] = []
        for path, content in self._iter_source_files(
            source_id=source_id,
            source_type=source_type,
            user_id=user_id,
        ):
            if path_prefix and not path.startswith(path_prefix):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if regex.search(line):
                    lo = max(0, idx - context_lines)
                    hi = min(len(lines), idx + context_lines + 1)
                    matches.append(
                        {
                            "path": path,
                            "line_no": idx + 1,
                            "line": line,
                            "context_before": lines[lo:idx],
                            "context_after": lines[idx + 1 : hi],
                        }
                    )
                    if len(matches) >= max_matches:
                        return matches
        return matches

    def _iter_source_files(
        self,
        source_id: str,
        source_type: str,
        user_id: str | None,
    ) -> Iterator[tuple[str, str]]:
        if source_type == "repo":
            yield from self._iter_repo_files(source_id, user_id)
        elif source_type == "paper":
            yield from self._iter_paper_sections(source_id, user_id)
        else:
            raise ValueError(f"unsupported source_type for grep: {source_type}")

    def _iter_repo_files(
        self, repo_id: str, user_id: str | None
    ) -> Iterator[tuple[str, str]]:
        with get_session() as session:
            repo = (
                session.query(Repository).filter(Repository.repo_id == repo_id).first()
            )
            if not repo or not repo.can_user_access(user_id):
                return

            if repo.local_path and Path(repo.local_path).exists():
                files = (
                    session.query(RepositoryFile)
                    .filter(RepositoryFile.repo_id == repo_id)
                    .all()
                )
                for f in files:
                    p = Path(repo.local_path) / f.file_path
                    if not p.exists():
                        continue
                    try:
                        yield f.file_path, p.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                return

            # Fallback: reconstruct from chunks.
            files = (
                session.query(RepositoryFile)
                .filter(RepositoryFile.repo_id == repo_id)
                .all()
            )
            for f in files:
                content = self._reconstruct_file(session, f.file_id)
                if content is not None:
                    yield f.file_path, content

    @staticmethod
    def _reconstruct_file(session: Session, file_id: str) -> str | None:
        chunks = (
            session.query(CodeChunk)
            .filter(CodeChunk.file_id == file_id)
            .order_by(CodeChunk.chunk_index)
            .all()
        )
        if not chunks:
            return None
        parts: list[str] = []
        last_end = 0
        for c in chunks:
            if c.start_line > last_end:
                parts.append(c.content)
            else:
                lines = c.content.split("\n")
                skip = last_end - c.start_line + 1
                if skip < len(lines):
                    parts.append("\n".join(lines[skip:]))
            last_end = c.end_line
        return "\n".join(parts)

    def _iter_paper_sections(
        self, paper_id: str, user_id: str | None
    ) -> Iterator[tuple[str, str]]:
        if not user_id:
            return
        from synsc.services.paper_service import PaperService

        svc = PaperService(user_id=user_id)
        paper = svc.get_paper(paper_id)
        if not paper:
            return
        for chunk in paper.get("chunks", []):
            path = chunk.get("section_title") or f"chunk_{chunk.get('chunk_index')}"
            yield path, chunk.get("content", "")
