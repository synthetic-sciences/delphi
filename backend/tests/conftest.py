"""Shared fixtures for the synsc-context test suite.

All tests operate against an in-process FastAPI TestClient — no running
server or real PostgreSQL instance is required.
"""

from __future__ import annotations

import atexit
import os
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# 1.  Environment — must happen BEFORE any synsc code is imported.
# ---------------------------------------------------------------------------

# Force auth OFF for most unit tests (individual tests can override)
os.environ.setdefault("SYNSC_REQUIRE_AUTH", "false")

# Provide a dummy DATABASE_URL so SynscConfig.initialize() succeeds
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")

# SERVER_SECRET is required for JWT encode/decode in auth tests
os.environ.setdefault("SERVER_SECRET", "test-secret-for-unit-tests-only")

# ---------------------------------------------------------------------------
# 2.  Module-level patches — active for the ENTIRE test session.
#
#     create_app() calls get_embedding_generator() (loads a ~500 MB
#     model) and init_db() runs in the lifespan startup.  Both must be
#     mocked BEFORE any test triggers that import.
# ---------------------------------------------------------------------------

_session_patches = [
    patch("synsc.database.connection.init_db"),
    patch("synsc.embeddings.generator.get_embedding_generator"),
    patch(
        "synsc.api.http_server._get_or_create_admin_user",
        return_value="test-admin-user-id",
    ),
    patch(
        "synsc.api.http_server._validate_api_key_db",
        return_value=None,
    ),
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
    """Reset the global config singleton and DB engine between tests."""
    import synsc.config as cfg
    import synsc.database.connection as conn

    cfg._config = None
    conn.reset_engine()
    yield
    cfg._config = None
    conn.reset_engine()


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """Return a FastAPI TestClient with auth disabled (SYNSC_REQUIRE_AUTH=false)."""
    from synsc.api.http_server import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_client() -> Generator[TestClient, None, None]:
    """TestClient with ``SYNSC_REQUIRE_AUTH=true`` — most endpoints need a key.

    Uses SYSTEM_PASSWORD for authentication (verify_api_key checks this as
    a fallback). Pass the password as X-API-Key or Authorization: Bearer header.
    """
    old_auth = os.environ.get("SYNSC_REQUIRE_AUTH")
    old_pw = os.environ.get("SYSTEM_PASSWORD")
    os.environ["SYNSC_REQUIRE_AUTH"] = "true"
    os.environ["SYSTEM_PASSWORD"] = "test-password-123"

    from synsc.api.http_server import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c

    # Restore previous values
    if old_auth is None:
        os.environ.pop("SYNSC_REQUIRE_AUTH", None)
    else:
        os.environ["SYNSC_REQUIRE_AUTH"] = old_auth
    if old_pw is None:
        os.environ.pop("SYSTEM_PASSWORD", None)
    else:
        os.environ["SYSTEM_PASSWORD"] = old_pw
