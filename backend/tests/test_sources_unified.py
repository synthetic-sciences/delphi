"""Unit tests for the unified /v1/search + /v1/sources surface.

Covers the service-level dispatchers in ``synsc.services.source_service``
and the HTTP endpoints that call into them.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _disable_slowapi(monkeypatch):
    """Slowapi keeps a global in-memory rate-limit counter that leaks across
    tests (no per-test reset hook). Disable it for this file so the tight
    INDEX_LIMIT (5/min) doesn't 429 the second /v1/sources test that runs."""
    from synsc.api.rate_limit import limiter
    from synsc.services import source_service

    was_enabled = limiter.enabled
    limiter.enabled = False
    monkeypatch.setattr(
        source_service,
        "publish_source_snapshot",
        lambda source_type, source_id, user_id: {
            "snapshot_id": f"snapshot-{source_id}",
            "source_id": source_id,
            "source_type": source_type,
            "version": "test-version",
        },
        raising=False,
    )
    yield
    limiter.enabled = was_enabled


# ---------------------------------------------------------------------------
# Service-level: unified_search
# ---------------------------------------------------------------------------


def test_normalize_mode_resolves_nia_aliases():
    from synsc.services.source_service import normalize_mode

    assert normalize_mode("targeted") == "precise"
    assert normalize_mode("universal") == "thorough"
    assert normalize_mode("precise") == "precise"
    assert normalize_mode("thorough") == "thorough"
    assert normalize_mode("web") == "web"


def test_normalize_mode_rejects_unknown_mode():
    import pytest

    from synsc.services.source_service import normalize_mode

    with pytest.raises(ValueError, match="unsupported search mode"):
        normalize_mode("zoomzoom")


def test_unified_search_dedupes_by_text_hash(monkeypatch):
    """Two hits with identical text collapse to one in the unified envelope."""
    from synsc.services import source_service

    duplicate = {
        "source_type": "repo",
        "source_id": "r1",
        "chunk_id": "c1",
        "text": "same body",
        "score": 0.9,
        "path": "a.py",
        "line_no": 1,
    }
    distinct = {
        "source_type": "paper",
        "source_id": "p1",
        "chunk_id": "c2",
        "text": "different body",
        "score": 0.8,
        "path": "Intro",
        "line_no": None,
    }

    monkeypatch.setattr(
        source_service,
        "unified_retrieve",
        lambda **kwargs: [duplicate, dict(duplicate, chunk_id="c1b"), distinct],
    )

    result = source_service.unified_search(query="q", k=10, mode="precise")

    assert result["mode_applied"] == "precise"
    assert result["total"] == 2
    assert {h["chunk_id"] for h in result["results"]} == {"c1", "c2"}


def test_unified_search_web_mode_uses_policy_executor(monkeypatch):
    from synsc.planner.contracts import (
        QueryExecution,
        RetrievalHit,
        RetrievalProvenance,
    )
    from synsc.providers.contracts import ExecutionLocation
    from synsc.services import query_planner_service, source_service

    captured = {}

    def execute(request, *, authenticated_user_id):
        captured["request"] = request
        captured["authenticated_user_id"] = authenticated_user_id
        return QueryExecution(
            plan_id="plan-1",
            hits=(
                RetrievalHit(
                    result_id="result-1",
                    text="Current public changes.",
                    score=1.0,
                    title="Release notes",
                    url="https://example.com/releases",
                    source_type="web",
                    source_id="https://example.com/releases",
                    locator="https://example.com/releases",
                    provenance=(
                        RetrievalProvenance(
                            step_id="01-provider-search",
                            provider="firecrawl-web",
                            execution=ExecutionLocation.REMOTE,
                            rank=1,
                            provider_score=1.0,
                        ),
                    ),
                ),
            ),
            records=(),
            stop_reason="completed",
            calls_used=1,
            remote_calls_used=1,
            bytes_used=200,
            elapsed_ms=5,
        )

    monkeypatch.setattr(query_planner_service, "execute_query", execute)

    result = source_service.unified_search(
        query="latest public release",
        k=10,
        mode="web",
        user_id="u1",
        network="online",
        query_classification="public",
        preferred_search_provider="firecrawl-web",
    )

    assert result["mode_applied"] == "web"
    assert result["total"] == 1
    assert result["results"][0]["chunk_id"] == "result-1"
    assert result["results"][0]["url"] == "https://example.com/releases"
    assert result["provider_execution"] == {
        "stop_reason": "completed",
        "calls_used": 1,
        "remote_calls_used": 1,
        "bytes_used": 200,
        "elapsed_ms": 5,
        "records": [],
    }
    request = captured["request"]
    assert request.source_types == ()
    assert request.include_web is True
    assert request.network.value == "online"
    assert request.query_classification.value == "public"
    assert request.preferred_search_provider == "firecrawl-web"
    assert captured["authenticated_user_id"] == "u1"


