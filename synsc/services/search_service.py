"""Search service for semantic code search.

Uses pgvector for semantic search with smart deduplication:
- Public repos are shared, but users only search repos in their collection
- Private repos are only accessible by the indexer

Post-retrieval quality pipeline:
1. Symbol-aware score boosting (exact symbol name matches)
2. Metadata-aware scoring (file path signals — demote tests/docs/examples)
3. Cross-encoder reranking (query+candidate attention for fine discrimination)
4. Dynamic similarity threshold (relative to top result)
5. MMR diversification (reduce near-duplicate results)
"""

import json
import os
import re
import time
from pathlib import Path

import numpy as np
import structlog
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from synsc.config import get_config
from synsc.database.connection import get_session
from synsc.database.models import (
    Repository,
    RepositoryFile,
    CodeChunk,
    UserRepository,
)
from synsc.embeddings.generator import EmbeddingGenerator
from synsc.indexing.vector_store import get_vector_store

logger = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Post-retrieval quality functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _extract_query_symbols(query: str) -> set[str]:
    """Extract likely symbol names from a search query.

    Matches identifiers that look like function/class/variable names:
    camelCase, snake_case, PascalCase, UPPER_CASE, dotted.paths.
    """
    # Match word-like tokens that look like code identifiers
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", query)
    symbols = set()
    for token in tokens:
        # Skip common English words that aren't code identifiers
        if len(token) <= 2 or token.lower() in {
            "the", "and", "for", "how", "does", "what", "this", "that",
            "with", "from", "use", "get", "set", "not", "all", "any",
            "find", "list", "show", "code", "file", "function", "class",
            "method", "where", "which",
        }:
            continue
        symbols.add(token.lower())
        # Also add parts of dotted paths: "fastapi.routing" → {"fastapi", "routing"}
        if "." in token:
            symbols.update(part.lower() for part in token.split(".") if len(part) > 2)
    return symbols


def _apply_symbol_boost(
    results: list[dict],
    query_symbols: set[str],
    boost: float = 0.15,
) -> list[dict]:
    """Boost relevance score for chunks whose symbol_names match query symbols.

    Args:
        results: Search results with 'similarity' and 'symbol_names' keys.
        query_symbols: Lowercased symbol names extracted from query.
        boost: Score boost for a symbol match (added to similarity).

    Returns:
        Results with updated 'similarity' scores (capped at 1.0).
    """
    if not query_symbols:
        return results

    for r in results:
        raw_symbols = r.get("symbol_names")
        if not raw_symbols:
            continue

        # symbol_names is stored as JSON array or list
        if isinstance(raw_symbols, str):
            try:
                raw_symbols = json.loads(raw_symbols)
            except (json.JSONDecodeError, TypeError):
                continue

        chunk_symbols = {s.lower() for s in raw_symbols if isinstance(s, str)}

        if query_symbols & chunk_symbols:
            r["similarity"] = min(r["similarity"] + boost, 1.0)

    return results


# Patterns indicating non-production code (tests, docs, examples, fixtures)
_DEMOTE_PATTERNS = re.compile(
    r"(?:^|/)"
    r"(?:test_|tests/|__tests__/|spec/|specs/|"
    r"docs_src/|docs/|doc/|examples?/|"
    r"fixtures?/|mocks?/|__mocks__/|__snapshots__/|"
    r"storybook/|stories/|e2e/|cypress/|playwright/|"
    r"benchmarks?/|sandbox/|demo/)",
    re.IGNORECASE,
)

# Patterns indicating a test file by name
_TEST_FILE_PATTERN = re.compile(
    r"(?:^|/)(?:test_.*|.*_test|.*\.test|.*\.spec|conftest)\.(?:py|js|ts|tsx|jsx)$",
    re.IGNORECASE,
)


# Content patterns indicating test/assertion code (not implementation)
_TEST_CONTENT_PATTERN = re.compile(
    r"(?:"
    r"\bassert\s|"
    r"\bdef test_|"
    r"\bpytest\b|"
    r"\b(?:mock|patch|MagicMock|monkeypatch)\b|"
    r"\bdescribe\(|"
    r"\bit\(|"
    r"\bexpect\(|"
    r"\bshould\b.*\b(?:equal|be|have)\b"
    r")",
    re.IGNORECASE,
)


