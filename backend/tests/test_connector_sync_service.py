"""Connector lifecycle and worker orchestration contracts."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

import pytest

from synsc.connectors.contracts import (
    ConnectorRecord,
    ConnectorSyncRequest,
    ConnectorSyncResponse,
)
from synsc.connectors.registry import ConnectorProviderRegistry
from synsc.connectors.service import (
    ConnectorSourceState,
    ConnectorSyncJobState,
    ConnectorSyncService,
)
from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
    ProviderDescriptor,
)


class FakeProvider:
    descriptor = ProviderDescriptor(
        name="fixture",
        version="1",
        capabilities=frozenset(
            {ProviderCapability.CONNECTOR, ProviderCapability.SYNC}
        ),
        execution=ExecutionLocation.LOCAL,
        accepted_classifications=frozenset(ContentClassification),
        supports_cancellation=True,
        supports_retry=True,
    )

    def __init__(self) -> None:
        self.requests: list[ConnectorSyncRequest] = []
        self.failure: Exception | None = None
        self.validated: dict[str, Any] | None = None

    def validate_configuration(
        self,
        configuration: dict[str, Any],
    ) -> None:
        self.validated = dict(configuration)

    def sync(self, request: ConnectorSyncRequest) -> ConnectorSyncResponse:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return ConnectorSyncResponse(
            records=(
                ConnectorRecord(
                    external_id="doc-1",
                    locator="docs/one.md",
                    content="hello",
                    accessible_principals=(request.user_id,),
                ),
            ),
            next_cursor={"page": 2},
        )


class FakeStore:
    def __init__(self) -> None:
        self.source = ConnectorSourceState(
            source_id="source-1",
            user_id="user-1",
            provider="fixture",
            display_name="Fixture",
            external_ref="fixture://one",
            classification=ContentClassification.PRIVATE,
            configuration={"scope": "one", "token": "super-secret"},
            cursor={"page": 1},
            enabled=True,
            schedule_seconds=None,
        )
        self.job = ConnectorSyncJobState(
            job_id="job-1",
            source_id=self.source.source_id,
            user_id=self.source.user_id,
            status="running",
            worker_id="worker-1",
            attempt_count=1,
        )
        self.created: dict[str, Any] | None = None
        self.applied: ConnectorSyncResponse | None = None
        self.failed: str | None = None
        self.retryable: bool | None = None

    def create_source(self, **kwargs: Any) -> dict[str, Any]:
        self.created = kwargs
        return {"source_id": "source-new", **kwargs, "cursor": None}

    def list_sources(
        self,
        *,
        user_id: str,
        provider: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        return [self.source.to_public_dict()]

    def get_source(
        self,
        source_id: str,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        return self.source.to_public_dict()

    def delete_source(self, source_id: str, *, user_id: str) -> bool:
        return source_id == self.source.source_id and user_id == self.source.user_id

    def enqueue_sync(
        self,
        source_id: str,
        *,
        user_id: str,
        priority: int,
    ) -> dict[str, Any]:
        return self.job.to_public_dict()

    def get_job(self, job_id: str, *, user_id: str) -> dict[str, Any]:
        return self.job.to_public_dict()

    def claim_next_job(
        self,
        *,
        worker_id: str,
    ) -> tuple[ConnectorSyncJobState, ConnectorSourceState] | None:
        return self.job, self.source

    def apply_sync_page(
        self,
        job: ConnectorSyncJobState,
        source: ConnectorSourceState,
        response: ConnectorSyncResponse,
    ) -> dict[str, Any]:
        self.applied = response
        return {
            "job_id": job.job_id,
            "status": "completed",
            "snapshot_id": "snapshot-1",
            "records_changed": len(response.records),
        }

    def fail_job(
        self,
        job: ConnectorSyncJobState,
        *,
        error_message: str,
        retryable: bool,
    ) -> str:
        self.failed = error_message
        self.retryable = retryable
        return "pending" if retryable else "failed"

    def enqueue_due(self, *, limit: int) -> int:
        return 2


def _service() -> tuple[ConnectorSyncService, FakeProvider, FakeStore]:
    provider = FakeProvider()
    registry = ConnectorProviderRegistry()
    registry.register(provider.descriptor, lambda: provider)
    store = FakeStore()
    return ConnectorSyncService(store=store, registry=registry), provider, store


def test_create_source_validates_provider_and_never_returns_configuration() -> None:
    service, provider, store = _service()

    result = service.create_source(
        user_id="user-1",
        provider="fixture",
        display_name="Fixture",
        external_ref="fixture://one",
        configuration={"token": "secret"},
        classification=ContentClassification.PRIVATE,
        schedule_seconds=300,
    )

    assert store.created is not None
    assert store.created["configuration"] == {"token": "secret"}
    assert provider.validated == {"token": "secret"}
    assert "configuration" not in result
    assert "token" not in repr(result)


def test_create_source_rejects_unknown_or_incompatible_provider() -> None:
    service, _, _ = _service()
    with pytest.raises(ValueError, match="not registered"):
        service.create_source(
            user_id="user-1",
            provider="missing",
            display_name="Missing",
            external_ref="missing://one",
            configuration={},
            classification=ContentClassification.PRIVATE,
        )

    remote_descriptor = ProviderDescriptor(
        name="public-only",
        version="1",
        capabilities=frozenset(
            {ProviderCapability.CONNECTOR, ProviderCapability.SYNC}
        ),
        execution=ExecutionLocation.REMOTE,
        accepted_classifications=frozenset(
            {ContentClassification.PUBLIC}
        ),
    )
    service.registry.register(remote_descriptor, lambda: FakeProvider())
    with pytest.raises(ValueError, match="classification"):
        service.create_source(
            user_id="user-1",
            provider="public-only",
            display_name="Private",
            external_ref="remote://one",
            configuration={},
            classification=ContentClassification.PRIVATE,
        )


def test_run_once_passes_decrypted_state_and_applies_page() -> None:
    service, provider, store = _service()

    result = service.run_once(worker_id="worker-1")

    assert result == {
        "job_id": "job-1",
        "status": "completed",
        "snapshot_id": "snapshot-1",
        "records_changed": 1,
    }
    assert provider.requests[0].configuration == {
        "scope": "one",
        "token": "super-secret",
    }
    assert provider.requests[0].cursor == {"page": 1}
    assert store.applied is not None
    assert store.applied.next_cursor == {"page": 2}


def test_run_once_records_failure_without_applying_cursor() -> None:
    service, provider, store = _service()
    provider.failure = RuntimeError("provider unavailable")

    result = service.run_once(worker_id="worker-1")

    assert result == {
        "job_id": "job-1",
        "status": "failed",
        "error": "provider unavailable",
    }
    assert store.applied is None
    assert store.failed == "provider unavailable"
    assert store.retryable is False


def test_run_once_redacts_configuration_values_from_failures() -> None:
    service, provider, store = _service()
    provider.failure = RuntimeError(
        "provider rejected token super-secret for scope one"
    )

    result = service.run_once(worker_id="worker-1")

    assert result is not None
    assert "super-secret" not in result["error"]
    assert " scope one" not in result["error"]
    assert store.failed == (
        "provider rejected token [redacted] for scope [redacted]"
    )


def test_run_once_rejects_mismatched_worker_lease() -> None:
    service, _, store = _service()
    store.job = replace(store.job, worker_id="worker-other")

    with pytest.raises(RuntimeError, match="lease"):
        service.run_once(worker_id="worker-1")


def test_schedule_due_delegates_with_bound() -> None:
    service, _, _ = _service()
    assert service.schedule_due(limit=20) == 2
    with pytest.raises(ValueError, match="limit"):
        service.schedule_due(limit=0)


def test_run_once_rejects_provider_page_above_declared_limit() -> None:
    service, provider, store = _service()
    service.page_limit = 1

    def oversized(_request):
        record = ConnectorRecord(
            external_id="one",
            locator="one",
            content="one",
        )
        return ConnectorSyncResponse(
            records=(record, replace(record, external_id="two")),
            next_cursor={"page": 2},
        )

    provider.sync = oversized

    result = service.run_once(worker_id="worker-1")

    assert result is not None
    assert result["status"] == "failed"
    assert "page limit" in result["error"]
    assert store.applied is None


def test_run_once_rejects_non_advancing_paginated_cursor() -> None:
    service, provider, store = _service()

    def stalled(_request):
        return ConnectorSyncResponse(
            records=(),
            next_cursor={"page": 1},
            has_more=True,
        )

    provider.sync = stalled

    result = service.run_once(worker_id="worker-1")

    assert result is not None
    assert result["status"] == "failed"
    assert "advance cursor" in result["error"]
    assert store.applied is None


def test_run_once_enforces_deadline_and_requeues_retryable_timeout() -> None:
    service, provider, store = _service()
    service.timeout_ms = 10

    def blocking(request):
        while not request.cancellation.cancelled:
            time.sleep(0.001)
        raise TimeoutError("provider observed cancellation")

    provider.sync = blocking
    started = time.monotonic()

    result = service.run_once(worker_id="worker-1")

    assert time.monotonic() - started < 0.5
    assert result is not None
    assert result["status"] == "pending"
    assert store.retryable is True
    assert "timed out" in result["error"]