def test_unified_search_web_mode_is_local_only_and_private_by_default(
    monkeypatch,
):
    from synsc.planner.contracts import QueryExecution
    from synsc.services import query_planner_service, source_service

    captured = {}

    def execute(request, *, authenticated_user_id):
        captured["request"] = request
        return QueryExecution(
            plan_id="plan-1",
            hits=(),
            records=(),
            stop_reason="completed",
            calls_used=0,
            remote_calls_used=0,
            bytes_used=0,
            elapsed_ms=0,
        )

    monkeypatch.setattr(query_planner_service, "execute_query", execute)

    result = source_service.unified_search(
        query="possibly private query",
        mode="web",
    )

    assert captured["request"].network.value == "local_only"
    assert captured["request"].query_classification.value == "private"
    assert result["results"] == []
    assert result["notice"] == (
        "Web search was not executed; check request consent, deployment "
        "policy, provider availability, and credentials."
    )


def test_unified_search_web_mode_rejects_invalid_policy_values():
    from synsc.services.source_service import unified_search

    with pytest.raises(ValueError, match="unsupported network policy"):
        unified_search(query="query", mode="web", network="internet")
    with pytest.raises(ValueError, match="unsupported query classification"):
        unified_search(
            query="query",
            mode="web",
            query_classification="secret",
        )


def test_unified_search_web_mode_runs_registered_provider_end_to_end(
    monkeypatch,
):
    from types import SimpleNamespace

    from synsc.providers.contracts import (
        ContentClassification,
        ExecutionLocation,
        ProviderCapability,
        ProviderDescriptor,
        ProviderSearchHit,
        ProviderSearchResponse,
    )
    from synsc.providers.policy import NetworkPolicy
    from synsc.providers.registry import ProviderRegistry
    from synsc.services import query_planner_service, source_service

    class Provider:
        def search(self, request):
            return ProviderSearchResponse(
                hits=(
                    ProviderSearchHit(
                        hit_id="web-1",
                        text="Current release notes.",
                        score=1.0,
                        title="Release",
                        url="https://example.com/release",
                        source_type="web",
                        source_id="https://example.com/release",
                        locator="https://example.com/release",
                    ),
                )
            )

    registry = ProviderRegistry()
    registry.register(
        ProviderDescriptor(
            name="remote-web",
            version="1",
            capabilities=frozenset({ProviderCapability.SEARCH}),
            execution=ExecutionLocation.REMOTE,
            accepted_classifications=frozenset(
                {ContentClassification.PUBLIC}
            ),
        ),
        lambda **_: Provider(),
    )
    monkeypatch.setattr(
        query_planner_service,
        "get_provider_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        query_planner_service,
        "get_provider_policy_config",
        lambda: SimpleNamespace(
            network_policy=NetworkPolicy.ONLINE,
            allowed_remote_providers=[],
        ),
    )

    result = source_service.unified_search(
        query="current release",
        mode="web",
        network="online",
        query_classification="public",
        preferred_search_provider="remote-web",
    )

    assert result["total"] == 1
    assert result["results"][0]["text"] == "Current release notes."
    assert result["provider_execution"]["remote_calls_used"] == 1
    assert result["provider_execution"]["records"][0]["status"] == "success"


