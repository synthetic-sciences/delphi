"""Integration tests for every HTTP API endpoint.

These tests make REAL HTTP calls to a running synsc-context server.
No mocking — every request hits the actual database.

Requirements:
  • Server running at BASE_URL (default http://localhost:8742)
  • Valid API key in SYNSC_TEST_API_KEY env var (or default below)

Run:
    SYNSC_TEST_API_KEY=synsc_... pytest tests/test_http_endpoints.py -v
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

# ---------------------------------------------------------------------------
# Config — override via env vars
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("SYNSC_TEST_BASE_URL", "http://localhost:8742")
API_KEY = os.getenv(
    "SYNSC_TEST_API_KEY",
    "synsc_894f2b1dbf244113edbc767ad37ce68726453e56d42c1995",
)
AUTH = {"X-API-Key": API_KEY}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def http() -> httpx.Client:
    """Long-lived httpx client reused across all tests."""
    client = httpx.Client(base_url=BASE_URL, timeout=30)
    # Quick connectivity check
    try:
        r = client.get("/")
        r.raise_for_status()
    except httpx.ConnectError:
        pytest.skip(f"Server not reachable at {BASE_URL}")
    yield client
    client.close()


@pytest.fixture(scope="session")
def existing_repo_id(http: httpx.Client) -> str:
    """Return the ID of an already-indexed repo (first one)."""
    r = http.get("/v1/repositories", headers=AUTH)
    repos = r.json().get("repositories", [])
    if not repos:
        pytest.skip("No repos indexed — cannot run repo-dependent tests")
    return repos[0]["repo_id"]


@pytest.fixture(scope="session")
def existing_repo(http: httpx.Client) -> dict:
    """Return full first repo dict."""
    r = http.get("/v1/repositories", headers=AUTH)
    repos = r.json().get("repositories", [])
    if not repos:
        pytest.skip("No repos indexed")
    return repos[0]


@pytest.fixture(scope="session")
def existing_paper_id(http: httpx.Client) -> str:
    """Return the ID of an already-indexed paper (first one)."""
    r = http.get("/v1/papers", headers=AUTH)
    papers = r.json().get("papers", [])
    if not papers:
        pytest.skip("No papers indexed — cannot run paper-dependent tests")
    return papers[0]["paper_id"]


@pytest.fixture(scope="session")
def existing_file_path(http: httpx.Client, existing_repo_id: str) -> str:
    """Return a file path that exists in the first repo (via code search)."""
    # Use code search to discover a real file in this repo
    r = http.post(
        "/v1/search/code",
        headers={**AUTH, "Content-Type": "application/json"},
        json={"query": "import", "repo_ids": [existing_repo_id], "top_k": 1},
    )
    if r.status_code == 200:
        results = r.json().get("results", [])
        if results:
            return results[0]["file_path"]
    # Fallback: try common filenames
    for name in ["setup.py", "README.md", "pyproject.toml", "package.json", "setup.cfg"]:
        fr = http.post(
            "/v1/files/get",
            headers={**AUTH, "Content-Type": "application/json"},
            json={"repo_id": existing_repo_id, "file_path": name},
        )
        if fr.status_code == 200 and fr.json().get("success", False):
            return name
    pytest.skip("Could not find a known file in the first repo")


# ============================================================================
# 1.  Public / Info Endpoints
# ============================================================================


class TestPublicEndpoints:
    """No auth required."""

    def test_root(self, http: httpx.Client):
        r = http.get("/")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "Synsc Context API"
        assert "version" in data
        assert data["docs"] == "/docs"

    def test_health(self, http: httpx.Client):
        r = http.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert data["database_backend"] == "postgresql"
        assert data["vector_backend"] == "pgvector"
        assert data["auth_backend"] == "supabase"
        assert isinstance(data["uptime_seconds"], (int, float))
        assert isinstance(data["indexed_repos"], int)
        assert isinstance(data["indexed_papers"], int)

    def test_config(self, http: httpx.Client):
        r = http.get("/config")
        assert r.status_code == 200
        data = r.json()
        assert "supabase_url" in data
        assert "supabase_publishable_key" in data
        assert "api_url" in data

    def test_openapi_docs(self, http: httpx.Client):
        r = http.get("/docs")
        assert r.status_code == 200

    def test_redoc(self, http: httpx.Client):
        r = http.get("/redoc")
        assert r.status_code == 200


# ============================================================================
# 2.  Auth Enforcement
# ============================================================================


class TestAuthEnforcement:
    """Protected endpoints must reject unauthenticated requests."""

    PROTECTED_GETS = [
        "/v1/repositories",
        "/v1/papers",
        "/v1/keys",
        "/v1/activity",
        "/v1/activity/stats",
        "/v1/jobs",
    ]

    PROTECTED_POSTS = [
        ("/v1/repositories/index", {"url": "owner/repo"}),
        ("/v1/search/code", {"query": "hello"}),
        ("/v1/search/papers", {"query": "attention"}),
        ("/v1/symbols/search", {"name": "main"}),
        ("/v1/files/get", {"repo_id": str(uuid.uuid4()), "file_path": "x"}),
        ("/v1/keys", {"name": "test"}),
        ("/v1/jobs", {"job_type": "repository", "target": "owner/repo"}),
    ]

    @pytest.mark.parametrize("path", PROTECTED_GETS)
    def test_get_without_key(self, http: httpx.Client, path):
        r = http.get(path)  # no auth header
        assert r.status_code == 401

    @pytest.mark.parametrize("path,body", PROTECTED_POSTS)
    def test_post_without_key(self, http: httpx.Client, path, body):
        r = http.post(path, json=body)  # no auth header
        assert r.status_code == 401

    def test_invalid_key_rejected(self, http: httpx.Client):
        r = http.get("/v1/repositories", headers={"X-API-Key": "synsc_bogus_key_000"})
        assert r.status_code == 401


# ============================================================================
# 3.  Repository Endpoints
# ============================================================================


class TestRepositoryEndpoints:
    """CRUD + search for code repositories."""

    def test_list_repositories(self, http: httpx.Client):
        r = http.get("/v1/repositories", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert isinstance(data["repositories"], list)

    def test_list_repositories_with_limit(self, http: httpx.Client):
        r = http.get("/v1/repositories?limit=1", headers=AUTH)
        assert r.status_code == 200
        repos = r.json()["repositories"]
        assert len(repos) <= 1

    def test_get_repository(self, http: httpx.Client, existing_repo_id: str):
        r = http.get(f"/v1/repositories/{existing_repo_id}", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["repo_id"] == existing_repo_id
        assert "stats" in data
        assert "languages" in data

    def test_get_repository_bad_uuid(self, http: httpx.Client):
        r = http.get("/v1/repositories/not-a-uuid", headers=AUTH)
        assert r.status_code == 400
        assert "Invalid" in r.json()["error"]

    def test_get_repository_not_found(self, http: httpx.Client):
        fake = str(uuid.uuid4())
        r = http.get(f"/v1/repositories/{fake}", headers=AUTH)
        # Should be 200 with success=false or 404
        assert r.status_code in (200, 404)


# ============================================================================
# 4.  Code Search
# ============================================================================


class TestCodeSearch:
    """Semantic code search and symbol search."""

    def test_search_code(self, http: httpx.Client):
        r = http.post(
            "/v1/search/code",
            headers={**AUTH, "Content-Type": "application/json"},
            json={"query": "authentication", "top_k": 5},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert isinstance(data["results"], list)

    def test_search_code_with_language(self, http: httpx.Client):
        r = http.post(
            "/v1/search/code",
            headers={**AUTH, "Content-Type": "application/json"},
            json={"query": "import", "language": "python", "top_k": 3},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True

    def test_search_code_with_repo_filter(self, http: httpx.Client, existing_repo_id: str):
        r = http.post(
            "/v1/search/code",
            headers={**AUTH, "Content-Type": "application/json"},
            json={"query": "main", "repo_ids": [existing_repo_id], "top_k": 3},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        # All results should be from the requested repo
        for result in data["results"]:
            assert result["repo_id"] == existing_repo_id

    def test_search_symbols(self, http: httpx.Client):
        r = http.post(
            "/v1/symbols/search",
            headers={**AUTH, "Content-Type": "application/json"},
            json={"name": "main"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert isinstance(data["symbols"], list)

    def test_search_symbols_by_type(self, http: httpx.Client):
        r = http.post(
            "/v1/symbols/search",
            headers={**AUTH, "Content-Type": "application/json"},
            json={"name": "main", "symbol_type": "function"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        for sym in data["symbols"]:
            assert sym["symbol_type"] == "function"


# ============================================================================
# 5.  File Access
# ============================================================================


class TestFileAccess:
    """File content retrieval from indexed repos."""

    def test_get_file(self, http: httpx.Client, existing_repo_id: str, existing_file_path: str):
        r = http.post(
            "/v1/files/get",
            headers={**AUTH, "Content-Type": "application/json"},
            json={"repo_id": existing_repo_id, "file_path": existing_file_path},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "content" in data
        assert len(data["content"]) > 0

    def test_get_file_with_line_range(self, http: httpx.Client, existing_repo_id: str, existing_file_path: str):
        r = http.post(
            "/v1/files/get",
            headers={**AUTH, "Content-Type": "application/json"},
            json={
                "repo_id": existing_repo_id,
                "file_path": existing_file_path,
                "start_line": 1,
                "end_line": 5,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True

    def test_get_file_bad_uuid(self, http: httpx.Client):
        r = http.post(
            "/v1/files/get",
            headers={**AUTH, "Content-Type": "application/json"},
            json={"repo_id": "not-a-uuid", "file_path": "main.py"},
        )
        assert r.status_code == 400

    def test_get_file_not_found(self, http: httpx.Client, existing_repo_id: str):
        r = http.post(
            "/v1/files/get",
            headers={**AUTH, "Content-Type": "application/json"},
            json={"repo_id": existing_repo_id, "file_path": "nonexistent_xyz_abc.py"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("success") is False or "not found" in str(data).lower()


# ============================================================================
# 6.  Paper Endpoints
# ============================================================================


class TestPaperEndpoints:
    """CRUD for research papers."""

    def test_list_papers(self, http: httpx.Client):
        r = http.get("/v1/papers", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert isinstance(data["papers"], list)

    def test_list_papers_with_limit(self, http: httpx.Client):
        r = http.get("/v1/papers?limit=1", headers=AUTH)
        assert r.status_code == 200
        papers = r.json()["papers"]
        assert len(papers) <= 1

    def test_get_citations(self, http: httpx.Client, existing_paper_id: str):
        r = http.get(f"/v1/papers/{existing_paper_id}/citations", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "citations" in data
        assert isinstance(data["citations"], list)

    def test_get_equations(self, http: httpx.Client, existing_paper_id: str):
        r = http.get(f"/v1/papers/{existing_paper_id}/equations", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "equations" in data
        assert isinstance(data["equations"], list)


# ============================================================================
# 7.  API Key Management
# ============================================================================


class TestApiKeyEndpoints:
    """Full lifecycle: list → create → revoke → delete."""

    def test_list_keys(self, http: httpx.Client):
        r = http.get("/v1/keys", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert isinstance(data["keys"], list)
        assert data["total"] >= 1  # At least our test key exists

    def test_key_lifecycle(self, http: httpx.Client):
        """Create → verify in list → revoke → delete."""
        # --- Create ---
        r = http.post(
            "/v1/keys",
            headers={**AUTH, "Content-Type": "application/json"},
            json={"name": "pytest-integration-test"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "key" in data  # plaintext key returned once
        assert data["key"].startswith("synsc_")
        key_id = data["key_id"]

        # --- Verify it appears in list ---
        r = http.get("/v1/keys", headers=AUTH)
        ids = [k["id"] for k in r.json()["keys"]]
        assert key_id in ids

        # --- Revoke ---
        r = http.post(f"/v1/keys/{key_id}/revoke", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["success"] is True

        # --- Delete ---
        r = http.delete(f"/v1/keys/{key_id}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["success"] is True

        # --- Gone from list ---
        r = http.get("/v1/keys", headers=AUTH)
        ids = [k["id"] for k in r.json()["keys"]]
        assert key_id not in ids


# ============================================================================
# 8.  Activity & Stats
# ============================================================================


class TestActivityEndpoints:
    """Activity log and aggregate stats."""

    def test_list_activity(self, http: httpx.Client):
        r = http.get("/v1/activity?time_range=30d", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert isinstance(data["activities"], list)

    def test_list_activity_with_limit(self, http: httpx.Client):
        r = http.get("/v1/activity?time_range=7d&limit=2", headers=AUTH)
        assert r.status_code == 200
        acts = r.json()["activities"]
        assert len(acts) <= 2

    def test_activity_stats(self, http: httpx.Client):
        r = http.get("/v1/activity/stats?time_range=30d", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        stats = data["stats"]
        assert "total" in stats
        assert "by_action" in stats
        assert isinstance(stats["total"], int)


# ============================================================================
# 9.  Job Queue
# ============================================================================


class TestJobEndpoints:
    """Job listing and status."""

    def test_list_jobs(self, http: httpx.Client):
        r = http.get("/v1/jobs", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert isinstance(data["jobs"], list)

    def test_get_job_bad_uuid(self, http: httpx.Client):
        r = http.get("/v1/jobs/not-a-uuid", headers=AUTH)
        assert r.status_code == 400

    def test_get_job_not_found(self, http: httpx.Client):
        fake = str(uuid.uuid4())
        r = http.get(f"/v1/jobs/{fake}", headers=AUTH)
        # Should return something (not crash)
        assert r.status_code in (200, 404)


# ============================================================================
# 10.  CLI Auth
# ============================================================================


class TestCliAuth:
    """Device-flow authentication for CLI tools."""

    def test_start_and_poll(self, http: httpx.Client):
        # Start session
        r = http.post("/api/cli/auth/start")
        assert r.status_code == 200
        data = r.json()
        assert "device_code" in data
        assert "user_code" in data
        assert data["expires_in"] > 0

        # Poll — should be pending
        device_code = data["device_code"]
        r = http.get(f"/api/cli/auth/status/{device_code}")
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

    def test_poll_unknown_session(self, http: httpx.Client):
        r = http.get("/api/cli/auth/status/nonexistent-device-code-xyz")
        # Should be 404 or return expired
        assert r.status_code in (200, 404)


# ============================================================================
# 11.  Error Handling (no internal leaks)
# ============================================================================


class TestErrorHandling:
    """Verify error responses don't leak internals."""

    def test_bad_uuid_returns_clean_error(self, http: httpx.Client):
        r = http.get("/v1/repositories/not-a-uuid", headers=AUTH)
        assert r.status_code == 400
        body = str(r.json())
        assert "traceback" not in body.lower()
        assert "sqlalchemy" not in body.lower()

    def test_404_endpoint(self, http: httpx.Client):
        r = http.get("/v1/nonexistent", headers=AUTH)
        assert r.status_code in (404, 405)
