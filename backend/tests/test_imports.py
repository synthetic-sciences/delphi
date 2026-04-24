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
    "synsc.logging",
    "synsc.api.http_server",
    "synsc.api.mcp_server",
    "synsc.api.rate_limit",
    "synsc.database.models",
    "synsc.embeddings.generator",
    "synsc.core.git_client",
    "synsc.services.indexing_service",
    "synsc.services.search_service",
    "synsc.services.paper_service",
    "synsc.services.symbol_service",
    "synsc.workers.indexing_worker",
]


@pytest.mark.parametrize("module_name", CORE_MODULES)
def test_core_module_imports(module_name: str):
    """Each core module should import without raising."""
    mod = importlib.import_module(module_name)
    assert mod is not None
