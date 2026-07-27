"""Hosted web-search and crawl adapter contracts."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from synsc.providers.contracts import (
    CancellationToken,
    ProviderCrawlRequest,
    ProviderFailureCode,
    ProviderSearchRequest,
    ProviderUnavailableError,
)
from synsc.providers.firecrawl import FirecrawlProvider


def _provider(
    handler: Any,
    *,
    clock: Any = None,
    sleep: Any = None,
) -> FirecrawlProvider:
    kwargs: dict[str, Any] = {
        "api_key": "test-key",
        "transport": httpx.MockTransport(handler),
    }
    if clock is not None:
        kwargs["clock"] = clock
    if sleep is not None:
        kwargs["sleep"] = sleep
    return FirecrawlProvider(**kwargs)


def test_provider_requires_runtime_credential(monkeypatch) -> None:
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    with pytest.raises(ProviderUnavailableError) as caught:
        FirecrawlProvider()

    assert caught.value.failure.code is ProviderFailureCode.UNAUTHORIZED
    assert "FIRECRAWL_API_KEY" not in str(caught.value)


def test_search_sends_only_bounded_query_fields_and_normalizes_results() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "url": str(request.url),
                "authorization": request.headers["authorization"],
                "body": json.loads(request.content),
            }
        )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "web": [
                        {
                            "title": "Release notes",
                            "description": "Current public changes.",
                            "url": "https://example.com/releases",
                            "category": "web",
                            "unexpected": {"secret": "must-not-propagate"},
                        },
                        {
                            "title": "Docs",
                            "description": "API documentation.",
                            "url": "https://docs.example.com/api",
                        },
                    ]
                },
            },
        )

    provider = _provider(handler)
    response = provider.search(
        ProviderSearchRequest(
            query="latest public release",
            limit=2,
            timeout_ms=1_500,
            max_response_bytes=4_000,
        )
    )

    assert seen == [
        {
            "method": "POST",
            "url": "https://api.firecrawl.dev/v2/search",
            "authorization": "Bearer test-key",
            "body": {
                "query": "latest public release",
                "limit": 2,
                "sources": ["web"],
                "timeout": 1_500,
            },
        }
    ]
    assert [hit.url for hit in response.hits] == [
        "https://example.com/releases",
        "https://docs.example.com/api",
    ]
    assert [hit.score for hit in response.hits] == [1.0, 0.5]
    assert response.hits[0].source_type == "web"
    assert response.hits[0].metadata == {"category": "web"}
    assert response.consumed_bytes <= 4_000
    provider.close()


def test_search_drops_unsafe_result_urls() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "web": [
                        {
                            "title": "Unsafe",
                            "description": "Must not surface.",
                            "url": "file:///etc/passwd",
                        },
                        {
                            "title": "Credential URL",
                            "description": "Must not surface.",
                            "url": "https://user:pass@example.com/private",
                        },
                        {
                            "title": "",
                            "description": "Safe result.",
                            "url": "https://example.com/safe",
                        },
                        {
                            "title": "Private literal",
                            "description": "Must not surface.",
                            "url": "http://127.0.0.1/admin",
                        },
                    ]
                },
            },
        )

    provider = _provider(handler)
    response = provider.search(
        ProviderSearchRequest(query="safe", max_response_bytes=4_000)
    )

    assert [hit.url for hit in response.hits] == ["https://example.com/safe"]
    assert response.hits[0].title is None
    provider.close()


def test_search_rejects_provider_query_limit_without_sending_request() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    provider = _provider(handler)
    with pytest.raises(ProviderUnavailableError) as caught:
        provider.search(ProviderSearchRequest(query="x" * 501))

    assert caught.value.failure.code is ProviderFailureCode.CONTENT_REJECTED
    assert called is False
    provider.close()


def test_search_honors_pre_cancelled_request_without_network_call() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    cancellation = CancellationToken()
    cancellation.cancel()
    provider = _provider(handler)
    with pytest.raises(ProviderUnavailableError) as caught:
        provider.search(
            ProviderSearchRequest(
                query="cancelled",
                cancellation=cancellation,
            )
        )

    assert caught.value.failure.code is ProviderFailureCode.CANCELLED
    assert called is False
    provider.close()


@pytest.mark.parametrize(
    ("status", "expected_code", "retryable"),
    [
        (401, ProviderFailureCode.UNAUTHORIZED, False),
        (402, ProviderFailureCode.BUDGET_EXHAUSTED, False),
        (408, ProviderFailureCode.TIMEOUT, True),
        (429, ProviderFailureCode.RATE_LIMITED, True),
        (503, ProviderFailureCode.UNAVAILABLE, True),
    ],
)
def test_http_failures_are_normalized_without_leaking_provider_body(
    status: int,
    expected_code: ProviderFailureCode,
    retryable: bool,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"Retry-After": "7"},
            text="credential=test-key internal provider details",
        )

    provider = _provider(handler)
    with pytest.raises(ProviderUnavailableError) as caught:
        provider.search(ProviderSearchRequest(query="public query"))

    assert caught.value.failure.code is expected_code
    assert caught.value.failure.retryable is retryable
    assert "test-key" not in str(caught.value)
    assert "internal provider details" not in str(caught.value)
    if status == 429:
        assert caught.value.failure.retry_after_seconds == 7
    provider.close()


def test_search_rejects_response_that_exceeds_raw_byte_ceiling() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"success":true,"data":{"web":[]}}' + b" " * 300,
        )

    provider = _provider(handler)
    with pytest.raises(ProviderUnavailableError) as caught:
        provider.search(
            ProviderSearchRequest(
                query="bounded",
                max_response_bytes=256,
            )
        )

    assert caught.value.failure.code is ProviderFailureCode.INVALID_RESPONSE
    provider.close()


def test_search_enforces_absolute_deadline_during_streaming_response() -> None:
    now = [0.0]

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            now[0] = 2.0
            yield b'{"success":true,"data":{"web":[]}}'

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=SlowStream())

    provider = _provider(handler, clock=lambda: now[0])
    with pytest.raises(ProviderUnavailableError) as caught:
        provider.search(
            ProviderSearchRequest(
                query="deadline",
                timeout_ms=1_000,
            )
        )

    assert caught.value.failure.code is ProviderFailureCode.TIMEOUT
    provider.close()


def test_crawl_rejects_non_public_target_before_provider_call() -> None:
    called = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    provider = _provider(handler)
    with pytest.raises(ProviderUnavailableError) as caught:
        provider.crawl(
            ProviderCrawlRequest(url="http://169.254.169.254/latest/meta-data/")
        )

    assert caught.value.failure.code is ProviderFailureCode.CONTENT_REJECTED
    assert called is False
    provider.close()


def test_crawl_starts_bounded_job_polls_and_normalizes_pages(
    monkeypatch,
) -> None:
    from synsc.providers import firecrawl

    monkeypatch.setattr(
        firecrawl,
        "validate_public_http_url",
        lambda url: None,
    )
    requests: list[tuple[str, str, dict[str, Any] | None]] = []
    responses: Iterator[httpx.Response] = iter(
        [
            httpx.Response(
                200,
                json={
                    "success": True,
                    "id": "123e4567-e89b-12d3-a456-426614174000",
                    "url": "https://docs.example.com/",
                },
            ),
            httpx.Response(
                200,
                json={
                    "status": "scraping",
                    "total": 2,
                    "completed": 1,
                    "data": [],
                },
            ),
            httpx.Response(
                200,
                json={
                    "status": "completed",
                    "total": 2,
                    "completed": 2,
                    "data": [
                        {
                            "markdown": "# Start",
                            "metadata": {
                                "title": "Start",
                                "sourceURL": "https://docs.example.com/",
                                "language": "en",
                                "statusCode": 200,
                                "ignored": {"nested": "value"},
                            },
                        },
                        {
                            "markdown": "# API",
                            "metadata": {
                                "title": "API",
                                "url": "https://docs.example.com/api",
                            },
                        },
                    ],
                },
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            (
                request.method,
                str(request.url),
                json.loads(request.content) if request.content else None,
            )
        )
        return next(responses)

    provider = _provider(handler, sleep=lambda _: None)
    response = provider.crawl(
        ProviderCrawlRequest(
            url="https://docs.example.com/",
            max_pages=2,
            max_depth=1,
            timeout_ms=5_000,
            max_response_bytes=10_000,
        )
    )

    assert requests[0] == (
        "POST",
        "https://api.firecrawl.dev/v2/crawl",
        {
            "allowExternalLinks": False,
            "allowSubdomains": False,
            "ignoreRobotsTxt": False,
            "limit": 2,
            "maxDiscoveryDepth": 1,
            "scrapeOptions": {
                "formats": ["markdown"],
                "onlyMainContent": True,
                "skipTlsVerification": False,
                "storeInCache": False,
                "timeout": 5_000,
            },
            "url": "https://docs.example.com/",
        },
    )
    assert requests[1][:2] == (
        "GET",
        "https://api.firecrawl.dev/v2/crawl/123e4567-e89b-12d3-a456-426614174000",
    )
    assert requests[2][:2] == requests[1][:2]
    assert response.job_id == "123e4567-e89b-12d3-a456-426614174000"
    assert [page.url for page in response.pages] == [
        "https://docs.example.com/",
        "https://docs.example.com/api",
    ]
    assert response.pages[0].metadata == {
        "language": "en",
        "status_code": 200,
    }
    assert response.truncated is False
    assert response.consumed_bytes <= 10_000
    provider.close()


def test_crawl_rejects_cross_origin_pages_even_if_provider_returns_them(
    monkeypatch,
) -> None:
    from synsc.providers import firecrawl

    monkeypatch.setattr(
        firecrawl,
        "validate_public_http_url",
        lambda url: None,
    )
    responses = iter(
        [
            httpx.Response(
                200,
                json={
                    "success": True,
                    "id": "123e4567-e89b-12d3-a456-426614174000",
                    "url": "https://docs.example.com/",
                },
            ),
            httpx.Response(
                200,
                json={
                    "status": "completed",
                    "data": [
                        {
                            "markdown": "external",
                            "metadata": {
                                "sourceURL": "https://attacker.example/external",
                            },
                        },
                        {
                            "markdown": "local",
                            "metadata": {
                                "sourceURL": "https://docs.example.com/local",
                            },
                        },
                    ],
                },
            ),
        ]
    )
    provider = _provider(lambda _: next(responses), sleep=lambda _: None)

    response = provider.crawl(
        ProviderCrawlRequest(
            url="https://docs.example.com/",
            max_pages=2,
        )
    )

    assert [page.url for page in response.pages] == [
        "https://docs.example.com/local"
    ]
    provider.close()


def test_crawl_stops_polling_at_request_deadline(monkeypatch) -> None:
    from synsc.providers import firecrawl

    monkeypatch.setattr(
        firecrawl,
        "validate_public_http_url",
        lambda url: None,
    )
    responses = iter(
        [
            httpx.Response(
                200,
                json={
                    "success": True,
                    "id": "123e4567-e89b-12d3-a456-426614174000",
                    "url": "https://docs.example.com/",
                },
            ),
            httpx.Response(
                200,
                json={"status": "scraping", "data": []},
            ),
        ]
    )
    now = [0.0]

    def advance(_: float) -> None:
        now[0] = 6.0

    provider = _provider(
        lambda _: next(responses),
        clock=lambda: now[0],
        sleep=advance,
    )

    with pytest.raises(ProviderUnavailableError) as caught:
        provider.crawl(
            ProviderCrawlRequest(
                url="https://docs.example.com/",
                timeout_ms=5_000,
            )
        )

    assert caught.value.failure.code is ProviderFailureCode.TIMEOUT
    provider.close()


def test_crawl_response_budget_is_cumulative_across_start_and_polls(
    monkeypatch,
) -> None:
    from synsc.providers import firecrawl

    monkeypatch.setattr(
        firecrawl,
        "validate_public_http_url",
        lambda url: None,
    )
    responses = iter(
        [
            httpx.Response(
                200,
                json={
                    "success": True,
                    "id": "123e4567-e89b-12d3-a456-426614174000",
                    "url": "https://docs.example.com/",
                },
            ),
            httpx.Response(
                200,
                json={
                    "status": "scraping",
                    "data": [],
                    "padding": "x" * 40,
                },
            ),
            httpx.Response(
                200,
                json={
                    "status": "completed",
                    "data": [
                        {
                            "markdown": "ok",
                            "metadata": {
                                "sourceURL": "https://docs.example.com/",
                            },
                        }
                    ],
                },
            ),
        ]
    )
    provider = _provider(lambda _: next(responses), sleep=lambda _: None)

    with pytest.raises(ProviderUnavailableError) as caught:
        provider.crawl(
            ProviderCrawlRequest(
                url="https://docs.example.com/",
                max_pages=1,
                max_response_bytes=256,
            )
        )

    assert caught.value.failure.code is ProviderFailureCode.INVALID_RESPONSE
    provider.close()
