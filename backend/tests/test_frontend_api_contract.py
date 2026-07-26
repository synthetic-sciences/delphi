"""Contract checks for routes used by the browser API client."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_API = REPOSITORY_ROOT / "frontend" / "src" / "lib" / "api.ts"


def test_symbol_search_uses_registered_backend_route() -> None:
    source = FRONTEND_API.read_text()

    assert 'apiFetch("/v1/symbols/search"' in source
    assert 'apiFetch("/v1/search/symbols"' not in source


def test_repository_indexing_does_not_force_main_branch() -> None:
    source = FRONTEND_API.read_text()

    assert 'branch = "main"' not in source


def test_paper_indexing_sends_a_supported_request_field() -> None:
    source = FRONTEND_API.read_text()

    assert "JSON.stringify({ url: source })" in source
    assert "JSON.stringify({ source })" not in source
