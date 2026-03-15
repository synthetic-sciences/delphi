"""Shared fixtures for the synsc-context test suite.

All tests operate against an in-process FastAPI TestClient — no running
server or real Supabase/PostgreSQL instance is required.
"""

from __future__ import annotations

import atexit
import os
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# 1.  Environment — must happen BEFORE any synsc code is imported.
# ---------------------------------------------------------------------------

# Force auth OFF for most unit tests (individual tests can override)
os.environ.setdefault("SYNSC_REQUIRE_AUTH", "false")

# Provide dummy Supabase credentials so SynscConfig.initialize() succeeds
os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_DATABASE_URL", "postgresql://test:test@localhost:54322/test")

# ---------------------------------------------------------------------------
# 2.  Module-level patches — active for the ENTIRE test session.
#
#     create_app() calls get_paper_embedding_generator() (loads a ~500 MB
#     model) and init_db() runs in the lifespan startup.  Both must be
#     mocked BEFORE any test triggers that import.
# ---------------------------------------------------------------------------

_session_patches = [
    patch("synsc.database.connection.init_db"),
    patch("synsc.embeddings.generator.get_paper_embedding_generator"),
]
for _p in _session_patches:
    _p.start()

# Clean up when the interpreter shuts down (after all tests complete).
for _p in _session_patches:
    atexit.register(_p.stop)

# ---------------------------------------------------------------------------
# 3.  Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset the global config singleton between tests."""
    import synsc.config as cfg

    cfg._config = None
    yield
    cfg._config = None


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """Return a FastAPI TestClient with auth disabled (SYNSC_REQUIRE_AUTH=false)."""
    from synsc.api.http_server import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_client() -> Generator[TestClient, None, None]:
    """TestClient with ``SYNSC_REQUIRE_AUTH=true`` — most endpoints need a key."""
    old = os.environ.get("SYNSC_REQUIRE_AUTH")
    os.environ["SYNSC_REQUIRE_AUTH"] = "true"

    from synsc.api.http_server import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c

    # Restore previous value
    if old is None:
        os.environ.pop("SYNSC_REQUIRE_AUTH", None)
    else:
        os.environ["SYNSC_REQUIRE_AUTH"] = old
