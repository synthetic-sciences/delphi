"""Smoke tests – verify core modules import without errors.

These catch broken imports, circular dependencies, and missing packages
early without needing a running database.
"""

import importlib
import pytest


CORE_MODULES = [
    "synsc",
    "synsc.config",
    "synsc.cli",
    "synsc.api.http_server",
    "synsc.api.mcp_server",
    "synsc.database.models",
    "synsc.embeddings.generator",
    "synsc.core.git_client",
    "synsc.services.indexing_service",
    "synsc.services.search_service",
    "synsc.services.paper_service_supabase",
    "synsc.services.symbol_service",
    "synsc.supabase_auth",
    "synsc.workers.indexing_worker",
]


@pytest.mark.parametrize("module_name", CORE_MODULES)
def test_core_module_imports(module_name: str):
    """Each core module should import without raising."""
    mod = importlib.import_module(module_name)
    assert mod is not None


def test_no_legacy_paper_service_import_in_mcp():
    """The MCP server must NOT import the legacy FAISS-based PaperService."""
    import ast
    from pathlib import Path

    mcp_path = Path("synsc/api/mcp_server.py")
    source = mcp_path.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "paper_service" in node.module:
                # Only paper_service_supabase is allowed
                assert "supabase" in node.module, (
                    f"MCP server imports legacy paper_service: {node.module}"
                )
