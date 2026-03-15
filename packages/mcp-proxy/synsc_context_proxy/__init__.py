"""
Lightweight MCP stdio proxy for SyntheticSciences Context.

Runs locally as an MCP stdio server and proxies all tool calls to the
hosted backend API. Users only need SYNSC_API_KEY — no heavy dependencies,
no Supabase credentials required.

Install:
    uvx synsc-context-proxy

Setup (Claude Desktop / Cursor / Claude Code):
    {
      "mcpServers": {
        "synsc-context": {
          "command": "uvx",
          "args": ["synsc-context-proxy"],
          "env": { "SYNSC_API_KEY": "YOUR_API_KEY" }
        }
      }
    }

Get your API key at https://context.syntheticsciences.ai
"""

import json
import os
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

REMOTE_URL = os.environ.get(
    "SYNSC_API_URL", "https://synsc-context.onrender.com"
)
API_KEY = os.environ.get("SYNSC_API_KEY", "")

server = FastMCP("synsc-context")


async def _call_remote(tool_name: str, arguments: dict) -> dict[str, Any]:
    """Forward a tool call to the remote /mcp endpoint via JSON-RPC."""
    if not API_KEY:
        return {"success": False, "error": "SYNSC_API_KEY environment variable is not set."}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{REMOTE_URL}/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=300,
        )

        # Handle HTTP errors (e.g. 401 Unauthorized)
        if resp.status_code != 200:
            detail = resp.text
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                pass
            return {"success": False, "error": f"HTTP {resp.status_code}: {detail}"}

        data = resp.json()

        if "error" in data:
            return {"success": False, "error": data["error"].get("message", "Remote server error")}

        # Extract text content from MCP response
        content = data.get("result", {}).get("content", [])
        for block in content:
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except (json.JSONDecodeError, TypeError):
                    return {"success": True, "result": block["text"]}

        return {"success": True, "result": str(content)}


# ---------------------------------------------------------------------------
# REPOSITORY TOOLS
# ---------------------------------------------------------------------------


@server.tool()
async def index_repository(url: str, branch: str = "main") -> dict[str, Any]:
    """Index a GitHub repository for semantic code search.

    SMART DEDUPLICATION:
    - If a PUBLIC repo is already indexed by someone else, it's instantly
      added to your collection (no re-indexing needed!)
    - If it's a NEW repo, it gets indexed and added to your collection
    - PRIVATE repos are only accessible by you

    Args:
        url: GitHub repository URL (https://github.com/owner/repo) or shorthand (owner/repo)
        branch: Branch to index (default: main)
    """
    return await _call_remote("index_repository", {"url": url, "branch": branch})


