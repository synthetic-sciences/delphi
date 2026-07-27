"""PostgreSQL persistence for durable, incremental connector synchronization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from synsc.connectors.contracts import ConnectorSyncResponse
from synsc.connectors.service import (
    ConnectorSourceState,
    ConnectorSyncJobState,
)
from synsc.database.connection import get_session
from synsc.providers.contracts import ContentClassification
from synsc.services.token_encryption import decrypt_token, encrypt_token
from synsc.snapshots.contracts import (
    SnapshotItem,
    SnapshotSourceType,
    SourceSnapshot,
    compute_snapshot_content_hash,
)
from synsc.snapshots.service import PostgresSnapshotStore


class ConnectorSourceNotFoundError(LookupError):
    """Raised when a connector source is absent or hidden from the caller."""


class ConnectorSyncJobNotFoundError(LookupError):
    """Raised when a sync job is absent or hidden from the caller."""


class ConnectorSyncLeaseLostError(RuntimeError):
    """Raised when a worker attempts to mutate work it no longer owns."""


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _encrypt_mapping(value: Mapping[str, Any]) -> str:
    try:
        payload = json.dumps(
            _plain_json(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "connector configuration and cursors must be JSON-compatible"
        ) from exc
    return encrypt_token(payload)


def _decrypt_mapping(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    decoded = json.loads(decrypt_token(value))
    if not isinstance(decoded, dict):
        raise ValueError("encrypted connector state must contain a JSON object")
    return {str(key): item for key, item in decoded.items()}


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _source_public(
    row: Mapping[str, Any] | RowMapping,
) -> dict[str, Any]:
    return {
        "source_id": str(row["source_id"]),
        "source_type": "connector",
        "provider": str(row["provider"]),
        "display_name": str(row["display_name"]),
        "external_ref": str(row["external_ref"]),
        "classification": str(row["classification"]),
        "enabled": bool(row["enabled"]),
        "schedule_seconds": (
            int(row["schedule_seconds"])
            if row.get("schedule_seconds") is not None
            else None
        ),
        "next_sync_at": _iso(row.get("next_sync_at")),
        "last_synced_at": _iso(row.get("last_synced_at")),
        "last_snapshot_id": (
            str(row["last_snapshot_id"])
            if row.get("last_snapshot_id") is not None
            else None
        ),
        "last_error": (
            str(row["last_error"])
            if row.get("last_error") is not None
            else None
        ),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _job_public(
    row: Mapping[str, Any] | RowMapping,
) -> dict[str, Any]:
    return {
        "job_id": str(row["job_id"]),
        "source_id": str(row["source_id"]),
        "status": str(row["status"]),
        "priority": int(row.get("priority") or 0),
        "attempt_count": int(row.get("attempt_count") or 0),
        "max_attempts": int(row.get("max_attempts") or 3),
        "records_changed": int(row.get("records_changed") or 0),
        "result_snapshot_id": (
            str(row["result_snapshot_id"])
            if row.get("result_snapshot_id") is not None
            else None
        ),
        "error_message": (
            str(row["error_message"])
            if row.get("error_message") is not None
            else None
        ),
        "created_at": _iso(row.get("created_at")),
        "started_at": _iso(row.get("started_at")),
        "completed_at": _iso(row.get("completed_at")),
    }


class PostgresConnectorSyncStore:
    """Own connector secrets, queue leases, and atomic snapshot activation."""

    def __init__(
        self,
        *,
        lease_seconds: int = 300,
        snapshot_store: PostgresSnapshotStore | None = None,
    ) -> None:
        if not 10 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 10 and 3600")
        self.lease_seconds = lease_seconds
        self.snapshot_store = snapshot_store or PostgresSnapshotStore()

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
    ) -> dict[str, Any]:
        encrypted_config = _encrypt_mapping(configuration)
        source_id = str(uuid4())
        with get_session() as session:
            row = session.execute(
                text(
                    """
                    INSERT INTO connector_sources (
                        source_id, user_id, indexed_by, is_public,
                        provider, display_name, external_ref,
                        classification, encrypted_config, enabled,
                        schedule_seconds, next_sync_at
                    ) VALUES (
                        :source_id, :user_id, :user_id, :is_public,
                        :provider, :display_name, :external_ref,
                        :classification, :encrypted_config, :enabled,
                        :schedule_seconds,
                        CASE
                            WHEN :enabled AND :schedule_seconds IS NOT NULL
                            THEN NOW() + (
                                :schedule_seconds * INTERVAL '1 second'
                            )
                            ELSE NULL
                        END
                    )
                    RETURNING *
                    """
                ),
                {
                    "source_id": source_id,
                    "user_id": user_id,
                    "is_public": (
                        classification is ContentClassification.PUBLIC
                    ),
                    "provider": provider,
                    "display_name": display_name,
                    "external_ref": external_ref,
                    "classification": classification.value,
                    "encrypted_config": encrypted_config,
                    "enabled": enabled,
                    "schedule_seconds": schedule_seconds,
                },
            ).mappings().one()
            session.execute(
                text(
                    """
                    INSERT INTO user_connector_sources (user_id, source_id)
                    VALUES (:user_id, :source_id)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"user_id": user_id, "source_id": source_id},
            )
        return _source_public(row)

    def list_sources(
        self,
        *,
        user_id: str,
        provider: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        with get_session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT source.*
                    FROM connector_sources source
                    JOIN user_connector_sources access
                      ON access.source_id = source.source_id
                     AND access.user_id = :user_id
                    WHERE (
                        :provider IS NULL OR source.provider = :provider
                    )
                    ORDER BY source.created_at DESC, source.source_id DESC
                    LIMIT :limit
                    """
                ),
                {
                    "user_id": user_id,
                    "provider": provider,
                    "limit": limit,
                },
            ).mappings().all()
        return [_source_public(row) for row in rows]

    def get_source(
        self,
        source_id: str,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        with get_session() as session:
            row = session.execute(
                text(
                    """
                    SELECT source.*
                    FROM connector_sources source
                    JOIN user_connector_sources access
                      ON access.source_id = source.source_id
                     AND access.user_id = :user_id
                    WHERE source.source_id = :source_id
                    """
                ),
                {"source_id": source_id, "user_id": user_id},
            ).mappings().first()
        if row is None:
            raise ConnectorSourceNotFoundError("Connector source not found.")
        return _source_public(row)

    def delete_source(self, source_id: str, *, user_id: str) -> bool:
        with get_session() as session:
            row = session.execute(
                text(
                    """
                    DELETE FROM connector_sources
                    WHERE source_id = :source_id
                      AND indexed_by = :user_id
                    RETURNING source_id
                    """
                ),
                {"source_id": source_id, "user_id": user_id},
            ).first()
        return row is not None

    def enqueue_sync(
        self,
        source_id: str,
        *,
        user_id: str,
        priority: int,
    ) -> dict[str, Any]:
        with get_session() as session:
            session.execute(
                text(
                    """
                    SELECT pg_advisory_xact_lock(
                        hashtextextended(:source_id, 0)
                    )
                    """
                ),
                {"source_id": source_id},
            )
            source = session.execute(
                text(
                    """
                    SELECT source_id, user_id, enabled
                    FROM connector_sources
                    WHERE source_id = :source_id
                      AND EXISTS (
                          SELECT 1 FROM user_connector_sources access
                          WHERE access.source_id = connector_sources.source_id
                            AND access.user_id = :user_id
                      )
                    FOR UPDATE
                    """
                ),
                {"source_id": source_id, "user_id": user_id},
            ).mappings().first()
            if source is None:
                raise ConnectorSourceNotFoundError(
                    "Connector source not found."
                )
            if not bool(source["enabled"]):
                raise ValueError("Connector source is disabled.")
            existing = session.execute(
                text(
                    """
                    SELECT * FROM connector_sync_jobs
                    WHERE source_id = :source_id
                      AND status IN ('pending', 'running')
                    """
                ),
                {"source_id": source_id},
            ).mappings().first()
            if existing is not None:
                return _job_public(existing)
            row = session.execute(
                text(
                    """
                    INSERT INTO connector_sync_jobs (
                        job_id, source_id, user_id, status, priority
                    ) VALUES (
                        :job_id, :source_id, :user_id, 'pending', :priority
                    )
                    RETURNING *
                    """
                ),
                {
                    "job_id": str(uuid4()),
                    "source_id": source_id,
                    "user_id": str(source["user_id"]),
                    "priority": priority,
                },
            ).mappings().one()
        return _job_public(row)

    def get_job(self, job_id: str, *, user_id: str) -> dict[str, Any]:
        with get_session() as session:
            row = session.execute(
                text(
                    """
                    SELECT * FROM connector_sync_jobs
                    WHERE job_id = :job_id AND user_id = :user_id
                    """
                ),
                {"job_id": job_id, "user_id": user_id},
            ).mappings().first()
        if row is None:
            raise ConnectorSyncJobNotFoundError(
                "Connector sync job not found."
            )
        return _job_public(row)

    def claim_next_job(
        self,
        *,
        worker_id: str,
    ) -> tuple[ConnectorSyncJobState, ConnectorSourceState] | None:
        with get_session() as session:
            session.execute(
                text(
                    """
                    UPDATE connector_sync_jobs
                    SET status = CASE
                            WHEN attempt_count < max_attempts
                            THEN 'pending'
                            ELSE 'failed'
                        END,
                        worker_id = NULL,
                        lease_expires_at = NULL,
                        error_message = CASE
                            WHEN attempt_count < max_attempts
                            THEN error_message
                            ELSE COALESCE(
                                error_message,
                                'Connector sync lease expired.'
                            )
                        END,
                        completed_at = CASE
                            WHEN attempt_count < max_attempts
                            THEN NULL
                            ELSE NOW()
                        END,
                        updated_at = NOW()
                    WHERE status = 'running'
                      AND lease_expires_at < NOW()
                    """
                )
            )
            row = session.execute(
                text(
                    """
                    WITH candidate AS (
                        SELECT job.job_id
                        FROM connector_sync_jobs job
                        JOIN connector_sources source
                          ON source.source_id = job.source_id
                        WHERE job.status = 'pending'
                          AND job.attempt_count < job.max_attempts
                          AND source.enabled IS TRUE
                        ORDER BY job.priority DESC, job.created_at, job.job_id
                        LIMIT 1
                        FOR UPDATE OF job SKIP LOCKED
                    )
                    UPDATE connector_sync_jobs job
                    SET status = 'running',
                        worker_id = :worker_id,
                        attempt_count = job.attempt_count + 1,
                        started_at = COALESCE(job.started_at, NOW()),
                        lease_expires_at = NOW() + (
                            :lease_seconds * INTERVAL '1 second'
                        ),
                        updated_at = NOW()
                    FROM candidate, connector_sources source
                    WHERE job.job_id = candidate.job_id
                      AND source.source_id = job.source_id
                    RETURNING job.*, source.provider, source.display_name,
                              source.external_ref, source.classification,
                              source.encrypted_config,
                              source.encrypted_cursor, source.enabled,
                              source.schedule_seconds
                    """
                ),
                {
                    "worker_id": worker_id,
                    "lease_seconds": self.lease_seconds,
                },
            ).mappings().first()
            if row is None:
                return None
            try:
                configuration = _decrypt_mapping(
                    str(row["encrypted_config"])
                )
                cursor = _decrypt_mapping(
                    str(row["encrypted_cursor"])
                    if row.get("encrypted_cursor") is not None
                    else None
                )
            except Exception:
                session.execute(
                    text(
                        """
                        UPDATE connector_sync_jobs
                        SET status = 'failed',
                            error_message = 'Connector state could not be decrypted.',
                            completed_at = NOW(),
                            worker_id = NULL,
                            lease_expires_at = NULL,
                            updated_at = NOW()
                        WHERE job_id = :job_id
                        """
                    ),
                    {"job_id": row["job_id"]},
                )
                session.execute(
                    text(
                        """
                        UPDATE connector_sources
                        SET last_error =
                                'Connector state could not be decrypted.',
                            updated_at = NOW()
                        WHERE source_id = :source_id
                        """
                    ),
                    {"source_id": row["source_id"]},
                )
                return None
        assert configuration is not None
        job = ConnectorSyncJobState(
            job_id=str(row["job_id"]),
            source_id=str(row["source_id"]),
            user_id=str(row["user_id"]),
            status=str(row["status"]),
            worker_id=(
                str(row["worker_id"])
                if row.get("worker_id") is not None
                else None
            ),
            attempt_count=int(row["attempt_count"]),
        )
        source = ConnectorSourceState(
            source_id=str(row["source_id"]),
            user_id=str(row["user_id"]),
            provider=str(row["provider"]),
            display_name=str(row["display_name"]),
            external_ref=str(row["external_ref"]),
            classification=ContentClassification(
                str(row["classification"])
            ),
            configuration=configuration,
            cursor=cursor,
            enabled=bool(row["enabled"]),
            schedule_seconds=(
                int(row["schedule_seconds"])
                if row.get("schedule_seconds") is not None
                else None
            ),
        )
        return job, source

    @staticmethod
    def _current_items(
        session: Any,
        source_id: str,
    ) -> tuple[dict[str, dict[str, Any]], str | None]:
        head = session.execute(
            text(
                """
                SELECT head.snapshot_id
                FROM source_snapshot_heads head
                WHERE head.source_type = 'connector'
                  AND head.source_id = :source_id
                """
            ),
            {"source_id": source_id},
        ).mappings().first()
        if head is None:
            return {}, None
        rows = session.execute(
            text(
                """
                SELECT origin_item_id, locator, content, token_count, metadata
                FROM source_snapshot_items
                WHERE snapshot_id = :snapshot_id
                ORDER BY ordinal
                """
            ),
            {"snapshot_id": head["snapshot_id"]},
        ).mappings().all()
        items: dict[str, dict[str, Any]] = {}
        for row in rows:
            metadata = dict(row.get("metadata") or {})
            external_id = str(
                metadata.get("connector_external_id")
                or row["origin_item_id"]
            )
            items[external_id] = {
                "locator": str(row["locator"]),
                "content": str(row["content"]),
                "token_count": (
                    int(row["token_count"])
                    if row.get("token_count") is not None
                    else None
                ),
                "metadata": metadata,
            }
        return items, str(head["snapshot_id"])

    def apply_sync_page(
        self,
        job: ConnectorSyncJobState,
        source: ConnectorSourceState,
        response: ConnectorSyncResponse,
    ) -> dict[str, Any]:
        encrypted_cursor = (
            _encrypt_mapping(response.next_cursor)
            if response.next_cursor is not None
            else None
        )
        with get_session() as session:
            lease = session.execute(
                text(
                    """
                    SELECT job.status, job.worker_id, job.attempt_count,
                           source.provider, source.display_name,
                           source.external_ref, source.classification,
                           source.user_id, source.schedule_seconds
                    FROM connector_sync_jobs job
                    JOIN connector_sources source
                      ON source.source_id = job.source_id
                    WHERE job.job_id = :job_id
                      AND job.source_id = :source_id
                    FOR UPDATE OF job, source
                    """
                ),
                {"job_id": job.job_id, "source_id": source.source_id},
            ).mappings().first()
            if (
                lease is None
                or lease["status"] != "running"
                or lease["worker_id"] != job.worker_id
                or int(lease["attempt_count"]) != job.attempt_count
            ):
                raise ConnectorSyncLeaseLostError(
                    f"Connector sync lease lost for job {job.job_id}."
                )

            current, current_snapshot_id = self._current_items(
                session,
                source.source_id,
            )
            for record in response.records:
                principals = record.accessible_principals
                revoked = (
                    principals is not None
                    and source.user_id not in principals
                    and "*" not in principals
                )
                session.execute(
                    text(
                        """
                        INSERT INTO connector_record_access (
                            source_id, external_id_hash, external_id,
                            principals, revoked
                        ) VALUES (
                            :source_id, :external_id_hash, :external_id,
                            CAST(:principals AS JSONB), :revoked
                        )
                        ON CONFLICT (source_id, external_id_hash) DO UPDATE
                        SET external_id = EXCLUDED.external_id,
                            principals = EXCLUDED.principals,
                            revoked = EXCLUDED.revoked,
                            updated_at = NOW()
                        """
                    ),
                    {
                        "source_id": source.source_id,
                        "external_id_hash": hashlib.sha256(
                            record.external_id.encode("utf-8")
                        ).hexdigest(),
                        "external_id": record.external_id,
                        "principals": (
                            json.dumps(list(principals))
                            if principals is not None
                            else None
                        ),
                        "revoked": bool(record.deleted or revoked),
                    },
                )
                if record.deleted or revoked:
                    current.pop(record.external_id, None)
                    continue
                metadata = dict(record.to_dict()["metadata"])
                metadata["connector_external_id"] = record.external_id
                current[record.external_id] = {
                    "locator": record.locator,
                    "content": record.content,
                    "token_count": len(record.content.split()),
                    "metadata": metadata,
                }

            snapshot_id = current_snapshot_id
            if response.records or snapshot_id is None:
                items = tuple(
                    SnapshotItem(
                        ordinal=ordinal,
                        origin_item_id=str(
                            uuid5(
                                NAMESPACE_URL,
                                (
                                    f"delphi:connector:{source.source_id}:"
                                    f"{external_id}"
                                ),
                            )
                        ),
                        locator=str(item["locator"]),
                        content=str(item["content"]),
                        token_count=(
                            int(item["token_count"])
                            if item.get("token_count") is not None
                            else None
                        ),
                        metadata=dict(item["metadata"]),
                    )
                    for ordinal, (external_id, item) in enumerate(
                        sorted(current.items())
                    )
                )
                content_hash = compute_snapshot_content_hash(items)
                empty_fingerprint = hashlib.sha256(b"").hexdigest()
                candidate = SourceSnapshot(
                    snapshot_id=str(uuid4()),
                    source_id=source.source_id,
                    source_type=SnapshotSourceType.CONNECTOR,
                    version=f"content:{content_hash[:16]}",
                    content_hash=content_hash,
                    external_ref=source.external_ref,
                    display_name=source.display_name,
                    classification=source.classification,
                    item_count=len(items),
                    total_tokens=sum(
                        item.token_count or 0 for item in items
                    ),
                    embedding_model="none",
                    embedding_fingerprint=empty_fingerprint,
                    vector_count=0,
                    vectors_complete=not items,
                    created_by=source.user_id,
                    manifest={
                        "provider": source.provider,
                        "records_changed": len(response.records),
                    },
                )
                published, created = self.snapshot_store.put_snapshot(
                    session,
                    candidate,
                    items,
                )
                if created:
                    published = self.snapshot_store.seal_snapshot(
                        session,
                        published.snapshot_id,
                    )
                self.snapshot_store.set_head(
                    session,
                    SnapshotSourceType.CONNECTOR,
                    source.source_id,
                    published.snapshot_id,
                )
                snapshot_id = published.snapshot_id

            assert snapshot_id is not None
            session.execute(
                text(
                    """
                    UPDATE connector_sources
                    SET encrypted_cursor = :encrypted_cursor,
                        last_synced_at = NOW(),
                        last_snapshot_id = :snapshot_id,
                        last_error = NULL,
                        next_sync_at = CASE
                            WHEN :has_more THEN NOW()
                            WHEN enabled AND schedule_seconds IS NOT NULL
                            THEN NOW() + (
                                schedule_seconds * INTERVAL '1 second'
                            )
                            ELSE NULL
                        END,
                        updated_at = NOW()
                    WHERE source_id = :source_id
                    """
                ),
                {
                    "source_id": source.source_id,
                    "encrypted_cursor": encrypted_cursor,
                    "snapshot_id": snapshot_id,
                    "has_more": response.has_more,
                },
            )
            row = session.execute(
                text(
                    """
                    UPDATE connector_sync_jobs
                    SET status = CASE
                            WHEN :has_more THEN 'pending'
                            ELSE 'completed'
                        END,
                        records_changed =
                            records_changed + :records_changed,
                        attempt_count = CASE
                            WHEN :has_more THEN 0
                            ELSE attempt_count
                        END,
                        result_snapshot_id = :snapshot_id,
                        error_message = NULL,
                        worker_id = NULL,
                        lease_expires_at = NULL,
                        completed_at = CASE
                            WHEN :has_more THEN NULL
                            ELSE NOW()
                        END,
                        updated_at = NOW()
                    WHERE job_id = :job_id
                      AND status = 'running'
                      AND worker_id = :worker_id
                      AND attempt_count = :attempt_count
                    RETURNING *
                    """
                ),
                {
                    "job_id": job.job_id,
                    "worker_id": job.worker_id,
                    "attempt_count": job.attempt_count,
                    "has_more": response.has_more,
                    "records_changed": len(response.records),
                    "snapshot_id": snapshot_id,
                },
            ).mappings().first()
            if row is None:
                raise ConnectorSyncLeaseLostError(
                    f"Connector sync lease lost for job {job.job_id}."
                )
        result = _job_public(row)
        result["snapshot_id"] = snapshot_id
        return result

    def fail_job(
        self,
        job: ConnectorSyncJobState,
        *,
        error_message: str,
        retryable: bool,
    ) -> str | None:
        safe_error = error_message[:2000]
        with get_session() as session:
            row = session.execute(
                text(
                    """
                    UPDATE connector_sync_jobs
                    SET status = CASE
                            WHEN :retryable
                             AND attempt_count < max_attempts
                            THEN 'pending'
                            ELSE 'failed'
                        END,
                        error_message = :error_message,
                        completed_at = CASE
                            WHEN :retryable
                             AND attempt_count < max_attempts
                            THEN NULL
                            ELSE NOW()
                        END,
                        worker_id = NULL,
                        lease_expires_at = NULL,
                        updated_at = NOW()
                    WHERE job_id = :job_id
                      AND status = 'running'
                      AND worker_id = :worker_id
                      AND attempt_count = :attempt_count
                    RETURNING source_id, status
                    """
                ),
                {
                    "job_id": job.job_id,
                    "worker_id": job.worker_id,
                    "attempt_count": job.attempt_count,
                    "error_message": safe_error,
                    "retryable": retryable,
                },
            ).mappings().first()
            if row is None:
                return None
            session.execute(
                text(
                    """
                    UPDATE connector_sources
                    SET last_error = :error_message,
                        next_sync_at = CASE
                            WHEN :job_status = 'pending'
                            THEN next_sync_at
                            WHEN enabled AND schedule_seconds IS NOT NULL
                            THEN NOW() + (
                                schedule_seconds * INTERVAL '1 second'
                            )
                            ELSE NULL
                        END,
                        updated_at = NOW()
                    WHERE source_id = :source_id
                    """
                ),
                {
                    "source_id": row["source_id"],
                    "error_message": safe_error,
                    "job_status": row["status"],
                },
            )
        return str(row["status"])

    def enqueue_due(self, *, limit: int) -> int:
        with get_session() as session:
            rows = session.execute(
                text(
                    """
                    WITH due AS (
                        SELECT source.source_id, source.user_id,
                               source.schedule_seconds
                        FROM connector_sources source
                        WHERE source.enabled IS TRUE
                          AND source.schedule_seconds IS NOT NULL
                          AND source.next_sync_at <= NOW()
                          AND NOT EXISTS (
                              SELECT 1 FROM connector_sync_jobs job
                              WHERE job.source_id = source.source_id
                                AND job.status IN ('pending', 'running')
                          )
                        ORDER BY source.next_sync_at, source.source_id
                        LIMIT :limit
                        FOR UPDATE SKIP LOCKED
                    ),
                    advanced AS (
                        UPDATE connector_sources source
                        SET next_sync_at = NOW() + (
                                due.schedule_seconds
                                * INTERVAL '1 second'
                            ),
                            updated_at = NOW()
                        FROM due
                        WHERE source.source_id = due.source_id
                        RETURNING source.source_id, source.user_id
                    )
                    INSERT INTO connector_sync_jobs (
                        job_id, source_id, user_id, status, priority
                    )
                    SELECT gen_random_uuid()::text, source_id, user_id,
                           'pending', 0
                    FROM advanced
                    RETURNING job_id
                    """
                ),
                {"limit": limit},
            ).all()
        return len(rows)
