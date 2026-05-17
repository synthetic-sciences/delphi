"""Tests for the public Try-Live endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from synsc.api.http_server import create_app

    return TestClient(create_app())


def test_try_live_disabled_by_default(client):
    r = client.get("/v1/try", params={"q": "fastapi"})
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"]


def test_try_live_enabled_via_env(monkeypatch, client):
    monkeypatch.setenv("SYNSC_PUBLIC_TRY_ENABLED", "true")
    # Stub the search so we don't need a real DB
    from synsc.services import source_service

    def fake_unified_search(**kwargs):
        return {
            "results": [
                {
                    "source_id": "s1",
                    "source_type": "repo",
                    "text": "x" * 1000,  # should get truncated
                    "score": 0.9,
                    "path": "main.py",
                }
            ],
            "total": 1,
            "mode_applied": "precise",
        }

    monkeypatch.setattr(source_service, "unified_search", fake_unified_search)
    r = client.get("/v1/try", params={"q": "fastapi"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["query"] == "fastapi"
    assert body["results"][0]["_truncated"] is True
    assert len(body["results"][0]["text"]) <= 410


def test_try_live_rejects_oversized_query(monkeypatch, client):
    monkeypatch.setenv("SYNSC_PUBLIC_TRY_ENABLED", "true")
    r = client.get("/v1/try", params={"q": "x" * 600})
    assert r.status_code == 400


def test_try_live_rejects_huge_k(monkeypatch, client):
    monkeypatch.setenv("SYNSC_PUBLIC_TRY_ENABLED", "true")
    r = client.get("/v1/try", params={"q": "ok", "k": 100})
    assert r.status_code == 400
