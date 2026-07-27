"""Connector lifecycle and incremental synchronization orchestration."""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from synsc.connectors.contracts import (
    ConnectorProvider,
    ConnectorSyncRequest,
    ConnectorSyncResponse,
)
from synsc.connectors.registry import (
    ConnectorProviderRegistry,
    get_connector_provider_registry,
)
from synsc.providers.contracts import (
    CancellationToken,
    ContentClassification,
    ProviderUnavailableError,
)


def _secret_strings(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        secrets: list[str] = []
        for item in value.values():
            secrets.extend(_secret_strings(item))
        return secrets
    if isinstance(value, (list, tuple)):
        secrets = []
        for item in value:
            secrets.extend(_secret_strings(item))
        return secrets
    if isinstance(value, str) and value:
        return [value]
    return []


def _safe_provider_error(
    exc: Exception,
    source: ConnectorSourceState,
) -> str:
    message = str(exc)[:2000] or type(exc).__name__
    secrets = _secret_strings(source.configuration)
    if source.cursor is not None:
        secrets.extend(_secret_strings(source.cursor))
    for secret in sorted(set(secrets), key=len, reverse=True):
        message = message.replace(secret, "[redacted]")
    return message


def _provider_failure_is_retryable(
    exc: Exception,
    *,
    supports_retry: bool,
) -> bool:
    if isinstance(exc, ProviderUnavailableError):
        return bool(exc.failure.retryable)
    return bool(
        supports_retry
        and isinstance(exc, (TimeoutError, ConnectionError, OSError))
    )


def _sync_with_deadline(
    provider: ConnectorProvider,
    request: ConnectorSyncRequest,
) -> ConnectorSyncResponse:
    """Enforce the provider deadline even for a non-cooperative adapter."""

    outcome: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def invoke() -> None:
        try:
            outcome.put((True, provider.sync(request)))
        except Exception as exc:
            outcome.put((False, exc))

    thread = threading.Thread(
        target=invoke,
        daemon=True,
        name=f"connector-provider-{provider.descriptor.name}",
    )
    thread.start()
    thread.join(request.timeout_ms / 1000)
    if thread.is_alive():
        request.cancellation.cancel()
        raise TimeoutError("Connector provider timed out.")
    succeeded, value = outcome.get_nowait()
    if not succeeded:
        assert isinstance(value, Exception)
        raise value
    if not isinstance(value, ConnectorSyncResponse):
        raise TypeError("Connector provider returned an invalid response.")
    return value


@dataclass(frozen=True)
class ConnectorSourceState:
    """Internal source state, including decrypted runtime-only values."""

    source_id: str
    user_id: str
    provider: str
    display_name: str
    external_ref: str
    classification: ContentClassification
    configuration: Mapping[str, Any] = field(repr=False)
    cursor: Mapping[str, Any] | None = field(default=None, repr=False)
    enabled: bool = True
    schedule_seconds: int | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": "connector",
            "user_id": self.user_id,
            "provider": self.provider,
            "display_name": self.display_name,
            "external_ref": self.external_ref,
            "classification": self.classification.value,
            "enabled": self.enabled,
            "schedule_seconds": self.schedule_seconds,
        }


@dataclass(frozen=True)
class ConnectorSyncJobState:
    """Claimed connector job identity and lease generation."""

    job_id: str
    source_id: str
    user_id: str
    status: str
    worker_id: str | None
    attempt_count: int

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "source_id": self.source_id,
            "user_id": self.user_id,
            "status": self.status,
            "attempt_count": self.attempt_count,
        }


