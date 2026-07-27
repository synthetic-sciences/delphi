"""Lazy provider registration and deterministic capability selection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Any

from synsc.providers.contracts import (
    ExecutionLocation,
    ProviderCapability,
    ProviderDescriptor,
    ProviderFailure,
    ProviderFailureCode,
    ProviderHealth,
    ProviderUnavailableError,
)
from synsc.providers.policy import NetworkPolicy

ProviderFactory = Callable[..., object]


class ProviderRegistryError(RuntimeError):
    """Base class for provider catalog errors."""


class ProviderNotFoundError(ProviderRegistryError):
    """Raised when an explicitly named provider is absent."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"provider '{name}' is not registered")


class ProviderCapabilityUnavailableError(ProviderRegistryError):
    """Raised when no policy-compatible provider can satisfy a capability."""

    def __init__(self, capability: ProviderCapability):
        self.capability = capability
        super().__init__(f"no available provider supports {capability.value}")


@dataclass(frozen=True)
class ProviderRegistration:
    """Descriptor, lazy factory, and deterministic selection priority."""

    descriptor: ProviderDescriptor
    factory: ProviderFactory
    priority: int = 100


class ProviderRegistry:
    """In-memory provider catalog whose factories stay lazy until selected."""

    def __init__(self) -> None:
        self._registrations: dict[str, ProviderRegistration] = {}

    def register(
        self,
        descriptor: ProviderDescriptor,
        factory: ProviderFactory,
        *,
        priority: int = 100,
    ) -> None:
        if descriptor.name in self._registrations:
            raise ProviderRegistryError(
                f"provider '{descriptor.name}' is already registered"
            )
        self._registrations[descriptor.name] = ProviderRegistration(
            descriptor=descriptor,
            factory=factory,
            priority=priority,
        )

    def get(self, name: str) -> ProviderRegistration:
        try:
            return self._registrations[name]
        except KeyError as exc:
            raise ProviderNotFoundError(name) from exc

    def list_descriptors(self) -> list[ProviderDescriptor]:
        return [
            registration.descriptor
            for _, registration in sorted(self._registrations.items())
        ]

    def list_registrations(
        self,
        *,
        capability: ProviderCapability | None = None,
        execution: ExecutionLocation | None = None,
        include_unavailable: bool = False,
    ) -> list[ProviderRegistration]:
        """Return deterministic candidates without constructing providers."""

        registrations = [
            registration
            for registration in self._registrations.values()
            if (capability is None or capability in registration.descriptor.capabilities)
            and (execution is None or registration.descriptor.execution is execution)
            and (
                include_unavailable
                or registration.descriptor.health is not ProviderHealth.UNAVAILABLE
            )
        ]
        registrations.sort(
            key=lambda registration: (
                registration.priority,
                registration.descriptor.name,
            )
        )
        return registrations

    @staticmethod
    def _network_allows(
        registration: ProviderRegistration,
        network: NetworkPolicy,
        allowed_providers: frozenset[str],
    ) -> bool:
        if registration.descriptor.execution is ExecutionLocation.LOCAL:
            return True
        if network in (NetworkPolicy.OFFLINE, NetworkPolicy.LOCAL_ONLY):
            return False
        if network is NetworkPolicy.ALLOWLISTED:
            return registration.descriptor.name in allowed_providers
        return True

    def select(
        self,
        capability: ProviderCapability,
        network: NetworkPolicy,
        *,
        allowed_providers: frozenset[str] = frozenset(),
        preferred_name: str | None = None,
    ) -> ProviderRegistration:
        if preferred_name is None:
            candidates = list(self._registrations.values())
        else:
            candidates = [self.get(preferred_name)]

        candidates = [
            registration
            for registration in candidates
            if capability in registration.descriptor.capabilities
            and registration.descriptor.health is not ProviderHealth.UNAVAILABLE
            and self._network_allows(registration, network, allowed_providers)
        ]
        if not candidates:
            raise ProviderCapabilityUnavailableError(capability)

        candidates.sort(
            key=lambda registration: (
                registration.descriptor.execution is ExecutionLocation.REMOTE,
                registration.priority,
                registration.descriptor.name,
            )
        )
        return candidates[0]

    def create(self, name: str, **kwargs: Any) -> object:
        registration = self.get(name)
        try:
            return registration.factory(**kwargs)
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(
                ProviderFailure(
                    code=ProviderFailureCode.INTERNAL_ERROR,
                    message="Provider construction failed.",
                    retryable=False,
                    provider=name,
                    cause=exc,
                )
            ) from None


_provider_registry: ProviderRegistry | None = None
_provider_registry_lock = Lock()


def get_provider_registry() -> ProviderRegistry:
    """Return the process-wide registry without constructing any providers."""

    global _provider_registry
    if _provider_registry is None:
        with _provider_registry_lock:
            if _provider_registry is None:
                registry = ProviderRegistry()
                from synsc.providers.builtins import register_builtin_providers

                register_builtin_providers(registry)
                _provider_registry = registry
    return _provider_registry


def reset_provider_registry() -> None:
    """Replace the global registry, primarily for configuration reloads and tests."""

    global _provider_registry
    with _provider_registry_lock:
        _provider_registry = None