# ---------------------------------------------------------------------------
# Service-level: index_source
# ---------------------------------------------------------------------------


def test_index_source_repo_dispatches_to_indexing_service(monkeypatch):
    from synsc.services import source_service

    fake_indexer = MagicMock()
    fake_indexer.index_repository.return_value = {
        "success": True,
        "repo_id": "r-uuid",
        "status": "indexed",
    }
    monkeypatch.setattr(
        source_service, "_get_indexing_service", lambda user_id: fake_indexer
    )

    result = source_service.index_source(
        source_type="repo",
        url="https://github.com/owner/repo",
        options={"branch": "main", "deep_index": False},
        user_id="u1",
    )

    fake_indexer.index_repository.assert_called_once()
    assert result["source_id"] == "r-uuid"
    assert result["source_type"] == "repo"
    assert result["status"] == "indexed"
    assert result["external_ref"] == "https://github.com/owner/repo"
    assert result["snapshot"]["snapshot_id"] == "snapshot-r-uuid"


def test_successful_index_publishes_snapshot_before_ready_response(
    monkeypatch,
) -> None:
    from synsc.services import source_service

    fake_indexer = MagicMock()
    fake_indexer.index_repository.return_value = {
        "success": True,
        "repo_id": "r-uuid",
        "status": "updated",
    }
    publish = MagicMock(
        return_value={
            "snapshot_id": "snapshot-1",
            "source_id": "r-uuid",
            "source_type": "repo",
            "version": "commit-a",
        }
    )
    monkeypatch.setattr(
        source_service,
        "_get_indexing_service",
        lambda user_id: fake_indexer,
    )
    monkeypatch.setattr(
        source_service,
        "publish_source_snapshot",
        publish,
    )

    result = source_service.index_source(
        source_type="repo",
        url="https://github.com/owner/repo",
        user_id="u1",
    )

    publish.assert_called_once_with("repo", "r-uuid", user_id="u1")
    assert result["snapshot"]["snapshot_id"] == "snapshot-1"


def test_pending_or_failed_index_does_not_publish_snapshot(monkeypatch) -> None:
    from synsc.services import source_service

    publish = MagicMock()
    monkeypatch.setattr(
        source_service,
        "publish_source_snapshot",
        publish,
    )
    fake_indexer = MagicMock()
    monkeypatch.setattr(
        source_service,
        "_get_indexing_service",
        lambda user_id: fake_indexer,
    )

    fake_indexer.index_repository.return_value = {
        "success": True,
        "repo_id": "pending-id",
        "status": "pending",
    }
    pending = source_service.index_source(
        source_type="repo",
        url="https://github.com/owner/repo",
        user_id="u1",
    )
    fake_indexer.index_repository.return_value = {
        "success": False,
        "error": "clone failed",
    }
    failed = source_service.index_source(
        source_type="repo",
        url="https://github.com/owner/repo",
        user_id="u1",
    )

    assert pending["status"] == "pending"
    assert failed["status"] == "error"
    publish.assert_not_called()


def test_index_source_repo_failure_surfaces_error_envelope(monkeypatch):
    """When the underlying indexer reports success=False, the dispatcher
    must mirror that as status='error' instead of pretending it indexed."""
    from synsc.services import source_service

    fake_indexer = MagicMock()
    fake_indexer.index_repository.return_value = {
        "success": False,
        "error": "b'main' is not a valid branch or tag",
        "status": "error",
    }
    monkeypatch.setattr(
        source_service, "_get_indexing_service", lambda user_id: fake_indexer
    )

    result = source_service.index_source(
        source_type="repo",
        url="https://github.com/owner/repo",
        user_id="u1",
    )

    assert result["status"] == "error"
    assert result["source_id"] == ""
    assert "not a valid branch" in result["error"]


def test_post_v1_sources_failure_returns_502(client, monkeypatch):
    """A per-type service failure must map to HTTP 502, not 200."""
    from synsc.services import source_service

    fake_indexer = MagicMock()
    fake_indexer.index_repository.return_value = {
        "success": False,
        "error": "clone failed",
    }
    monkeypatch.setattr(
        source_service, "_get_indexing_service", lambda user_id: fake_indexer
    )

    r = client.post(
        "/v1/sources",
        json={"source_type": "repo", "url": "https://github.com/dead/dead"},
    )
    assert r.status_code == 502
    assert "clone failed" in r.json()["detail"]