@server.tool()
async def list_repositories(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """List repositories in your collection.

    Shows all repos you've added (indexed or shared).
    You can only search repos that are in your collection.

    Args:
        limit: Maximum number of repositories to return (default: 50)
        offset: Number of repositories to skip for pagination
    """
    return await _call_remote("list_repositories", {"limit": limit, "offset": offset})


@server.tool()
async def get_repository(repo_id: str) -> dict[str, Any]:
    """Get detailed information about an indexed repository.

    Args:
        repo_id: Repository identifier (UUID)
    """
    return await _call_remote("get_repository", {"repo_id": repo_id})


@server.tool()
async def delete_repository(repo_id: str) -> dict[str, Any]:
    """Permanently delete a repository from the index.

    WARNING: This deletes ALL data including files, chunks, and embeddings.
    For PUBLIC repos, this removes it for ALL users who added it!

    Args:
        repo_id: Repository identifier (UUID)
    """
    return await _call_remote("delete_repository", {"repo_id": repo_id})


@server.tool()
async def remove_from_collection(repo_id: str) -> dict[str, Any]:
    """Remove a repository from your collection.

    This removes the repo from YOUR searchable collection without deleting
    the actual indexed data. The repo remains available for other users.

    Args:
        repo_id: Repository identifier (UUID)
    """
    return await _call_remote("remove_from_collection", {"repo_id": repo_id})


# ---------------------------------------------------------------------------
# SEARCH TOOLS
# ---------------------------------------------------------------------------


@server.tool()
async def search_code(
    query: str,
    repo_ids: list[str] | None = None,
    language: str | None = None,
    file_pattern: str | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    """Search code using natural language or keywords.

    Uses semantic search (embeddings) to find relevant code snippets.
    Results are ranked by relevance score.

    Args:
        query: Natural language query or keywords
        repo_ids: Optional list of repository IDs to limit search
        language: Filter by programming language (e.g., "python", "typescript")
        file_pattern: Glob pattern for file paths (e.g., "*.test.ts", "src/**/*.py")
        top_k: Number of results to return (default: 10, max: 100)
    """
    return await _call_remote(
        "search_code",
        {
            "query": query,
            "repo_ids": repo_ids,
            "language": language,
            "file_pattern": file_pattern,
            "top_k": top_k,
        },
    )


@server.tool()
async def get_file(
    repo_id: str,
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict[str, Any]:
    """Get file content from an indexed repository.

    Retrieves the full file or a specific line range.

    Args:
        repo_id: Repository identifier
        file_path: Path to file within repository (e.g., "src/main.py")
        start_line: Starting line number (1-indexed, optional)
        end_line: Ending line number (optional)
    """
    return await _call_remote(
        "get_file",
        {
            "repo_id": repo_id,
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
        },
    )


# ---------------------------------------------------------------------------
# ANALYSIS TOOLS
# ---------------------------------------------------------------------------


@server.tool()
async def analyze_repository(repo_id: str) -> dict[str, Any]:
    """Get comprehensive analysis of an indexed repository.

    Provides deep understanding of a codebase including:
    - Directory structure with annotations
    - Entry points (main files, CLI, API endpoints)
    - Dependencies from manifest files
    - Framework detection
    - Architecture pattern detection
    - Key files (README, configs, CI/CD)
    - Coding conventions

    Args:
        repo_id: Repository identifier (UUID)
    """
    return await _call_remote("analyze_repository", {"repo_id": repo_id})


@server.tool()
async def get_directory_structure(
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
    return await _call_remote(
        "get_directory_structure",
        {"repo_id": repo_id, "max_depth": max_depth, "annotate": annotate},
    )


# ---------------------------------------------------------------------------
# SYMBOL TOOLS
# ---------------------------------------------------------------------------


@server.tool()
async def search_symbols(
    name: str,
    repo_ids: list[str] | None = None,
    symbol_type: str | None = None,
    language: str | None = None,
    top_k: int = 20,
) -> dict[str, Any]:
    """Search for code symbols (functions, classes, methods) by name.

    Finds functions, classes, and methods using partial name matching.
    Use this to locate specific code constructs without knowing their exact location.

    Args:
        name: Symbol name to search for (partial match supported)
        repo_ids: Optional list of repository IDs to limit search
        symbol_type: Filter by type: "function", "class", "method"
        language: Filter by programming language (e.g., "python")
        top_k: Maximum results to return (default: 20)
    """
    return await _call_remote(
        "search_symbols",
        {
            "name": name,
            "repo_ids": repo_ids,
            "symbol_type": symbol_type,
            "language": language,
            "top_k": top_k,
        },
    )


@server.tool()
async def get_symbol(symbol_id: str) -> dict[str, Any]:
    """Get detailed information about a specific code symbol.

    Returns complete symbol details including full docstring,
    parameters with types, return type, and decorators.

    Args:
        symbol_id: Symbol identifier (UUID from search_symbols)
    """
    return await _call_remote("get_symbol", {"symbol_id": symbol_id})


# ---------------------------------------------------------------------------
# RESEARCH PAPER TOOLS
# ---------------------------------------------------------------------------


@server.tool()
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
    """
    return await _call_remote("index_paper", {"source": source})


@server.tool()
async def list_papers(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """List all indexed papers.

    Args:
        limit: Maximum papers to return (default: 50)
        offset: Number of papers to skip for pagination
    """
    return await _call_remote("list_papers", {"limit": limit, "offset": offset})


@server.tool()
async def get_paper(paper_id: str) -> dict[str, Any]:
    """Get full paper content with all extracted features.

    Returns complete paper data including sections, citations, equations,
    and code snippets.

    Args:
        paper_id: Paper identifier (UUID)
    """
    return await _call_remote("get_paper", {"paper_id": paper_id})


@server.tool()
async def search_papers(query: str, top_k: int = 5) -> dict[str, Any]:
    """Search papers using semantic search.

    Uses embeddings to find relevant papers by meaning, not just keywords.

    Args:
        query: Natural language search query
        top_k: Number of results to return (default: 5)
    """
    return await _call_remote("search_papers", {"query": query, "top_k": top_k})


@server.tool()
async def get_citations(paper_id: str) -> dict[str, Any]:
    """Extract all citations from a paper.

    Args:
        paper_id: Paper identifier (UUID)
    """
    return await _call_remote("get_citations", {"paper_id": paper_id})


@server.tool()
async def get_equations(paper_id: str) -> dict[str, Any]:
    """Extract all equations from a paper.

    Args:
        paper_id: Paper identifier (UUID)
    """
    return await _call_remote("get_equations", {"paper_id": paper_id})


@server.tool()
async def get_code_snippets(paper_id: str) -> dict[str, Any]:
    """Extract all code snippets from a paper.

    Args:
        paper_id: Paper identifier (UUID)
    """
    return await _call_remote("get_code_snippets", {"paper_id": paper_id})


@server.tool()
async def generate_report(paper_id: str) -> dict[str, Any]:
    """Generate comprehensive markdown report for a paper.

    Creates a detailed report optimized for LLM consumption including
    content, citations, and equations.

    Args:
        paper_id: Paper identifier (UUID)
    """
    return await _call_remote("generate_report", {"paper_id": paper_id})


@server.tool()
async def compare_papers(paper_ids: list[str]) -> dict[str, Any]:
    """Compare multiple papers side-by-side.

    Provides comparison including common themes and differences.

    Args:
        paper_ids: List of 2-5 paper identifiers (UUIDs)
    """
    return await _call_remote("compare_papers", {"paper_ids": paper_ids})


# ---------------------------------------------------------------------------
# HUGGINGFACE DATASET TOOLS
# ---------------------------------------------------------------------------


@server.tool()
async def index_dataset(source: str) -> dict[str, Any]:
    """Index a HuggingFace dataset card for semantic search.

    Indexes dataset metadata and README content (never downloads actual data rows).

    Supports multiple formats:
    - Plain ID: "imdb", "openai/gsm8k"
    - HF URL: "https://huggingface.co/datasets/openai/gsm8k"

    Features global deduplication - if dataset already indexed,
    returns existing dataset ID instantly.

    Args:
        source: HuggingFace dataset ID or URL
    """
    return await _call_remote("index_dataset", {"source": source})


@server.tool()
async def list_datasets(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """List all indexed datasets.

    Args:
        limit: Maximum datasets to return (default: 50)
        offset: Number of datasets to skip for pagination
    """
    return await _call_remote("list_datasets", {"limit": limit, "offset": offset})


@server.tool()
async def get_dataset(dataset_id: str) -> dict[str, Any]:
    """Get detailed information about an indexed dataset.

    Returns dataset metadata including description, features, splits,
    tags, and chunk content.

    Args:
        dataset_id: Dataset identifier (UUID)
    """
    return await _call_remote("get_dataset", {"dataset_id": dataset_id})


@server.tool()
async def search_datasets(query: str, top_k: int = 10) -> dict[str, Any]:
    """Search datasets using semantic search.

    Uses embeddings to find relevant datasets by meaning, not just keywords.

    Args:
        query: Natural language search query
        top_k: Number of results to return (default: 10)
    """
    return await _call_remote("search_datasets", {"query": query, "top_k": top_k})


@server.tool()
async def delete_dataset(dataset_id: str) -> dict[str, Any]:
    """Remove a dataset from your collection.

    For public datasets, removes from your collection only (data stays for others).
    For private/gated datasets, fully deletes all data.

    Args:
        dataset_id: Dataset identifier (UUID)
    """
    return await _call_remote("delete_dataset", {"dataset_id": dataset_id})


def main():
    """Entry point for synsc-context-proxy CLI."""
    if not API_KEY:
        print(
            "Error: SYNSC_API_KEY environment variable is not set.\n"
            "Get your API key from https://context.syntheticsciences.ai",
            file=sys.stderr,
        )
        sys.exit(1)

    server.run(transport="stdio")


if __name__ == "__main__":
    main()
