"""Integration tests for every MCP server tool.

These tests call the MCP tool functions DIRECTLY against the real database.
No mocking — each tool hits Supabase/PostgreSQL for real.

Requirements:
  • Real database credentials in the environment (loaded from .env)
  • At least one indexed repo and one indexed paper in the DB
  • Valid API key in SYNSC_TEST_API_KEY env var (or default below)

Run:
    SYNSC_TEST_API_KEY=synsc_... pytest tests/test_mcp_tools.py -v
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Environment setup — load .env BEFORE any synsc imports
# ---------------------------------------------------------------------------

def _load_dotenv():
    """Manually load .env file into os.environ (no external dependency).

    Uses force-set (not setdefault) because conftest.py already set dummy
    values before this file is imported.
    """
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)', line)
        if m:
            key, val = m.group(1), m.group(2)
            # Strip surrounding quotes
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            os.environ[key] = val  # Force-set, overriding conftest dummies


_load_dotenv()

API_KEY = os.getenv(
    "SYNSC_TEST_API_KEY",
    "synsc_894f2b1dbf244113edbc767ad37ce68726453e56d42c1995",
)

# MCP tools read SYNSC_API_KEY as auth fallback when no context var is set
os.environ["SYNSC_API_KEY"] = API_KEY


# ---------------------------------------------------------------------------
# Undo the conftest session-level mocks so we can use real DB
# ---------------------------------------------------------------------------

import tests.conftest as _root_conftest  # noqa: E402

for _p in _root_conftest._session_patches:
    try:
        _p.stop()
    except RuntimeError:
        pass  # Already stopped


# ---------------------------------------------------------------------------
# Real DB initialisation
# ---------------------------------------------------------------------------

def _init_real_db():
    """Initialise the real database connection."""
    import importlib

    # Reset config singleton so it picks up the real env vars
    import synsc.config as cfg
    cfg._config = None

    # Reload supabase_auth so its module-level constants pick up the real env
    import synsc.supabase_auth
    importlib.reload(synsc.supabase_auth)

    from synsc.database.connection import init_db
    try:
        init_db()
        return True
    except Exception:
        return False


_DB_READY = _init_real_db()


# ---------------------------------------------------------------------------
# MCP tool extraction
# ---------------------------------------------------------------------------

def _extract_tools() -> dict[str, Any]:
    """Create the MCP server and extract all registered tool functions."""
    from synsc.api.mcp_server import create_server

    server = create_server()

    tools: dict[str, Any] = {}
    tool_mgr = getattr(server, "_tool_manager", None)
    if tool_mgr and hasattr(tool_mgr, "_tools"):
        for name, tool_obj in tool_mgr._tools.items():
            tools[name] = tool_obj.fn
    return tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mcp_tools() -> dict[str, Any]:
    if not _DB_READY:
        pytest.skip("Real database not available — skipping MCP integration tests")
    tools = _extract_tools()
    if not tools:
        pytest.skip("Could not extract MCP tool functions from FastMCP server")
    return tools


@pytest.fixture(scope="session")
def existing_repo_id(mcp_tools) -> str:
    """Get a real repo_id from the database."""
    result = mcp_tools["list_repositories"](1, 0)
    repos = result.get("repositories", [])
    if not repos:
        pytest.skip("No repos indexed")
    return repos[0]["repo_id"]


@pytest.fixture(scope="session")
def existing_paper_id(mcp_tools) -> str:
    """Get a real paper_id from the database."""
    result = mcp_tools["list_papers"](1, 0)
    papers = result.get("papers", [])
    if not papers:
        pytest.skip("No papers indexed")
    return papers[0]["paper_id"]


# ============================================================================
# Tool Registration
# ============================================================================


class TestToolRegistration:
    """Verify the MCP server registers all expected tools."""

    EXPECTED_CODE_TOOLS = [
        "index_repository",
        "list_repositories",
        "get_repository",
        "delete_repository",
        "search_code",
        "get_file",
        "search_symbols",
        "analyze_repository",
    ]

    EXPECTED_PAPER_TOOLS = [
        "index_paper",
        "list_papers",
        "get_paper",
        "search_papers",
        "get_citations",
        "get_equations",
        "get_code_snippets",
        "generate_report",
        "compare_papers",
    ]

    def test_all_code_tools_registered(self, mcp_tools):
        for name in self.EXPECTED_CODE_TOOLS:
            assert name in mcp_tools, f"Code tool '{name}' not registered"

    def test_all_paper_tools_registered(self, mcp_tools):
        for name in self.EXPECTED_PAPER_TOOLS:
            assert name in mcp_tools, f"Paper tool '{name}' not registered"

    def test_total_tool_count(self, mcp_tools):
        expected = len(self.EXPECTED_CODE_TOOLS) + len(self.EXPECTED_PAPER_TOOLS)
        assert len(mcp_tools) >= expected, (
            f"Expected ≥{expected} tools, got {len(mcp_tools)}: {sorted(mcp_tools)}"
        )


# ============================================================================
# Code Repository Tools (real DB)
# ============================================================================


class TestCodeTools:
    """Call each code/repository MCP tool against the real database."""

    def test_list_repositories(self, mcp_tools):
        result = mcp_tools["list_repositories"](50, 0)
        assert isinstance(result, dict)
        assert "repositories" in result
        assert isinstance(result["repositories"], list)
        assert result["total"] >= 1, "Expected at least 1 indexed repo"

    def test_get_repository(self, mcp_tools, existing_repo_id: str):
        result = mcp_tools["get_repository"](existing_repo_id)
        assert isinstance(result, dict)
        assert result.get("repo_id") == existing_repo_id or result.get("success") is True

    def test_search_code(self, mcp_tools):
        result = mcp_tools["search_code"]("import os", top_k=3)
        assert isinstance(result, dict)
        assert "results" in result
        assert isinstance(result["results"], list)

    def test_search_code_with_language(self, mcp_tools):
        result = mcp_tools["search_code"](
            "main function", language="python", top_k=3,
        )
        assert isinstance(result, dict)
        assert "results" in result

    def test_search_code_with_repo_filter(self, mcp_tools, existing_repo_id: str):
        result = mcp_tools["search_code"](
            "setup", repo_ids=[existing_repo_id], top_k=3,
        )
        assert isinstance(result, dict)
        for r in result.get("results", []):
            assert r["repo_id"] == existing_repo_id

    def test_get_file(self, mcp_tools, existing_repo_id: str):
        # First find a file that exists
        search = mcp_tools["search_code"]("import", repo_ids=[existing_repo_id], top_k=1)
        results = search.get("results", [])
        if not results:
            pytest.skip("No search results to get a file path from")

        file_path = results[0]["file_path"]
        result = mcp_tools["get_file"](existing_repo_id, file_path)
        assert isinstance(result, dict)
        assert "content" in result or "file_path" in result

    def test_search_symbols(self, mcp_tools):
        result = mcp_tools["search_symbols"]("main", top_k=5)
        assert isinstance(result, dict)
        assert "symbols" in result
        assert isinstance(result["symbols"], list)

    def test_search_symbols_by_type(self, mcp_tools):
        result = mcp_tools["search_symbols"]("main", symbol_type="function", top_k=5)
        assert isinstance(result, dict)
        for sym in result.get("symbols", []):
            assert sym["symbol_type"] == "function"

    def test_analyze_repository(self, mcp_tools, existing_repo_id: str):
        result = mcp_tools["analyze_repository"](existing_repo_id)
        assert isinstance(result, dict)
        # Should have analysis fields
        assert any(
            k in result
            for k in ("structure", "entry_points", "frameworks", "repo_id", "analysis")
        )


# ============================================================================
# Paper Tools (real DB)
# ============================================================================


class TestPaperTools:
    """Call each paper MCP tool against the real database."""

    def test_list_papers(self, mcp_tools):
        result = mcp_tools["list_papers"](50, 0)
        assert isinstance(result, dict)
        assert result["success"] is True
        assert isinstance(result["papers"], list)

    def test_get_paper(self, mcp_tools, existing_paper_id: str):
        result = mcp_tools["get_paper"](existing_paper_id)
        assert isinstance(result, dict)
        assert result["success"] is True
        assert "title" in result

    def test_get_paper_not_found(self, mcp_tools):
        import uuid
        fake_id = str(uuid.uuid4())
        result = mcp_tools["get_paper"](fake_id)
        assert isinstance(result, dict)
        assert result["success"] is False

    def test_search_papers(self, mcp_tools):
        result = mcp_tools["search_papers"]("encryption", top_k=3)
        assert isinstance(result, dict)
        assert "results" in result

    def test_get_citations(self, mcp_tools, existing_paper_id: str):
        result = mcp_tools["get_citations"](existing_paper_id)
        assert isinstance(result, dict)
        assert result["success"] is True
        assert "citations" in result
        assert isinstance(result["citations"], list)
        assert "total_citations" in result

    def test_get_equations(self, mcp_tools, existing_paper_id: str):
        result = mcp_tools["get_equations"](existing_paper_id)
        assert isinstance(result, dict)
        assert result["success"] is True
        assert "equations" in result
        assert isinstance(result["equations"], list)

    def test_get_code_snippets(self, mcp_tools, existing_paper_id: str):
        result = mcp_tools["get_code_snippets"](existing_paper_id)
        assert isinstance(result, dict)
        assert result["success"] is True
        assert "snippets" in result

    def test_generate_report(self, mcp_tools, existing_paper_id: str):
        result = mcp_tools["generate_report"](existing_paper_id)
        assert isinstance(result, dict)
        assert result["success"] is True
        assert "report" in result
        assert isinstance(result["report"], str)
        assert len(result["report"]) > 0

    def test_generate_report_not_found(self, mcp_tools):
        import uuid
        result = mcp_tools["generate_report"](str(uuid.uuid4()))
        assert isinstance(result, dict)
        assert result["success"] is False

    def test_compare_papers_too_few(self, mcp_tools):
        result = mcp_tools["compare_papers"](["only-one"])
        assert result["success"] is False
        assert "at least 2" in result["error"].lower()

    def test_compare_papers_too_many(self, mcp_tools):
        ids = [f"p{i}" for i in range(6)]
        result = mcp_tools["compare_papers"](ids)
        assert result["success"] is False

    def test_compare_papers(self, mcp_tools, existing_paper_id: str):
        # Compare the same paper with itself (simplest test with 1 paper)
        result = mcp_tools["compare_papers"]([existing_paper_id, existing_paper_id])
        assert isinstance(result, dict)
        assert result["success"] is True
        assert result["count"] == 2


# ============================================================================
# Restart conftest patches for other test files
# ============================================================================

def teardown_module():
    """Re-apply conftest patches so other test files are unaffected."""
    for _p in _root_conftest._session_patches:
        try:
            _p.start()
        except RuntimeError:
            pass  # Already started
