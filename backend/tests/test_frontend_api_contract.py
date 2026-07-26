"""Contract checks for routes used by the browser API client."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_API = REPOSITORY_ROOT / "frontend" / "src" / "lib" / "api.ts"


def test_symbol_search_uses_registered_backend_route() -> None:
    source = FRONTEND_API.read_text()

    assert 'apiFetch("/v1/symbols/search"' in source
    assert 'apiFetch("/v1/search/symbols"' not in source