def test_index_source_unsupported_type_raises_value_error():
    import pytest

    from synsc.services.source_service import index_source

    with pytest.raises(ValueError, match="unsupported source_type"):
        index_source(source_type="movie", url="x", user_id="u1")


def test_index_source_docs_now_dispatches_to_docs_service(monkeypatch):
    """Docs indexing landed — dispatcher now hands off to DocsService."""
    from synsc.services import docs_service as ds_mod
    from synsc.services import source_service

    fake = MagicMock()
    fake.index_docs.return_value = {
        "success": True,
        "status": "indexed",
        "docs_id": "d-uuid",
    }
    monkeypatch.setattr(ds_mod, "get_docs_service", lambda user_id=None: fake)

    out = source_service.index_source(
        source_type="docs",
        url="https://docs.example.com",
        user_id="u1",
    )
    assert out["source_type"] == "docs"
    assert out["source_id"] == "d-uuid"


def test_index_source_paper_requires_user_id():
    import pytest

    from synsc.services.source_service import index_source

    with pytest.raises(ValueError, match="paper indexing requires"):
        index_source(source_type="paper", url="2301.12345", user_id=None)


# ---------------------------------------------------------------------------
# Service-level: list_sources
# ---------------------------------------------------------------------------


def test_list_sources_filters_by_type(monkeypatch):
    from synsc.services import source_service

    fake_indexer = MagicMock()
    fake_indexer.list_repositories.return_value = {
        "repositories": [
            {
                "repo_id": "r1",
                "owner": "facebook",
                "name": "react",
                "url": "https://github.com/facebook/react",
                "indexed_at": "2026-04-01",
            }
        ]
    }
    monkeypatch.setattr(
        source_service, "_get_indexing_service", lambda user_id: fake_indexer
    )

    out = source_service.list_sources(source_type="repo", user_id="u1")
    assert len(out) == 1
    assert out[0]["source_type"] == "repo"
    assert out[0]["display_name"] == "facebook/react"
    # Paper / dataset branches must not be touched when filtering to repo only.
    assert all(o["source_type"] == "repo" for o in out)


# ---------------------------------------------------------------------------
# HTTP: /v1/search, /v1/sources, GET /v1/sources
# ---------------------------------------------------------------------------


