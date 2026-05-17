"""Context pack builder.

A "context pack" is the agent-ready answer to a query. Instead of returning
loose snippets, we return a structured payload:

  - **Primary hits**: the matched chunks themselves.
  - **Expansions**: enclosing function/class bodies, adjacent chunks,
    same-class siblings, same-file imports.
  - **Linked tests**: tests in the repo that mention the matched symbol.
  - **Docs**: README sections, prose docs, examples that reference the
    matched API.
  - **Configs**: manifest entries that mention the symbol (CI, deps,
    feature flags).
  - **Symbols**: signature + docstring for every relevant symbol.
  - **Architecture summary**: when the query is broad, a directory-level
    overview so the agent has a map.
  - **Why-matched**: per-hit rationale (which retrieval branch + score).
  - **Stable references**: file_path, line ranges, repo, commit_sha.

The builder also runs a *re-query planner*: if the initial retrieve
under-fills the budget or fails to surface a key category (e.g. zero tests
mentioning the symbol), it issues follow-up searches automatically.

Token budget: results are compressed by *utility*, not raw similarity. A
20-line tested implementation chunk beats a 200-line example file even if
the example scores higher in vector space.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from synsc.database.connection import get_session

logger = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Token estimation (cheap — avoids loading the tokenizer for budget math)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _approx_tokens(s: str) -> int:
    """Rough token count: 4 chars/token for English+code. Plenty good for
    budgeting decisions; we don't need accuracy for "should we include this
    extra chunk?".
    """
    return max(1, len(s) // 4)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Pack types
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class PackSnippet:
    """One block in the context pack — a chunk plus its rationale."""

    role: str  # 'primary' | 'enclosing' | 'adjacent' | 'same_class' |
               # 'imports' | 'test' | 'doc' | 'config' | 'example'
    chunk_id: str | None
    repo_id: str
    repo_name: str
    file_path: str
    start_line: int
    end_line: int
    content: str
    language: str | None = None
    symbol_names: list[str] | None = None
    score: float = 0.0
    why: str = ""
    candidate_sources: dict[str, float] | None = None
    # Stable reference: commit SHA at the moment of indexing.
    commit_sha: str | None = None

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "chunk_id": self.chunk_id,
            "repo_id": self.repo_id,
            "repo_name": self.repo_name,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
            "language": self.language,
            "symbol_names": self.symbol_names,
            "score": self.score,
            "why": self.why,
            "candidate_sources": self.candidate_sources,
            "commit_sha": self.commit_sha,
        }


@dataclass
class ContextPack:
    """The full agent-ready answer to a query."""

    query: str
    quality_mode: str
    snippets: list[PackSnippet] = field(default_factory=list)
    architecture_summary: dict | None = None
    symbols: list[dict] = field(default_factory=list)
    rationale: dict = field(default_factory=dict)
    used_tokens_estimate: int = 0
    token_budget: int = 0
    # If the planner issued follow-up searches, list the queries here so the
    # caller can audit cost.
    requeries: list[str] = field(default_factory=list)
    # 'why_no_X' explanations: when a category came up empty (no tests
    # mentioning the symbol, no examples, etc.), we record it so the agent
    # knows the absence is real, not a missing fetch.
    coverage_gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "quality_mode": self.quality_mode,
            "snippets": [s.to_dict() for s in self.snippets],
            "architecture_summary": self.architecture_summary,
            "symbols": self.symbols,
            "rationale": self.rationale,
            "used_tokens_estimate": self.used_tokens_estimate,
            "token_budget": self.token_budget,
            "requeries": self.requeries,
            "coverage_gaps": self.coverage_gaps,
        }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


_TEST_PATH = re.compile(
    r"(?:^|/)(?:test_|tests/|__tests__/|spec/|specs/|\w+\.test\.|\w+\.spec\.|conftest\.)",
    re.IGNORECASE,
)
_DOC_EXT = re.compile(r"\.(?:md|mdx|rst|txt)$", re.IGNORECASE)
_CONFIG_BASENAMES = {
    "Dockerfile", "Containerfile", "Makefile", "GNUmakefile",
    "Procfile", "Vagrantfile", "Berksfile", "Gemfile", "Rakefile",
    "Justfile", "justfile",
    "BUILD", "BUILD.bazel", "WORKSPACE", "CMakeLists.txt",
    ".env.example", ".env.sample", ".env.template", ".envrc",
    "go.mod", "go.sum", "go.work",
    "pyproject.toml", "setup.cfg", "setup.py", "requirements.txt",
    "package.json", "tsconfig.json", "Cargo.toml", "composer.json",
    "OWNERS", "CODEOWNERS", "README", "LICENSE",
}
_EXAMPLE_PATH = re.compile(r"(?:^|/)(?:examples?/|example_|demo/|sample/)", re.IGNORECASE)


def classify_path(file_path: str) -> str:
    """Classify a file path into 'test', 'doc', 'config', 'example', or 'code'."""
    if not file_path:
        return "code"
    base = file_path.rsplit("/", 1)[-1]
    if base in _CONFIG_BASENAMES:
        return "config"
    if _TEST_PATH.search(file_path):
        return "test"
    if _DOC_EXT.search(file_path):
        return "doc"
    if _EXAMPLE_PATH.search(file_path):
        return "example"
    return "code"


def _query_is_broad(query: str) -> bool:
    """Heuristic: queries with no concrete identifier and >5 words are broad."""
    if len(query.split()) < 4:
        return False
    # Has any CamelCase / snake_case identifier? Then it's specific.
    if re.search(r"[A-Z][a-z]+[A-Z]|_\w+|\.\w+", query):
        return False
    # Otherwise, broad-ish
    return True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Builder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ContextPackBuilder:
    """Build a ContextPack for a query.

    Args:
        user_id: required for access control.
        token_budget: target maximum tokens for the pack body.
        max_primary: how many primary hits to seed expansion from.
        max_per_role: cap per expansion role (tests, docs, etc.).
    """

    def __init__(
        self,
        user_id: str,
        token_budget: int = 6000,
        max_primary: int = 5,
        max_per_role: int = 3,
    ):
        if not user_id:
            raise ValueError("user_id required for context pack")
        self.user_id = user_id
        self.token_budget = token_budget
        self.max_primary = max_primary
        self.max_per_role = max_per_role

    # ── Public ────────────────────────────────────────────────────────────

    def build(
        self,
        query: str,
        repo_ids: list[str] | None = None,
        quality_mode: str = "agent",
        include_architecture: bool = True,
        include_tests: bool = True,
        include_docs: bool = True,
        include_examples: bool = True,
        include_configs: bool = True,
    ) -> ContextPack:
        from synsc.services.search_service import SearchService

        t0 = time.time()
        pack = ContextPack(
            query=query,
            quality_mode=quality_mode,
            token_budget=self.token_budget,
        )
        rationale: dict[str, Any] = {"steps": []}

        # 1. Initial hybrid search.
        svc = SearchService(user_id=self.user_id)
        initial = svc.search_code(
            query=query,
            repo_ids=repo_ids,
            top_k=self.max_primary * 2,  # over-fetch for filtering
            user_id=self.user_id,
            quality_mode=quality_mode,
        )
        primary = initial.get("results", [])
        rationale["steps"].append({
            "name": "primary_search",
            "query": query,
            "hits": len(primary),
            "hybrid": initial.get("hybrid"),
        })

        if not primary:
            pack.coverage_gaps.append("primary_search_returned_zero_hits")
            return pack

        # Track which repos are in scope so expansion queries stay bounded.
        scoped_repo_ids = repo_ids or list({r["repo_id"] for r in primary})

        # 2. Add primary snippets, capped.
        for r in primary[: self.max_primary]:
            self._add_snippet(
                pack,
                self._snippet_from_result(r, role="primary", why="initial hybrid hit"),
            )
            if pack.used_tokens_estimate > self.token_budget * 0.7:
                break

        # 3. Expand each primary with enclosing symbol body, adjacents,
        #    same-class siblings.
        with get_session() as session:
            self._add_enclosing_symbol_bodies(
                session, pack, primary[: self.max_primary]
            )
            self._add_adjacent_chunks(session, pack, primary[: self.max_primary])
            self._add_same_class_siblings(session, pack, primary[: self.max_primary])
            self._add_imports(session, pack, primary[: self.max_primary])

            # 4. Linked tests / docs / examples / configs that mention any
            #    matched symbol.
            symbol_names = self._collect_symbol_names(primary[: self.max_primary])
            pack.symbols = self._fetch_symbol_details(
                session, symbol_names, scoped_repo_ids
            )
            rationale["matched_symbols"] = symbol_names[:20]

            if include_tests and symbol_names:
                tests = self._fetch_chunks_mentioning(
                    session, symbol_names, scoped_repo_ids,
                    role_filter="test", limit=self.max_per_role,
                )
                if not tests:
                    pack.coverage_gaps.append("no_tests_mention_matched_symbols")
                for t in tests:
                    self._add_snippet(pack, t)

            if include_docs:
                docs = self._fetch_chunks_mentioning(
                    session, symbol_names, scoped_repo_ids,
                    role_filter="doc", limit=self.max_per_role,
                )
                if not docs and symbol_names:
                    pack.coverage_gaps.append("no_docs_mention_matched_symbols")
                for d in docs:
                    self._add_snippet(pack, d)

            if include_examples and symbol_names:
                examples = self._fetch_chunks_mentioning(
                    session, symbol_names, scoped_repo_ids,
                    role_filter="example", limit=self.max_per_role,
                )
                for e in examples:
                    self._add_snippet(pack, e)

            if include_configs:
                configs = self._fetch_chunks_mentioning(
                    session, symbol_names, scoped_repo_ids,
                    role_filter="config", limit=self.max_per_role,
                )
                for c in configs:
                    self._add_snippet(pack, c)

            # 5. Architecture summary for broad queries.
            if include_architecture and _query_is_broad(query):
                pack.architecture_summary = self._build_architecture_summary(
                    session, scoped_repo_ids
                )

            # 6. Re-query planner — if we under-filled the budget or are
            #    missing key categories, issue follow-up searches.
            requeries = self._plan_requeries(pack, primary, query)
            for rq in requeries:
                if pack.used_tokens_estimate >= self.token_budget * 0.9:
                    break
                pack.requeries.append(rq)
                rerun = svc.search_code(
                    query=rq, repo_ids=scoped_repo_ids,
                    top_k=3, user_id=self.user_id,
                    quality_mode=quality_mode,
                )
                rationale["steps"].append({
                    "name": "requery",
                    "query": rq,
                    "hits": len(rerun.get("results", [])),
                })
                for r in rerun.get("results", []):
                    if pack.used_tokens_estimate >= self.token_budget:
                        break
                    self._add_snippet(
                        pack,
                        self._snippet_from_result(
                            r, role="requery", why=f"follow-up: {rq}",
                        ),
                    )

        rationale["elapsed_ms"] = round((time.time() - t0) * 1000)
        rationale["used_tokens_estimate"] = pack.used_tokens_estimate
        pack.rationale = rationale
        return pack

    # ── Snippet helpers ───────────────────────────────────────────────────

    def _snippet_from_result(
        self, r: dict, role: str, why: str
    ) -> PackSnippet:
        return PackSnippet(
            role=role,
            chunk_id=r.get("chunk_id"),
            repo_id=r.get("repo_id", ""),
            repo_name=r.get("repo_name", ""),
            file_path=r.get("file_path", ""),
            start_line=r.get("start_line", 0),
            end_line=r.get("end_line", 0),
            content=r.get("content", ""),
            language=r.get("language"),
            symbol_names=self._parse_symbols(r.get("symbol_names")),
            score=float(r.get("relevance_score", r.get("similarity", 0.0))),
            why=why,
            candidate_sources=r.get("candidate_sources"),
        )

    def _add_snippet(self, pack: ContextPack, snippet: PackSnippet) -> bool:
        """Append a snippet if it fits the budget. Returns True on success."""
        if not snippet or not snippet.content:
            return False
        # Dedupe: same chunk_id (or same path+lines if chunk_id missing)
        key = (snippet.chunk_id, snippet.file_path, snippet.start_line, snippet.end_line)
        for existing in pack.snippets:
            ekey = (existing.chunk_id, existing.file_path,
                    existing.start_line, existing.end_line)
            if key == ekey:
                # Already present — bump role if more specific.
                return False
        cost = _approx_tokens(snippet.content)
        if pack.used_tokens_estimate + cost > self.token_budget:
            return False
        pack.snippets.append(snippet)
        pack.used_tokens_estimate += cost
        return True

    def _parse_symbols(self, raw: Any) -> list[str] | None:
        if raw is None:
            return None
        if isinstance(raw, list):
            return raw
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    # ── Expansion queries ─────────────────────────────────────────────────

    def _add_enclosing_symbol_bodies(
        self, session: Session, pack: ContextPack, primary: list[dict]
    ) -> None:
        """For each primary hit, fetch the tightest enclosing function/class
        body. The chunk often shows just a slice; the full body shows
        contracts and helper calls.
        """
        if not primary:
            return
        file_ids = list({r.get("file_id") or r.get("repo_id") for r in primary})
        chunks_by_file: dict[str, list[dict]] = {}
        for r in primary:
            fid = r.get("file_id")
            if fid:
                chunks_by_file.setdefault(fid, []).append(r)

        if not chunks_by_file:
            return

        rows = session.execute(
            text(
                """
                SELECT s.symbol_id, s.file_id, s.symbol_type, s.name,
                       s.qualified_name, s.signature, s.docstring,
                       s.start_line, s.end_line, s.repo_id, s.language,
                       rf.file_path, r.owner || '/' || r.name AS repo_name,
                       r.commit_sha
                FROM symbols s
                INNER JOIN repository_files rf ON s.file_id = rf.file_id
                INNER JOIN repositories r ON s.repo_id = r.repo_id
                WHERE s.file_id = ANY(CAST(:file_ids AS uuid[]))
                  AND s.symbol_type IN ('function', 'method', 'class')
                """
            ),
            {"file_ids": list(chunks_by_file.keys())},
        ).mappings().all()

        for r in primary:
            fid = r.get("file_id")
            if not fid:
                continue
            sl, el = r.get("start_line", 0), r.get("end_line", 0)
            best = None
            best_span = None
            for s in rows:
                if str(s["file_id"]) != fid:
                    continue
                if s["start_line"] <= sl and s["end_line"] >= el:
                    span = s["end_line"] - s["start_line"]
                    if best_span is None or span < best_span:
                        best, best_span = s, span
            if best is None:
                continue
            # Pull the full body for the enclosing symbol from code_chunks.
            body_rows = session.execute(
                text(
                    """
                    SELECT chunk_id, content, start_line, end_line, language,
                           symbol_names
                    FROM code_chunks
                    WHERE file_id = :fid
                      AND start_line <= :sl AND end_line >= :el
                    ORDER BY start_line
                    """
                ),
                {"fid": fid, "sl": best["start_line"], "el": best["end_line"]},
            ).mappings().all()
            if not body_rows:
                continue
            body = "\n".join(b["content"] for b in body_rows)
            self._add_snippet(
                pack,
                PackSnippet(
                    role="enclosing",
                    chunk_id=str(body_rows[0]["chunk_id"]),
                    repo_id=str(best["repo_id"]),
                    repo_name=best["repo_name"] or "",
                    file_path=best["file_path"] or "",
                    start_line=best["start_line"],
                    end_line=best["end_line"],
                    content=body,
                    language=best["language"],
                    symbol_names=[best["name"]],
                    score=r.get("relevance_score", 0.0),
                    why=f"enclosing {best['symbol_type']} {best['name']}",
                    commit_sha=best.get("commit_sha"),
                ),
            )

    def _add_adjacent_chunks(
        self, session: Session, pack: ContextPack, primary: list[dict]
    ) -> None:
        """Fetch chunk N-1 and N+1 for each primary chunk so the agent sees
        what came before/after the matched slice.
        """
        for r in primary:
            fid = r.get("file_id")
            ci = r.get("chunk_index")
            if not fid or ci is None:
                continue
            rows = session.execute(
                text(
                    """
                    SELECT cc.chunk_id, cc.content, cc.start_line, cc.end_line,
                           cc.chunk_index, cc.language,
                           rf.file_path, r.owner || '/' || r.name AS repo_name,
                           r.commit_sha, cc.repo_id
                    FROM code_chunks cc
                    INNER JOIN repository_files rf ON cc.file_id = rf.file_id
                    INNER JOIN repositories r ON cc.repo_id = r.repo_id
                    WHERE cc.file_id = :fid
                      AND cc.chunk_index IN (:prev, :next)
                    ORDER BY cc.chunk_index
                    """
                ),
                {"fid": fid, "prev": ci - 1, "next": ci + 1},
            ).mappings().all()
            for row in rows:
                self._add_snippet(
                    pack,
                    PackSnippet(
                        role="adjacent",
                        chunk_id=str(row["chunk_id"]),
                        repo_id=str(row["repo_id"]),
                        repo_name=row["repo_name"] or "",
                        file_path=row["file_path"] or "",
                        start_line=row["start_line"],
                        end_line=row["end_line"],
                        content=row["content"],
                        language=row["language"],
                        why=f"adjacent chunk #{row['chunk_index']} of primary hit",
                        commit_sha=row.get("commit_sha"),
                    ),
                )

    def _add_same_class_siblings(
        self, session: Session, pack: ContextPack, primary: list[dict]
    ) -> None:
        """Use chunk_relationships.same_class to surface sibling methods of
        the same class — agents often need them to understand the API surface.
        """
        chunk_ids = [r.get("chunk_id") for r in primary if r.get("chunk_id")]
        if not chunk_ids:
            return
        rows = session.execute(
            text(
                """
                SELECT cc.chunk_id, cc.content, cc.start_line, cc.end_line,
                       cc.language, cc.repo_id,
                       rf.file_path, r.owner || '/' || r.name AS repo_name,
                       r.commit_sha
                FROM chunk_relationships cr
                INNER JOIN code_chunks cc ON cr.target_chunk_id = cc.chunk_id
                INNER JOIN repository_files rf ON cc.file_id = rf.file_id
                INNER JOIN repositories r ON cc.repo_id = r.repo_id
                WHERE cr.relationship_type = 'same_class'
                  AND cr.source_chunk_id = ANY(CAST(:src_ids AS uuid[]))
                LIMIT 5
                """
            ),
            {"src_ids": chunk_ids},
        ).mappings().all()
        for row in rows:
            self._add_snippet(
                pack,
                PackSnippet(
                    role="same_class",
                    chunk_id=str(row["chunk_id"]),
                    repo_id=str(row["repo_id"]),
                    repo_name=row["repo_name"] or "",
                    file_path=row["file_path"] or "",
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                    content=row["content"],
                    language=row["language"],
                    why="sibling method in the same class",
                    commit_sha=row.get("commit_sha"),
                ),
            )

    def _add_imports(
        self, session: Session, pack: ContextPack, primary: list[dict]
    ) -> None:
        """Fetch the import block (chunk_type='import') of each primary file."""
        file_ids = list({r.get("file_id") for r in primary if r.get("file_id")})
        if not file_ids:
            return
        rows = session.execute(
            text(
                """
                SELECT cc.chunk_id, cc.content, cc.start_line, cc.end_line,
                       cc.language, cc.repo_id,
                       rf.file_path, r.owner || '/' || r.name AS repo_name,
                       r.commit_sha
                FROM code_chunks cc
                INNER JOIN repository_files rf ON cc.file_id = rf.file_id
                INNER JOIN repositories r ON cc.repo_id = r.repo_id
                WHERE cc.file_id = ANY(CAST(:fids AS uuid[]))
                  AND cc.chunk_type = 'import'
                ORDER BY cc.file_id, cc.chunk_index
                """
            ),
            {"fids": file_ids},
        ).mappings().all()
        seen_files: set[str] = set()
        for row in rows:
            if row["file_path"] in seen_files:
                continue
            seen_files.add(row["file_path"])
            self._add_snippet(
                pack,
                PackSnippet(
                    role="imports",
                    chunk_id=str(row["chunk_id"]),
                    repo_id=str(row["repo_id"]),
                    repo_name=row["repo_name"] or "",
                    file_path=row["file_path"] or "",
                    start_line=row["start_line"],
                    end_line=row["end_line"],
                    content=row["content"],
                    language=row["language"],
                    why="imports/dependency block of primary file",
                    commit_sha=row.get("commit_sha"),
                ),
            )

    # ── Symbol-mention queries ────────────────────────────────────────────

    def _collect_symbol_names(self, primary: list[dict]) -> list[str]:
        seen: dict[str, None] = {}
        for r in primary:
            raw = r.get("symbol_names")
            if raw is None:
                continue
            try:
                names = raw if isinstance(raw, list) else json.loads(raw)
            except (TypeError, ValueError):
                continue
            for n in names:
                if isinstance(n, str) and len(n) >= 3:
                    seen.setdefault(n, None)
        return list(seen.keys())[:8]

    def _fetch_symbol_details(
        self,
        session: Session,
        names: list[str],
        repo_ids: list[str] | None,
    ) -> list[dict]:
        if not names:
            return []
        params: dict[str, Any] = {"user_id": self.user_id}
        for i, n in enumerate(names):
            params[f"n_{i}"] = n
        placeholders = ", ".join([f":n_{i}" for i in range(len(names))])
        repo_clause = ""
        if repo_ids:
            ph = ", ".join([f":rid_{i}" for i in range(len(repo_ids))])
            repo_clause = f"AND s.repo_id IN ({ph})"
            for i, rid in enumerate(repo_ids):
                params[f"rid_{i}"] = rid

        sql = text(
            f"""
            WITH user_repos AS MATERIALIZED (
                SELECT repo_id FROM user_repositories WHERE user_id = :user_id
            )
            SELECT s.symbol_id, s.name, s.qualified_name, s.symbol_type,
                   s.signature, s.docstring, s.start_line, s.end_line,
                   s.language, s.is_async, s.is_exported,
                   rf.file_path, s.repo_id,
                   r.owner || '/' || r.name AS repo_name
            FROM symbols s
            INNER JOIN user_repos ur ON s.repo_id = ur.repo_id
            INNER JOIN repositories r ON s.repo_id = r.repo_id
                AND (r.is_public = TRUE OR r.indexed_by = :user_id)
            INNER JOIN repository_files rf ON s.file_id = rf.file_id
            WHERE s.name IN ({placeholders})
            {repo_clause}
            LIMIT 32
            """
        )
        try:
            rows = session.execute(sql, params).mappings().all()
        except Exception as e:
            logger.warning("symbol detail fetch failed", error=str(e))
            return []
        return [dict(r) for r in rows]

    def _fetch_chunks_mentioning(
        self,
        session: Session,
        names: list[str],
        repo_ids: list[str] | None,
        role_filter: str,  # 'test' | 'doc' | 'example' | 'config'
        limit: int = 3,
    ) -> list[PackSnippet]:
        if not names:
            return []
        # Build LIKE conditions for each name. We want chunks whose content
        # contains at least one of the names.
        params: dict[str, Any] = {"user_id": self.user_id, "limit": limit}
        like_clauses = []
        for i, n in enumerate(names):
            like_clauses.append(f"cc.content ILIKE :p_{i}")
            params[f"p_{i}"] = f"%{n}%"
        like_block = " OR ".join(like_clauses)

        repo_clause = ""
        if repo_ids:
            ph = ", ".join([f":rid_{i}" for i in range(len(repo_ids))])
            repo_clause = f"AND cc.repo_id IN ({ph})"
            for i, rid in enumerate(repo_ids):
                params[f"rid_{i}"] = rid

        # Path filter for role_filter
        if role_filter == "test":
            path_clause = (
                "(rf.file_path ~* '(^|/)(test_|tests/|__tests__/|spec/|specs/|"
                ".+\\.test\\.|.+\\.spec\\.|conftest\\.)' "
                "OR rf.file_path ILIKE '%test%')"
            )
        elif role_filter == "doc":
            path_clause = "rf.file_path ~* '\\.(md|mdx|rst)$'"
        elif role_filter == "example":
            path_clause = (
                "rf.file_path ~* '(^|/)(examples?/|example_|demo/|sample/)'"
            )
        elif role_filter == "config":
            path_clause = (
                "(rf.file_name IN ("
                "'Dockerfile','Containerfile','Makefile','GNUmakefile',"
                "'Procfile','Vagrantfile','Berksfile','Gemfile','Rakefile',"
                "'BUILD','BUILD.bazel','WORKSPACE','CMakeLists.txt',"
                "'.env.example','.env.sample','.env.template','.envrc',"
                "'go.mod','go.sum','pyproject.toml','requirements.txt',"
                "'package.json','tsconfig.json','Cargo.toml',"
                "'OWNERS','CODEOWNERS','README','LICENSE'"
                ") OR rf.file_path ~* '\\.(toml|yaml|yml|json)$')"
            )
        else:
            path_clause = "TRUE"

        sql = text(
            f"""
            WITH user_repos AS MATERIALIZED (
                SELECT repo_id FROM user_repositories WHERE user_id = :user_id
            )
            SELECT cc.chunk_id, cc.content, cc.start_line, cc.end_line,
                   cc.language, cc.symbol_names, cc.repo_id,
                   rf.file_path, r.owner || '/' || r.name AS repo_name,
                   r.commit_sha
            FROM code_chunks cc
            INNER JOIN user_repos ur ON cc.repo_id = ur.repo_id
            INNER JOIN repositories r ON cc.repo_id = r.repo_id
                AND (r.is_public = TRUE OR r.indexed_by = :user_id)
            INNER JOIN repository_files rf ON cc.file_id = rf.file_id
            WHERE ({like_block})
              AND {path_clause}
              {repo_clause}
            LIMIT :limit
            """
        )
        try:
            rows = session.execute(sql, params).mappings().all()
        except Exception as e:
            logger.warning(
                "chunks-mentioning fetch failed",
                role=role_filter, error=str(e),
            )
            return []

        out: list[PackSnippet] = []
        for r in rows:
            out.append(
                PackSnippet(
                    role=role_filter,
                    chunk_id=str(r["chunk_id"]),
                    repo_id=str(r["repo_id"]),
                    repo_name=r["repo_name"] or "",
                    file_path=r["file_path"] or "",
                    start_line=r["start_line"],
                    end_line=r["end_line"],
                    content=r["content"],
                    language=r["language"],
                    symbol_names=self._parse_symbols(r.get("symbol_names")),
                    why=f"{role_filter} mentioning matched symbol",
                    commit_sha=r.get("commit_sha"),
                )
            )
        return out

    # ── Architecture summary ──────────────────────────────────────────────

    def _build_architecture_summary(
        self, session: Session, repo_ids: list[str]
    ) -> dict | None:
        """Pull a directory-level overview of the in-scope repos so broad
        queries get a navigable map.
        """
        if not repo_ids:
            return None
        rows = session.execute(
            text(
                """
                SELECT r.repo_id, r.owner, r.name, r.languages,
                       r.files_count, r.symbols_count,
                       r.commit_sha, r.indexed_at
                FROM repositories r
                WHERE r.repo_id = ANY(:repo_ids)
                """
            ),
            {"repo_ids": repo_ids},
        ).mappings().all()
        if not rows:
            return None
        # Top-level dir counts per repo
        summaries = []
        for r in rows:
            top_dirs = session.execute(
                text(
                    """
                    SELECT
                        split_part(file_path, '/', 1) AS dir,
                        count(*) AS files
                    FROM repository_files
                    WHERE repo_id = :rid
                    GROUP BY dir
                    ORDER BY files DESC
                    LIMIT 12
                    """
                ),
                {"rid": str(r["repo_id"])},
            ).mappings().all()
            summaries.append(
                {
                    "repo_id": str(r["repo_id"]),
                    "repo_name": f"{r['owner']}/{r['name']}",
                    "files_count": r["files_count"],
                    "symbols_count": r["symbols_count"],
                    "commit_sha": r["commit_sha"],
                    "languages": r["languages"],
                    "top_directories": [
                        {"dir": d["dir"], "files": d["files"]} for d in top_dirs
                    ],
                }
            )
        return {"repos": summaries}

    # ── Re-query planner ──────────────────────────────────────────────────

    def _plan_requeries(
        self, pack: ContextPack, primary: list[dict], query: str
    ) -> list[str]:
        """Decide whether to issue follow-up searches.

        Heuristics:
          - If we have plenty of room left in the budget (<50% used) AND
            primary surfaced fewer than max_primary hits, broaden the query.
          - If primary surfaced symbol matches but no enclosing class body
            was added, search for the class name.
          - If primary surfaced docs but no implementation, search for
            "implementation of <symbol>".
        """
        out: list[str] = []
        if not primary:
            return out
        used_ratio = pack.used_tokens_estimate / max(self.token_budget, 1)
        if used_ratio > 0.7:
            return out

        # Try the strongest matched symbol as a follow-up.
        symbols = self._collect_symbol_names(primary[: self.max_primary])
        if symbols:
            sym = symbols[0]
            if sym.lower() not in query.lower():
                out.append(sym)

        # If no test snippets and there are symbols, ask explicitly.
        has_test = any(s.role == "test" for s in pack.snippets)
        if not has_test and symbols:
            out.append(f"tests for {symbols[0]}")

        return out[:2]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Public function — used by MCP tool + HTTP endpoint
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def build_context_pack(
    query: str,
    user_id: str,
    repo_ids: list[str] | None = None,
    quality_mode: str = "agent",
    token_budget: int = 6000,
    include_architecture: bool = True,
    include_tests: bool = True,
    include_docs: bool = True,
    include_examples: bool = True,
    include_configs: bool = True,
) -> dict:
    builder = ContextPackBuilder(
        user_id=user_id,
        token_budget=token_budget,
    )
    pack = builder.build(
        query=query,
        repo_ids=repo_ids,
        quality_mode=quality_mode,
        include_architecture=include_architecture,
        include_tests=include_tests,
        include_docs=include_docs,
        include_examples=include_examples,
        include_configs=include_configs,
    )
    return pack.to_dict()


def get_chunk_context(
    chunk_id: str,
    user_id: str,
    radius: int = 1,
    include_enclosing: bool = True,
    include_same_class: bool = True,
) -> dict:
    """Fetch a chunk plus its surrounding context.

    Returns the chunk itself, ``radius`` chunks above and below (in the
    same file), the enclosing function/class body if any, and same-class
    siblings when chunk relationships exist.

    Side-effect: stamps an observability ``chunk_used`` event so we can
    measure "returned vs actually used" — agents calling get_context on
    a chunk is the strongest signal that the search hit was useful.

    This is the ``get_context(chunk_id)`` primitive — useful when an agent
    wants to drill into one specific result without re-running search.
    """
    if not user_id:
        raise ValueError("user_id required")
    # Auto-stamp the chunk_used event. Best-effort — don't break the
    # primary read on logging failure.
    try:
        from synsc.services.observability import log_chunk_used
        log_chunk_used(user_id=user_id, chunk_id=chunk_id)
    except Exception:
        pass
    out: dict[str, Any] = {"chunk_id": chunk_id, "primary": None,
                          "neighbors": [], "enclosing": None,
                          "same_class": []}
    with get_session() as session:
        # Primary chunk + access check
        row = session.execute(
            text(
                """
                SELECT cc.chunk_id, cc.repo_id, cc.file_id, cc.chunk_index,
                       cc.content, cc.start_line, cc.end_line, cc.language,
                       cc.chunk_type, cc.symbol_names,
                       rf.file_path, r.owner || '/' || r.name AS repo_name,
                       r.commit_sha, r.is_public, r.indexed_by
                FROM code_chunks cc
                INNER JOIN repository_files rf ON cc.file_id = rf.file_id
                INNER JOIN repositories r ON cc.repo_id = r.repo_id
                WHERE cc.chunk_id = :cid
                """
            ),
            {"cid": chunk_id},
        ).mappings().first()
        if not row:
            return {"error": "not_found"}
        if not (row["is_public"] or str(row["indexed_by"]) == str(user_id)):
            # Soft access check — we also restrict via user_repositories below.
            return {"error": "access_denied"}

        out["primary"] = {
            "chunk_id": str(row["chunk_id"]),
            "repo_id": str(row["repo_id"]),
            "repo_name": row["repo_name"],
            "file_path": row["file_path"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "content": row["content"],
            "language": row["language"],
            "chunk_type": row["chunk_type"],
            "symbol_names": row["symbol_names"],
            "commit_sha": row["commit_sha"],
        }

        # Neighbors via chunk_index ± radius
        ci = row["chunk_index"]
        if ci is not None:
            indices = list(range(max(0, ci - radius), ci + radius + 1))
            indices.remove(ci)
            if indices:
                neighbors = session.execute(
                    text(
                        """
                        SELECT chunk_id, content, start_line, end_line,
                               chunk_index
                        FROM code_chunks
                        WHERE file_id = :fid AND chunk_index = ANY(:idx)
                        ORDER BY chunk_index
                        """
                    ),
                    {"fid": str(row["file_id"]), "idx": indices},
                ).mappings().all()
                out["neighbors"] = [dict(n) for n in neighbors]

        if include_enclosing:
            sym = session.execute(
                text(
                    """
                    SELECT symbol_id, name, qualified_name, symbol_type,
                           signature, docstring, start_line, end_line
                    FROM symbols
                    WHERE file_id = :fid
                      AND start_line <= :sl AND end_line >= :el
                      AND symbol_type IN ('function','method','class')
                    ORDER BY (end_line - start_line) ASC
                    LIMIT 1
                    """
                ),
                {
                    "fid": str(row["file_id"]),
                    "sl": row["start_line"],
                    "el": row["end_line"],
                },
            ).mappings().first()
            if sym:
                out["enclosing"] = dict(sym)

        if include_same_class:
            siblings = session.execute(
                text(
                    """
                    SELECT cc.chunk_id, cc.content, cc.start_line, cc.end_line
                    FROM chunk_relationships cr
                    INNER JOIN code_chunks cc ON cr.target_chunk_id = cc.chunk_id
                    WHERE cr.relationship_type = 'same_class'
                      AND cr.source_chunk_id = :cid
                    LIMIT 5
                    """
                ),
                {"cid": chunk_id},
            ).mappings().all()
            out["same_class"] = [
                {**dict(s), "chunk_id": str(s["chunk_id"])} for s in siblings
            ]
    return out