def _apply_metadata_scoring(
    results: list[dict],
    path_penalty: float = 0.08,
    content_penalty: float = 0.04,
) -> list[dict]:
    """Adjust scores based on file path and content signals.

    Uses two layers:
    1. File path: demotes test dirs, doc dirs, example dirs
    2. Content: demotes chunks heavy on assert/mock/pytest patterns

    Penalties stack: a test file in tests/ with lots of asserts gets both.
    No boost for implementation — avoids false positives on similar_sig cases
    where both correct and decoy chunks contain definitions.

    Args:
        results: Search results with 'file_path', 'content', 'similarity' keys.
        path_penalty: Score penalty for test/doc/example file paths.
        content_penalty: Score penalty for test-heavy content.

    Returns:
        Results with adjusted scores.
    """
    for r in results:
        penalty = 0.0
        file_path = r.get("file_path", "")
        content = r.get("content", "")

        # Path-based signals
        if file_path and (
            _DEMOTE_PATTERNS.search(file_path)
            or _TEST_FILE_PATTERN.search(file_path)
        ):
            penalty += path_penalty

        # Content-based signals (demote only, no boost)
        if content:
            num_lines = max(content.count("\n") + 1, 1)
            test_hits = len(_TEST_CONTENT_PATTERN.findall(content))
            if test_hits / num_lines > 0.15:
                penalty += content_penalty

        if penalty > 0:
            r["similarity"] = max(r["similarity"] - penalty, 0.0)

    return results


def _apply_dynamic_threshold(
    results: list[dict],
    min_absolute: float = 0.3,
    relative_factor: float = 0.6,
) -> list[dict]:
    """Filter results using a dynamic threshold relative to the top score.

    If the best result has similarity 0.92, the cutoff becomes
    max(0.3, 0.92 * 0.6) = 0.552 — dropping low-quality tail results
    that the fixed 0.3 threshold would have kept.

    Args:
        results: Search results sorted by similarity (descending).
        min_absolute: Hard floor — never drop above this threshold.
        relative_factor: Fraction of top score used as dynamic cutoff.

    Returns:
        Filtered results.
    """
    if not results:
        return results

    top_score = max(r["similarity"] for r in results)
    threshold = max(min_absolute, top_score * relative_factor)

    return [r for r in results if r["similarity"] >= threshold]


