"""Lazy, deterministic provider registry tests."""

from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock

import pytest

from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
    ProviderDescriptor,
    ProviderFailureCode,
    ProviderHealth,
    ProviderUnavailableError,
)
from synsc.providers.policy import NetworkPolicy
from synsc.providers.registry import (
    ProviderCapabilityUnavailableError,
    ProviderNotFoundError,
    ProviderRegistry,
    ProviderRegistryError,
    get_provider_registry,
    reset_provider_registry,
)


def _descriptor(
    name: str,
    execution: ExecutionLocation,
    *,
    capability: ProviderCapability = ProviderCapability.EMBEDDING,
    health: ProviderHealth = ProviderHealth.READY,
) -> ProviderDescriptor:
    return ProviderDescriptor(
        name=name,
        version="1",
        capabilities=frozenset({capability}),
        execution=execution,
        accepted_classifications=frozenset(ContentClassification),
        health=health,
    )


def test_listing_does_not_construct_provider() -> None:
    factory = MagicMock(return_value=object())
    registry = ProviderRegistry()
    registry.register(_descriptor("remote", ExecutionLocation.REMOTE), factory)

    assert [item.name for item in registry.list_descriptors()] == ["remote"]
    factory.assert_not_called()


def test_listing_is_sorted_by_provider_name() -> None:
    registry = ProviderRegistry()
    registry.register(
        _descriptor("z-provider", ExecutionLocation.LOCAL),
        lambda: "z",
    )
    registry.register(
        _descriptor("a-provider", ExecutionLocation.LOCAL),
        lambda: "a",
    )

    assert [item.name for item in registry.list_descriptors()] == [
        "a-provider",
        "z-provider",
    ]


def test_selection_prefers_local_then_priority_then_name() -> None:
    registry = ProviderRegistry()
    registry.register(
        _descriptor("remote", ExecutionLocation.REMOTE),
        lambda: "remote",
        priority=1,
    )
    registry.register(
        _descriptor("local-z", ExecutionLocation.LOCAL),
        lambda: "z",
        priority=20,
    )
    registry.register(
        _descriptor("local-b", ExecutionLocation.LOCAL),
        lambda: "b",
        priority=10,
    )
    registry.register(
        _descriptor("local-a", ExecutionLocation.LOCAL),
        lambda: "a",
        priority=10,
    )

    selected = registry.select(
        ProviderCapability.EMBEDDING,
        NetworkPolicy.ONLINE,
    )

    assert selected.descriptor.name == "local-a"


def test_duplicate_name_is_rejected() -> None:
    registry = ProviderRegistry()
    descriptor = _descriptor("same", ExecutionLocation.LOCAL)
    registry.register(descriptor, lambda: object())

    with pytest.raises(ProviderRegistryError, match="already registered"):
        registry.register(descriptor, lambda: object())


def test_unknown_explicit_provider_is_rejected() -> None:
    with pytest.raises(ProviderNotFoundError, match="missing"):
        ProviderRegistry().get("missing")


def test_remote_only_capability_is_unavailable_offline() -> None:
    registry = ProviderRegistry()
    registry.register(
        _descriptor("remote", ExecutionLocation.REMOTE),
        lambda: object(),
    )

    with pytest.raises(
        ProviderCapabilityUnavailableError,
        match="embedding",
    ):
        registry.select(ProviderCapability.EMBEDDING, NetworkPolicy.OFFLINE)


def test_allowlisted_selection_filters_remote_providers() -> None:
    registry = ProviderRegistry()
    registry.register(
        _descriptor("remote-b", ExecutionLocation.REMOTE),
        lambda: "b",
        priority=1,
    )
    registry.register(
        _descriptor("remote-a", ExecutionLocation.REMOTE),
        lambda: "a",
        priority=2,
    )

    selected = registry.select(
        ProviderCapability.EMBEDDING,
        NetworkPolicy.ALLOWLISTED,
        allowed_providers=frozenset({"remote-a"}),
    )

    assert selected.descriptor.name == "remote-a"


def test_explicit_selection_still_obeys_network_policy() -> None:
    registry = ProviderRegistry()
    registry.register(
        _descriptor("remote", ExecutionLocation.REMOTE),
        lambda: object(),
    )

    with pytest.raises(ProviderCapabilityUnavailableError):
        registry.select(
            ProviderCapability.EMBEDDING,
            NetworkPolicy.LOCAL_ONLY,
            preferred_name="remote",
        )