class ConnectorSyncStore(Protocol):
    """Persistence boundary for connector lifecycle and atomic page apply."""

    def create_source(
        self,
        *,
        user_id: str,
        provider: str,
        display_name: str,
        external_ref: str,
        configuration: Mapping[str, Any],
        classification: ContentClassification,
        schedule_seconds: int | None,
        enabled: bool,
    ) -> dict[str, Any]: ...

    def list_sources(
        self,
        *,
        user_id: str,
        provider: str | None,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    def get_source(
        self,
        source_id: str,
        *,
        user_id: str,
    ) -> dict[str, Any]: ...

    def delete_source(self, source_id: str, *, user_id: str) -> bool: ...

    def enqueue_sync(
        self,
        source_id: str,
        *,
        user_id: str,
        priority: int,
    ) -> dict[str, Any]: ...

    def get_job(self, job_id: str, *, user_id: str) -> dict[str, Any]: ...

    def claim_next_job(
        self,
        *,
        worker_id: str,
    ) -> tuple[ConnectorSyncJobState, ConnectorSourceState] | None: ...

    def apply_sync_page(
        self,
        job: ConnectorSyncJobState,
        source: ConnectorSourceState,
        response: ConnectorSyncResponse,
    ) -> dict[str, Any]: ...

    def fail_job(
        self,
        job: ConnectorSyncJobState,
        *,
        error_message: str,
        retryable: bool,
    ) -> str | None: ...

    def enqueue_due(self, *, limit: int) -> int: ...


class ConnectorSyncService:
    """User-facing connector lifecycle plus one worker execution step."""

    def __init__(
        self,
        *,
        store: ConnectorSyncStore | None = None,
        registry: ConnectorProviderRegistry | None = None,
        page_limit: int = 250,
        timeout_ms: int = 60_000,
    ) -> None:
        if not 1 <= page_limit <= 1000:
            raise ValueError("page_limit must be between 1 and 1000")
        if not 1 <= timeout_ms <= 300_000:
            raise ValueError("timeout_ms must be between 1 and 300000")
        if store is None:
            from synsc.connectors.postgres import PostgresConnectorSyncStore

            store = PostgresConnectorSyncStore()
        self.store = store
        self.registry = registry or get_connector_provider_registry()
        self.page_limit = page_limit
        self.timeout_ms = timeout_ms

    def create_source(
        self,
        *,
        user_id: str,
        provider: str,
        display_name: str,
        external_ref: str,
        configuration: Mapping[str, Any],
        classification: ContentClassification,
        schedule_seconds: int | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        for label, value in (
            ("user_id", user_id),
            ("provider", provider),
            ("display_name", display_name),
            ("external_ref", external_ref),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be empty")
        if schedule_seconds is not None and not 60 <= schedule_seconds <= 31_536_000:
            raise ValueError(
                "schedule_seconds must be between 60 and 31536000"
            )
        descriptor = self.registry.descriptor(provider)
        if descriptor is None:
            raise ValueError(
                f"connector provider '{provider}' is not registered"
            )
        if classification not in descriptor.accepted_classifications:
            raise ValueError(
                f"connector provider '{provider}' does not accept "
                f"classification '{classification.value}'"
            )
        connector = self.registry.create(provider)
        connector.validate_configuration(configuration)
        result = self.store.create_source(
            user_id=user_id,
            provider=provider,
            display_name=display_name,
            external_ref=external_ref,
            configuration=configuration,
            classification=classification,
            schedule_seconds=schedule_seconds,
            enabled=enabled,
        )
        return {
            key: value
            for key, value in result.items()
            if key not in {"configuration", "cursor"}
        }

    def list_sources(
        self,
        *,
        user_id: str,
        provider: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        return self.store.list_sources(
            user_id=user_id,
            provider=provider,
            limit=limit,
        )

    def get_source(
        self,
        source_id: str,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        return self.store.get_source(source_id, user_id=user_id)

    def delete_source(self, source_id: str, *, user_id: str) -> bool:
        return self.store.delete_source(source_id, user_id=user_id)

    def enqueue_sync(
        self,
        source_id: str,
        *,
        user_id: str,
        priority: int = 0,
    ) -> dict[str, Any]:
        if not -100 <= priority <= 100:
            raise ValueError("priority must be between -100 and 100")
        return self.store.enqueue_sync(
            source_id,
            user_id=user_id,
            priority=priority,
        )

    def get_job(self, job_id: str, *, user_id: str) -> dict[str, Any]:
        return self.store.get_job(job_id, user_id=user_id)

    def run_once(self, *, worker_id: str) -> dict[str, Any] | None:
        claimed = self.store.claim_next_job(worker_id=worker_id)
        if claimed is None:
            return None
        job, source = claimed
        if job.worker_id != worker_id or job.status != "running":
            raise RuntimeError(
                f"connector job {job.job_id} has an invalid worker lease"
            )
        provider: ConnectorProvider | None = None
        try:
            provider = self.registry.create(source.provider)
            response = _sync_with_deadline(
                provider,
                ConnectorSyncRequest(
                    user_id=source.user_id,
                    configuration=source.configuration,
                    cursor=source.cursor,
                    limit=self.page_limit,
                    timeout_ms=self.timeout_ms,
                    cancellation=CancellationToken(),
                ),
            )
            if len(response.records) > self.page_limit:
                raise ValueError(
                    "Connector provider exceeded the requested page limit."
                )
            response_bytes = len(
                json.dumps(
                    response.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            )
            max_response_bytes = (
                provider.descriptor.max_response_bytes or 100_000_000
            )
            if response_bytes > max_response_bytes:
                raise ValueError(
                    "Connector provider exceeded its response byte limit."
                )
            if (
                response.has_more
                and response.next_cursor == source.cursor
            ):
                raise ValueError(
                    "Connector provider did not advance cursor for a "
                    "paginated response."
                )
            return self.store.apply_sync_page(
                job,
                source,
                response,
            )
        except Exception as exc:
            error_message = _safe_provider_error(exc, source)
            retryable = _provider_failure_is_retryable(
                exc,
                supports_retry=bool(
                    provider is not None
                    and provider.descriptor.supports_retry
                ),
            )
            status = self.store.fail_job(
                job,
                error_message=error_message,
                retryable=retryable,
            )
            if status is None:
                raise RuntimeError(
                    f"connector job {job.job_id} lost its failure lease"
                ) from exc
            return {
                "job_id": job.job_id,
                "status": status,
                "error": error_message,
            }

    def schedule_due(self, *, limit: int = 100) -> int:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        return self.store.enqueue_due(limit=limit)


_service: ConnectorSyncService | None = None


def get_connector_sync_service() -> ConnectorSyncService:
    """Return the process connector service."""

    global _service
    if _service is None:
        _service = ConnectorSyncService()
    return _service


def reset_connector_sync_service() -> None:
    """Clear process state for isolated tests."""

    global _service
    _service = None
