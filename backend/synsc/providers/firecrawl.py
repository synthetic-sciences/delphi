"""Optional Firecrawl v2 adapter for bounded web search and site crawling."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlparse

import httpx

from synsc.network.public_http import (
    PublicHTTPTransport,
    validate_public_http_url,
)
from synsc.providers.contracts import (
    CancellationToken,
    ProviderCrawlPage,
    ProviderCrawlRequest,
    ProviderCrawlResponse,
    ProviderFailure,
    ProviderFailureCode,
    ProviderSearchHit,
    ProviderSearchRequest,
    ProviderSearchResponse,
    ProviderUnavailableError,
)

_PROVIDER_NAME = "firecrawl-web"
_API_BASE_URL = "https://api.firecrawl.dev"
_POLL_INTERVAL_SECONDS = 0.25
_SAFE_METADATA_FIELDS = {
    "category": "category",
}
_SAFE_CRAWL_METADATA_FIELDS = {
    "language": "language",
    "statusCode": "status_code",
}


def _failure(
    code: ProviderFailureCode,
    message: str,
    *,
    retryable: bool,
    retry_after_seconds: float | None = None,
    cause: BaseException | None = None,
) -> ProviderUnavailableError:
    return ProviderUnavailableError(
        ProviderFailure(
            code=code,
            message=message,
            retryable=retryable,
            provider=_PROVIDER_NAME,
            retry_after_seconds=retry_after_seconds,
            cause=cause,
        )
    )


def _cancelled() -> ProviderUnavailableError:
    return _failure(
        ProviderFailureCode.CANCELLED,
        "Provider operation was cancelled.",
        retryable=False,
    )


def _is_safe_http_url(url: object) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    try:
        _ = parsed.port
    except ValueError:
        return False
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        return False
    try:
        return ipaddress.ip_address(hostname).is_global
    except ValueError:
        return True


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlparse(url)
    assert parsed.hostname is not None
    return (
        parsed.scheme.lower(),
        parsed.hostname.lower(),
        parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
    )


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _safe_scalar(value: object) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, (str, int, bool))


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


class FirecrawlProvider:
    """Fixed-origin, credential-lazy adapter for Firecrawl's v2 API."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        credential = api_key or os.getenv("FIRECRAWL_API_KEY") or ""
        if not credential.strip():
            raise _failure(
                ProviderFailureCode.UNAUTHORIZED,
                "Provider credential is not configured.",
                retryable=False,
            )
        self._clock = clock
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=_API_BASE_URL,
            headers={
                "Authorization": f"Bearer {credential}",
                "Content-Type": "application/json",
            },
            transport=transport or PublicHTTPTransport(),
            follow_redirects=False,
            timeout=None,
            trust_env=False,
        )

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        retry_after = _retry_after(response)
        if status in {401, 403}:
            raise _failure(
                ProviderFailureCode.UNAUTHORIZED,
                "Provider credential was rejected.",
                retryable=False,
            )
        if status == 402:
            raise _failure(
                ProviderFailureCode.BUDGET_EXHAUSTED,
                "Provider account budget is exhausted.",
                retryable=False,
            )
        if status in {408, 504}:
            raise _failure(
                ProviderFailureCode.TIMEOUT,
                "Provider operation timed out.",
                retryable=True,
                retry_after_seconds=retry_after,
            )
        if status == 429:
            raise _failure(
                ProviderFailureCode.RATE_LIMITED,
                "Provider rate limit was reached.",
                retryable=True,
                retry_after_seconds=retry_after,
            )
        if status >= 500:
            raise _failure(
                ProviderFailureCode.UNAVAILABLE,
                "Provider is temporarily unavailable.",
                retryable=True,
                retry_after_seconds=retry_after,
            )
        raise _failure(
            ProviderFailureCode.INVALID_RESPONSE,
            "Provider rejected the request.",
            retryable=False,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        timeout_ms: int,
        deadline: float,
        max_response_bytes: int,
        cancellation: CancellationToken,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int]:
        if cancellation.cancelled:
            raise _cancelled()
        remaining_seconds = deadline - self._clock()
        if remaining_seconds <= 0:
            raise _failure(
                ProviderFailureCode.TIMEOUT,
                "Provider operation timed out.",
                retryable=True,
            )
        try:
            with self._client.stream(
                method,
                path,
                json=dict(payload) if payload is not None else None,
                timeout=min(timeout_ms / 1000, remaining_seconds),
            ) as response:
                if self._clock() >= deadline:
                    raise _failure(
                        ProviderFailureCode.TIMEOUT,
                        "Provider operation timed out.",
                        retryable=True,
                    )
                self._raise_for_status(response)
                body = bytearray()
                for chunk in response.iter_bytes():
                    if cancellation.cancelled:
                        raise _cancelled()
                    if self._clock() >= deadline:
                        raise _failure(
                            ProviderFailureCode.TIMEOUT,
                            "Provider operation timed out.",
                            retryable=True,
                        )
                    if len(body) + len(chunk) > max_response_bytes:
                        raise _failure(
                            ProviderFailureCode.INVALID_RESPONSE,
                            "Provider response exceeded its byte ceiling.",
                            retryable=False,
                        )
                    body.extend(chunk)
                if self._clock() >= deadline:
                    raise _failure(
                        ProviderFailureCode.TIMEOUT,
                        "Provider operation timed out.",
                        retryable=True,
                    )
        except ProviderUnavailableError:
            raise
        except httpx.TimeoutException as exc:
            raise _failure(
                ProviderFailureCode.TIMEOUT,
                "Provider operation timed out.",
                retryable=True,
                cause=exc,
            ) from None
        except httpx.HTTPError as exc:
            raise _failure(
                ProviderFailureCode.UNAVAILABLE,
                "Provider request failed.",
                retryable=True,
                cause=exc,
            ) from None

        try:
            decoded = json.loads(
                body,
                parse_constant=_reject_json_constant,
            )
        except (ValueError, UnicodeDecodeError) as exc:
            raise _failure(
                ProviderFailureCode.INVALID_RESPONSE,
                "Provider returned invalid JSON.",
                retryable=False,
                cause=exc,
            ) from None
        if not isinstance(decoded, dict):
            raise _failure(
                ProviderFailureCode.INVALID_RESPONSE,
                "Provider returned an invalid response envelope.",
                retryable=False,
            )
        return decoded, len(body)

    @staticmethod
    def _bounded_search_response(
        hits: list[ProviderSearchHit],
        max_response_bytes: int,
    ) -> ProviderSearchResponse:
        accepted: list[ProviderSearchHit] = []
        for hit in hits:
            candidate = ProviderSearchResponse(hits=(*accepted, hit))
            if candidate.consumed_bytes > max_response_bytes:
                break
            accepted.append(hit)
        return ProviderSearchResponse(hits=tuple(accepted))

    def search(self, request: ProviderSearchRequest) -> ProviderSearchResponse:
        if len(request.query) > 500:
            raise _failure(
                ProviderFailureCode.CONTENT_REJECTED,
                "Search query exceeds the provider limit.",
                retryable=False,
            )
        payload = {
            "query": request.query,
            "limit": request.limit,
            "sources": ["web"],
            "timeout": max(1_000, request.timeout_ms),
        }
        deadline = self._clock() + request.timeout_ms / 1000
        envelope, _ = self._request_json(
            "POST",
            "/v2/search",
            timeout_ms=request.timeout_ms,
            deadline=deadline,
            max_response_bytes=request.max_response_bytes,
            cancellation=request.cancellation,
            payload=payload,
        )
        if envelope.get("success") is not True:
            raise _failure(
                ProviderFailureCode.INVALID_RESPONSE,
                "Provider reported an unsuccessful search.",
                retryable=False,
            )
        data = envelope.get("data")
        raw_hits = data.get("web") if isinstance(data, Mapping) else None
        if not isinstance(raw_hits, list):
            raise _failure(
                ProviderFailureCode.INVALID_RESPONSE,
                "Provider search results were malformed.",
                retryable=False,
            )

        hits: list[ProviderSearchHit] = []
        for raw in raw_hits[: request.limit]:
            if not isinstance(raw, Mapping):
                continue
            url = raw.get("url")
            if not _is_safe_http_url(url):
                continue
            assert isinstance(url, str)
            title = raw.get("title")
            description = raw.get("description")
            normalized_title = (
                title.strip() or None if isinstance(title, str) else None
            )
            normalized_text = (
                description.strip() if isinstance(description, str) else ""
            )
            if not normalized_title and not normalized_text:
                continue
            metadata = {
                target: raw[source]
                for source, target in _SAFE_METADATA_FIELDS.items()
                if _safe_scalar(raw.get(source))
            }
            rank = len(hits) + 1
            hits.append(
                ProviderSearchHit(
                    hit_id=hashlib.sha256(url.encode("utf-8")).hexdigest(),
                    text=normalized_text,
                    score=1.0 / rank,
                    title=normalized_title,
                    url=url,
                    source_type="web",
                    source_id=url,
                    locator=url,
                    metadata=metadata,
                )
            )
        return self._bounded_search_response(
            hits,
            request.max_response_bytes,
        )

    @staticmethod
    def _bounded_crawl_response(
        pages: list[ProviderCrawlPage],
        *,
        job_id: str,
        max_response_bytes: int,
        provider_truncated: bool,
    ) -> ProviderCrawlResponse:
        accepted: list[ProviderCrawlPage] = []
        truncated = provider_truncated
        for page in pages:
            candidate = ProviderCrawlResponse(
                pages=(*accepted, page),
                job_id=job_id,
                truncated=provider_truncated,
            )
            if candidate.consumed_bytes > max_response_bytes:
                truncated = True
                break
            accepted.append(page)
        return ProviderCrawlResponse(
            pages=tuple(accepted),
            job_id=job_id,
            truncated=truncated,
        )

    def _crawl_pages(
        self,
        envelope: Mapping[str, Any],
        request: ProviderCrawlRequest,
        job_id: str,
    ) -> ProviderCrawlResponse:
        raw_pages = envelope.get("data")
        if not isinstance(raw_pages, list):
            raise _failure(
                ProviderFailureCode.INVALID_RESPONSE,
                "Provider crawl results were malformed.",
                retryable=False,
            )
        base_origin = _origin(request.url)
        pages: list[ProviderCrawlPage] = []
        for raw in raw_pages:
            if len(pages) >= request.max_pages or not isinstance(raw, Mapping):
                break
            markdown = raw.get("markdown")
            metadata = raw.get("metadata")
            if not isinstance(markdown, str) or not markdown:
                continue
            if not isinstance(metadata, Mapping):
                metadata = {}
            page_url = metadata.get("sourceURL") or metadata.get("url")
            if not _is_safe_http_url(page_url):
                continue
            assert isinstance(page_url, str)
            if request.same_origin_only and _origin(page_url) != base_origin:
                continue
            title = metadata.get("title")
            normalized_title = (
                title.strip() or None if isinstance(title, str) else None
            )
            safe_metadata = {
                target: metadata[source]
                for source, target in _SAFE_CRAWL_METADATA_FIELDS.items()
                if _safe_scalar(metadata.get(source))
            }
            pages.append(
                ProviderCrawlPage(
                    page_id=hashlib.sha256(page_url.encode("utf-8")).hexdigest(),
                    url=page_url,
                    markdown=markdown,
                    title=normalized_title,
                    metadata=safe_metadata,
                )
            )
        return self._bounded_crawl_response(
            pages,
            job_id=job_id,
            max_response_bytes=request.max_response_bytes,
            provider_truncated=bool(envelope.get("next")),
        )

    def crawl(self, request: ProviderCrawlRequest) -> ProviderCrawlResponse:
        try:
            validate_public_http_url(request.url)
        except ValueError as exc:
            raise _failure(
                ProviderFailureCode.CONTENT_REJECTED,
                "Crawl target must be a public HTTP(S) URL.",
                retryable=False,
                cause=exc,
            ) from None

        started = self._clock()
        deadline = started + request.timeout_ms / 1000
        payload = {
            "url": request.url,
            "limit": request.max_pages,
            "maxDiscoveryDepth": request.max_depth,
            "allowExternalLinks": not request.same_origin_only,
            "allowSubdomains": False,
            "ignoreRobotsTxt": False,
            "scrapeOptions": {
                "formats": ["markdown"],
                "onlyMainContent": True,
                "skipTlsVerification": False,
                "storeInCache": False,
                "timeout": request.timeout_ms,
            },
        }
        remaining_response_bytes = request.max_response_bytes
        start_response, consumed_bytes = self._request_json(
            "POST",
            "/v2/crawl",
            timeout_ms=request.timeout_ms,
            deadline=deadline,
            max_response_bytes=remaining_response_bytes,
            cancellation=request.cancellation,
            payload=payload,
        )
        remaining_response_bytes -= consumed_bytes
        if start_response.get("success") is not True:
            raise _failure(
                ProviderFailureCode.INVALID_RESPONSE,
                "Provider did not start the crawl.",
                retryable=False,
            )
        raw_job_id = start_response.get("id")
        try:
            job_id = str(uuid.UUID(str(raw_job_id)))
        except (ValueError, TypeError, AttributeError):
            raise _failure(
                ProviderFailureCode.INVALID_RESPONSE,
                "Provider returned an invalid crawl job identifier.",
                retryable=False,
            ) from None

        while True:
            if request.cancellation.cancelled:
                raise _cancelled()
            remaining_ms = int((deadline - self._clock()) * 1000)
            if remaining_ms <= 0:
                raise _failure(
                    ProviderFailureCode.TIMEOUT,
                    "Provider crawl timed out.",
                    retryable=True,
                )
            if remaining_response_bytes <= 0:
                raise _failure(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Provider response exceeded its byte ceiling.",
                    retryable=False,
                )
            status_response, consumed_bytes = self._request_json(
                "GET",
                f"/v2/crawl/{job_id}",
                timeout_ms=remaining_ms,
                deadline=deadline,
                max_response_bytes=remaining_response_bytes,
                cancellation=request.cancellation,
            )
            remaining_response_bytes -= consumed_bytes
            status = status_response.get("status")
            if status == "completed":
                return self._crawl_pages(status_response, request, job_id)
            if status == "failed":
                raise _failure(
                    ProviderFailureCode.UNAVAILABLE,
                    "Provider crawl failed.",
                    retryable=True,
                )
            if status != "scraping":
                raise _failure(
                    ProviderFailureCode.INVALID_RESPONSE,
                    "Provider returned an unknown crawl status.",
                    retryable=False,
                )
            self._sleep(
                min(
                    _POLL_INTERVAL_SECONDS,
                    max(0.0, deadline - self._clock()),
                )
            )
