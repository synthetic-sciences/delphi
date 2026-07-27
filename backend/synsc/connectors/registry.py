"""Lazy registry for connector providers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from synsc.connectors.contracts import ConnectorProvider
from synsc.providers.contracts import (
    ProviderCapability,
    ProviderDescriptor,
    ProviderFailure,
    ProviderFailureCode,
    ProviderHealth,
    ProviderUnavailableError,
)

ConnectorFactory = Callable[[], ConnectorProvider]


class ConnectorProviderRegistry:
    """Register descriptors eagerly while constructing adapters lazily."""

    def __init__(self) -> None:
        self._entries: dict[
            str,
            tuple[ProviderDescriptor, ConnectorFactory],
        ] = {}

    def register(
        self,
        descriptor: ProviderDescriptor,
        factory: ConnectorFactory,
    ) -> None:
        required = {
            ProviderCapability.CONNECTOR,
            ProviderCapability.SYNC,
        }
        if not required.issubset(descriptor.capabilities):
            raise ValueError(
                "connector providers must declare connector and sync capabilities"
            )
        if descriptor.name in self._entries:
            raise ValueError(
                f"connector provider '{descriptor.name}' is already registered"
            )
        self._entries[descriptor.name] = (descriptor, factory)

    def descriptor(self, name: str) -> ProviderDescriptor | None:
        entry = self._entries.get(name)
        return entry[0] if entry is not None else None

    def create(self, name: str) -> ConnectorProvider:
        entry = self._entries.get(name)
        if entry is None:
            raise ProviderUnavailableError(
                ProviderFailure(
                    code=ProviderFailureCode.UNAVAILABLE,
                    message="Connector provider is not registered.",
                    retryable=False,
                    provider=name,
                )
            )
        descriptor, factory = entry
        if descriptor.health is ProviderHealth.UNAVAILABLE:
            raise ProviderUnavailableError(
                ProviderFailure(
                    code=ProviderFailureCode.UNAVAILABLE,
                    message="Connector provider is unavailable.",
                    retryable=False,
                    provider=name,
                )
            )
        provider = factory()
        if not isinstance(provider, ConnectorProvider):
            raise TypeError(
                f"connector provider factory '{name}' returned an invalid adapter"
            )
        return provider

    def list(self) -> list[dict[str, Any]]:
        return [
            descriptor.to_dict()
            for descriptor, _ in sorted(
                self._entries.values(),
                key=lambda entry: entry[0].name,
            )
        ]


_registry: ConnectorProviderRegistry | None = None


def get_connector_provider_registry() -> ConnectorProviderRegistry:
    """Return the process registry with local providers installed once."""

    global _registry
    if _registry is None:
        from synsc.connectors.local_folder import LocalFolderConnector

        _registry = ConnectorProviderRegistry()
        _registry.register(
            LocalFolderConnector.descriptor,
            LocalFolderConnector,
        )
    return _registry


def reset_connector_provider_registry() -> None:
    """Clear process state for isolated tests."""

    global _registry
    _registry = None
