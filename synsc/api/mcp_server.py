"""
Unified MCP Server for Synsc Context.

Provides tools for code repository, research paper, and HuggingFace dataset indexing.
"""

import contextvars
import logging
import os
import time
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logger = logging.getLogger(__name__)

# Context variables for request-scoped auth
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


def get_current_user_id() -> str | None:
    """Get the user ID from the current request context."""
    return _current_user_id.get()


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
            "https://context.syntheticsciences.ai",
            "https://app.inkvell.ai",
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

    # ==========================================================================
    # AUTH HELPERS
    # ==========================================================================
    
    def get_authenticated_user_id() -> str | None:
        """Get user_id from API key."""
        from synsc.supabase_auth import validate_api_key_hybrid
        
        api_key = _current_api_key.get()
        if not api_key:
            api_key = os.environ.get("SYNSC_API_KEY")
        
        if not api_key:
            return None
        
        is_valid, user_id = validate_api_key_hybrid(api_key)
        if is_valid and user_id != "local":
            return user_id
        return None

    # ==========================================================================
    # ACTIVITY LOGGING (MCP tool calls only)
    # ==========================================================================

    def _log_activity(
        user_id: str | None,
        action: str,
        resource_type: str = None,
        resource_id: str = None,
        query: str = None,
        results_count: int = None,
        duration_ms: int = None,
        metadata: dict = None,
    ) -> None:
        """Fire-and-forget activity logging for MCP tool calls. Never raises."""
        if not user_id:
            return
        try:
            from synsc.supabase_auth import get_supabase_auth
            auth_service = get_supabase_auth()
            auth_service.log_activity(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                query=query,
                results_count=results_count,
                duration_ms=duration_ms,
                metadata=metadata,
            )
        except Exception as e:
            logger.debug("Activity logging failed (non-critical)", error=str(e))

    # ==========================================================================
    # CODE REPOSITORY TOOLS
    # ==========================================================================

    @server.tool()
    def index_repository(url: str, branch: str = "main", deep_index: bool = False) -> dict[str, Any]:
        """Index a GitHub repository for semantic code search.

        Args:
            url: GitHub repository URL (e.g., "facebook/react" or full URL)
            branch: Branch to index (default: main)
            deep_index: Full AST chunking per function/class (slower, higher quality)

        Returns:
            Dictionary with repo_id, files_indexed, chunks_created, etc.
        """
        from synsc.services.indexing_service import IndexingService

        start = time.time()
        service = IndexingService()
        user_id = get_authenticated_user_id()

        result = service.index_repository(url, branch, user_id=user_id, deep_index=deep_index)
        _log_activity(
            user_id=user_id, action="index_repository", resource_type="repository",
            resource_id=result.get("repo_id"), duration_ms=int((time.time() - start) * 1000),
            metadata={"repo_url": url, "branch": branch, "source": "mcp"},
        )
        return result

    @server.tool()
    def list_repositories(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List all indexed repositories.
        
        Args:
            limit: Maximum repositories to return
            offset: Pagination offset
            
        Returns:
            Dictionary with repositories list and total count
        """
        from synsc.services.indexing_service import IndexingService
        
        start = time.time()
        service = IndexingService()
        user_id = get_authenticated_user_id()
        
        result = service.list_repositories(limit, offset, user_id=user_id)
        _log_activity(
            user_id=user_id, action="list_repositories", resource_type="repository",
            results_count=result.get("total", 0), duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    @server.tool()
    def get_repository(repo_id: str) -> dict[str, Any]:
        """Get detailed information about an indexed repository.
        
        Args:
            repo_id: Repository identifier
            
        Returns:
            Repository details including stats, languages, etc.
        """
        from synsc.services.indexing_service import IndexingService
        
        start = time.time()
        service = IndexingService()
        user_id = get_authenticated_user_id()
        
        result = service.get_repository(repo_id, user_id=user_id)
        _log_activity(
            user_id=user_id, action="get_repository", resource_type="repository",
            resource_id=repo_id, duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    @server.tool()
    def delete_repository(repo_id: str) -> dict[str, Any]:
        """Delete an indexed repository.
        
        Args:
            repo_id: Repository identifier
            
        Returns:
            Success status
        """
        from synsc.services.indexing_service import IndexingService
        
        start = time.time()
        service = IndexingService()
        user_id = get_authenticated_user_id()
        
        result = service.delete_repository(repo_id, user_id=user_id)
        _log_activity(
            user_id=user_id, action="delete_repository", resource_type="repository",
            resource_id=repo_id, duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    @server.tool()
    def search_code(
        query: str,
        repo_ids: list[str] | None = None,
        language: str | None = None,
        file_pattern: str | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Search code using natural language or keywords.
        
        Args:
            query: Natural language search query
            repo_ids: Optional list of repo IDs to search
            language: Filter by programming language
            file_pattern: Glob pattern for file paths
            top_k: Number of results to return
            
        Returns:
            Search results with code snippets and relevance scores
        """
        from synsc.services.search_service import SearchService
        
        start = time.time()
        service = SearchService()
        user_id = get_authenticated_user_id()
        
        result = service.search_code(
            query=query, repo_ids=repo_ids, language=language,
            file_pattern=file_pattern, top_k=top_k, user_id=user_id,
        )
        _log_activity(
            user_id=user_id, action="search_code", resource_type="search",
            query=query, results_count=len(result.get("results", [])),
            duration_ms=int((time.time() - start) * 1000),
            metadata={"language": language, "top_k": top_k, "source": "mcp"},
        )
        return result

    @server.tool()
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
        
        start = time.time()
        service = SearchService()
        user_id = get_authenticated_user_id()
        
        result = service.get_file(repo_id, file_path, start_line, end_line, user_id=user_id)
        _log_activity(
            user_id=user_id, action="get_file", resource_type="repository",
            resource_id=repo_id, duration_ms=int((time.time() - start) * 1000),
            metadata={"file_path": file_path, "source": "mcp"},
        )
        return result

    @server.tool()
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
        
        start = time.time()
        service = SymbolService()
        user_id = get_authenticated_user_id()
        
        result = service.search_symbols(
            name=name, repo_ids=repo_ids, symbol_type=symbol_type,
            language=language, top_k=top_k, user_id=user_id,
        )
        _log_activity(
            user_id=user_id, action="search_symbols", resource_type="search",
            query=name, results_count=len(result.get("symbols", [])),
            duration_ms=int((time.time() - start) * 1000),
            metadata={"symbol_type": symbol_type, "source": "mcp"},
        )
        return result

    @server.tool()
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
        
        start = time.time()
        service = AnalysisService()
        user_id = get_authenticated_user_id()
        
        result = service.analyze_repository(repo_id, user_id=user_id)
        _log_activity(
            user_id=user_id, action="analyze_repository", resource_type="repository",
            resource_id=repo_id, duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    @server.tool()
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

        start = time.time()
        service = AnalysisService()
        user_id = get_authenticated_user_id()

        result = service.get_directory_structure(
            repo_id, max_depth=max_depth, annotate=annotate, user_id=user_id,
        )
        _log_activity(
            user_id=user_id, action="get_directory_structure", resource_type="repository",
            resource_id=repo_id, duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    @server.tool()
    def get_symbol(symbol_id: str) -> dict[str, Any]:
        """Get detailed information about a specific code symbol.

        Returns complete symbol details including full docstring,
        parameters with types, return type, and decorators.

        Args:
            symbol_id: Symbol identifier (UUID from search_symbols)
        """
        from synsc.services.symbol_service import SymbolService

        start = time.time()
        service = SymbolService()
        user_id = get_authenticated_user_id()

        result = service.get_symbol(symbol_id, user_id=user_id)
        _log_activity(
            user_id=user_id, action="get_symbol", resource_type="symbol",
            resource_id=symbol_id, duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    @server.tool()
    def remove_from_collection(repo_id: str) -> dict[str, Any]:
        """Remove a repository from your collection without deleting it.

        This removes the repo from YOUR searchable collection without deleting
        the actual indexed data. The repo remains available for other users.

        Args:
            repo_id: Repository identifier (UUID)
        """
        from synsc.services.indexing_service import IndexingService

        start = time.time()
        service = IndexingService()
        user_id = get_authenticated_user_id()

        result = service.remove_from_collection(repo_id, user_id=user_id)
        _log_activity(
            user_id=user_id, action="remove_from_collection", resource_type="repository",
            resource_id=repo_id, duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    # ==========================================================================
    # RESEARCH PAPER TOOLS
    # ==========================================================================

    @server.tool()
    def index_paper(source: str) -> dict[str, Any]:
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
        import tempfile
        import os
        from synsc.services.paper_service_supabase import get_paper_service
        from synsc.core.arxiv_client import parse_arxiv_id, download_arxiv_pdf, get_arxiv_metadata, ArxivError
        
        start = time.time()
        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)
        
        # Check if source is a local PDF
        if os.path.isfile(source) and source.lower().endswith(".pdf"):
            result = service.index_paper(pdf_path=source, source="upload")
        else:
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
                result = service.index_paper(
                    pdf_path=pdf_path, source="arxiv",
                    arxiv_id=arxiv_id, arxiv_metadata=arxiv_metadata,
                )
            finally:
                try:
                    os.unlink(pdf_path)
                except OSError:
                    pass
        
        _log_activity(
            user_id=user_id, action="index_paper", resource_type="paper",
            resource_id=result.get("paper_id"), duration_ms=int((time.time() - start) * 1000),
            metadata={"source_input": source, "source": "mcp"},
        )
        return result

    @server.tool()
    def list_papers(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List all indexed papers.
        
        Args:
            limit: Maximum papers to return
            offset: Pagination offset
            
        Returns:
            Dictionary with papers list and total count
        """
        from synsc.services.paper_service_supabase import get_paper_service
        
        start = time.time()
        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)
        
        papers = service.list_papers(limit=limit)
        result = {"success": True, "papers": papers, "total": len(papers)}
        _log_activity(
            user_id=user_id, action="list_papers", resource_type="paper",
            results_count=len(papers), duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    @server.tool()
    def get_paper(paper_id: str) -> dict[str, Any]:
        """Get full paper content with all extracted features.
        
        Args:
            paper_id: Paper identifier
            
        Returns:
            Complete paper data including sections, citations, equations
        """
        from synsc.services.paper_service_supabase import get_paper_service
        
        start = time.time()
        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)
        
        paper = service.get_paper(paper_id)
        result = {"success": True, **paper} if paper else {"success": False, "error": "Paper not found"}
        _log_activity(
            user_id=user_id, action="get_paper", resource_type="paper",
            resource_id=paper_id, duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    @server.tool()
    def search_papers(query: str, top_k: int = 5) -> dict[str, Any]:
        """Search papers using semantic search.
        
        Args:
            query: Natural language search query
            top_k: Number of results to return
            
        Returns:
            Matching papers with relevance scores
        """
        from synsc.services.paper_service_supabase import get_paper_service
        
        start = time.time()
        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)
        
        result = service.search_papers(query=query, top_k=top_k)
        _log_activity(
            user_id=user_id, action="search_papers", resource_type="search",
            query=query, results_count=len(result.get("results", [])),
            duration_ms=int((time.time() - start) * 1000),
            metadata={"top_k": top_k, "source": "mcp"},
        )
        return result

    @server.tool()
    def get_citations(paper_id: str) -> dict[str, Any]:
        """Extract all citations from a paper.
        
        Args:
            paper_id: Paper identifier
            
        Returns:
            List of citations with context and links to indexed papers
        """
        from synsc.services.paper_service_supabase import get_paper_service
        
        start = time.time()
        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)
        
        citations = service.get_citations(paper_id)
        result = {
            "success": True,
            "paper_id": paper_id,
            "citations": citations,
            "total_citations": len(citations),
        }
        _log_activity(
            user_id=user_id, action="get_citations", resource_type="paper",
            resource_id=paper_id, results_count=result["total_citations"],
            duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    @server.tool()
    def get_equations(paper_id: str) -> dict[str, Any]:
        """Extract all equations from a paper.
        
        Args:
            paper_id: Paper identifier
            
        Returns:
            List of LaTeX equations with context
        """
        from synsc.services.paper_service_supabase import get_paper_service
        
        start = time.time()
        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)
        
        equations = service.get_equations(paper_id)
        result = {
            "success": True,
            "paper_id": paper_id,
            "equations": equations,
            "total_equations": len(equations),
        }
        _log_activity(
            user_id=user_id, action="get_equations", resource_type="paper",
            resource_id=paper_id, results_count=result["total_equations"],
            duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    @server.tool()
    def get_code_snippets(paper_id: str) -> dict[str, Any]:
        """Extract all code snippets from a paper.
        
        Args:
            paper_id: Paper identifier
            
        Returns:
            List of code blocks with language detection
        """
        from synsc.services.paper_service_supabase import get_paper_service
        
        start = time.time()
        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)
        
        # Code snippets are stored in paper_code_snippets table
        try:
            snippets = service.client.select("paper_code_snippets", "*", {"paper_id": paper_id})
        except Exception:
            snippets = []
        
        result = {
            "success": True,
            "paper_id": paper_id,
            "snippets": snippets,
            "total_snippets": len(snippets),
        }
        _log_activity(
            user_id=user_id, action="get_code_snippets", resource_type="paper",
            resource_id=paper_id, results_count=result["total_snippets"],
            duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    @server.tool()
    def generate_report(paper_id: str) -> dict[str, Any]:
        """Generate comprehensive markdown report for a paper.
        
        Creates a detailed report optimized for LLM consumption.
        
        Args:
            paper_id: Paper identifier
            
        Returns:
            Comprehensive markdown report
        """
        from synsc.services.paper_service_supabase import get_paper_service
        
        start = time.time()
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
        _log_activity(
            user_id=user_id, action="generate_report", resource_type="paper",
            resource_id=paper_id, duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    @server.tool()
    def compare_papers(paper_ids: list[str]) -> dict[str, Any]:
        """Compare multiple papers side-by-side.
        
        Args:
            paper_ids: List of 2-5 paper identifiers
            
        Returns:
            Comparison including common themes and differences
        """
        from synsc.services.paper_service_supabase import get_paper_service
        
        if not paper_ids or len(paper_ids) < 2:
            return {"success": False, "error": "Need at least 2 papers to compare"}
        
        if len(paper_ids) > 5:
            return {"success": False, "error": "Maximum 5 papers for comparison"}
        
        start = time.time()
        user_id = get_authenticated_user_id()
        service = get_paper_service(user_id=user_id)
        
        papers = []
        for pid in paper_ids:
            paper = service.get_paper(pid)
            if paper:
                papers.append({
                    "paper_id": pid,
                    "title": paper.get("title", "Untitled"),
                    "authors": paper.get("authors", "Unknown"),
                    "abstract": paper.get("abstract", ""),
                    "chunk_count": len(paper.get("chunks", [])),
                })
        
        if len(papers) < 2:
            return {"success": False, "error": "Could not retrieve at least 2 papers"}
        
        result = {
            "success": True,
            "papers": papers,
            "count": len(papers),
        }
        _log_activity(
            user_id=user_id, action="compare_papers", resource_type="paper",
            duration_ms=int((time.time() - start) * 1000),
            metadata={"paper_count": len(paper_ids), "source": "mcp"},
        )
        return result

    # ==========================================================================
    # HuggingFace Token Helpers
    # ==========================================================================

    def _require_hf_token(user_id: str | None) -> str:
        """Check the user has an HF token and return the decrypted value.

        Returns the plaintext token, or raises ValueError if not found.
        """
        if not user_id:
            raise ValueError("Authentication required")
        try:
            from synsc.supabase_auth import get_supabase_client
            from synsc.services.token_encryption import decrypt_token

            db = get_supabase_client()
            rows = db.select(
                "huggingface_tokens", columns="encrypted_token",
                filters={"user_id": user_id},
            )
            if not rows:
                raise ValueError(
                    "HuggingFace token required. Connect your HuggingFace account "
                    "at https://context.syntheticsciences.ai/api-keys"
                )
            try:
                db.update("huggingface_tokens", {"last_used_at": "now()"}, {"user_id": user_id})
            except Exception:
                pass
            return decrypt_token(rows[0]["encrypted_token"])
        except ValueError:
            raise
        except Exception as e:
            logger.error("Failed to retrieve HF token for MCP", error=str(e))
            raise ValueError("Failed to retrieve HuggingFace token")

    # ==========================================================================
    # HUGGINGFACE DATASET TOOLS
    # ==========================================================================

    @server.tool()
    def index_dataset(source: str) -> dict[str, Any]:
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
        from synsc.services.dataset_service import get_dataset_service
        from synsc.core.huggingface_client import parse_hf_dataset_id, HuggingFaceError

        start = time.time()
        user_id = get_authenticated_user_id()

        try:
            hf_token = _require_hf_token(user_id)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        service = get_dataset_service(user_id=user_id)

        try:
            hf_id = parse_hf_dataset_id(source)
        except HuggingFaceError:
            hf_id = source.strip()

        result = service.index_dataset(hf_id, hf_token=hf_token)
        _log_activity(
            user_id=user_id, action="index_dataset", resource_type="dataset",
            resource_id=result.get("dataset_id"),
            duration_ms=int((time.time() - start) * 1000),
            metadata={"source_input": source, "source": "mcp"},
        )
        return result

    @server.tool()
    def list_datasets(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List all indexed HuggingFace datasets.

        Shows datasets in your collection that have been indexed for search.

        Args:
            limit: Maximum number of datasets to return (default: 50)
            offset: Number of datasets to skip for pagination

        Returns:
            Dictionary with datasets list and total count
        """
        from synsc.services.dataset_service import get_dataset_service

        start = time.time()
        user_id = get_authenticated_user_id()

        try:
            _require_hf_token(user_id)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        service = get_dataset_service(user_id=user_id)
        datasets = service.list_datasets(limit=limit)

        _log_activity(
            user_id=user_id, action="list_datasets", resource_type="dataset",
            duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return {"success": True, "datasets": datasets, "total": len(datasets)}

    @server.tool()
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

        start = time.time()
        user_id = get_authenticated_user_id()

        try:
            _require_hf_token(user_id)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        service = get_dataset_service(user_id=user_id)
        dataset = service.get_dataset(dataset_id)

        if not dataset:
            return {"success": False, "error": "Dataset not found or access denied"}

        _log_activity(
            user_id=user_id, action="get_dataset", resource_type="dataset",
            resource_id=dataset_id,
            duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return {"success": True, "dataset": dataset}

    @server.tool()
    def search_datasets(query: str, top_k: int = 10) -> dict[str, Any]:
        """Search datasets using semantic search over dataset cards.

        Uses Gemini embeddings to find relevant datasets by meaning.
        Searches through indexed dataset documentation (README cards).

        Args:
            query: Natural language search query
            top_k: Number of results to return (default: 10)

        Returns:
            Matching dataset chunks with relevance scores
        """
        from synsc.services.dataset_service import get_dataset_service

        start = time.time()
        user_id = get_authenticated_user_id()

        try:
            _require_hf_token(user_id)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        service = get_dataset_service(user_id=user_id)
        result = service.search_datasets(query=query, top_k=top_k)

        results_count = len(result.get("results", [])) if isinstance(result, dict) else 0
        _log_activity(
            user_id=user_id, action="search_datasets", resource_type="search",
            query=query, results_count=results_count,
            duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    @server.tool()
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

        start = time.time()
        user_id = get_authenticated_user_id()

        try:
            _require_hf_token(user_id)
        except ValueError as e:
            return {"success": False, "error": str(e)}

        service = get_dataset_service(user_id=user_id)
        result = service.delete_dataset(dataset_id)

        _log_activity(
            user_id=user_id, action="delete_dataset", resource_type="dataset",
            resource_id=dataset_id,
            duration_ms=int((time.time() - start) * 1000),
            metadata={"source": "mcp"},
        )
        return result

    return server


def run_server():
    """Run the MCP server in stdio mode."""
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    run_server()