def test_unavailable_provider_is_not_selected() -> None:
    registry = ProviderRegistry()
    registry.register(
        _descriptor(
            "down",
            ExecutionLocation.LOCAL,
            health=ProviderHealth.UNAVAILABLE,
        ),
        lambda: object(),
    )

    with pytest.raises(ProviderCapabilityUnavailableError):
        registry.select(ProviderCapability.EMBEDDING, NetworkPolicy.ONLINE)


def test_candidate_listing_filters_without_constructing_and_sorts_priority() -> None:
    ready = MagicMock(return_value=object())
    unavailable = MagicMock(return_value=object())
    registry = ProviderRegistry()
    registry.register(
        _descriptor(
            "ready-b",
            ExecutionLocation.REMOTE,
            capability=ProviderCapability.SEARCH,
        ),
        ready,
        priority=20,
    )
    registry.register(
        _descriptor(
            "ready-a",
            ExecutionLocation.REMOTE,
            capability=ProviderCapability.SEARCH,
        ),
        ready,
        priority=10,
    )
    registry.register(
        _descriptor(
            "down",
            ExecutionLocation.REMOTE,
            capability=ProviderCapability.SEARCH,
            health=ProviderHealth.UNAVAILABLE,
        ),
        unavailable,
        priority=1,
    )

    registrations = registry.list_registrations(
        capability=ProviderCapability.SEARCH,
        execution=ExecutionLocation.REMOTE,
    )

    assert [item.descriptor.name for item in registrations] == [
        "ready-a",
        "ready-b",
    ]
    ready.assert_not_called()
    unavailable.assert_not_called()


def test_create_constructs_only_the_named_provider() -> None:
    selected_factory = MagicMock(return_value="selected")
    other_factory = MagicMock(return_value="other")
    registry = ProviderRegistry()
    registry.register(
        _descriptor("selected", ExecutionLocation.LOCAL),
        selected_factory,
    )
    registry.register(
        _descriptor("other", ExecutionLocation.LOCAL),
        other_factory,
    )

    assert registry.create("selected", token="runtime-value") == "selected"
    selected_factory.assert_called_once_with(token="runtime-value")
    other_factory.assert_not_called()


def test_create_normalizes_factory_failure_without_leaking_cause() -> None:
    def fail(**_: object) -> object:
        raise RuntimeError("api-key=secret-value")

    registry = ProviderRegistry()
    registry.register(
        _descriptor("broken", ExecutionLocation.REMOTE),
        fail,
    )

    with pytest.raises(ProviderUnavailableError) as exc_info:
        registry.create("broken")

    failure = exc_info.value.failure
    assert failure.code is ProviderFailureCode.INTERNAL_ERROR
    assert failure.provider == "broken"
    assert failure.message == "Provider construction failed."
    assert "secret-value" not in str(exc_info.value)
    rendered_traceback = "".join(
        traceback.format_exception(exc_info.value)
    )
    assert "secret-value" not in rendered_traceback


def test_global_registry_is_published_only_after_initialization(
    monkeypatch,
) -> None:
    from synsc.providers import builtins

    reset_provider_registry()
    first_registered = Event()
    finish_registration = Event()
    second_started = Event()
    second_returned = Event()

    def register_in_two_steps(registry: ProviderRegistry) -> None:
        registry.register(
            _descriptor("first", ExecutionLocation.LOCAL),
            lambda: object(),
        )
        first_registered.set()
        assert finish_registration.wait(timeout=2)
        registry.register(
            _descriptor("second", ExecutionLocation.LOCAL),
            lambda: object(),
        )

    def get_second_snapshot() -> list[str]:
        second_started.set()
        registry = get_provider_registry()
        snapshot = [
            item.name for item in registry.list_descriptors()
        ]
        second_returned.set()
        return snapshot

    monkeypatch.setattr(
        builtins,
        "register_builtin_providers",
        register_in_two_steps,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(get_provider_registry)
        assert first_registered.wait(timeout=2)
        second = executor.submit(get_second_snapshot)
        assert second_started.wait(timeout=2)
        try:
            assert not second_returned.wait(timeout=0.1)
        finally:
            finish_registration.set()

        assert first.result(timeout=2) is get_provider_registry()
        assert second.result(timeout=2) == ["first", "second"]

    reset_provider_registry()


def test_reset_replaces_global_registry() -> None:
    reset_provider_registry()
    first = get_provider_registry()
    first.register(
        _descriptor("temporary", ExecutionLocation.LOCAL),
        lambda: object(),
    )

    reset_provider_registry()
    second = get_provider_registry()

    assert second is not first
    assert "local-embeddings" in {
        item.name for item in second.list_descriptors()
    }
