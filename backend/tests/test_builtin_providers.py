"""Built-in provider catalog and compatibility factory tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from synsc.providers.builtins import register_builtin_providers
from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
    ProviderDescriptor,
)
from synsc.providers.registry import (
    ProviderRegistry,
    get_provider_registry,
    reset_provider_registry,
)


def _embedding_descriptor(name: str) -> ProviderDescriptor:
    return ProviderDescriptor(
        name=name,
        version="1",
        capabilities=frozenset({ProviderCapability.EMBEDDING}),
        execution=ExecutionLocation.LOCAL,
        accepted_classifications=frozenset(ContentClassification),
    )


def test_builtin_catalog_loads_without_remote_credentials(monkeypatch) -> None:
    for name in (
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "EMBEDDING_API_KEY",
        "HF_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    registry = ProviderRegistry()

    register_builtin_providers(registry)

    descriptors = {item.name: item for item in registry.list_descriptors()}
    assert {
        "local-embeddings",
        "hash-embeddings",
        "gemini-embeddings",
        "openai-embeddings",
        "huggingface-embeddings",
        "gemini-research",
        "firecrawl-web",
        "local-folder",
        "slack-connector",
        "gdrive-connector",
        "spreadsheet-connector",
    } <= descriptors.keys()
    assert descriptors["local-embeddings"].execution is ExecutionLocation.LOCAL
    assert descriptors["local-index"].execution is ExecutionLocation.LOCAL
    assert ProviderCapability.SEARCH in descriptors["local-index"].capabilities
    assert descriptors["local-index"].supports_cancellation is True
    assert descriptors["gemini-research"].execution is ExecutionLocation.REMOTE
    assert descriptors["gemini-research"].supports_streaming is False
    assert descriptors["gemini-research"].supports_cancellation is False
    assert descriptors["gemini-research"].supports_retry is False
    assert descriptors["gemini-embeddings"].supports_retry is False
    assert descriptors["firecrawl-web"].execution is ExecutionLocation.REMOTE
    assert descriptors["firecrawl-web"].capabilities == frozenset(
        {ProviderCapability.SEARCH, ProviderCapability.CRAWL}
    )
    assert descriptors["firecrawl-web"].accepted_classifications == frozenset(
        {ContentClassification.PUBLIC}
    )
    assert descriptors["firecrawl-web"].supports_cancellation is True
    assert descriptors["firecrawl-web"].supports_retry is True
    assert descriptors["local-folder"].execution is ExecutionLocation.LOCAL
    assert descriptors["local-folder"].capabilities == frozenset(
        {ProviderCapability.CONNECTOR, ProviderCapability.SYNC}
    )


def test_builtin_catalog_registration_does_not_construct_factories() -> None:
    registry = ProviderRegistry()

    with (
        patch(
            "synsc.embeddings.providers.GeminiEmbeddingProvider",
        ) as gemini_embeddings,
        patch(
            "synsc.services.research_providers.gemini.GeminiResearchProvider",
        ) as gemini_research,
    ):
        register_builtin_providers(registry)
        registry.list_descriptors()

    gemini_embeddings.assert_not_called()
    gemini_research.assert_not_called()


def test_global_registry_contains_builtins_after_reset() -> None:
    reset_provider_registry()

    names = {item.name for item in get_provider_registry().list_descriptors()}

    assert "local-embeddings" in names
    assert "gemini-research" in names


def test_gemini_research_factory_receives_runtime_key() -> None:
    registry = ProviderRegistry()
    register_builtin_providers(registry)

    with patch(
        "synsc.services.research_providers.gemini.GeminiResearchProvider",
    ) as provider:
        created = registry.create("gemini-research", api_key="runtime-key")

    assert created is provider.return_value
    provider.assert_called_once_with(api_key="runtime-key")


def test_embedding_factory_uses_registry_without_changing_aliases(
    monkeypatch,
) -> None:
    from synsc.embeddings import generator

    fake = MagicMock()
    registry = ProviderRegistry()
    registry.register(_embedding_descriptor("hash-embeddings"), lambda: fake)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")
    monkeypatch.setattr(
        generator,
        "get_provider_registry",
        lambda: registry,
        raising=False,
    )
    assert generator.create_embedding_provider() is fake


def test_unknown_embedding_provider_still_falls_back_to_local(
    monkeypatch,
) -> None:
    from synsc.embeddings import generator

    fake = MagicMock()
    registry = ProviderRegistry()
    registry.register(_embedding_descriptor("local-embeddings"), lambda: fake)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "not-real")
    monkeypatch.setattr(
        generator,
        "get_provider_registry",
        lambda: registry,
        raising=False,
    )
    assert generator.create_embedding_provider() is fake


def test_research_service_constructs_provider_through_registry(
    monkeypatch,
) -> None:
    from synsc.services import research_service

    fake_provider = MagicMock()
    registry = MagicMock()
    registry.create.return_value = fake_provider
    config = SimpleNamespace(
        research=SimpleNamespace(
            provider="gemini",
            api_key="server-key",
        )
    )
    monkeypatch.setattr(research_service, "get_config", lambda: config)
    monkeypatch.setattr(
        research_service,
        "get_user_research_api_key",
        lambda user_id, provider: "user-key",
    )
    monkeypatch.setattr(
        research_service,
        "get_provider_registry",
        lambda: registry,
        raising=False,
    )

    created = research_service.ResearchService(user_id="user-1").provider

    assert created is fake_provider
    registry.create.assert_called_once_with(
        "gemini-research",
        api_key="user-key",
    )
