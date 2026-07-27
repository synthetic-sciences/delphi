"""Deployment-bounded execution for optional crawl providers."""

from __future__ import annotations

import json
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import suppress
from dataclasses import dataclass, replace
from threading import Thread
from typing import Any

from synsc.config import get_provider_policy_config
from synsc.providers.contracts import (
    ContentClassification,
    CrawlProvider,
    ExecutionLocation,
    ProviderCapability,
    ProviderCrawlRequest,
    ProviderCrawlResponse,
    ProviderFailure,
    ProviderFailureCode,
    ProviderUnavailableError,
)
from synsc.providers.policy import (
    EgressDecision,
    EgressPolicy,
    EgressRequest,
    NetworkPolicy,
    OutboundField,
)
from synsc.providers.registry import (
    ProviderRegistration,
    ProviderRegistry,
    get_provider_registry,
)

_NETWORK_RANK = {
    NetworkPolicy.OFFLINE: 0,
    NetworkPolicy.LOCAL_ONLY: 1,
    NetworkPolicy.ALLOWLISTED: 2,
    NetworkPolicy.ONLINE: 3,
}


@dataclass(frozen=True)
class CrawlExecutionRequest:
    """Provider-neutral crawl request plus explicit egress controls."""

    crawl: ProviderCrawlRequest
    network: NetworkPolicy = NetworkPolicy.LOCAL_ONLY
    classification: ContentClassification = ContentClassification.PRIVATE
    allowed_providers: frozenset[str] = frozenset()
    preferred_provider: str | None = None
    source_opt_in: bool = False
    one_request_override: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.crawl, ProviderCrawlRequest):
            raise TypeError("crawl must be a ProviderCrawlRequest")
        if any(not provider.strip() for provider in self.allowed_providers):
            raise ValueError("allowed_providers cannot contain empty values")
        if (
            self.preferred_provider is not None
            and not self.preferred_provider.strip()
        ):
            raise ValueError("preferred_provider must not be empty")


@dataclass(frozen=True)
class CrawlExecution:
    """Auditable result of one policy-approved crawl provider call."""

    provider: str
    decision: EgressDecision
    response: ProviderCrawlResponse

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "decision": self.decision.to_dict(),
            "response": self.response.to_dict(),
        }


def _failure(
    code: ProviderFailureCode,
    message: str,
    *,
    retryable: bool,
    provider: str,
    cause: BaseException | None = None,
) -> ProviderUnavailableError:
    return ProviderUnavailableError(
        ProviderFailure(
            code=code,
            message=message,
            retryable=retryable,
            provider=provider,
            cause=cause,
        )
    )


def _effective_controls(
    request: CrawlExecutionRequest,
) -> tuple[NetworkPolicy, frozenset[str]]:
    config = get_provider_policy_config()
    network = min(
        (request.network, config.network_policy),
        key=_NETWORK_RANK.__getitem__,
    )
    allowed_providers = request.allowed_providers
    if network is NetworkPolicy.ALLOWLISTED:
        configured = frozenset(config.allowed_remote_providers)
        if config.network_policy is NetworkPolicy.ALLOWLISTED:
            allowed_providers = (
                configured & request.allowed_providers
                if request.allowed_providers
                else configured
            )
    return network, allowed_providers


def _select_registration(
    request: CrawlExecutionRequest,
    registry: ProviderRegistry,
) -> ProviderRegistration:
    registrations = registry.list_registrations(
        capability=ProviderCapability.CRAWL,
    )
    if request.preferred_provider is not None:
        registrations = [
            registration
            for registration in registrations
            if registration.descriptor.name == request.preferred_provider
        ]
    registrations.sort(
        key=lambda registration: (
            registration.descriptor.execution is ExecutionLocation.REMOTE,
            registration.priority,
            registration.descriptor.name,
        )
    )
    if registrations:
        return registrations[0]
    raise _failure(
        ProviderFailureCode.UNAVAILABLE,
        "No available crawl provider matches the request.",
        retryable=False,
        provider=request.preferred_provider or "crawl",
    )