def test_post_v1_search_returns_unified_envelope(client, monkeypatch):
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "unified_retrieve",
        lambda **kwargs: [
            {
                "source_type": "repo",
                "source_id": "r1",
                "chunk_id": "c1",
                "text": "match",
                "score": 0.9,
                "path": "a.py",
                "line_no": 1,
            }
        ],
    )

    r = client.post(
        "/v1/search",
        json={"query": "q", "mode": "precise", "k": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["mode_applied"] == "precise"
    assert body["total"] == 1
    assert body["results"][0]["chunk_id"] == "c1"


def test_post_v1_search_invalid_mode_returns_400(client):
    r = client.post("/v1/search", json={"query": "q", "mode": "zoomzoom"})
    assert r.status_code == 400
    assert "unsupported search mode" in r.json()["detail"]


def test_post_v1_search_forwards_explicit_web_policy_controls(
    client,
    monkeypatch,
):
    from synsc.services import source_service

    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return {"results": [], "total": 0, "mode_applied": "web"}

    monkeypatch.setattr(source_service, "unified_search", fake_search)

    response = client.post(
        "/v1/search",
        json={
            "query": "latest public release",
            "mode": "web",
            "network": "allowlisted",
            "query_classification": "public",
            "allowed_providers": ["firecrawl-web"],
            "preferred_search_provider": "firecrawl-web",
        },
    )

    assert response.status_code == 200
    assert captured["network"] == "allowlisted"
    assert captured["query_classification"] == "public"
    assert captured["allowed_providers"] == ["firecrawl-web"]
    assert captured["preferred_search_provider"] == "firecrawl-web"


def test_post_v1_search_rejects_invalid_web_policy_control(client):
    response = client.post(
        "/v1/search",
        json={
            "query": "latest public release",
            "mode": "web",
            "network": "internet",
        },
    )

    assert response.status_code == 422


def test_get_v1_sources_returns_listing(client, monkeypatch):
    from synsc.services import source_service

    fake_indexer = MagicMock()
    fake_indexer.list_repositories.return_value = {
        "repositories": [
            {
                "repo_id": "r1",
                "owner": "facebook",
                "name": "react",
                "url": "https://github.com/facebook/react",
                "indexed_at": "2026-04-01",
            }
        ]
    }
    monkeypatch.setattr(
        source_service, "_get_indexing_service", lambda user_id: fake_indexer
    )

    r = client.get("/v1/sources?type=repo")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["total"] == 1
    assert body["sources"][0]["source_type"] == "repo"


def test_post_v1_sources_dispatches_to_index_source(client, monkeypatch):
    from synsc.services import source_service

    fake_indexer = MagicMock()
    fake_indexer.index_repository.return_value = {
        "repo_id": "r-uuid",
        "status": "pending",
    }
    monkeypatch.setattr(
        source_service, "_get_indexing_service", lambda user_id: fake_indexer
    )

    r = client.post(
        "/v1/sources",
        json={
            "source_type": "repo",
            "url": "https://github.com/owner/repo",
            "options": {"branch": "main"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["source_id"] == "r-uuid"
    assert body["source_type"] == "repo"


def test_post_v1_sources_async_persists_a_durable_job(client, monkeypatch):
    """Accepted async work must live in PostgreSQL, not an event-loop task."""
    from synsc.services import job_queue_service

    queue = MagicMock()
    queue.create_source_job.return_value = {
        "success": True,
        "job_id": "job-123",
        "status": "pending",
        "message": "Job queued successfully",
    }
    monkeypatch.setattr(job_queue_service, "get_job_queue_service", lambda: queue)

    response = client.post(
        "/v1/sources",
        json={
            "source_type": "docs",
            "url": "https://docs.example.com",
            "display_name": "Example docs",
            "options": {"max_pages": 25},
            "async_mode": True,
        },
    )

    assert response.status_code == 202
    assert response.json()["job_id"] == "job-123"
    queue.create_source_job.assert_called_once_with(
        user_id="00000000-0000-0000-0000-000000000000",
        source_type="docs",
        url="https://docs.example.com",
        display_name="Example docs",
        options={"max_pages": 25},
    )


def test_auto_index_on_miss_uses_the_durable_queue(monkeypatch):
    """Search-triggered indexing must survive the API process exiting."""
    from synsc.services import job_queue_service, source_service

    queue = MagicMock()
    queue.create_source_job.return_value = {
        "success": True,
        "job_id": "job-456",
        "status": "pending",
    }
    monkeypatch.setattr(job_queue_service, "get_job_queue_service", lambda: queue)

    queued = source_service._queue_async_index(
        url="https://github.com/pallets/flask",
        display_name="flask",
        user_id="user-1",
    )

    assert queued is True
    queue.create_source_job.assert_called_once_with(
        user_id="user-1",
        source_type="repo",
        url="https://github.com/pallets/flask",
        display_name="flask",
        options=None,
    )


def test_post_v1_sources_docs_dispatches_to_docs_service(client, monkeypatch):
    """Docs landed — endpoint now returns 200 with the canonical envelope."""
    from synsc.services import docs_service as ds_mod

    fake = MagicMock()
    fake.index_docs.return_value = {
        "success": True,
        "status": "indexed",
        "docs_id": "d-uuid",
        "url": "https://example.com",
        "pages": 5,
        "chunks": 30,
    }
    monkeypatch.setattr(ds_mod, "get_docs_service", lambda user_id=None: fake)

    r = client.post(
        "/v1/sources",
        json={"source_type": "docs", "url": "https://example.com/sitemap.xml"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["source_type"] == "docs"
    assert body["source_id"] == "d-uuid"
