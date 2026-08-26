"""Tests that API error responses never leak internal details."""

from unittest.mock import patch


def test_search_code_error_is_generic(client):
    """POST /v1/search/code should return a generic error on failure."""
    with patch(
        "synsc.services.search_service.SearchService.search_code",
        side_effect=RuntimeError("pgvector index corrupt"),
    ):
        resp = client.post("/v1/search/code", json={"query": "hello"})

    body = resp.json()
    assert "pgvector" not in str(body)
    assert resp.status_code == 500
    assert "Code search failed" in body.get("error", "")


def test_search_code_rejects_unknown_filter_fields(client):
    """A misspelled repository filter must not silently become global search."""
    with patch(
        "synsc.services.search_service.SearchService.search_code"
    ) as search_code:
        resp = client.post(
            "/v1/search/code",
            json={
                "query": "authentication",
                "repository_ids": ["misspelled-filter"],
            },
        )

    assert resp.status_code == 422
    search_code.assert_not_called()
