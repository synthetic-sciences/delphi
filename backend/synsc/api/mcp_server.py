"""
Unified MCP Server for Synsc Context.

Provides tools for code repository, research paper, and HuggingFace dataset indexing.
"""

import contextvars
import json
import os
import time
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logger = structlog.get_logger(__name__)

# Context variables for request-scoped auth (set by http_server.py /mcp proxy)
_current_api_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_api_key", default=None
)
_current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_user_id", default=None
)


def set_current_api_key(api_key: str | None) -> None:
    """Set the API key for the current request context."""
    _current_api_key.set(api_key)


def get_current_api_key() -> str | None:
    """Get the API key from the current request context."""
    return _current_api_key.get()


def set_current_user_id(user_id: str | None) -> None:
    """Set the user ID for the current request context."""
    _current_user_id.set(user_id)


def get_current_user_id() -> str | None:
    """Get the user ID from the current request context."""
    return _current_user_id.get()


def _log_activity(
    user_id: str,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    query: str | None = None,
    results_count: int | None = None,
    duration_ms: int | None = None,
    metadata: dict | None = None,
) -> None:
    """Log a user activity to the activity_log table (best-effort)."""
    try:
        from synsc.database.connection import get_session
        from sqlalchemy import text
        with get_session() as session:
            session.execute(
                text(
                    "INSERT INTO activity_log "
                    "(user_id, action, resource_type, resource_id, query, results_count, duration_ms, metadata) "
                    "VALUES (:uid, :action, :rtype, :rid, :query, :rcnt, :dur, :meta)"
                ),
                {
                    "uid": user_id,
                    "action": action,
                    "rid": resource_id,
                    "rtype": resource_type,
                    "query": query,
                    "rcnt": results_count,
                    "dur": duration_ms,
                    "meta": json.dumps(metadata) if metadata else None,
                },
            )
            session.commit()
    except Exception as e:
        logger.warning("Failed to log activity", error=str(e))