def _close_provider(provider: object) -> None:
    close = getattr(provider, "close", None)
    if callable(close):
        with suppress(BaseException):
            close()


def execute_crawl(
    request: CrawlExecutionRequest,
    *,
    authenticated_user_id: str | None,
    registry: ProviderRegistry | None = None,
    policy: EgressPolicy | None = None,
) -> CrawlExecution:
    """Execute one crawl without exceeding deployment or request policy."""

    selected_registry = registry or get_provider_registry()
    selected_policy = policy or EgressPolicy()
    registration = _select_registration(request, selected_registry)
    descriptor = registration.descriptor
    network, allowed_providers = _effective_controls(request)
    egress_request = EgressRequest(
        network=network,
        classification=request.classification,
        provider=descriptor.name,
        capability=ProviderCapability.CRAWL,
        purpose="retrieve bounded public website content",
        fields=frozenset({OutboundField.URL}),
        source_opt_in=request.source_opt_in,
        one_request_override=request.one_request_override,
        allowed_providers=allowed_providers,
    )
    decision = selected_policy.evaluate(egress_request, descriptor)
    if not decision.allowed:
        raise _failure(
            ProviderFailureCode.FORBIDDEN_BY_POLICY,
            "Crawl provider call was denied by egress policy.",
            retryable=False,
            provider=descriptor.name,
        )

    effective_response_cap = request.crawl.max_response_bytes
    if descriptor.max_response_bytes is not None:
        effective_response_cap = min(
            effective_response_cap,
            descriptor.max_response_bytes,
        )
    if effective_response_cap < 256:
        raise _failure(
            ProviderFailureCode.CONTENT_REJECTED,
            "Crawl response byte ceiling is too small.",
            retryable=False,
            provider=descriptor.name,
        )
    provider_request = replace(
        request.crawl,
        max_response_bytes=effective_response_cap,
    )
    request_bytes = len(
        json.dumps(
            provider_request.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    )
    if (
        descriptor.max_request_bytes is not None
        and request_bytes > descriptor.max_request_bytes
    ):
        raise _failure(
            ProviderFailureCode.CONTENT_REJECTED,
            "Crawl request exceeded the provider byte ceiling.",
            retryable=False,
            provider=descriptor.name,
        )

    future: Future[ProviderCrawlResponse] = Future()

    def call() -> None:
        provider: object | None = None
        try:
            provider = selected_registry.create(
                descriptor.name,
                user_id=authenticated_user_id,
            )
            if not isinstance(provider, CrawlProvider):
                raise TypeError("provider does not implement crawl")
            response = provider.crawl(provider_request)
            if not isinstance(response, ProviderCrawlResponse):
                raise TypeError("provider returned an invalid crawl response")
            if response.consumed_bytes > provider_request.max_response_bytes:
                raise TypeError("provider response exceeded its byte ceiling")
        except BaseException as exc:
            if isinstance(exc, Exception):
                future.set_exception(exc)
            else:
                future.set_exception(
                    RuntimeError("Provider execution failed.")
                )
            return
        finally:
            if provider is not None:
                _close_provider(provider)
        future.set_result(response)

    thread = Thread(
        target=call,
        name=f"crawl-provider-{descriptor.name}",
        daemon=True,
    )
    thread.start()
    try:
        response = future.result(
            timeout=provider_request.timeout_ms / 1000
        )
    except FutureTimeoutError:
        provider_request.cancellation.cancel()
        raise _failure(
            ProviderFailureCode.TIMEOUT,
            "Crawl provider operation timed out.",
            retryable=True,
            provider=descriptor.name,
        ) from None
    except ProviderUnavailableError:
        raise
    except Exception as exc:
        raise _failure(
            ProviderFailureCode.INVALID_RESPONSE,
            "Crawl provider execution failed.",
            retryable=False,
            provider=descriptor.name,
            cause=exc,
        ) from None

    return CrawlExecution(
        provider=descriptor.name,
        decision=decision,
        response=response,
    )
