"""Tests for the curated source catalog (cold-start resolution)."""
from __future__ import annotations

from synsc.services.catalog import CATALOG, CatalogService


def test_resolve_exact_name() -> None:
    entry = CatalogService().resolve("fastapi")
    assert entry is not None
    assert entry["name"] == "fastapi"
    assert "github.com" in entry["url"]
    assert entry["kind"] == "repository"


def test_resolve_alias() -> None:
    # "nextjs" is an alias of "next.js"
    entry = CatalogService().resolve("nextjs")
    assert entry is not None
    assert entry["name"] == "next.js"


def test_resolve_separator_insensitive() -> None:
    # "next js" should normalize to "next.js"
    entry = CatalogService().resolve("next js")
    assert entry is not None
    assert entry["name"] == "next.js"


def test_alias_k8s_resolves_kubernetes() -> None:
    entry = CatalogService().resolve("k8s")
    assert entry is not None
    assert entry["name"] == "kubernetes"


def test_search_prefix_and_ranking() -> None:
    results = CatalogService().search("react", limit=5)
    assert results
    # Exact name should rank first.
    assert results[0]["name"] == "react"


def test_search_by_category_filter() -> None:
    results = CatalogService().search("", limit=100, category="ai-ml")
    assert results
    assert all(r["category"] == "ai-ml" for r in results)


def test_search_description_match() -> None:
    # "orchestration" appears in the kubernetes description.
    results = CatalogService().search("orchestration", limit=5)
    names = {r["name"] for r in results}
    assert "kubernetes" in names


def test_unknown_returns_empty() -> None:
    assert CatalogService().resolve("totally-not-a-real-lib-xyz-123") is None


def test_catalog_entries_are_well_formed() -> None:
    seen_names = set()
    for entry in CATALOG:
        assert entry.name and entry.name.lower() not in seen_names, f"dup: {entry.name}"
        seen_names.add(entry.name.lower())
        assert entry.kind in ("repository", "documentation")
        assert entry.url.startswith("http")
        assert entry.description
        assert entry.category


def test_categories_listed() -> None:
    cats = CatalogService().categories()
    assert "frontend" in cats and "ai-ml" in cats and "database" in cats


def test_catalog_http_endpoint(client) -> None:
    resp = client.get("/v1/catalog?q=pytorch")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    names = {r["name"] for r in data["results"]}
    assert "pytorch" in names
    assert "ai-ml" in data["categories"]


def test_catalog_http_list_all(client) -> None:
    resp = client.get("/v1/catalog?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 5