def _apply_mmr(
    results: list[dict],
    query_embedding: np.ndarray,
    embeddings: dict[str, np.ndarray] | None = None,
    top_k: int = 10,
    lambda_param: float = 0.7,
) -> list[dict]:
    """Apply Maximal Marginal Relevance to diversify results.

    MMR balances relevance to the query with diversity among selected results.
    score = λ * sim(candidate, query) - (1-λ) * max_sim(candidate, already_selected)

    Since we don't have chunk embeddings in-memory, we approximate inter-result
    similarity using content overlap (Jaccard on token sets). This avoids an
    extra DB round-trip and works well for catching near-duplicate chunks.

    Args:
        results: Candidate results (should be more than top_k for best effect).
        query_embedding: Not used in content-based mode, kept for future use.
        embeddings: Optional pre-fetched embeddings keyed by chunk_id.
        top_k: Number of results to select.
        lambda_param: Balance between relevance (1.0) and diversity (0.0).

    Returns:
        top_k results selected by MMR.
    """
    if len(results) <= top_k:
        return results

    # Tokenize content for Jaccard similarity
    def _tokenize(text: str) -> set[str]:
        return set(text.lower().split())

    token_sets = [_tokenize(r["content"]) for r in results]

    def _jaccard(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    selected_indices: list[int] = []
    remaining = list(range(len(results)))

    for _ in range(top_k):
        if not remaining:
            break

        best_idx = None
        best_score = -float("inf")

        for idx in remaining:
            relevance = results[idx]["similarity"]

            # Max similarity to any already-selected result
            max_sim = 0.0
            for sel_idx in selected_indices:
                sim = _jaccard(token_sets[idx], token_sets[sel_idx])
                if sim > max_sim:
                    max_sim = sim

            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim

            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx

        selected_indices.append(best_idx)
        remaining.remove(best_idx)

    return [results[i] for i in selected_indices]


def _enrich_results_with_context(results: list[dict]) -> list[dict]:
    """Enrich search results with enclosing symbol docstrings/signatures and adjacent context.

    Post-retrieval enrichment: for each result, finds the tightest enclosing
    symbol (function/class) and prepends its signature and docstring to the
    chunk content. Also fetches the previous chunk for flow context.

    This runs after MMR selection, so operates on at most top_k (~10) results.
    Uses two batched SQL queries — expected latency ~10-30ms.
    """
    if not results:
        return results

    file_ids = list({r["file_id"] for r in results if r.get("file_id")})
    if not file_ids:
        return results

    try:
        with get_session() as session:
            # Batch query 1: all symbols for relevant files
            symbol_rows = session.execute(
                text("""
                    SELECT file_id, name, qualified_name, symbol_type,
                           signature, docstring, start_line, end_line
                    FROM symbols
                    WHERE file_id = ANY(CAST(:file_ids AS uuid[]))
                """),
                {"file_ids": file_ids},
            ).fetchall()

            # Group symbols by file_id
            symbols_by_file: dict[str, list] = {}
            for s in symbol_rows:
                symbols_by_file.setdefault(str(s.file_id), []).append(s)

            # Batch query 2: adjacent (previous) chunks
            prev_lookups = []
            for r in results:
                ci = r.get("chunk_index")
                if ci is not None and ci > 0:
                    prev_lookups.append({"fid": r["file_id"], "ci": ci - 1})

            adjacent_chunks: dict[tuple[str, int], str] = {}
            if prev_lookups:
                # Build values list for batch lookup
                fid_list = [p["fid"] for p in prev_lookups]
                ci_list = [p["ci"] for p in prev_lookups]
                adj_rows = session.execute(
                    text("""
                        SELECT file_id, chunk_index, content
                        FROM code_chunks
                        WHERE file_id = ANY(CAST(:fids AS uuid[])) AND chunk_index = ANY(:cis)
                    """),
                    {"fids": fid_list, "cis": ci_list},
                ).fetchall()
                for row in adj_rows:
                    adjacent_chunks[(str(row.file_id), row.chunk_index)] = row.content

            # Enrich each result
            for r in results:
                prefix_parts = []
                file_id = r.get("file_id")
                if not file_id:
                    continue

                # Find tightest enclosing symbol (smallest span containing chunk)
                file_symbols = symbols_by_file.get(file_id, [])
                best_symbol = None
                best_span = float("inf")
                for s in file_symbols:
                    if s.start_line <= r["start_line"] and s.end_line >= r["end_line"]:
                        span = s.end_line - s.start_line
                        if span < best_span:
                            best_span = span
                            best_symbol = s

                if best_symbol:
                    if best_symbol.signature:
                        prefix_parts.append(
                            f"# {best_symbol.symbol_type}: {best_symbol.signature}"
                        )
                    if best_symbol.docstring:
                        doc_lines = best_symbol.docstring.strip().split("\n")[:3]
                        truncated = "\n# ".join(doc_lines)
                        if len(truncated) > 200:
                            truncated = truncated[:200] + "..."
                        prefix_parts.append(f"# Docstring: {truncated}")

                # Previous chunk context (last 5 lines)
                ci = r.get("chunk_index")
                if ci is not None and ci > 0:
                    prev_content = adjacent_chunks.get((file_id, ci - 1))
                    if prev_content:
                        prev_lines = prev_content.strip().split("\n")[-5:]
                        prefix_parts.append(
                            "# preceding context:\n# " + "\n# ".join(prev_lines)
                        )

                if prefix_parts:
                    prefix = "\n".join(prefix_parts)
                    # Cap total prefix size
                    if len(prefix) > 500:
                        prefix = prefix[:500] + "\n# ..."
                    r["content"] = prefix + "\n\n" + r["content"]

    except Exception as e:
        # Enrichment is best-effort — don't fail the search
        logger.warning("Context enrichment failed, returning raw results", error=str(e))

    return results


class SearchService:
    """Service for semantic code search.
    
    ACCESS CONTROL:
    - Users can only search repos in their collection (user_repositories)
    - Public repos can be added to collection; private repos only by indexer
    """

    def __init__(self, user_id: str | None = None):
        """Initialize the search service.
        
        Args:
            user_id: User ID for access control.
        """
        self.config = get_config()
        self.user_id = user_id
        self._embedding_generator = None
        self._vector_store = None
    
    @property
    def embedding_generator(self):
        """Lazy-load embedding generator."""
        if self._embedding_generator is None:
            self._embedding_generator = EmbeddingGenerator()
        return self._embedding_generator
    
    @property
    def vector_store(self):
        """Lazy-load vector store."""
        if self._vector_store is None:
            self._vector_store = get_vector_store()
        return self._vector_store

    def search_code(
        self,
        query: str,
        repo_ids: list[str] | None = None,
        language: str | None = None,
        file_pattern: str | None = None,
        top_k: int = 10,
        user_id: str | None = None,
    ) -> dict:
        """Search code using semantic search.
        
        ACCESS CONTROL: Only searches repos in user's collection.
        
        Args:
            query: Search query (natural language or keywords)
            repo_ids: Optional list of repository IDs to search (must be in collection)
            language: Filter by programming language
            file_pattern: Filter by file path pattern
            top_k: Number of results to return
            user_id: User ID for access control (overrides constructor user_id)
            
        Returns:
            Dict with search results
        """
        start_time = time.time()
        effective_user_id = user_id or self.user_id
        
        # Require user_id
        if not effective_user_id:
            return {
                "success": False,
                "query": query,
                "error": "Authentication required",
                "message": "You must be authenticated to search",
            }
        
        try:
            # Generate query embedding
            t_embed = time.time()
            query_embedding = self.embedding_generator.generate_single(query)
            embed_ms = (time.time() - t_embed) * 1000

            # Over-fetch for post-retrieval quality pipeline
            # Need extra candidates for: pattern filtering, symbol boosting
            # reordering, dynamic threshold pruning, and MMR selection
            fetch_k = max(top_k * 3, 20)

            # Search pgvector (access control is in the vector store)
            t_db = time.time()
            raw_results = self.vector_store.search(
                query_embedding=query_embedding,
                user_id=effective_user_id,
                repo_ids=repo_ids,
                language=language,
                top_k=fetch_k,
            )
            db_ms = (time.time() - t_db) * 1000

            # Apply file pattern filter early (before quality pipeline)
            if file_pattern:
                import fnmatch
                raw_results = [
                    r for r in raw_results
                    if fnmatch.fnmatch(r.get("file_path", ""), file_pattern)
                ]

            # --- Quality pipeline ---

            # 1. Symbol-aware score boosting
            query_symbols = _extract_query_symbols(query)
            if query_symbols:
                _apply_symbol_boost(raw_results, query_symbols)

            # 2. Metadata-aware scoring (demote tests/docs/examples)
            _apply_metadata_scoring(raw_results)

            # Re-sort after boosting + metadata adjustments
            raw_results.sort(key=lambda r: r["similarity"], reverse=True)

            # 3. Cross-encoder reranking (blended with vector similarity)
            #    Disabled by default — ms-marco model hurts code search quality.
            #    Enable with SYNSC_ENABLE_RERANKER=true when a code-specific
            #    cross-encoder is available.
            if (
                len(raw_results) > 1
                and os.getenv("SYNSC_ENABLE_RERANKER", "").lower() in ("true", "1")
            ):
                try:
                    from synsc.services.reranker import get_reranker
                    reranker = get_reranker()
                    raw_results = reranker.rerank(
                        query=query,
                        results=raw_results,
                    )
                except Exception as e:
                    logger.warning(
                        "Reranker unavailable, falling back to vector similarity",
                        error=str(e),
                    )

            # 4. Dynamic similarity threshold
            raw_results = _apply_dynamic_threshold(
                raw_results,
                min_absolute=self.config.search.min_similarity_score,
            )

            # 5. MMR diversification (select top_k from remaining candidates)
            raw_results = _apply_mmr(
                raw_results,
                query_embedding=query_embedding,
                top_k=top_k,
            )

            # 6. Context enrichment (attach docstrings/signatures)
            raw_results = _enrich_results_with_context(raw_results)

            # Format results
            results = []
            for r in raw_results:
                results.append({
                    "repo_id": r["repo_id"],
                    "repo_name": r.get("repo_name", ""),
                    "file_path": r.get("file_path", ""),
                    "chunk_id": r["chunk_id"],
                    "content": r["content"],
                    "start_line": r["start_line"],
                    "end_line": r["end_line"],
                    "language": r.get("language"),
                    "relevance_score": r["similarity"],
                    "chunk_type": r.get("chunk_type", "code"),
                    "is_public": r.get("is_public", True),
                })
            
            elapsed_time = (time.time() - start_time) * 1000

            logger.debug(
                "Search timing breakdown",
                embed_ms=round(embed_ms, 1),
                db_ms=round(db_ms, 1),
                total_ms=round(elapsed_time, 1),
                pipeline_ms=round(elapsed_time - embed_ms - db_ms, 1),
                results=len(results),
            )

            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
                "search_time_ms": elapsed_time,
                "timing": {
                    "embedding_ms": round(embed_ms, 1),
                    "db_search_ms": round(db_ms, 1),
                    "pipeline_ms": round(elapsed_time - embed_ms - db_ms, 1),
                },
            }
            
        except Exception as e:
            logger.error("Search failed", error=str(e), user_id=effective_user_id)
            return {
                "success": False,
                "query": query,
                "error": str(e),
                "message": f"Search failed: {e}",
            }

    def get_file(
        self,
        repo_id: str,
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        user_id: str | None = None,
    ) -> dict:
        """Get file content from a repository.
        
        ACCESS CONTROL:
        - Public repos: User must have it in their collection
        - Private repos: Only the indexer can access
        
        Args:
            repo_id: Repository ID
            file_path: Path to file within repository
            start_line: Starting line (1-indexed)
            end_line: Ending line
            user_id: User ID for authorization
            
        Returns:
            Dict with file content
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
                }
            
            # Check access control
            if not repo.can_user_access(effective_user_id):
                return {
                    "success": False,
                    "error": "Access denied",
                    "message": "You don't have access to this private repository",
                }
            
            # Check if in user's collection (for public repos)
            if effective_user_id:
                user_repo = session.query(UserRepository).filter(
                    UserRepository.user_id == effective_user_id,
                    UserRepository.repo_id == repo_id,
                ).first()
                
                if not user_repo and repo.is_public:
                    return {
                        "success": False,
                        "error": "Not in collection",
                        "message": "Add this repository to your collection first",
                    }
            
            db_file = session.query(RepositoryFile).filter(
                RepositoryFile.repo_id == repo_id,
                RepositoryFile.file_path == file_path,
            ).first()
            
            if not db_file:
                return {
                    "success": False,
                    "error": "File not found",
                }
            
            content = None
            source = None
            
            # Try to read from local clone first (if available)
            if repo.local_path:
                full_path = Path(repo.local_path) / file_path
                if full_path.exists():
                    content = full_path.read_text(encoding="utf-8", errors="ignore")
                    source = "local"
            
            # Fall back to reconstructing from chunks (cloud mode)
            if content is None:
                content = self._reconstruct_file_from_chunks(session, db_file.file_id)
                if content is not None:
                    source = "chunks"
            
            if content is None:
                return {
                    "success": False,
                    "error": "File content not available",
                    "message": "Local clone not found and no chunks indexed for this file",
                }
            
            total_lines = content.count("\n") + 1
            
            # Apply line range
            if start_line or end_line:
                lines = content.split("\n")
                start = (start_line or 1) - 1
                end = end_line or len(lines)
                content = "\n".join(lines[start:end])
            
            return {
                "success": True,
                "repo_id": repo_id,
                "file_path": file_path,
                "content": content,
                "language": db_file.language,
                "total_lines": total_lines,
                "start_line": start_line or 1,
                "end_line": end_line or total_lines,
                "source": source,  # "local" or "chunks"
                "is_public": repo.is_public,
            }
    
    def _reconstruct_file_from_chunks(self, session, file_id: str) -> str | None:
        """Reconstruct file content from indexed chunks.
        
        Chunks are ordered by chunk_index and concatenated.
        Note: This may not perfectly reproduce the original file due to
        overlap removal and chunking boundaries.
        
        Args:
            session: Database session
            file_id: File identifier
            
        Returns:
            Reconstructed file content, or None if no chunks found
        """
        chunks = session.query(CodeChunk).filter(
            CodeChunk.file_id == file_id
        ).order_by(CodeChunk.chunk_index).all()
        
        if not chunks:
            return None
        
        # Simple reconstruction: join chunks, removing overlap
        # This is approximate since chunk overlap means content duplication
        content_parts = []
        last_end_line = 0
        
        for chunk in chunks:
            if chunk.start_line > last_end_line:
                # No overlap with previous chunk
                content_parts.append(chunk.content)
            else:
                # Overlapping content - skip lines we've already added
                lines = chunk.content.split("\n")
                skip_lines = last_end_line - chunk.start_line + 1
                if skip_lines < len(lines):
                    content_parts.append("\n".join(lines[skip_lines:]))
            
            last_end_line = chunk.end_line
        
        return "\n".join(content_parts) if content_parts else None
