"""Policy and lifecycle boundaries for hosted crawl execution."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
    ProviderCrawlPage,
    ProviderCrawlRequest,
    ProviderCrawlResponse,
    ProviderDescriptor,
    ProviderFailureCode,
    ProviderUnavailableError,
)
from synsc.providers.policy import NetworkPolicy, OutboundField
from synsc.providers.registry import ProviderRegistry
from synsc.services import crawl_provider_service
from synsc.services.crawl_provider_service import (
    CrawlExecutionRequest,
    execute_crawl,
)


def _registry(factory) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(
        ProviderDescriptor(
            name="remote-crawl",
            version="1",
            capabilities=frozenset({ProviderCapability.CRAWL}),
            execution=ExecutionLocation.REMOTE,
            accepted_classifications=frozenset(
                {ContentClassification.PUBLIC}
            ),
            max_request_bytes=8_192,
            max_response_bytes=1_024,
        ),
        factory,
    )
    return registry


def test_crawl_service_applies_deployment_network_ceiling_before_factory(
    monkeypatch,
) -> None:
    constructed = False

    def factory(**_):
        nonlocal constructed
        constructed = True
        return object()

    monkeypatch.setattr(
        crawl_provider_service,
        "get_provider_policy_config",
        lambda: SimpleNamespace(
            network_policy=NetworkPolicy.LOCAL_ONLY,
            allowed_remote_providers=[],
        ),
    )

    with pytest.raises(ProviderUnavailableError) as caught:
        execute_crawl(
            CrawlExecutionRequest(
                crawl=ProviderCrawlRequest(
                    url="https://docs.example.com/",
                ),
                network=NetworkPolicy.ONLINE,
                classification=ContentClassification.PUBLIC,
            ),
            authenticated_user_id="u1",
            registry=_registry(factory),
        )

    assert caught.value.failure.code is ProviderFailureCode.FORBIDDEN_BY_POLICY
    assert constructed is False


def test_crawl_service_executes_public_allowed_provider_and_closes_it(
    monkeypatch,
) -> None:
    observed = []
    closed = False

    class Provider:
        def crawl(self, request):
            observed.append(request)
            return ProviderCrawlResponse(
                pages=(
                    ProviderCrawlPage(
                        page_id="page-1",
                        url=request.url,
                        markdown="# Docs",
                    ),
                )
            )

        def close(self):
            nonlocal closed
            closed = True

    monkeypatch.setattr(
        crawl_provider_service,
        "get_provider_policy_config",
        lambda: SimpleNamespace(
            network_policy=NetworkPolicy.ALLOWLISTED,
            allowed_remote_providers=["remote-crawl"],
        ),
    )
    result = execute_crawl(
        CrawlExecutionRequest(
            crawl=ProviderCrawlRequest(
                url="https://docs.example.com/",
                max_response_bytes=4_096,
            ),
            network=NetworkPolicy.ALLOWLISTED,
            classification=ContentClassification.PUBLIC,
            allowed_providers=frozenset({"remote-crawl", "not-configured"}),
            preferred_provider="remote-crawl",
        ),
        authenticated_user_id="u1",
        registry=_registry(lambda **_: Provider()),
    )

    assert result.provider == "remote-crawl"
    assert result.decision.allowed is True
    assert result.decision.allowed_fields == frozenset({OutboundField.URL})
    assert result.response.pages[0].markdown == "# Docs"
    assert observed[0].max_response_bytes == 1_024
    assert closed is True


def test_crawl_service_rejects_private_url_egress_even_with_source_opt_in(
    monkeypatch,
) -> None:
    constructed = False

    def factory(**_):
        nonlocal constructed
        constructed = True
        return object()

    monkeypatch.setattr(
        crawl_provider_service,
        "get_provider_policy_config",
        lambda: SimpleNamespace(
            network_policy=NetworkPolicy.ONLINE,
            allowed_remote_providers=[],
        ),
    )

    with pytest.raises(ProviderUnavailableError) as caught:
        execute_crawl(
            CrawlExecutionRequest(
                crawl=ProviderCrawlRequest(
                    url="https://docs.example.com/",
                ),
                network=NetworkPolicy.ONLINE,
                classification=ContentClassification.PRIVATE,
                source_opt_in=True,
            ),
            authenticated_user_id="u1",
            registry=_registry(factory),
        )

    assert caught.value.failure.code is ProviderFailureCode.FORBIDDEN_BY_POLICY
    assert constructed is False
