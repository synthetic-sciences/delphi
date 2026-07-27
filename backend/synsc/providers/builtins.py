"""Lazy registrations for Delphi's built-in local and optional providers."""

from __future__ import annotations

from typing import Any

from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
    ProviderDescriptor,
    ProviderHealth,
)
from synsc.providers.registry import ProviderRegistry

_ALL_CLASSIFICATIONS = frozenset(ContentClassification)


def _local_embeddings(**kwargs: Any) -> object:
    from synsc.embeddings.generator import EmbeddingGenerator

    return EmbeddingGenerator(**kwargs)


def _hash_embeddings(**_: Any) -> object:
    from synsc.embeddings.providers import HashEmbeddingProvider

    return HashEmbeddingProvider()


def _gemini_embeddings(**_: Any) -> object:
    from synsc.embeddings.providers import GeminiEmbeddingProvider

    return GeminiEmbeddingProvider()


def _openai_embeddings(**_: Any) -> object:
    from synsc.embeddings.providers import OpenAIEmbeddingProvider

    return OpenAIEmbeddingProvider()


def _huggingface_embeddings(**_: Any) -> object:
    from synsc.embeddings.providers import HuggingFaceEmbeddingProvider

    return HuggingFaceEmbeddingProvider()


def _local_index_search(**kwargs: Any) -> object:
    from synsc.planner.providers import LocalIndexSearchProvider

    return LocalIndexSearchProvider(user_id=kwargs.get("user_id"))


def _gemini_research(**kwargs: Any) -> object:
    from synsc.services.research_providers.gemini import GeminiResearchProvider

    api_key = kwargs.get("api_key")
    if not isinstance(api_key, str):
        raise ValueError("gemini research requires an api_key")
    return GeminiResearchProvider(api_key=api_key)


def _connector(source_type: str) -> object:
    from synsc.services.connectors import get_connector

    connector = get_connector(source_type)
    if connector is None:
        raise RuntimeError(f"connector '{source_type}' is not registered")
    return connector


def _descriptor(
    name: str,
    capability: ProviderCapability,
    execution: ExecutionLocation,
    *,
    health: ProviderHealth = ProviderHealth.READY,
    extra_capabilities: frozenset[ProviderCapability] = frozenset(),
    supports_cancellation: bool = False,
) -> ProviderDescriptor:
    return ProviderDescriptor(
        name=name,
        version="1",
        capabilities=frozenset({capability}) | extra_capabilities,
        execution=execution,
        accepted_classifications=_ALL_CLASSIFICATIONS,
        health=health,
        supports_cancellation=supports_cancellation,
    )


def register_builtin_providers(registry: ProviderRegistry) -> None:
    """Register metadata and factories without constructing any provider."""

    registry.register(
        _descriptor(
            "local-index",
            ProviderCapability.SEARCH,
            ExecutionLocation.LOCAL,
            supports_cancellation=True,
        ),
        _local_index_search,
        priority=5,
    )
    registry.register(
        _descriptor(
            "local-embeddings",
            ProviderCapability.EMBEDDING,
            ExecutionLocation.LOCAL,
        ),
        _local_embeddings,
        priority=10,
    )
    registry.register(
        _descriptor(
            "hash-embeddings",
            ProviderCapability.EMBEDDING,
            ExecutionLocation.LOCAL,
        ),
        _hash_embeddings,
        priority=20,
    )
    registry.register(
        _descriptor(
            "gemini-embeddings",
            ProviderCapability.EMBEDDING,
            ExecutionLocation.REMOTE,
        ),
        _gemini_embeddings,
        priority=100,
    )
    registry.register(
        _descriptor(
            "openai-embeddings",
            ProviderCapability.EMBEDDING,
            ExecutionLocation.REMOTE,
        ),
        _openai_embeddings,
        priority=110,
    )
    registry.register(
        _descriptor(
            "huggingface-embeddings",
            ProviderCapability.EMBEDDING,
            ExecutionLocation.REMOTE,
        ),
        _huggingface_embeddings,
        priority=120,
    )
    registry.register(
        _descriptor(
            "gemini-research",
            ProviderCapability.SYNTHESIS,
            ExecutionLocation.REMOTE,
            extra_capabilities=frozenset({ProviderCapability.RESEARCH}),
        ),
        _gemini_research,
        priority=100,
    )
    registry.register(
        _descriptor(
            "slack-connector",
            ProviderCapability.CONNECTOR,
            ExecutionLocation.REMOTE,
            health=ProviderHealth.UNAVAILABLE,
        ),
        lambda: _connector("slack"),
    )
    registry.register(
        _descriptor(
            "gdrive-connector",
            ProviderCapability.CONNECTOR,
            ExecutionLocation.REMOTE,
            health=ProviderHealth.UNAVAILABLE,
        ),
        lambda: _connector("gdrive"),
    )
    registry.register(
        _descriptor(
            "spreadsheet-connector",
            ProviderCapability.CONNECTOR,
            ExecutionLocation.LOCAL,
            health=ProviderHealth.UNAVAILABLE,
        ),
        lambda: _connector("spreadsheet"),
    )