def create_server() -> FastMCP:
    """Create the unified MCP server with all tools."""

    instructions = """
# Synsc Context - Unified MCP Server

Provides deep context to AI agents through:
- **Code Repository Indexing** - Index GitHub repos, search code, find symbols
- **Research Paper Indexing** - Index arXiv papers, extract citations, equations
- **HuggingFace Dataset Indexing** - Index dataset cards, search metadata

## Code Tools:
- `index_repository(url, branch)` - Index a GitHub repository
- `list_repositories()` - List indexed repositories
- `search_code(query, ...)` - Semantic code search
- `get_file(repo_id, file_path)` - Get file content
- `search_symbols(name, ...)` - Find functions, classes
- `analyze_repository(repo_id)` - Deep code analysis

## Paper Tools:
- `index_paper(source)` - Index from arXiv or PDF
- `list_papers(limit, offset)` - List indexed papers
- `search_papers(query, top_k)` - Semantic paper search
- `get_paper(paper_id)` - Get paper content
- `get_citations(paper_id)` - Extract citations
- `get_equations(paper_id)` - Extract equations
- `generate_report(paper_id)` - Generate markdown report

## Dataset Tools:
- `index_dataset(source)` - Index HuggingFace dataset card
- `list_datasets(limit, offset)` - List indexed datasets
- `search_datasets(query, top_k)` - Semantic dataset search
- `get_dataset(dataset_id)` - Get dataset details
- `delete_dataset(dataset_id)` - Delete a dataset
"""

    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
        allowed_hosts=["*"],
        allowed_origins=[
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
        ],
    )

    server = FastMCP(
        name="synsc-context",
        instructions=instructions,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        transport_security=transport_security,
    )

    # ------------------------------------------------------------------
    # Scoped MCP surfaces (Nia parity).
    #
    # ``SYNSC_MCP_PROFILE`` selects a subset of tools to expose. Agents
    # pay a token cost for every tool definition in the MCP handshake;
    # exposing only the relevant subset for a workflow is a free win.
    #
    # Profile values:
    #   all     — every tool (default)
    #   code    — repos: index/search/symbols/context/analyze
    #   papers  — papers + research + datasets
    #   docs    — docs / sources / generic search / resolve
    #   thesis  — Thesis graph tools
    #   minimal — resolve_source + search + read_source (the 3-tool starter)
    # ------------------------------------------------------------------
    _profile = os.environ.get("SYNSC_MCP_PROFILE", "all").strip().lower()
    _profile_groups: dict[str, set[str]] = {
        "all": {"code", "papers", "datasets", "research", "docs", "thesis", "sources", "minimal"},
        "code": {"code", "sources", "minimal"},
        "papers": {"papers", "research", "datasets", "sources", "minimal"},
        "docs": {"docs", "sources", "minimal"},
        "thesis": {"thesis", "sources", "minimal"},
        "minimal": {"minimal"},
    }
    _enabled_groups = _profile_groups.get(_profile, _profile_groups["all"])
    if _profile not in _profile_groups:
        logger.warning(
            "unknown SYNSC_MCP_PROFILE, falling back to 'all'",
            profile=_profile,
        )

    def _tool_in(*groups: str):
        """Wrap ``@server.tool()`` with a profile gate.

        Usage: ``@_tool_in("code")`` instead of ``@server.tool()``. If the
        tool's group(s) don't intersect the active profile the decorator
        returns the function un-registered (still importable / unit-testable).
        """
        enabled = any(g in _enabled_groups for g in groups)
        if not enabled:
            def _skip(fn):  # noqa: ANN001
                logger.debug("mcp: skipping tool by profile", tool=fn.__name__, groups=groups)
                return fn
            return _skip
        return server.tool()

    # ==========================================================================
    # AUTH HELPERS
    # ==========================================================================

    def get_authenticated_user_id() -> str | None:
        """Get user_id for the current request.

        Two modes:
          - HTTP proxy: user_id is set in _current_user_id by http_server.py
          - stdio (direct MCP): validate SYNSC_API_KEY env var against the DB
        """
        # Check contextvars first (set by HTTP /mcp proxy)
        uid = _current_user_id.get()
        if uid:
            return uid

        # Stdio mode: validate from env var
        import hashlib
        api_key = _current_api_key.get() or os.environ.get("SYNSC_API_KEY")
        if not api_key:
            return None

        try:
            from synsc.database.connection import get_session
            from sqlalchemy import text

            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            with get_session() as session:
                row = session.execute(
                    text("SELECT user_id FROM api_keys WHERE key_hash = :hash AND is_revoked = false LIMIT 1"),
                    {"hash": key_hash},
                ).mappings().first()
                return row["user_id"] if row else None
        except Exception as e:
            logger.error("Failed to validate API key", error=str(e))
            return None

    # ==========================================================================
    # CODE REPOSITORY TOOLS
    # ==========================================================================

    @_tool_in("code")
    async def index_repository(
        url: str,
        branch: str | None = None,
        deep_index: bool = False,
        force_reindex: bool = False,
        quality_mode: str | None = None,
        include_tests: bool | None = None,
        include_docs: bool | None = None,
        include_examples: bool | None = None,
    ) -> dict[str, Any]:
        """Index a GitHub repository for semantic code search (agent-grade by default).

        If the repository was previously indexed and has new commits, performs a
        diff-aware re-index — only changed files are re-processed, preserving the
        repo_id and all user collection links.

        Quality mode (default 'agent' for MCP):
          - 'agent': index everything useful (tests, docs, examples, configs,
            manifests, dotfiles), AST chunking on, hybrid retrieval, rerank top
            50, lower min-chunk threshold so small but meaningful files are kept.
          - 'balanced': skip nothing structural, AST chunking on, no rerank.
          - 'fast': legacy behavior — skip tests/docs/examples, turbo chunking.

        Args:
            url: GitHub repository URL (e.g., "facebook/react" or full URL)
            branch: Branch to index. None auto-detects the repo's default branch.
            deep_index: Full AST chunking per function/class. Implied by agent mode.
            force_reindex: Skip diff detection and fully re-index from scratch.
            quality_mode: 'agent' (default for MCP), 'balanced', or 'fast'.
            include_tests: Force include/exclude test files independent of mode.
            include_docs: Force include/exclude docs/markdown independent of mode.
            include_examples: Force include/exclude examples/fixtures.

        Returns:
            Dictionary with repo_id, files_indexed, chunks_created, diff_stats,
            and the quality_mode that was actually applied.
        """
        import asyncio
        from synsc.config import get_config
        from synsc.services.indexing_service import IndexingService

        # MCP gets agent-quality by default unless caller passes 'fast'/'balanced'.
        if quality_mode is None:
            quality_mode = get_config().quality.mcp_default_mode

        service = IndexingService()
        user_id = get_authenticated_user_id()

        result = await asyncio.to_thread(
            service.index_repository, url, branch, user_id=user_id,
            deep_index=deep_index, force_reindex=force_reindex,
            quality_mode=quality_mode,
            include_tests=include_tests,
            include_docs=include_docs,
            include_examples=include_examples,
        )
        # Stamp the mode that was applied so the agent knows what it got.
        if isinstance(result, dict):
            result.setdefault("quality_mode", quality_mode)
        uid = get_authenticated_user_id()
        if uid:
            _log_activity(
                uid, "index_repository", resource_type="repository",
                metadata={"url": url, "branch": branch, "quality_mode": quality_mode},
            )
        return result

    @_tool_in("code")
    def list_repositories(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List all indexed repositories.

        Args:
            limit: Maximum repositories to return (max 200)
            offset: Pagination offset

        Returns:
            Dictionary with repositories list and total count
        """
        from synsc.services.indexing_service import IndexingService

        limit = min(limit, 200)
        service = IndexingService()
        user_id = get_authenticated_user_id()

        result = service.list_repositories(limit, offset, user_id=user_id)
        uid = get_authenticated_user_id()
        if uid:
            _log_activity(uid, "list_repositories", resource_type="repository")
        return result

    @_tool_in("code")
    def get_repository(repo_id: str) -> dict[str, Any]:
        """Get detailed information about an indexed repository.

        Args:
            repo_id: Repository identifier

        Returns:
            Repository details including stats, languages, etc.
        """
        from synsc.services.indexing_service import IndexingService

        service = IndexingService()
        user_id = get_authenticated_user_id()

        result = service.get_repository(repo_id, user_id=user_id)
        return result

    @_tool_in("code")
    def delete_repository(repo_id: str) -> dict[str, Any]:
        """Delete an indexed repository.

        Args:
            repo_id: Repository identifier

        Returns:
            Success status
        """
        from synsc.services.indexing_service import IndexingService

        service = IndexingService()
        user_id = get_authenticated_user_id()

        result = service.delete_repository(repo_id, user_id=user_id)
        return result

    @_tool_in("code")
    async def search_code(
        query: str,
        repo_ids: list[str] | None = None,
        language: str | None = None,
        file_pattern: str | None = None,
        top_k: int = 10,
        quality_mode: str | None = None,
    ) -> dict[str, Any]:
        """Hybrid code search (agent-quality by default for MCP).

        Runs five retrieval branches and fuses them: vector embedding
        (semantic), BM25 / full-text (keyword), exact symbol lookup,
        exact path/glob match, and trigram fallback. The cross-encoder
        reranker re-orders the top fused window.

        Each result carries ``candidate_sources`` showing which branches
        contributed — vital for debugging "why did Delphi miss this?".

        Args:
            query: Natural language search query
            repo_ids: Optional list of repo IDs to search
            language: Filter by programming language
            file_pattern: Glob pattern for file paths (applied to the path
                branch BEFORE vector retrieval, so exact-file intent is
                never filtered out)
            top_k: Number of results to return
            quality_mode: Override the retrieval mode for this call. None =
                MCP default (agent). Pass 'fast' for legacy pure-vector.

        Returns:
            Search results with code snippets, relevance scores, and a
            ``hybrid`` block showing how many candidates each branch hit.
        """
        import asyncio
        from synsc.config import get_config
        from synsc.services.search_service import SearchService

        if quality_mode is None:
            quality_mode = get_config().quality.mcp_default_mode

        service = SearchService()
        user_id = get_authenticated_user_id()

        result = await asyncio.to_thread(
            service.search_code,
            query=query, repo_ids=repo_ids, language=language,
            file_pattern=file_pattern, top_k=top_k, user_id=user_id,
            quality_mode=quality_mode,
        )
        uid = get_authenticated_user_id()
        if uid:
            _log_activity(uid, "search_code", resource_type="repository", query=query, results_count=len(result.get("results", [])))
        return result

    @_tool_in("code")
    def get_file(
        repo_id: str,
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        """Get file content from an indexed repository.

        Args:
            repo_id: Repository identifier
            file_path: Path to file within repository
            start_line: Optional starting line (1-indexed)
            end_line: Optional ending line

        Returns:
            File content and metadata
        """
        from synsc.services.search_service import SearchService

        service = SearchService()
        user_id = get_authenticated_user_id()

        result = service.get_file(repo_id, file_path, start_line, end_line, user_id=user_id)
        uid = get_authenticated_user_id()
        if uid:
            _log_activity(uid, "get_file", resource_type="repository", resource_id=repo_id, metadata={"file_path": file_path})
        return result

    @_tool_in("code")
    def search_symbols(
        name: str,
        repo_ids: list[str] | None = None,
        symbol_type: str | None = None,
        language: str | None = None,
        top_k: int = 20,
    ) -> dict[str, Any]:
        """Search for code symbols (functions, classes, methods).

        Args:
            name: Symbol name to search for (partial match)
            repo_ids: Optional list of repo IDs to search
            symbol_type: Filter by type (function, class, method)
            language: Filter by programming language
            top_k: Number of results to return

        Returns:
            Matching symbols with signatures and locations
        """
        from synsc.services.symbol_service import SymbolService

        service = SymbolService()
        user_id = get_authenticated_user_id()

        result = service.search_symbols(
            name=name, repo_ids=repo_ids, symbol_type=symbol_type,
            language=language, top_k=top_k, user_id=user_id,
        )
        uid = get_authenticated_user_id()
        if uid:
            _log_activity(uid, "search_symbols", resource_type="repository", query=name, results_count=len(result.get("results", [])))
        return result

    @_tool_in("code")
    def analyze_repository(repo_id: str) -> dict[str, Any]:
        """Get comprehensive analysis of an indexed repository.

        Provides deep understanding including:
        - Directory structure with annotations
        - Entry points (main files, CLI, API endpoints)
        - Dependencies from manifest files
        - Framework detection
        - Architecture pattern detection

        Args:
            repo_id: Repository identifier

        Returns:
            Comprehensive analysis results
        """
        from synsc.services.analysis_service import AnalysisService

        service = AnalysisService()
        user_id = get_authenticated_user_id()

        result = service.analyze_repository(repo_id, user_id=user_id)
        return result

    @_tool_in("code")
    def get_directory_structure(
        repo_id: str,
        max_depth: int = 4,
        annotate: bool = True,
    ) -> dict[str, Any]:
        """Get the directory structure of an indexed repository.

        Returns a tree representation of the repository's file structure
        with optional annotations explaining the purpose of each directory.

        Args:
            repo_id: Repository identifier (UUID)
            max_depth: Maximum directory depth to show (default: 4)
            annotate: Whether to add purpose annotations to directories (default: true)
        """
        from synsc.services.analysis_service import AnalysisService

        service = AnalysisService()
        user_id = get_authenticated_user_id()

        result = service.get_directory_structure(
            repo_id, max_depth=max_depth, annotate=annotate, user_id=user_id,
        )
        return result

    @_tool_in("code")
    def get_symbol(symbol_id: str) -> dict[str, Any]:
        """Get detailed information about a specific code symbol.

        Returns complete symbol details including full docstring,
        parameters with types, return type, and decorators.

        Args:
            symbol_id: Symbol identifier (UUID from search_symbols)
        """
        from synsc.services.symbol_service import SymbolService

        service = SymbolService()
        user_id = get_authenticated_user_id()

        result = service.get_symbol(symbol_id, user_id=user_id)
        return result

    @_tool_in("code")
    async def build_context_pack(
        query: str,
        repo_ids: list[str] | None = None,
        quality_mode: str | None = None,
        token_budget: int = 6000,
        include_architecture: bool = True,
        include_tests: bool = True,
        include_docs: bool = True,
        include_examples: bool = True,
        include_configs: bool = True,
    ) -> dict[str, Any]:
        """Build an agent-ready context pack for a query.

        Instead of returning isolated snippets, this tool assembles a
        structured payload designed for direct agent consumption:

          - **Primary hits** from hybrid search (vector+BM25+symbol+path).
          - **Enclosing function/class bodies** for each primary hit.
          - **Adjacent chunks** (N-1 / N+1) for flow context.
          - **Same-class siblings** so the agent sees the full API surface.
          - **Imports/dependencies** of each primary file.
          - **Linked tests** that mention the matched symbol.
          - **Linked docs / examples / configs** that reference the API.
          - **Symbol details**: signatures + docstrings.
          - **Architecture summary** for broad queries (top dirs, lang split).
          - **Why-matched** rationale and stable file_path:line ranges.

        A token budgeter compresses by *utility* (tested implementation
        beats long example file) rather than raw similarity. A re-query
        planner kicks in when the budget is under-filled or a key
        category is missing.

        Args:
            query: The agent's question.
            repo_ids: Optional list of repo IDs to scope the pack to.
            quality_mode: 'fast'/'balanced'/'agent' (default agent).
            token_budget: Approximate target token budget for the pack body.
            include_architecture: Add a directory-level overview for broad queries.
            include_tests/docs/examples/configs: Toggle per-category inclusion.
        """
        import asyncio
        from synsc.config import get_config
        from synsc.services.context_pack import build_context_pack as _build_pack

        if quality_mode is None:
            quality_mode = get_config().quality.mcp_default_mode

        user_id = get_authenticated_user_id()
        if not user_id:
            return {
                "success": False,
                "error_code": "auth_required",
                "message": "Authentication required for context pack",
            }

        result = await asyncio.to_thread(
            _build_pack,
            query=query, user_id=user_id, repo_ids=repo_ids,
            quality_mode=quality_mode,
            token_budget=token_budget,
            include_architecture=include_architecture,
            include_tests=include_tests,
            include_docs=include_docs,
            include_examples=include_examples,
            include_configs=include_configs,
        )
        _log_activity(
            user_id, "build_context_pack",
            resource_type="repository", query=query,
            metadata={"quality_mode": quality_mode, "token_budget": token_budget},
        )
        return {"success": True, **result}

    @_tool_in("code")
    def get_context(
        chunk_id: str,
        radius: int = 1,
        include_enclosing: bool = True,
        include_same_class: bool = True,
    ) -> dict[str, Any]:
        """Fetch one chunk plus its surrounding context.

        Returns the chunk itself, ``radius`` chunks above and below (in the
        same file), the tightest enclosing function/class body, and any
        same-class sibling chunks. Use this when you need to drill into a
        specific search hit without re-running a query.

        Args:
            chunk_id: The chunk identifier (UUID) from a search result.
            radius: How many adjacent chunks to fetch on each side (default 1).
            include_enclosing: Include the enclosing symbol body (default true).
            include_same_class: Include same-class sibling chunks (default true).
        """
        from synsc.services.context_pack import get_chunk_context

        user_id = get_authenticated_user_id()
        if not user_id:
            return {
                "success": False,
                "error_code": "auth_required",
                "message": "Authentication required",
            }
        result = get_chunk_context(
            chunk_id=chunk_id,
            user_id=user_id,
            radius=radius,
            include_enclosing=include_enclosing,
            include_same_class=include_same_class,
        )
        if "error" in result:
            return {"success": False, "error_code": result["error"]}
        return {"success": True, **result}

    @_tool_in("code")
    def remove_from_collection(repo_id: str) -> dict[str, Any]:
        """Remove a repository from your collection without deleting it.

        This removes the repo from YOUR searchable collection without deleting
        the actual indexed data. The repo remains available for other users.

        Args:
            repo_id: Repository identifier (UUID)
        """
        from synsc.services.indexing_service import IndexingService

        service = IndexingService()
        user_id = get_authenticated_user_id()

        result = service.remove_from_collection(repo_id, user_id=user_id)
        return result

    # ==========================================================================
    # RESEARCH PAPER TOOLS
    # ==========================================================================

    @_tool_in("papers")
    async def index_paper(source: str) -> dict[str, Any]:
        """Index a research paper from arXiv or local PDF.

        Supports multiple formats:
        - arXiv URLs: "https://arxiv.org/abs/2401.12345"
        - arXiv IDs: "2401.12345"
        - Local PDF: "/path/to/paper.pdf"

        Features global deduplication - if paper already indexed,
        returns existing paper ID instantly.

        Args:
            source: arXiv URL/ID or local PDF path

        Returns:
            Dictionary with paper_id, title, authors, chunks, etc.
        """
        import asyncio
        import tempfile
        import os
        from synsc.services.paper_service import get_paper_service
        from synsc.core.arxiv_client import parse_arxiv_id, download_arxiv_pdf, get_arxiv_metadata, ArxivError

        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)

        def _do_index():
            # Check if source is a local PDF
            if os.path.isfile(source) and source.lower().endswith(".pdf"):
                return service.index_paper(pdf_path=source, source="upload")

            # Treat as arXiv URL or ID
            try:
                arxiv_id = parse_arxiv_id(source) if "arxiv" in source.lower() else source.strip()
            except ArxivError:
                arxiv_id = source.strip()

            arxiv_metadata = None
            try:
                arxiv_metadata = get_arxiv_metadata(arxiv_id)
            except Exception:
                pass

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                pdf_path = tmp.name
            try:
                download_arxiv_pdf(arxiv_id, pdf_path)
                return service.index_paper(
                    pdf_path=pdf_path, source="arxiv",
                    arxiv_id=arxiv_id, arxiv_metadata=arxiv_metadata,
                )
            finally:
                try:
                    os.unlink(pdf_path)
                except OSError:
                    pass

        result = await asyncio.to_thread(_do_index)

        uid = get_authenticated_user_id()
        if uid:
            _log_activity(uid, "index_paper", resource_type="paper", metadata={"source": source})
        return result

    @_tool_in("papers")
    def list_papers(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List all indexed papers.

        Args:
            limit: Maximum papers to return (max 200)
            offset: Pagination offset

        Returns:
            Dictionary with papers list and total count
        """
        from synsc.services.paper_service import get_paper_service

        limit = min(limit, 200)
        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)

        papers = service.list_papers(limit=limit)
        result = {"success": True, "papers": papers, "total": len(papers)}
        uid = get_authenticated_user_id()
        if uid:
            _log_activity(uid, "list_papers", resource_type="paper")
        return result

    @_tool_in("papers")
    def get_paper(paper_id: str, section: str | None = None) -> dict[str, Any]:
        """Get full paper content, optionally filtered to a single section.

        Args:
            paper_id: Paper identifier.
            section: Optional section filter — one of 'abstract',
                'introduction', 'methods', 'results', 'discussion',
                'conclusion', 'references', 'related work', or a regex
                that matches `chunk.section_title`.
        """
        from synsc.services.paper_service import get_paper_service

        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)

        try:
            paper = service.get_paper(paper_id, section=section)
        except ValueError as e:
            return {
                "success": False,
                "error_code": "invalid_input",
                "message": str(e),
            }
        if not paper:
            return {"success": False, "error_code": "not_found", "message": "Paper not found"}
        return {"success": True, **paper}

    @_tool_in("papers")
    async def search_papers(
        query: str,
        top_k: int = 5,
        topic: str | None = None,
        tokens: int | None = None,
    ) -> dict[str, Any]:
        """Search papers using semantic search.

        Args:
            query: Natural language search query
            top_k: Number of results to return
            topic: Optional section/keyword filter applied post-retrieval.
            tokens: Optional total token budget across all returned hits.

        Returns:
            Matching papers with relevance scores
        """
        import asyncio

        from synsc.services.budget import (
            budget_results,
            filter_results_by_topic,
        )
        from synsc.services.paper_service import get_paper_service

        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)

        result = await asyncio.to_thread(service.search_papers, query=query, top_k=top_k)
        if topic and isinstance(result.get("results"), list):
            result["results"] = filter_results_by_topic(
                result["results"],
                topic,
                text_keys=("content", "section_title", "section"),
            )
        if tokens and isinstance(result.get("results"), list):
            result["results"] = budget_results(
                result["results"], tokens, text_key="content"
            )
        uid = get_authenticated_user_id()
        if uid:
            _log_activity(
                uid,
                "search_papers",
                resource_type="paper",
                query=query,
                results_count=len(result.get("results", [])),
                metadata={"topic": topic, "tokens": tokens},
            )
        return result

    @_tool_in("papers")
    def get_citations(paper_id: str) -> dict[str, Any]:
        """Extract all citations from a paper.

        Args:
            paper_id: Paper identifier

        Returns:
            List of citations with context and links to indexed papers
        """
        from synsc.services.paper_service import get_paper_service

        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)

        citations = service.get_citations(paper_id)
        result = {
            "success": True,
            "paper_id": paper_id,
            "citations": citations,
            "total_citations": len(citations),
        }
        return result

    @_tool_in("papers")
    def get_equations(paper_id: str) -> dict[str, Any]:
        """Extract all equations from a paper.

        Args:
            paper_id: Paper identifier

        Returns:
            List of LaTeX equations with context
        """
        from synsc.services.paper_service import get_paper_service

        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)

        equations = service.get_equations(paper_id)
        result = {
            "success": True,
            "paper_id": paper_id,
            "equations": equations,
            "total_equations": len(equations),
        }
        return result

    @_tool_in("papers")
    def get_code_snippets(paper_id: str) -> dict[str, Any]:
        """Extract all code snippets from a paper.

        Args:
            paper_id: Paper identifier

        Returns:
            List of code blocks with language detection
        """
        from synsc.database.connection import get_session
        from sqlalchemy import text

        user_id = get_authenticated_user_id()

        # Code snippets are stored in paper_code_snippets table
        try:
            with get_session() as session:
                rows = session.execute(
                    text("SELECT * FROM paper_code_snippets WHERE paper_id = :pid"),
                    {"pid": paper_id},
                ).mappings().all()
                snippets = [dict(r) for r in rows]
        except Exception:
            snippets = []

        result = {
            "success": True,
            "paper_id": paper_id,
            "snippets": snippets,
            "total_snippets": len(snippets),
        }
        return result

    @_tool_in("papers")
    def generate_report(paper_id: str) -> dict[str, Any]:
        """Generate comprehensive markdown report for a paper.

        Creates a detailed report optimized for LLM consumption.

        Args:
            paper_id: Paper identifier

        Returns:
            Comprehensive markdown report
        """
        from synsc.services.paper_service import get_paper_service

        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)

        paper = service.get_paper(paper_id)
        if not paper:
            return {"success": False, "error": "Paper not found"}

        # Build a markdown report from paper data
        title = paper.get("title", "Untitled")
        authors = paper.get("authors", "Unknown")
        abstract = paper.get("abstract", "")
        chunks = paper.get("chunks", [])

        citations = service.get_citations(paper_id)
        equations = service.get_equations(paper_id)

        report_lines = [
            f"# {title}",
            f"\n**Authors**: {authors}",
            f"\n## Abstract\n\n{abstract}",
        ]

        if chunks:
            report_lines.append("\n## Content\n")
            for chunk in chunks:
                section = chunk.get("section_title", "")
                if section:
                    report_lines.append(f"\n### {section}\n")
                report_lines.append(chunk.get("content", ""))

        if citations:
            report_lines.append(f"\n## Citations ({len(citations)})\n")
            for c in citations[:20]:
                report_lines.append(f"- {c.get('raw_text', c.get('citation_text', ''))}")

        if equations:
            report_lines.append(f"\n## Equations ({len(equations)})\n")
            for eq in equations[:20]:
                report_lines.append(f"- `{eq.get('latex', eq.get('equation_text', ''))}`")

        result = {
            "success": True,
            "paper_id": paper_id,
            "title": title,
            "report": "\n".join(report_lines),
        }
        return result

    @_tool_in("papers")
    def compare_papers(paper_ids: list[str]) -> dict[str, Any]:
        """Compare multiple papers side-by-side.

        Returns structured data for each paper including title, authors,
        abstract, section headings, citation count, and equation count.
        The calling LLM should synthesize the comparison from this data.

        Args:
            paper_ids: List of 2-5 paper identifiers

        Returns:
            Structured comparison data for each paper
        """
        from synsc.services.paper_service import get_paper_service

        if not paper_ids or len(paper_ids) < 2:
            return {"success": False, "error": "Need at least 2 papers to compare"}

        if len(paper_ids) > 5:
            return {"success": False, "error": "Maximum 5 papers for comparison"}

        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)

        papers = []
        for pid in paper_ids:
            paper = service.get_paper(pid)
            if paper:
                chunks = paper.get("chunks", [])
                sections = list(dict.fromkeys(
                    c.get("section_title", "") for c in chunks if c.get("section_title")
                ))
                citations = service.get_citations(pid)
                equations = service.get_equations(pid)
                papers.append({
                    "paper_id": pid,
                    "title": paper.get("title", "Untitled"),
                    "authors": paper.get("authors", "Unknown"),
                    "abstract": paper.get("abstract", ""),
                    "sections": sections,
                    "chunk_count": len(chunks),
                    "citation_count": len(citations),
                    "equation_count": len(equations),
                })

        if len(papers) < 2:
            return {"success": False, "error": "Could not retrieve at least 2 papers"}

        result = {
            "success": True,
            "papers": papers,
            "count": len(papers),
        }
        return result

    @_tool_in("papers")
    def extract_quoted_evidence(
        paper_id: str,
        claim: str,
        max_quotes: int = 5,
    ) -> dict[str, Any]:
        """Extract literal sentences from a paper that ground a claim.

        Use this when an agent is about to write something like "the paper
        shows X" — instead of paraphrasing, ask Delphi for the actual
        quote. Returns the top sentences ranked by token overlap with the
        claim, along with section + page so the agent can cite precisely.

        Args:
            paper_id: Paper identifier (UUID).
            claim: The claim being grounded (a sentence or short phrase).
            max_quotes: Maximum number of supporting sentences to return.
        """
        from synsc.services.paper_retrieval import extract_quoted_evidence as _q

        user_id = get_authenticated_user_id()
        if not user_id:
            return {
                "success": False,
                "error_code": "auth_required",
                "message": "Authentication required",
            }
        return _q(
            paper_id=paper_id,
            claim=claim,
            user_id=user_id,
            max_quotes=max_quotes,
        )

    @_tool_in("papers")
    def joint_retrieval(
        query: str,
        paper_ids: list[str] | None = None,
        repo_ids: list[str] | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Joint retrieval across papers, code, and the Thesis graph.

        Single tool call returns paper hits + code hits + Thesis-graph hits
        for a query. Built for research workflows where the agent wants to
        cite a paper, reference an implementation, and pick up prior
        decisions from the graph in one shot.

        Args:
            query: Natural-language query.
            paper_ids: Optional paper scope.
            repo_ids: Optional repo scope.
            top_k: Top hits per source.
        """
        from synsc.services.paper_retrieval import joint_retrieval as _joint

        user_id = get_authenticated_user_id()
        if not user_id:
            return {
                "success": False,
                "error_code": "auth_required",
                "message": "Authentication required",
            }
        result = _joint(
            query=query, user_id=user_id,
            paper_ids=paper_ids, repo_ids=repo_ids, top_k=top_k,
        )
        return {"success": True, **result}

    @_tool_in("papers")
    def delete_paper(paper_id: str) -> dict[str, Any]:
        """Delete an indexed paper and all associated data.

        Removes the paper, its chunks, embeddings, citations, equations,
        and code snippets.

        Args:
            paper_id: Paper identifier (UUID)

        Returns:
            Success status
        """
        from synsc.services.paper_service import get_paper_service

        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)

        result = service.delete_paper(paper_id)
        if user_id:
            _log_activity(user_id, "delete_paper", resource_type="paper", resource_id=paper_id)
        return result

    # ==========================================================================
    # HUGGINGFACE DATASET TOOLS
    # ==========================================================================

    @_tool_in("datasets")
    async def index_dataset(source: str) -> dict[str, Any]:
        """Index a HuggingFace dataset for semantic search.

        Supports multiple formats:
        - Dataset IDs: "imdb", "openai/gsm8k"
        - HuggingFace URLs: "https://huggingface.co/datasets/openai/gsm8k"

        Indexes the dataset card (README documentation) for semantic search.
        Does NOT download actual dataset rows.

        Features global deduplication - if dataset already indexed,
        returns existing dataset ID instantly.

        Args:
            source: HuggingFace dataset ID or URL

        Returns:
            Dictionary with dataset_id, name, hf_id, chunks, etc.
        """
        import asyncio
        from synsc.services.dataset_service import get_dataset_service
        from synsc.core.huggingface_client import parse_hf_dataset_id, HuggingFaceError

        user_id = get_authenticated_user_id()

        hf_token = os.environ.get("HF_TOKEN", "")

        service = get_dataset_service(user_id=user_id)

        try:
            hf_id = parse_hf_dataset_id(source)
        except HuggingFaceError:
            hf_id = source.strip()

        result = await asyncio.to_thread(service.index_dataset, hf_id, hf_token=hf_token)
        return result

    @_tool_in("datasets")
    def list_datasets(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List all indexed HuggingFace datasets.

        Shows datasets in your collection that have been indexed for search.

        Args:
            limit: Maximum number of datasets to return (default: 50, max 200)
            offset: Number of datasets to skip for pagination

        Returns:
            Dictionary with datasets list and total count
        """
        from synsc.services.dataset_service import get_dataset_service

        limit = min(limit, 200)
        user_id = get_authenticated_user_id()

        service = get_dataset_service(user_id=user_id)
        datasets = service.list_datasets(limit=limit)

        return {"success": True, "datasets": datasets, "total": len(datasets)}

    @_tool_in("datasets")
    def get_dataset(dataset_id: str) -> dict[str, Any]:
        """Get detailed information about an indexed dataset.

        Returns dataset metadata including features, splits, languages,
        and all indexed chunks from the dataset card.

        Args:
            dataset_id: Dataset identifier (UUID)

        Returns:
            Complete dataset data with metadata and chunks
        """
        from synsc.services.dataset_service import get_dataset_service

        user_id = get_authenticated_user_id()

        service = get_dataset_service(user_id=user_id)
        dataset = service.get_dataset(dataset_id)

        if not dataset:
            return {"success": False, "error": "Dataset not found or access denied"}

        return {"success": True, "dataset": dataset}

    @_tool_in("datasets")
    async def search_datasets(query: str, top_k: int = 10) -> dict[str, Any]:
        """Search datasets using semantic search over dataset cards.

        Uses sentence-transformers embeddings to find relevant datasets by meaning.
        Searches through indexed dataset documentation (README cards).

        Args:
            query: Natural language search query
            top_k: Number of results to return (default: 10)

        Returns:
            Matching dataset chunks with relevance scores
        """
        import asyncio
        from synsc.services.dataset_service import get_dataset_service

        user_id = get_authenticated_user_id()

        service = get_dataset_service(user_id=user_id)
        result = await asyncio.to_thread(service.search_datasets, query=query, top_k=top_k)

        return result

    @_tool_in("datasets")
    def delete_dataset(dataset_id: str) -> dict[str, Any]:
        """Delete an indexed dataset.

        For public datasets: removes from your collection (data stays for others).
        For private/gated datasets: fully deletes all data.

        Args:
            dataset_id: Dataset identifier (UUID)

        Returns:
            Success status
        """
        from synsc.services.dataset_service import get_dataset_service

        user_id = get_authenticated_user_id()

        service = get_dataset_service(user_id=user_id)
        result = service.delete_dataset(dataset_id)

        return result

    # ==========================================================================
    # UNIFIED RESEARCH TOOL
    # ==========================================================================

    @_tool_in("research")
    def research(
        query: str,
        mode: str = "quick",
        source_ids: list[str] | None = None,
        source_types: list[str] | None = None,
        k: int | None = None,
    ) -> dict[str, Any]:
        """RAG synthesis across indexed sources. Modes: quick / deep / oracle.

        Requires a configured research provider (Gemini API key) on the Delphi
        server. If the server has no provider configured, this tool returns
        ``{"success": False, "error_code": "provider_not_configured"}`` —
        relay that message to the user; do not retry.

        Args:
            query: Research question or topic.
            mode: 'quick' (~30s, top_k=10), 'deep' (~120s, iterative),
                  'oracle' (~300s, tool-use).
            source_ids: Optional list of source IDs (repos, papers, datasets)
                        to scope retrieval to.
            source_types: Optional filter: any of 'repo', 'paper', 'dataset'.
            k: Override retrieval top_k.

        On error, the response shape is always
        ``{"success": False, "error_code": <stable-string>, "message": <human-readable>}``
        with one of the codes: ``invalid_mode``, ``provider_not_configured``,
        ``internal_error``.
        """
        from synsc.config import get_config
        from synsc.services.research_service import ResearchService

        if mode not in ("quick", "deep", "oracle"):
            return {
                "success": False,
                "error_code": "invalid_mode",
                "message": (
                    f"Invalid mode '{mode}': expected quick / deep / oracle"
                ),
            }

        config = get_config()
        if config.research.provider == "gemini" and not config.research.api_key:
            return {
                "success": False,
                "error_code": "provider_not_configured",
                "provider": config.research.provider,
                "action_required": "configure_api_key",
                "message": (
                    f"Research provider '{config.research.provider}' is not "
                    "configured on this Delphi instance. Ask the user to set "
                    "GEMINI_API_KEY in the server environment to enable this "
                    "tool — do not retry until they confirm it's configured."
                ),
            }

        start = time.time()
        user_id = get_authenticated_user_id()
        try:
            result = ResearchService().run(
                query=query,
                mode=mode,  # type: ignore[arg-type]
                source_ids=source_ids,
                source_types=source_types,
                k=k,
                user_id=user_id,
            )
        except Exception as e:
            return {
                "success": False,
                "error_code": "internal_error",
                "message": str(e),
            }
        _log_activity(
            user_id=user_id,
            action="research",
            resource_type="research",
            query=query,
            duration_ms=int((time.time() - start) * 1000),
            metadata={"mode": mode, "source": "mcp"},
        )
        return {"success": True, **result}

    @_tool_in("docs")
    def grep_source(
        source_id: str,
        pattern: str,
        source_type: str = "repo",
        path_prefix: str | None = None,
        max_matches: int = 100,
        context_lines: int = 2,
    ) -> dict[str, Any]:
        """Regex search within a single indexed source.

        Args:
            source_id: Repository or paper ID.
            pattern: Python regex pattern.
            source_type: 'repo' or 'paper'.
            path_prefix: Optional path prefix to scope the search.
            max_matches: Upper bound on matches returned (default 100).
            context_lines: Lines of context above / below each match (default 2).
        """
        from synsc.services.grep_service import GrepService

        start = time.time()
        user_id = get_authenticated_user_id()
        try:
            matches = GrepService().grep_source(
                source_id=source_id,
                source_type=source_type,
                pattern=pattern,
                path_prefix=path_prefix,
                max_matches=max_matches,
                context_lines=context_lines,
                user_id=user_id,
            )
        except ValueError as e:
            return {
                "success": False,
                "error_code": "invalid_input",
                "message": str(e),
            }
        _log_activity(
            user_id=user_id,
            action="grep_source",
            resource_type=source_type,
            resource_id=source_id,
            query=pattern,
            results_count=len(matches),
            duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return {"success": True, "source_id": source_id, "matches": matches}

    # ==========================================================================
    # UNIFIED SOURCE TOOLS (Nia-parity P1)
    # ==========================================================================

    @_tool_in("sources", "minimal")
    def search(
        query: str,
        source_ids: list[str] | None = None,
        source_types: list[str] | None = None,
        k: int = 10,
        mode: str = "precise",
        topic: str | None = None,
        tokens: int | None = None,
    ) -> dict[str, Any]:
        """Unified search across indexed code + papers + datasets.

        Modes: 'precise' (fewer, higher quality), 'thorough' (more results),
        'web' (fallback, returns empty stub). Accepts Nia aliases: 'targeted'
        maps to 'precise', 'universal' maps to 'thorough'.

        Args:
            query: Natural language query.
            source_ids: Optional list of source IDs to scope the search.
            source_types: Filter: any of 'repo', 'paper', 'dataset'.
            k: Number of hits (default 10, max 100).
            mode: 'precise' / 'thorough' / 'web' / 'targeted' / 'universal'.
            topic: Optional Context7-style sub-area filter applied to result
                text/path after retrieval.
            tokens: Optional total token budget across all returned hits.
                Truncates trailing results to fit; the last partial hit is
                marked ``_truncated: true``.
        """
        from synsc.services.budget import (
            budget_results,
            filter_results_by_topic,
        )
        from synsc.services.source_service import unified_search

        start = time.time()
        user_id = get_authenticated_user_id()
        try:
            result = unified_search(
                query=query,
                source_ids=source_ids,
                source_types=source_types,
                k=k,
                mode=mode,
                user_id=user_id,
            )
        except ValueError as e:
            return {
                "success": False,
                "error_code": "invalid_input",
                "message": str(e),
            }

        if topic and isinstance(result.get("results"), list):
            result["results"] = filter_results_by_topic(
                result["results"], topic, text_keys=("text", "path")
            )
            result["total"] = len(result["results"])
        if tokens and isinstance(result.get("results"), list):
            result["results"] = budget_results(
                result["results"], tokens, text_key="text"
            )

        _log_activity(
            user_id=user_id,
            action="unified_search",
            query=query,
            results_count=result.get("total", 0),
            duration_ms=int((time.time() - start) * 1000),
            metadata={
                "mode": mode,
                "topic": topic,
                "tokens": tokens,
                "source": "mcp",
            },
        )
        return {"success": True, **result}

    @_tool_in("sources")
    def index_source(
        source_type: str,
        url: str,
        display_name: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Unified indexing dispatch — repo / paper / dataset / docs.

        For repos, MCP gets agent-quality indexing by default (tests, docs,
        examples, configs, manifests, dotfiles all included; AST chunking;
        rerank). Pass ``options={'quality_mode': 'fast'}`` for the legacy
        fast-skip behavior.

        Args:
            source_type: 'repo', 'paper', 'dataset', or 'docs' (docs lands later).
            url: GitHub URL, arXiv URL/ID, HF dataset ID, or docs URL.
            display_name: Optional friendly label.
            options: Per-type options. Repo accepts: ``branch``, ``deep_index``,
                ``force_reindex``, ``quality_mode``, ``include_tests``,
                ``include_docs``, ``include_examples``.
        """
        from synsc.config import get_config
        from synsc.services.source_service import index_source as _index_source

        # Default repo indexing to MCP agent mode unless caller said otherwise.
        if source_type == "repo":
            options = dict(options or {})
            options.setdefault(
                "quality_mode", get_config().quality.mcp_default_mode
            )

        start = time.time()
        user_id = get_authenticated_user_id()
        try:
            result = _index_source(
                source_type=source_type,
                url=url,
                display_name=display_name,
                options=options,
                user_id=user_id,
            )
        except NotImplementedError as e:
            return {
                "success": False,
                "error_code": "not_implemented",
                "message": str(e),
            }
        except ValueError as e:
            return {
                "success": False,
                "error_code": "invalid_input",
                "message": str(e),
            }
        _log_activity(
            user_id=user_id,
            action="index_source",
            resource_type=source_type,
            resource_id=result.get("source_id") or None,
            duration_ms=int((time.time() - start) * 1000),
            metadata={"url": url, "source": "mcp"},
        )

        # Reflect a per-type service failure in the tool envelope so the
        # calling agent can surface it instead of believing the index ran.
        if result.get("status") == "error":
            return {
                "success": False,
                "error_code": "indexing_failed",
                "message": result.get("error") or "indexing failed",
                "raw": result.get("raw"),
            }
        return {"success": True, **result}

    @_tool_in("sources", "minimal")
    def resolve_source(
        name: str,
        source_types: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Context7-style name→source resolver.

        Pass a free-form name ("fastapi", "transformers", "Attention is All You
        Need") and get ranked candidates back, each with a canonical
        ``source_id`` to feed to ``read_source`` / ``search``.

        Returns matches across repos / papers / datasets / docs (filterable
        via ``source_types``), ordered by:
          - exact > prefix > substring match quality
          - higher trust_score (stars / citations / verified) tiebreaks

        Args:
            name: Free-form library / repo / dataset / paper name.
            source_types: Subset of 'repo','paper','dataset','docs'.
            limit: Max candidates returned (default 10).
        """
        from synsc.services.source_service import (
            resolve_source_id,
            resolve_source_name,
        )

        start = time.time()
        user_id = get_authenticated_user_id()

        # If the caller gives us something resolvable to a single canonical
        # form (UUID, owner/repo, arxiv:ID, hf:ID, github URL), return that
        # as a single high-confidence match.
        try:
            uid, stype = resolve_source_id(name, user_id=user_id)
            single = [
                {
                    "source_id": uid,
                    "source_type": stype,
                    "display_name": name,
                    "external_ref": name,
                    "match_quality": 4,
                    "trust_score": 0.0,
                    "extra": {"resolved_via": "canonical"},
                }
            ]
            _log_activity(
                user_id=user_id,
                action="resolve_source",
                query=name,
                results_count=1,
                duration_ms=int((time.time() - start) * 1000),
                metadata={"path": "canonical", "source": "mcp"},
            )
            return {"success": True, "candidates": single, "total": 1}
        except ValueError:
            pass

        candidates = resolve_source_name(
            name=name,
            user_id=user_id,
            source_types=source_types,
            limit=limit,
        )
        _log_activity(
            user_id=user_id,
            action="resolve_source",
            query=name,
            results_count=len(candidates),
            duration_ms=int((time.time() - start) * 1000),
            metadata={"path": "fuzzy", "source": "mcp"},
        )
        return {
            "success": True,
            "candidates": candidates,
            "total": len(candidates),
        }

    @_tool_in("sources")
    def list_sources(source_type: str | None = None) -> dict[str, Any]:
        """List indexed sources, optionally filtered by type.

        Args:
            source_type: Optional filter: 'repo', 'paper', 'dataset'.
        """
        from synsc.services.source_service import list_sources as _list_sources

        start = time.time()
        user_id = get_authenticated_user_id()
        sources = _list_sources(source_type=source_type, user_id=user_id)
        _log_activity(
            user_id=user_id,
            action="list_sources",
            results_count=len(sources),
            duration_ms=int((time.time() - start) * 1000),
            metadata={"type_filter": source_type, "source": "mcp"},
        )
        return {"success": True, "sources": sources, "total": len(sources)}

    @_tool_in("sources", "minimal")
    def read_source(
        source_id: str,
        source_type: str = "paper",
        path: str | None = None,
        section: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
        topic: str | None = None,
        tokens: int | None = None,
    ) -> dict[str, Any]:
        """Read content from an indexed source.

        - paper: supports ``section=`` (canonical token or regex).
        - repo:  requires ``path=``; optional ``start_line``/``end_line``.
        - docs:  whole-docs read; pair with ``topic`` to narrow.

        Args:
            source_id: Paper / repo / docs ID.
            source_type: 'paper' (default), 'repo', or 'docs'.
            path: Required for repo reads.
            section: Optional for paper reads — 'abstract', 'introduction',
                'methods', 'results', 'discussion', 'conclusion', 'references',
                'related work', or a regex.
            start_line: Repo read — optional 1-indexed start line.
            end_line: Repo read — optional end line.
            topic: Optional Context7-style sub-area filter. For papers and
                docs, narrows to chunks whose heading/section/body matches
                any topic token (e.g. 'routing', 'hooks', 'authentication').
            tokens: Optional token budget for the returned body. Default
                budget (~5000) applied when omitted; pass 0 to disable.
        """
        from synsc.services.budget import (
            budget_results,
            default_budget,
            filter_results_by_topic,
            truncate_to_tokens,
        )

        effective_tokens = tokens if tokens is not None else default_budget()
        start = time.time()
        user_id = get_authenticated_user_id()

        if source_type == "paper":
            from synsc.services.paper_service import get_paper_service

            try:
                paper = get_paper_service(user_id=user_id).get_paper(
                    source_id, section=section
                )
            except ValueError as e:
                return {
                    "success": False,
                    "error_code": "invalid_input",
                    "message": str(e),
                }
            if paper is None:
                return {
                    "success": False,
                    "error_code": "not_found",
                    "message": "paper not found",
                }

            # Apply topic narrowing to the chunk list if the paper exposes one.
            if topic and isinstance(paper.get("chunks"), list):
                paper["chunks"] = filter_results_by_topic(
                    paper["chunks"], topic, text_keys=("content", "section")
                )
            # Token budget over the joined body / chunk text.
            if effective_tokens:
                if isinstance(paper.get("chunks"), list):
                    paper["chunks"] = budget_results(
                        paper["chunks"], effective_tokens, text_key="content"
                    )
                if paper.get("text"):
                    paper["text"] = truncate_to_tokens(
                        paper["text"], effective_tokens
                    )

            _log_activity(
                user_id=user_id,
                action="read_source",
                resource_type="paper",
                resource_id=source_id,
                duration_ms=int((time.time() - start) * 1000),
                metadata={
                    "section": section,
                    "topic": topic,
                    "tokens": effective_tokens,
                    "source": "mcp",
                },
            )
            return {
                "success": True,
                "source_id": source_id,
                "source_type": "paper",
                **paper,
            }

        if source_type == "repo":
            if not path:
                return {
                    "success": False,
                    "error_code": "invalid_input",
                    "message": "repo read requires path=",
                }
            from synsc.services.search_service import SearchService

            res = SearchService(user_id=user_id).get_file(
                repo_id=source_id,
                file_path=path,
                start_line=start_line,
                end_line=end_line,
                user_id=user_id,
            )
            if not res.get("success"):
                return {
                    "success": False,
                    "error_code": "not_found",
                    "message": res.get("error", "not found"),
                }
            if effective_tokens and isinstance(res.get("content"), str):
                truncated = truncate_to_tokens(res["content"], effective_tokens)
                if truncated != res["content"]:
                    res["content"] = truncated
                    res["truncated"] = True
            _log_activity(
                user_id=user_id,
                action="read_source",
                resource_type="repo",
                resource_id=source_id,
                duration_ms=int((time.time() - start) * 1000),
                metadata={
                    "path": path,
                    "topic": topic,
                    "tokens": effective_tokens,
                    "source": "mcp",
                },
            )
            return {**res, "source_id": source_id, "source_type": "repo"}

        if source_type == "docs":
            from synsc.services.docs_service import get_docs_service

            svc = get_docs_service(user_id=user_id)
            # No dedicated single-source "read all" on docs yet — use a
            # topic-or-broad search scoped to this docs source.
            query = topic or "*"
            res = svc.search_docs(query=query, top_k=20)
            if not res.get("success"):
                return {
                    "success": False,
                    "error_code": "not_found",
                    "message": res.get("error", "not found"),
                }
            chunks = [r for r in res.get("results", []) if r.get("docs_id") == source_id]
            chunks = filter_results_by_topic(
                chunks, topic, text_keys=("content", "heading")
            )
            if effective_tokens:
                chunks = budget_results(chunks, effective_tokens, text_key="content")
            _log_activity(
                user_id=user_id,
                action="read_source",
                resource_type="docs",
                resource_id=source_id,
                duration_ms=int((time.time() - start) * 1000),
                metadata={"topic": topic, "tokens": effective_tokens, "source": "mcp"},
            )
            return {
                "success": True,
                "source_id": source_id,
                "source_type": "docs",
                "chunks": chunks,
                "count": len(chunks),
            }

        return {
            "success": False,
            "error_code": "invalid_input",
            "message": f"unsupported source_type: {source_type}",
        }

    @_tool_in("sources")
    def tree_source(
        source_id: str,
        action: str = "tree",
        path: str = "/",
        max_depth: int = 4,
        annotate: bool = True,
    ) -> dict[str, Any]:
        """Browse the directory structure of an indexed repository source.

        Two modes:
        - 'tree' (default): recursive tree view with optional annotations.
        - 'ls': flat single-level listing at ``path`` — equivalent to ``ls``.

        Args:
            source_id: Repository identifier.
            action: 'tree' or 'ls'.
            path: For ``action='ls'``, the directory path (default root).
            max_depth: For ``action='tree'``, max depth (default 4).
            annotate: For ``action='tree'``, attach directory purpose annotations.
        """
        if action not in ("tree", "ls"):
            return {
                "success": False,
                "error_code": "invalid_input",
                "message": f"invalid action: {action}",
            }

        from synsc.services.analysis_service import AnalysisService

        start = time.time()
        user_id = get_authenticated_user_id()
        svc = AnalysisService(user_id=user_id)
        if action == "ls":
            result = svc.list_directory(
                repo_id=source_id, path=path, user_id=user_id
            )
        else:
            result = svc.get_directory_structure(
                repo_id=source_id,
                max_depth=max_depth,
                annotate=annotate,
                user_id=user_id,
            )

        _log_activity(
            user_id=user_id,
            action=f"tree_source_{action}",
            resource_type="repository",
            resource_id=source_id,
            duration_ms=int((time.time() - start) * 1000),
            metadata={"action": action, "source": "mcp"},
        )
        return result

    # ==========================================================================
    # THESIS CONNECTOR TOOLS
    # ==========================================================================
    #
    # Thesis is the long-running research workflow system. Agents working in
    # Thesis need: "what's already been tried", "what's been decided", "what
    # tool contracts apply". The connector ports nodes / edges / artifacts /
    # executions / tool contracts into Delphi, then offers graph-aware
    # retrieval on top.

    @_tool_in("thesis")
    def thesis_register_workspace(
        external_id: str,
        name: str,
        display_name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        is_public: bool = False,
    ) -> dict[str, Any]:
        """Register (create or update) a Thesis workspace and link it to the user."""
        from synsc.services.thesis_connector import ingest_workspace

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        return ingest_workspace(
            user_id=user_id, external_id=external_id, name=name,
            display_name=display_name, description=description,
            tags=tags, is_public=is_public,
        )

    @_tool_in("thesis")
    def thesis_ingest_node(
        workspace_id: str,
        external_id: str,
        node_type: str,
        title: str | None = None,
        summary: str | None = None,
        content: str | None = None,
        status: str | None = None,
        outcome: str | None = None,
        tags: list[str] | None = None,
        decision_rationale: str | None = None,
        commit_sha: str | None = None,
        is_committed: bool = False,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        """Index (or re-index) a Thesis node — claim/hypothesis/plan/decision/insight.

        Embeds summary / content / rationale / outcome as separate chunks so
        a search for "rationale for choosing X" finds the rationale chunk
        instead of being diluted by the full node body.
        """
        from synsc.services.thesis_connector import ingest_node

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        return ingest_node(
            user_id=user_id, workspace_id=workspace_id,
            external_id=external_id, node_type=node_type,
            title=title, summary=summary, content=content,
            status=status, outcome=outcome, tags=tags,
            decision_rationale=decision_rationale,
            commit_sha=commit_sha, is_committed=is_committed,
            created_by=created_by,
        )

    @_tool_in("thesis")
    def thesis_ingest_edge(
        workspace_id: str,
        source_external_id: str,
        target_external_id: str,
        edge_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a directed edge between two nodes in a workspace."""
        from synsc.services.thesis_connector import ingest_edge

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        return ingest_edge(
            user_id=user_id, workspace_id=workspace_id,
            source_external_id=source_external_id,
            target_external_id=target_external_id,
            edge_type=edge_type, metadata=metadata,
        )

    @_tool_in("thesis")
    def thesis_ingest_artifact(
        workspace_id: str,
        kind: str,
        node_external_id: str | None = None,
        name: str | None = None,
        preview: str | None = None,
        uri: str | None = None,
        metadata: dict[str, Any] | None = None,
        external_id: str | None = None,
    ) -> dict[str, Any]:
        """Attach an artifact (table / plot / log / diff / metric / model)."""
        from synsc.services.thesis_connector import ingest_artifact

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        return ingest_artifact(
            user_id=user_id, workspace_id=workspace_id,
            node_external_id=node_external_id, kind=kind,
            name=name, preview=preview, uri=uri,
            metadata=metadata, external_id=external_id,
        )

    @_tool_in("thesis")
    def thesis_ingest_execution(
        workspace_id: str,
        tool: str | None,
        status: str | None,
        node_external_id: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        duration_ms: int | None = None,
        inputs: dict[str, Any] | None = None,
        output_summary: str | None = None,
        error: str | None = None,
        external_id: str | None = None,
    ) -> dict[str, Any]:
        """Record an execution / tool-call against a node."""
        from synsc.services.thesis_connector import ingest_execution

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        return ingest_execution(
            user_id=user_id, workspace_id=workspace_id,
            node_external_id=node_external_id, tool=tool, status=status,
            started_at=started_at, ended_at=ended_at, duration_ms=duration_ms,
            inputs=inputs, output_summary=output_summary, error=error,
            external_id=external_id,
        )

    @_tool_in("thesis")
    def thesis_ingest_tool_contract(
        tool_name: str,
        workspace_id: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
        when_to_use: str | None = None,
        avoid_when: str | None = None,
        signature: dict[str, Any] | None = None,
        examples: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register a tool-contract document so agents can fetch it via
        ``thesis_retrieve_tool_contract``.
        """
        from synsc.services.thesis_connector import ingest_tool_contract

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        return ingest_tool_contract(
            user_id=user_id, tool_name=tool_name, workspace_id=workspace_id,
            display_name=display_name, description=description,
            when_to_use=when_to_use, avoid_when=avoid_when,
            signature=signature, examples=examples, tags=tags,
        )

    @_tool_in("thesis")
    def build_thesis_context(
        question: str,
        node_id: str | None = None,
        workspace_ids: list[str] | None = None,
        token_budget: int = 4000,
    ) -> dict[str, Any]:
        """Build a Thesis-aware context pack for a research question.

        Returns matched nodes (vector + BM25 + artifact-aware ranking),
        a 2-hop subgraph around the top match, relevant artifacts (tables,
        plots, logs), tool contracts that apply, "what's been tried"
        (matched nodes + their executions), and "what shouldn't be
        repeated" (failed-outcome nodes).

        Args:
            question: The agent's question.
            node_id: Optional anchor node to start the subgraph walk from.
            workspace_ids: Optional workspace scope.
            token_budget: Approximate target tokens for the pack body.
        """
        from synsc.services.thesis_connector import build_thesis_context as _bld

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        return _bld(
            user_id=user_id, question=question, node_id=node_id,
            workspace_ids=workspace_ids, token_budget=token_budget,
        )

    @_tool_in("thesis")
    def summarize_relevant_subgraph(
        question: str,
        root_node_id: str | None = None,
        max_depth: int = 2,
    ) -> dict[str, Any]:
        """Return a compact subgraph summary for the matched region.

        Useful before drilling in — agent gets shape + size + edge types
        without pulling every node body.
        """
        from synsc.services.thesis_connector import summarize_relevant_subgraph as _sub

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        return _sub(
            user_id=user_id, question=question,
            root_node_id=root_node_id, max_depth=max_depth,
        )

    @_tool_in("thesis")
    def find_related_nodes(
        node_id: str | None = None,
        question: str | None = None,
        max_depth: int = 2,
        edge_types: list[str] | None = None,
        top_k: int = 25,
    ) -> dict[str, Any]:
        """Walk the Thesis graph from an anchor, BFS up to ``max_depth`` hops.

        Pass either ``node_id`` (an explicit anchor) or ``question`` (we
        anchor on the top semantic match). One must be supplied.
        """
        from synsc.services.thesis_connector import find_related_nodes as _rel

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        if not node_id and not question:
            return {
                "success": False,
                "error_code": "invalid_input",
                "message": "Pass either node_id= or question=",
            }
        nodes = _rel(
            user_id=user_id, node_id=node_id, question=question,
            max_depth=max_depth, edge_types=edge_types, top_k=top_k,
        )
        return {
            "success": True, "node_id": node_id, "question": question,
            "related": nodes,
        }

    @_tool_in("thesis")
    def find_relevant_artifacts(
        question: str,
        workspace_ids: list[str] | None = None,
        kinds: list[str] | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Find Thesis artifacts (tables / plots / logs) relevant to a question.

        Args:
            question: Search query.
            workspace_ids: Optional workspace scope.
            kinds: Optional artifact-kind filter (e.g. ['table','metric']).
            top_k: Number of artifacts to return.
        """
        from synsc.services.thesis_connector import find_relevant_artifacts as _art

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        artifacts = _art(
            user_id=user_id, query=question,
            workspace_ids=workspace_ids, kinds=kinds, top_k=top_k,
        )
        return {"success": True, "question": question, "artifacts": artifacts}

    @_tool_in("thesis")
    def thesis_retrieve_tool_contract(
        task: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Find tool-contract documents applicable to a task description.

        Returns signature + when_to_use + examples for each matched contract
        so the agent can call the tool correctly without separate lookup.
        """
        from synsc.services.thesis_connector import retrieve_tool_contract

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        contracts = retrieve_tool_contract(
            user_id=user_id, task=task, top_k=top_k,
        )
        return {"success": True, "task": task, "contracts": contracts}

    @_tool_in("thesis")
    def thesis_what_was_tried(
        question: str,
        workspace_ids: list[str] | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """"What has already been tried for this question?"

        Returns matched nodes plus their executions and outcomes — full
        "we tried Y, status was Z, here's what happened" picture.
        """
        from synsc.services.thesis_connector import find_what_was_tried

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        result = find_what_was_tried(
            user_id=user_id, question=question,
            workspace_ids=workspace_ids, top_k=top_k,
        )
        return {"success": True, **result}

    @_tool_in("thesis")
    def thesis_what_not_to_repeat(
        question: str,
        workspace_ids: list[str] | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """"What should I not repeat?" — failed-outcome nodes for the question."""
        from synsc.services.thesis_connector import find_what_not_to_repeat

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        result = find_what_not_to_repeat(
            user_id=user_id, question=question,
            workspace_ids=workspace_ids, top_k=top_k,
        )
        return {"success": True, **result}

    @_tool_in("thesis")
    def thesis_active_work_context(
        workspace_ids: list[str] | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Recent in-progress nodes + open executions — "what was I doing?"."""
        from synsc.services.thesis_connector import get_active_work_context

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        return get_active_work_context(
            user_id=user_id, workspace_ids=workspace_ids, top_k=top_k,
        )

    @_tool_in("thesis")
    def thesis_find_decisions(
        question: str,
        workspace_ids: list[str] | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Surface committed decisions related to a question (decision-memory ranking).

        Only nodes with ``node_type='decision'`` AND ``is_committed=TRUE``
        — locked-in rationale that subsequent work should respect.
        """
        from synsc.services.thesis_connector import find_decisions

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        decisions = find_decisions(
            user_id=user_id, question=question,
            workspace_ids=workspace_ids, top_k=top_k,
        )
        return {"success": True, "question": question, "decisions": decisions}

    @_tool_in("thesis")
    def thesis_search_nodes(
        query: str,
        workspace_ids: list[str] | None = None,
        node_types: list[str] | None = None,
        only_committed: bool = False,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Hybrid search over Thesis nodes (vector + BM25 + artifact-aware)."""
        from synsc.services.thesis_connector import search_thesis_nodes

        user_id = get_authenticated_user_id()
        if not user_id:
            return {"success": False, "error_code": "auth_required"}
        nodes = search_thesis_nodes(
            query=query, user_id=user_id,
            workspace_ids=workspace_ids, node_types=node_types,
            only_committed=only_committed, top_k=top_k,
        )
        return {"success": True, "query": query, "nodes": nodes}

    @_tool_in("code")
    def classify_failure(
        description: str,
        query: str | None = None,
        repo_id: str | None = None,
    ) -> dict[str, Any]:
        """"Delphi failed because" classifier.

        Pass a short description of what went wrong; we tag it with a
        stable failure-mode code and write to the activity log so we can
        aggregate over time and fix the right thing.
        """
        from synsc.services.observability import classify_failure as _cls

        user_id = get_authenticated_user_id()
        result = _cls(
            description=description, user_id=user_id,
            query=query, repo_id=repo_id,
        )
        return {"success": True, **result}

    return server


def run_server():
    """Run the MCP server in stdio mode."""
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    run_server()
