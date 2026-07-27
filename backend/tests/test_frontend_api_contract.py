"""Contract checks for routes used by the browser API client."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_API = REPOSITORY_ROOT / "frontend" / "src" / "lib" / "api.ts"
FRONTEND_CONFIG = REPOSITORY_ROOT / "frontend" / "next.config.mjs"


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


def test_frontend_proxy_covers_v2_workspace_routes() -> None:
    config = FRONTEND_CONFIG.read_text()

    assert "{ source: '/v2/:path*'," in config


def test_browser_api_calls_stay_same_origin_for_session_cookies() -> None:
    source = FRONTEND_API.read_text()

    assert "export const DIRECT_API_URL = API_URL;" in source
    assert 'process.env.NEXT_PUBLIC_API_URL || ""' not in source
