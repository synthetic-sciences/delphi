"""Publication and access services for immutable source snapshots."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from synsc.database.connection import get_session
from synsc.providers.contracts import (
    CancellationToken,
    ContentClassification,
)
from synsc.snapshots.contracts import (
    SnapshotItem,
    SnapshotSourceType,
    SourceSnapshot,
    compute_snapshot_content_hash,
)


class SnapshotError(RuntimeError):
    """Base class for safe snapshot-service failures."""


class SnapshotSourceNotFoundError(SnapshotError):
    """Raised when the requested logical source does not exist."""


class SnapshotNotFoundError(SnapshotError):
    """Raised when the requested snapshot does not exist."""


class SnapshotAccessDeniedError(SnapshotError):
    """Raised when a caller cannot access source or snapshot content."""


@dataclass(frozen=True)
class SnapshotMaterial:
    """Normalized source metadata and ordered items ready for publication."""

    source_id: str
    source_type: SnapshotSourceType
    version: str | None
    external_ref: str
    display_name: str
    classification: ContentClassification
    embedding_model: str
    embedding_fingerprint: str
    vector_count: int
    created_by: str | None
    manifest: Mapping[str, Any]
    items: tuple[SnapshotItem, ...]


class SnapshotStore(Protocol):
    """Persistence boundary used by snapshot publication orchestration."""

    def prepare_capture(self, session: Session) -> None: ...

    def load_material(
        self,
        session: Session,
        source_type: SnapshotSourceType,
        source_id: str,
        user_id: str | None,
    ) -> SnapshotMaterial: ...

    def put_snapshot(
        self,
        session: Session,
        snapshot: SourceSnapshot,
        items: tuple[SnapshotItem, ...],
    ) -> tuple[SourceSnapshot, bool]: ...

    def copy_embeddings(
        self,
        session: Session,
        snapshot_id: str,
        source_type: SnapshotSourceType,
    ) -> None: ...

    def set_head(
        self,
        session: Session,
        source_type: SnapshotSourceType,
        source_id: str,
        snapshot_id: str,
    ) -> None: ...

    def seal_snapshot(
        self,
        session: Session,
        snapshot_id: str,
    ) -> SourceSnapshot: ...

    def get_snapshot(
        self,
        session: Session,
        snapshot_id: str,
    ) -> SourceSnapshot | None: ...

    def resolve_snapshot(
        self,
        session: Session,
        source_type: SnapshotSourceType,
        source_id: str,
        version: str | None,
    ) -> SourceSnapshot | None: ...

    def can_access_snapshot(
        self,
        session: Session,
        snapshot: SourceSnapshot,
        user_id: str | None,
    ) -> bool: ...

    def get_search_snapshots(
        self,
        session: Session,
        snapshot_ids: tuple[str, ...],
        user_id: str | None,
        *,
        timeout_ms: int,
        cancellation: CancellationToken,
    ) -> list[tuple[SourceSnapshot, bool]]: ...

    def list_snapshots(
        self,
        session: Session,
        *,
        user_id: str | None,
        source_type: SnapshotSourceType | None,
        source_id: str | None,
        limit: int,
    ) -> list[SourceSnapshot]: ...

    def list_items(
        self,
        session: Session,
        snapshot: SourceSnapshot,
        *,
        user_id: str | None,
        offset: int,
        limit: int,
        locator_prefix: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def search_items(
        self,
        session: Session,
        snapshot_ids: tuple[str, ...],
        query: str,
        limit: int,
        user_id: str | None,
        *,
        timeout_ms: int,
        source_types: tuple[SnapshotSourceType, ...],
    ) -> list[dict[str, Any]]: ...


_SessionFactory = Callable[[], AbstractContextManager[Session]]
_RowData = Mapping[str, Any] | RowMapping
_SnapshotSearchResults = list[dict[str, Any]]
_CAPTURE_RETRY_SQLSTATES = frozenset({"40001", "40P01"})


def _is_retryable_capture_error(exc: DBAPIError) -> bool:
    code = getattr(exc.orig, "sqlstate", None) or getattr(
        exc.orig,
        "pgcode",
        None,
    )
    return code in _CAPTURE_RETRY_SQLSTATES


def _classification(value: object, *, is_public: bool) -> ContentClassification:
    if isinstance(value, str):
        try:
            return ContentClassification(value)
        except ValueError:
            pass
    return (
        ContentClassification.PUBLIC
        if is_public
        else ContentClassification.PRIVATE
    )


def _snapshot_from_mapping(row: _RowData) -> SourceSnapshot:
    manifest = row.get("manifest") or {}
    if isinstance(manifest, str):
        manifest = json.loads(manifest)
    return SourceSnapshot(
        snapshot_id=str(row["snapshot_id"]),
        source_id=str(row["source_id"]),
        source_type=SnapshotSourceType(str(row["source_type"])),
        version=str(row["version"]),
        content_hash=str(row["content_hash"]),
        external_ref=str(row["external_ref"]),
        display_name=str(row["display_name"]),
        classification=ContentClassification(str(row["classification"])),
        item_count=int(row["item_count"]),
        total_tokens=int(row["total_tokens"]),
        embedding_model=(
            str(row["embedding_model"])
            if row.get("embedding_model") is not None
            else "unknown"
        ),
        embedding_fingerprint=str(row["embedding_fingerprint"]),
        vector_count=int(row["vector_count"]),
        vectors_complete=bool(row["vectors_complete"]),
        created_by=(
            str(row["created_by"])
            if row.get("created_by") is not None
            else None
        ),
        manifest=manifest,
        created_at=(
            row["created_at"]
            if isinstance(row.get("created_at"), datetime)
            else None
        ),
        sealed_at=(
            row["sealed_at"]
            if isinstance(row.get("sealed_at"), datetime)
            else None
        ),
    )


class PostgresSnapshotStore:
    """PostgreSQL implementation that copies source chunks and vectors."""

    _ACCESS_TABLES = {
        "repo": (
            "repositories",
            "repo_id",
            "user_repositories",
            "repo_id",
        ),
        "paper": (
            "papers",
            "paper_id",
            "user_papers",
            "paper_id",
        ),
        "dataset": (
            "datasets",
            "dataset_id",
            "user_datasets",
            "dataset_id",
        ),
        "docs": (
            "documentation_sources",
            "docs_id",
            "user_documentation_sources",
            "docs_id",
        ),
        "connector": (
            "connector_sources",
            "source_id",
            "user_connector_sources",
            "source_id",
        ),
    }

    @classmethod
    def _snapshot_access_predicate(
        cls,
        alias: str = "snapshot",
        source_types: tuple[SnapshotSourceType, ...] | None = None,
    ) -> str:
        """Build one ACL predicate from fixed table identifiers."""

        branches = []
        selected = (
            tuple(source_type.value for source_type in source_types)
            if source_types is not None
            else tuple(cls._ACCESS_TABLES)
        )
        for (
            source_type,
            (
                source_table,
                source_id_column,
                access_table,
                access_id_column,
            ),
        ) in (
            (source_type, cls._ACCESS_TABLES[source_type])
            for source_type in selected
        ):
            branches.append(
                f"""
                (
                    {alias}.source_type = '{source_type}'
                    AND EXISTS (
                        SELECT 1 FROM {source_table} current_source
                        WHERE CAST(
                                  current_source.{source_id_column} AS TEXT
                              ) = {alias}.source_id
                          AND (
                              current_source.is_public IS TRUE
                              OR (
                                  :user_id IS NOT NULL
                                  AND (
                                      CAST(
                                          current_source.indexed_by AS TEXT
                                      ) = :user_id
                                      OR EXISTS (
                                          SELECT 1 FROM {access_table} access
                                          WHERE CAST(
                                                    access.user_id AS TEXT
                                                ) = :user_id
                                            AND CAST(
                                                    access.{access_id_column}
                                                    AS TEXT
                                                ) = {alias}.source_id
                                      )
                                  )
                              )
                          )
                    )
                )
                """
            )
        return "(" + " OR ".join(branches) + ")"

    _METADATA_QUERIES = {
        SnapshotSourceType.REPOSITORY: """
            SELECT r.repo_id AS source_id, r.commit_sha AS version,
                   r.url AS external_ref,
                   (r.owner || '/' || r.name) AS display_name,
                   r.visibility, r.is_public, r.embedding_model,
                   r.indexed_by AS created_by,
                   r.branch, r.files_count, r.chunks_count,
                   r.symbols_count, r.total_tokens, r.deep_indexed,
                   EXISTS (
                       SELECT 1 FROM user_repositories ur
                       WHERE ur.repo_id = r.repo_id
                         AND ur.user_id = :user_id
                   ) AS has_link
            FROM repositories r
            WHERE r.repo_id = :source_id
            FOR UPDATE OF r
        """,
        SnapshotSourceType.PAPER: """
            SELECT p.paper_id AS source_id, p.pdf_hash AS version,
                   COALESCE(p.pdf_url, p.arxiv_id, p.pdf_hash) AS external_ref,
                   p.title AS display_name,
                   p.visibility, p.is_public, p.embedding_model,
                   p.indexed_by AS created_by,
                   p.arxiv_id, p.pdf_hash, p.published_date,
                   p.page_count, p.chunk_count, p.citation_count,
                   EXISTS (
                       SELECT 1 FROM user_papers up
                       WHERE up.paper_id = p.paper_id
                         AND up.user_id = :user_id
                   ) AS has_link
            FROM papers p
            WHERE p.paper_id = :source_id
            FOR UPDATE OF p
        """,
        SnapshotSourceType.DATASET: """
            SELECT d.dataset_id AS source_id, NULL AS version,
                   d.hf_id AS external_ref,
                   COALESCE(d.name, d.hf_id) AS display_name,
                   d.visibility, d.is_public, d.embedding_model,
                   d.indexed_by AS created_by,
                   d.hf_id, d.license, d.downloads, d.likes,
                   d.dataset_size_bytes, d.chunk_count,
                   EXISTS (
                       SELECT 1 FROM user_datasets ud
                       WHERE ud.dataset_id = d.dataset_id
                         AND ud.user_id = :user_id
                   ) AS has_link
            FROM datasets d
            WHERE d.dataset_id = :source_id
            FOR UPDATE OF d
        """,
        SnapshotSourceType.DOCUMENTATION: """
            SELECT d.docs_id AS source_id, d.version AS version,
                   d.url AS external_ref,
                   COALESCE(d.display_name, d.url) AS display_name,
                   d.visibility, d.is_public, d.embedding_model,
                   d.indexed_by AS created_by,
                   d.url, d.sitemap_url, d.pages_count, d.chunks_count,
                   EXISTS (
                       SELECT 1 FROM user_documentation_sources ud
                       WHERE ud.docs_id = d.docs_id
                         AND ud.user_id = :user_id
                   ) AS has_link
            FROM documentation_sources d
            WHERE d.docs_id = :source_id
            FOR UPDATE OF d
        """,
    }

    _ITEM_QUERIES = {
        SnapshotSourceType.REPOSITORY: """
            SELECT c.chunk_id AS origin_item_id, f.file_path,
                   c.chunk_index, c.content, c.token_count,
                   c.start_line, c.end_line, c.chunk_type, c.language
            FROM code_chunks c
            JOIN repository_files f ON f.file_id = c.file_id
            WHERE c.repo_id = :source_id
            ORDER BY f.file_path, c.chunk_index, c.chunk_id
        """,
        SnapshotSourceType.PAPER: """
            SELECT c.chunk_id AS origin_item_id, c.chunk_index,
                   c.content, c.token_count, c.section_title,
                   c.page_number, c.chunk_type
            FROM paper_chunks c
            WHERE c.paper_id = :source_id
            ORDER BY c.chunk_index, c.chunk_id
        """,
        SnapshotSourceType.DATASET: """
            SELECT c.chunk_id AS origin_item_id, c.chunk_index,
                   c.content, c.token_count, c.section_title, c.chunk_type
            FROM dataset_chunks c
            WHERE c.dataset_id = :source_id
            ORDER BY c.chunk_index, c.chunk_id
        """,
        SnapshotSourceType.DOCUMENTATION: """
            SELECT c.chunk_id AS origin_item_id, c.chunk_index,
                   c.content, c.token_count, c.page_url, c.heading
            FROM documentation_chunks c
            WHERE c.docs_id = :source_id
            ORDER BY c.page_url, c.chunk_index, c.chunk_id
        """,
    }

    _EMBEDDING_TABLES = {
        SnapshotSourceType.REPOSITORY: "chunk_embeddings",
        SnapshotSourceType.PAPER: "paper_chunk_embeddings",
        SnapshotSourceType.DATASET: "dataset_chunk_embeddings",
        SnapshotSourceType.DOCUMENTATION: "documentation_chunk_embeddings",
    }

    _VECTOR_SOURCES = {
        SnapshotSourceType.REPOSITORY: ("chunk_embeddings", "repo_id"),
        SnapshotSourceType.PAPER: ("paper_chunk_embeddings", "paper_id"),
        SnapshotSourceType.DATASET: ("dataset_chunk_embeddings", "dataset_id"),
        SnapshotSourceType.DOCUMENTATION: (
            "documentation_chunk_embeddings",
            "docs_id",
        ),
    }

    _ACCESS_QUERIES = {
        SnapshotSourceType.REPOSITORY: """
            SELECT r.is_public, r.visibility,
                   CAST(r.indexed_by AS TEXT) AS owner_id,
                   EXISTS (
                       SELECT 1 FROM user_repositories access
                       WHERE CAST(access.user_id AS TEXT) = :user_id
                         AND CAST(access.repo_id AS TEXT)
                             = CAST(r.repo_id AS TEXT)
                   ) AS has_link
            FROM repositories r
            WHERE CAST(r.repo_id AS TEXT) = :source_id
        """,
        SnapshotSourceType.PAPER: """
            SELECT p.is_public, p.visibility,
                   CAST(p.indexed_by AS TEXT) AS owner_id,
                   EXISTS (
                       SELECT 1 FROM user_papers access
                       WHERE CAST(access.user_id AS TEXT) = :user_id
                         AND CAST(access.paper_id AS TEXT)
                             = CAST(p.paper_id AS TEXT)
                   ) AS has_link
            FROM papers p
            WHERE CAST(p.paper_id AS TEXT) = :source_id
        """,
        SnapshotSourceType.DATASET: """
            SELECT d.is_public, d.visibility,
                   CAST(d.indexed_by AS TEXT) AS owner_id,
                   EXISTS (
                       SELECT 1 FROM user_datasets access
                       WHERE CAST(access.user_id AS TEXT) = :user_id
                         AND CAST(access.dataset_id AS TEXT)
                             = CAST(d.dataset_id AS TEXT)
                   ) AS has_link
            FROM datasets d
            WHERE CAST(d.dataset_id AS TEXT) = :source_id
        """,
        SnapshotSourceType.DOCUMENTATION: """
            SELECT d.is_public, d.visibility,
                   CAST(d.indexed_by AS TEXT) AS owner_id,
                   EXISTS (
                       SELECT 1
                       FROM user_documentation_sources access
                       WHERE CAST(access.user_id AS TEXT) = :user_id
                         AND CAST(access.docs_id AS TEXT)
                             = CAST(d.docs_id AS TEXT)
                   ) AS has_link
            FROM documentation_sources d
            WHERE CAST(d.docs_id AS TEXT) = :source_id
        """,
        SnapshotSourceType.CONNECTOR: """
            SELECT c.is_public, c.classification AS visibility,
                   CAST(c.indexed_by AS TEXT) AS owner_id,
                   EXISTS (
                       SELECT 1
                       FROM user_connector_sources access
                       WHERE CAST(access.user_id AS TEXT) = :user_id
                         AND CAST(access.source_id AS TEXT)
                             = CAST(c.source_id AS TEXT)
                   ) AS has_link
            FROM connector_sources c
            WHERE CAST(c.source_id AS TEXT) = :source_id
        """,
    }

    def prepare_capture(self, session: Session) -> None:
        """Pin all source reads in this capture to one MVCC snapshot."""

        session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        )

    @staticmethod
    def _manifest(
        source_type: SnapshotSourceType,
        row: _RowData,
    ) -> dict[str, Any]:
        if source_type is SnapshotSourceType.REPOSITORY:
            return {
                "branch": row.get("branch"),
                "files_count": row.get("files_count") or 0,
                "chunks_count": row.get("chunks_count") or 0,
                "symbols_count": row.get("symbols_count") or 0,
                "total_tokens": row.get("total_tokens") or 0,
                "deep_indexed": bool(row.get("deep_indexed")),
            }
        if source_type is SnapshotSourceType.PAPER:
            return {
                "arxiv_id": row.get("arxiv_id"),
                "pdf_hash": row.get("pdf_hash"),
                "published_date": row.get("published_date"),
                "page_count": row.get("page_count") or 0,
                "chunk_count": row.get("chunk_count") or 0,
                "citation_count": row.get("citation_count") or 0,
            }
        if source_type is SnapshotSourceType.DATASET:
            return {
                "hf_id": row.get("hf_id"),
                "license": row.get("license"),
                "downloads": row.get("downloads") or 0,
                "likes": row.get("likes") or 0,
                "dataset_size_bytes": row.get("dataset_size_bytes") or 0,
                "chunk_count": row.get("chunk_count") or 0,
            }
        return {
            "url": row.get("url"),
            "sitemap_url": row.get("sitemap_url"),
            "pages_count": row.get("pages_count") or 0,
            "chunks_count": row.get("chunks_count") or 0,
        }

    @staticmethod
    def _snapshot_item(
        source_type: SnapshotSourceType,
        ordinal: int,
        row: _RowData,
    ) -> SnapshotItem:
        if source_type is SnapshotSourceType.REPOSITORY:
            locator = (
                f"{row['file_path']}:{row['start_line']}-{row['end_line']}"
            )
            metadata = {
                "file_path": row["file_path"],
                "chunk_index": row["chunk_index"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "chunk_type": row.get("chunk_type"),
                "language": row.get("language"),
            }
        elif source_type is SnapshotSourceType.PAPER:
            section = row.get("section_title") or "paper"
            page = row.get("page_number")
            locator = f"{section}#page={page}" if page is not None else section
            metadata = {
                "chunk_index": row["chunk_index"],
                "section_title": row.get("section_title"),
                "page_number": page,
                "chunk_type": row.get("chunk_type"),
            }
        elif source_type is SnapshotSourceType.DATASET:
            locator = row.get("section_title") or (
                f"dataset-chunk-{row['chunk_index']}"
            )
            metadata = {
                "chunk_index": row["chunk_index"],
                "section_title": row.get("section_title"),
                "chunk_type": row.get("chunk_type"),
            }
        else:
            heading = row.get("heading")
            locator = (
                f"{row['page_url']}#{heading}"
                if heading
                else str(row["page_url"])
            )
            metadata = {
                "chunk_index": row["chunk_index"],
                "page_url": row["page_url"],
                "heading": heading,
            }
        return SnapshotItem(
            ordinal=ordinal,
            origin_item_id=str(row["origin_item_id"]),
            locator=str(locator),
            content=str(row["content"]),
            token_count=(
                int(row["token_count"])
                if row.get("token_count") is not None
                else None
            ),
            metadata=metadata,
        )

    def _vector_state(
        self,
        session: Session,
        source_type: SnapshotSourceType,
        source_id: str,
    ) -> tuple[int, str]:
        table, source_column = self._VECTOR_SOURCES[source_type]
        row = session.execute(
            text(
                f"""
                SELECT
                    COUNT(*)::INTEGER AS vector_count,
                    encode(
                        digest(
                            COALESCE(
                                string_agg(
                                    encode(
                                        digest(
                                            CAST(chunk_id AS TEXT)
                                            || ':' || embedding::text,
                                            'sha256'
                                        ),
                                        'hex'
                                    ),
                                    '' ORDER BY CAST(chunk_id AS TEXT)
                                ),
                                ''
                            ),
                            'sha256'
                        ),
                        'hex'
                    ) AS embedding_fingerprint
                FROM {table}
                WHERE {source_column} = :source_id
                """
            ),
            {"source_id": source_id},
        ).mappings().one()
        fingerprint = row.get("embedding_fingerprint")
        return (
            int(row.get("vector_count") or 0),
            (
                str(fingerprint)
                if fingerprint is not None
                else hashlib.sha256(b"").hexdigest()
            ),
        )

    def load_material(
        self,
        session: Session,
        source_type: SnapshotSourceType,
        source_id: str,
        user_id: str | None,
    ) -> SnapshotMaterial:
        normalized_user_id = str(user_id) if user_id is not None else None
        row = session.execute(
            text(self._METADATA_QUERIES[source_type]),
            {"source_id": source_id, "user_id": normalized_user_id},
        ).mappings().first()
        if row is None:
            raise SnapshotSourceNotFoundError("Source not found.")
        is_public = bool(row.get("is_public"))
        created_by = (
            str(row["created_by"])
            if row.get("created_by") is not None
            else None
        )
        if not (
            is_public
            or (
                normalized_user_id is not None
                and (
                    created_by == normalized_user_id
                    or bool(row.get("has_link"))
                )
            )
        ):
            raise SnapshotAccessDeniedError("Source not found.")

        item_rows = session.execute(
            text(self._ITEM_QUERIES[source_type]),
            {"source_id": source_id},
        ).mappings().all()
        items = tuple(
            self._snapshot_item(source_type, ordinal, item_row)
            for ordinal, item_row in enumerate(item_rows)
        )
        vector_count, embedding_fingerprint = self._vector_state(
            session,
            source_type,
            source_id,
        )
        embedding_model = row.get("embedding_model")
        if embedding_model is None:
            embedding_model = "unknown"
        return SnapshotMaterial(
            source_id=str(row["source_id"]),
            source_type=source_type,
            version=(
                str(row["version"])
                if row.get("version") is not None
                else None
            ),
            external_ref=str(row["external_ref"]),
            display_name=str(row["display_name"]),
            classification=_classification(
                row.get("visibility"),
                is_public=is_public,
            ),
            embedding_model=str(embedding_model),
            embedding_fingerprint=embedding_fingerprint,
            vector_count=vector_count,
            created_by=created_by,
            manifest=self._manifest(source_type, row),
            items=items,
        )

    def put_snapshot(
        self,
        session: Session,
        snapshot: SourceSnapshot,
        items: tuple[SnapshotItem, ...],
    ) -> tuple[SourceSnapshot, bool]:
        public = snapshot.to_dict(include_owner=True)
        inserted = session.execute(
            text(
                """
                INSERT INTO source_snapshots (
                    snapshot_id, source_id, source_type, version,
                    content_hash, external_ref, display_name, classification,
                    item_count, total_tokens, embedding_model,
                    embedding_fingerprint, vector_count, vectors_complete,
                    created_by, manifest
                ) VALUES (
                    :snapshot_id, :source_id, :source_type, :version,
                    :content_hash, :external_ref, :display_name,
                    :classification, :item_count, :total_tokens,
                    :embedding_model, :embedding_fingerprint, :vector_count,
                    :vectors_complete, :created_by, CAST(:manifest AS JSONB)
                )
                ON CONFLICT (
                    source_type, source_id, version, content_hash,
                    embedding_model, embedding_fingerprint
                ) DO NOTHING
                RETURNING *
                """
            ),
            {
                **public,
                "source_type": snapshot.source_type.value,
                "classification": snapshot.classification.value,
                "manifest": json.dumps(public["manifest"], sort_keys=True),
            },
        ).mappings().first()
        if inserted is None:
            existing = session.execute(
                text(
                    """
                    SELECT * FROM source_snapshots
                    WHERE source_type = :source_type
                      AND source_id = :source_id
                      AND version = :version
                      AND content_hash = :content_hash
                      AND embedding_model = :embedding_model
                      AND embedding_fingerprint = :embedding_fingerprint
                    """
                ),
                {
                    "source_type": snapshot.source_type.value,
                    "source_id": snapshot.source_id,
                    "version": snapshot.version,
                    "content_hash": snapshot.content_hash,
                    "embedding_model": snapshot.embedding_model,
                    "embedding_fingerprint": (
                        snapshot.embedding_fingerprint
                    ),
                },
            ).mappings().one()
            return _snapshot_from_mapping(existing), False

        published = _snapshot_from_mapping(inserted)
        if items:
            session.execute(
                text(
                    """
                    INSERT INTO source_snapshot_items (
                        item_id, snapshot_id, ordinal, origin_item_id,
                        locator, content_hash, content, token_count, metadata
                    ) VALUES (
                        :item_id, :snapshot_id, :ordinal, :origin_item_id,
                        :locator, :content_hash, :content, :token_count,
                        CAST(:metadata AS JSONB)
                    )
                    """
                ),
                [
                    {
                        "item_id": str(uuid4()),
                        "snapshot_id": published.snapshot_id,
                        "ordinal": item.ordinal,
                        "origin_item_id": item.origin_item_id,
                        "locator": item.locator,
                        "content_hash": item.content_hash,
                        "content": item.content,
                        "token_count": item.token_count,
                        "metadata": json.dumps(
                            item.to_dict()["metadata"],
                            sort_keys=True,
                        ),
                    }
                    for item in items
                ],
            )
        return published, True

    def copy_embeddings(
        self,
        session: Session,
        snapshot_id: str,
        source_type: SnapshotSourceType,
    ) -> None:
        embedding_table = self._EMBEDDING_TABLES[source_type]
        session.execute(
            text(
                f"""
                INSERT INTO source_snapshot_item_embeddings (
                    embedding_id, snapshot_id, item_id, embedding
                )
                SELECT gen_random_uuid()::text, :snapshot_id,
                       item.item_id, source_embedding.embedding
                FROM source_snapshot_items item
                JOIN {embedding_table} source_embedding
                  ON CAST(source_embedding.chunk_id AS TEXT)
                     = item.origin_item_id
                WHERE item.snapshot_id = :snapshot_id
                ON CONFLICT (item_id) DO NOTHING
                """
            ),
            {"snapshot_id": snapshot_id},
        )

    def seal_snapshot(
        self,
        session: Session,
        snapshot_id: str,
    ) -> SourceSnapshot:
        snapshot = self.get_snapshot(session, snapshot_id)
        if snapshot is None:
            raise SnapshotNotFoundError("Snapshot not found.")
        copied = session.execute(
            text(
                """
                SELECT
                    COUNT(item.item_id)::INTEGER AS item_count,
                    COUNT(embedding.embedding_id)::INTEGER AS vector_count,
                    encode(
                        digest(
                            COALESCE(
                                string_agg(
                                    encode(
                                        digest(
                                            item.origin_item_id
                                            || ':'
                                            || embedding.embedding::text,
                                            'sha256'
                                        ),
                                        'hex'
                                    ),
                                    '' ORDER BY item.origin_item_id
                                ) FILTER (
                                    WHERE embedding.embedding_id IS NOT NULL
                                ),
                                ''
                            ),
                            'sha256'
                        ),
                        'hex'
                    ) AS embedding_fingerprint
                FROM source_snapshot_items item
                LEFT JOIN source_snapshot_item_embeddings embedding
                  ON embedding.item_id = item.item_id
                WHERE item.snapshot_id = :snapshot_id
                """
            ),
            {"snapshot_id": snapshot_id},
        ).mappings().one()
        if (
            int(copied.get("item_count") or 0) != snapshot.item_count
            or int(copied.get("vector_count") or 0)
            != snapshot.vector_count
            or str(copied.get("embedding_fingerprint") or "")
            != snapshot.embedding_fingerprint
        ):
            raise SnapshotError(
                "Snapshot copy verification failed; publication rolled back."
            )
        row = session.execute(
            text(
                """
                UPDATE source_snapshots
                SET sealed_at = NOW()
                WHERE snapshot_id = :snapshot_id
                  AND sealed_at IS NULL
                RETURNING *
                """
            ),
            {"snapshot_id": snapshot_id},
        ).mappings().first()
        if row is None:
            existing = self.get_snapshot(session, snapshot_id)
            if existing is None or existing.sealed_at is None:
                raise SnapshotNotFoundError("Snapshot not found.")
            return existing
        return _snapshot_from_mapping(row)

    def set_head(
        self,
        session: Session,
        source_type: SnapshotSourceType,
        source_id: str,
        snapshot_id: str,
    ) -> None:
        session.execute(
            text(
                """
                INSERT INTO source_snapshot_heads (
                    source_type, source_id, snapshot_id
                ) VALUES (:source_type, :source_id, :snapshot_id)
                ON CONFLICT (source_type, source_id) DO UPDATE
                SET snapshot_id = EXCLUDED.snapshot_id,
                    updated_at = NOW()
                """
            ),
            {
                "source_type": source_type.value,
                "source_id": source_id,
                "snapshot_id": snapshot_id,
            },
        )

    def get_snapshot(
        self,
        session: Session,
        snapshot_id: str,
    ) -> SourceSnapshot | None:
        row = session.execute(
            text(
                """
                SELECT * FROM source_snapshots
                WHERE snapshot_id = :snapshot_id
                """
            ),
            {"snapshot_id": snapshot_id},
        ).mappings().first()
        return _snapshot_from_mapping(row) if row is not None else None

    def resolve_snapshot(
        self,
        session: Session,
        source_type: SnapshotSourceType,
        source_id: str,
        version: str | None,
    ) -> SourceSnapshot | None:
        if version is None:
            row = session.execute(
                text(
                    """
                    SELECT snapshot.*
                    FROM source_snapshot_heads head
                    JOIN source_snapshots snapshot
                      ON snapshot.snapshot_id = head.snapshot_id
                    WHERE head.source_type = :source_type
                      AND head.source_id = :source_id
                    """
                ),
                {
                    "source_type": source_type.value,
                    "source_id": source_id,
                },
            ).mappings().first()
        else:
            row = session.execute(
                text(
                    """
                    SELECT * FROM source_snapshots
                    WHERE source_type = :source_type
                      AND source_id = :source_id
                      AND version = :version
                    ORDER BY created_at DESC, snapshot_id DESC
                    LIMIT 1
                    """
                ),
                {
                    "source_type": source_type.value,
                    "source_id": source_id,
                    "version": version,
                },
            ).mappings().first()
        return _snapshot_from_mapping(row) if row is not None else None

    def can_access_snapshot(
        self,
        session: Session,
        snapshot: SourceSnapshot,
        user_id: str | None,
    ) -> bool:
        current = session.execute(
            text(self._ACCESS_QUERIES[snapshot.source_type]),
            {"user_id": user_id, "source_id": snapshot.source_id},
        ).mappings().first()
        if current is None:
            return False
        if bool(current.get("is_public")):
            return True
        return bool(
            user_id is not None
            and (
                str(current.get("owner_id") or "") == user_id
                or bool(current.get("has_link"))
            )
        )

    def get_search_snapshots(
        self,
        session: Session,
        snapshot_ids: tuple[str, ...],
        user_id: str | None,
        *,
        timeout_ms: int,
        cancellation: CancellationToken,
    ) -> list[tuple[SourceSnapshot, bool]]:
        """Batch snapshot identity and current-source ACL preflight."""

        deadline = time.monotonic() + timeout_ms / 1000

        def remaining_timeout_ms() -> int:
            if cancellation.cancelled:
                raise TimeoutError("Snapshot search cancelled.")
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining <= 0:
                raise TimeoutError("Snapshot search timed out.")
            return remaining

        def apply_statement_timeout() -> None:
            session.execute(
                text(
                    """
                    SELECT set_config(
                        'statement_timeout',
                        :statement_timeout,
                        true
                    )
                    """
                ),
                {
                    "statement_timeout": (
                        f"{remaining_timeout_ms()}ms"
                    )
                },
            )

        apply_statement_timeout()
        snapshot_statement = text(
            """
            SELECT snapshot.*
            FROM source_snapshots snapshot
            WHERE snapshot.snapshot_id IN :snapshot_ids
              AND snapshot.sealed_at IS NOT NULL
            """
        ).bindparams(bindparam("snapshot_ids", expanding=True))
        rows = session.execute(
            snapshot_statement,
            {"snapshot_ids": snapshot_ids},
        ).mappings().all()
        snapshots = [_snapshot_from_mapping(row) for row in rows]
        if not snapshots:
            return []

        source_types = tuple(
            dict.fromkeys(snapshot.source_type for snapshot in snapshots)
        )
        access_predicate = self._snapshot_access_predicate(
            source_types=source_types,
        )
        apply_statement_timeout()
        access_statement = text(
            f"""
            SELECT snapshot.snapshot_id::text AS snapshot_id
            FROM source_snapshots snapshot
            WHERE snapshot.snapshot_id IN :snapshot_ids
              AND snapshot.sealed_at IS NOT NULL
              AND {access_predicate}
            """
        ).bindparams(bindparam("snapshot_ids", expanding=True))
        accessible_ids = {
            str(row["snapshot_id"])
            for row in session.execute(
                access_statement,
                {
                    "snapshot_ids": snapshot_ids,
                    "user_id": user_id,
                },
            ).mappings().all()
        }
        return [
            (snapshot, snapshot.snapshot_id in accessible_ids)
            for snapshot in snapshots
        ]

    def list_snapshots(
        self,
        session: Session,
        *,
        user_id: str | None,
        source_type: SnapshotSourceType | None,
        source_id: str | None,
        limit: int,
    ) -> list[SourceSnapshot]:
        clauses = [
            self._snapshot_access_predicate(
                source_types=(
                    (source_type,)
                    if source_type is not None
                    else None
                )
            )
        ]
        params: dict[str, Any] = {"limit": limit, "user_id": user_id}
        if source_type is not None:
            clauses.append("snapshot.source_type = :source_type")
            params["source_type"] = source_type.value
        if source_id is not None:
            clauses.append("snapshot.source_id = :source_id")
            params["source_id"] = source_id
        where = f"WHERE {' AND '.join(clauses)}"
        rows = session.execute(
            text(
                f"""
                SELECT snapshot.* FROM source_snapshots snapshot
                {where}
                ORDER BY snapshot.created_at DESC, snapshot.snapshot_id DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        return [_snapshot_from_mapping(row) for row in rows]

    def list_items(
        self,
        session: Session,
        snapshot: SourceSnapshot,
        *,
        user_id: str | None,
        offset: int,
        limit: int,
        locator_prefix: str | None = None,
    ) -> list[dict[str, Any]]:
        connector_acl = ""
        if snapshot.source_type is SnapshotSourceType.CONNECTOR:
            connector_acl = """
              AND EXISTS (
                  SELECT 1
                  FROM connector_record_access access
                  WHERE access.source_id = :source_id
                    AND access.external_id_hash = encode(
                        digest(
                            COALESCE(
                                source_snapshot_items.metadata
                                    ->> 'connector_external_id',
                                ''
                            ),
                            'sha256'
                        ),
                        'hex'
                    )
                    AND access.revoked IS FALSE
                    AND (
                        access.principals IS NULL
                        OR jsonb_exists(access.principals, '*')
                        OR (
                            :user_id IS NOT NULL
                            AND jsonb_exists(
                                access.principals,
                                CAST(:user_id AS TEXT)
                            )
                        )
                    )
              )
            """
        locator_filter = ""
        if locator_prefix is not None:
            locator_filter = """
              AND (
                  BTRIM(source_snapshot_items.locator, '/')
                      = :locator_prefix
                  OR LEFT(
                      BTRIM(source_snapshot_items.locator, '/'),
                      LENGTH(:locator_descendant)
                  ) = :locator_descendant
              )
            """
        rows = session.execute(
            text(
                f"""
                SELECT ordinal, origin_item_id, locator, content_hash,
                       content, token_count, metadata
                FROM source_snapshot_items
                WHERE snapshot_id = :snapshot_id
                {connector_acl}
                {locator_filter}
                ORDER BY ordinal
                OFFSET :offset LIMIT :limit
                """
            ),
            {
                "snapshot_id": snapshot.snapshot_id,
                "source_id": snapshot.source_id,
                "user_id": user_id,
                "offset": offset,
                "limit": limit,
                "locator_prefix": locator_prefix,
                "locator_descendant": (
                    f"{locator_prefix}/"
                    if locator_prefix is not None
                    else None
                ),
            },
        ).mappings().all()
        return [
            {
                "ordinal": int(row["ordinal"]),
                "origin_item_id": str(row["origin_item_id"]),
                "locator": str(row["locator"]),
                "content_hash": str(row["content_hash"]),
                "content": str(row["content"]),
                "token_count": (
                    int(row["token_count"])
                    if row.get("token_count") is not None
                    else None
                ),
                "metadata": row.get("metadata") or {},
            }
            for row in rows
        ]

    def search_items(
        self,
        session: Session,
        snapshot_ids: tuple[str, ...],
        query: str,
        limit: int,
        user_id: str | None,
        *,
        timeout_ms: int,
        source_types: tuple[SnapshotSourceType, ...],
    ) -> list[dict[str, Any]]:
        session.execute(
            text(
                """
                SELECT set_config(
                    'statement_timeout',
                    :statement_timeout,
                    true
                )
                """
            ),
            {"statement_timeout": f"{timeout_ms}ms"},
        )
        access_predicate = self._snapshot_access_predicate(
            source_types=source_types,
        )
        connector_item_acl = """
              AND (
                  snapshot.source_type <> 'connector'
                  OR EXISTS (
                      SELECT 1
                      FROM connector_record_access access
                      WHERE access.source_id = snapshot.source_id
                        AND access.external_id_hash = encode(
                            digest(
                                COALESCE(
                                    item.metadata
                                        ->> 'connector_external_id',
                                    ''
                                ),
                                'sha256'
                            ),
                            'hex'
                        )
                        AND access.revoked IS FALSE
                        AND (
                            access.principals IS NULL
                            OR jsonb_exists(access.principals, '*')
                            OR (
                                :user_id IS NOT NULL
                                AND jsonb_exists(
                                    access.principals,
                                    CAST(:user_id AS TEXT)
                                )
                            )
                        )
                  )
              )
        """
        statement = text(
            f"""
            WITH search_query AS (
                SELECT websearch_to_tsquery('simple', :query) AS value
            )
            SELECT item.snapshot_id::text AS snapshot_id,
                   snapshot.source_id::text AS source_id,
                   snapshot.source_type,
                   item.origin_item_id,
                   item.locator,
                   item.content,
                   item.metadata,
                   LEAST(
                       1.0,
                       ts_rank_cd(
                           to_tsvector('simple', item.content),
                           search_query.value
                       )
                       + CASE
                           WHEN strpos(lower(item.content), lower(:query)) > 0
                           THEN 0.2
                           ELSE 0.0
                         END
                   ) AS score
            FROM source_snapshot_items AS item
            JOIN source_snapshots AS snapshot
              ON snapshot.snapshot_id = item.snapshot_id
            CROSS JOIN search_query
            WHERE item.snapshot_id IN :snapshot_ids
              AND snapshot.sealed_at IS NOT NULL
              AND {access_predicate}
              {connector_item_acl}
              AND (
                  to_tsvector('simple', item.content) @@ search_query.value
                  OR strpos(lower(item.content), lower(:query)) > 0
              )
            ORDER BY score DESC, item.snapshot_id::text, item.ordinal
            LIMIT :limit
            """
        ).bindparams(bindparam("snapshot_ids", expanding=True))
        rows = session.execute(
            statement,
            {
                "snapshot_ids": snapshot_ids,
                "query": query,
                "limit": limit,
                "user_id": user_id,
            },
        ).mappings().all()
        return [
            {
                "snapshot_id": str(row["snapshot_id"]),
                "source_id": str(row["source_id"]),
                "source_type": str(row["source_type"]),
                "origin_item_id": str(row["origin_item_id"]),
                "locator": str(row["locator"]),
                "content": str(row["content"]),
                "score": float(row["score"] or 0.0),
                "metadata": row.get("metadata") or {},
            }
            for row in rows
        ]


class SnapshotService:
    """Publish, resolve, and inspect immutable source versions."""

    def __init__(
        self,
        *,
        store: SnapshotStore | None = None,
        session_factory: _SessionFactory = get_session,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store = store or PostgresSnapshotStore()
        self.session_factory = session_factory
        self.clock = clock

    def publish(
        self,
        source_type: SnapshotSourceType,
        source_id: str,
        *,
        user_id: str | None,
    ) -> SourceSnapshot:
        for attempt in range(3):
            try:
                return self._publish_once(
                    source_type,
                    source_id,
                    user_id=user_id,
                )
            except DBAPIError as exc:
                if (
                    attempt == 2
                    or not _is_retryable_capture_error(exc)
                ):
                    raise
        raise AssertionError("unreachable snapshot retry state")

    def _publish_once(
        self,
        source_type: SnapshotSourceType,
        source_id: str,
        *,
        user_id: str | None,
    ) -> SourceSnapshot:
        with self.session_factory() as session:
            self.store.prepare_capture(session)
            material = self.store.load_material(
                session,
                source_type,
                source_id,
                user_id,
            )
            content_hash = compute_snapshot_content_hash(material.items)
            version = material.version or f"content:{content_hash[:16]}"
            snapshot = SourceSnapshot(
                snapshot_id=str(uuid4()),
                source_id=material.source_id,
                source_type=material.source_type,
                version=version,
                content_hash=content_hash,
                external_ref=material.external_ref,
                display_name=material.display_name,
                classification=material.classification,
                item_count=len(material.items),
                total_tokens=sum(
                    item.token_count or 0 for item in material.items
                ),
                embedding_model=material.embedding_model,
                embedding_fingerprint=material.embedding_fingerprint,
                vector_count=material.vector_count,
                vectors_complete=(
                    material.vector_count == len(material.items)
                ),
                created_by=material.created_by or user_id,
                manifest=material.manifest,
            )
            published, created = self.store.put_snapshot(
                session,
                snapshot,
                material.items,
            )
            if created:
                self.store.copy_embeddings(
                    session,
                    published.snapshot_id,
                    source_type,
                )
                published = self.store.seal_snapshot(
                    session,
                    published.snapshot_id,
                )
            self.store.set_head(
                session,
                source_type,
                source_id,
                published.snapshot_id,
            )
            return published

    def get(
        self,
        snapshot_id: str,
        *,
        user_id: str | None,
        include_items: bool = False,
        item_offset: int = 0,
        item_limit: int = 100,
        locator_prefix: str | None = None,
    ) -> dict[str, Any]:
        if item_offset < 0:
            raise ValueError("item_offset must be non-negative")
        if not 1 <= item_limit <= 500:
            raise ValueError("item_limit must be between 1 and 500")
        if locator_prefix is not None and not locator_prefix.strip():
            raise ValueError("locator_prefix must not be empty")
        with self.session_factory() as session:
            snapshot = self.store.get_snapshot(session, snapshot_id)
            if snapshot is None:
                raise SnapshotNotFoundError("Snapshot not found.")
            if not self.store.can_access_snapshot(session, snapshot, user_id):
                raise SnapshotAccessDeniedError("Snapshot not found.")
            result = snapshot.to_dict()
            if include_items:
                result["items"] = self.store.list_items(
                    session,
                    snapshot,
                    user_id=user_id,
                    offset=item_offset,
                    limit=item_limit,
                    locator_prefix=locator_prefix,
                )
                result["item_offset"] = item_offset
                result["item_limit"] = item_limit
            return result

    def resolve(
        self,
        source_type: SnapshotSourceType,
        source_id: str,
        *,
        user_id: str | None,
        version: str | None = None,
    ) -> dict[str, Any]:
        with self.session_factory() as session:
            snapshot = self.store.resolve_snapshot(
                session,
                source_type,
                source_id,
                version,
            )
            if snapshot is None:
                raise SnapshotNotFoundError("Snapshot not found.")
            if not self.store.can_access_snapshot(session, snapshot, user_id):
                raise SnapshotAccessDeniedError("Snapshot not found.")
            return snapshot.to_dict()

    def list(
        self,
        *,
        user_id: str | None,
        source_type: SnapshotSourceType | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self.session_factory() as session:
            candidates = self.store.list_snapshots(
                session,
                user_id=user_id,
                source_type=source_type,
                source_id=source_id,
                limit=limit,
            )
            return [
                snapshot.to_dict()
                for snapshot in candidates
                if self.store.can_access_snapshot(
                    session,
                    snapshot,
                    user_id,
                )
            ]

    def search(
        self,
        snapshot_ids: tuple[str, ...],
        query: str,
        *,
        user_id: str | None,
        limit: int = 10,
        expected_sources: tuple[tuple[str, str], ...] | None = None,
        timeout_ms: int = 10_000,
        cancellation: CancellationToken | None = None,
    ) -> _SnapshotSearchResults:
        """Search only the named sealed snapshots after current-source ACL checks."""

        if not snapshot_ids:
            raise ValueError("at least one snapshot_id is required")
        if len(snapshot_ids) != len(set(snapshot_ids)):
            raise ValueError("snapshot_ids cannot contain duplicates")
        if len(snapshot_ids) > 100:
            raise ValueError("snapshot_ids can contain at most 100 entries")
        if any(not snapshot_id.strip() for snapshot_id in snapshot_ids):
            raise ValueError("snapshot_ids cannot contain empty values")
        if not query.strip():
            raise ValueError("query must not be empty")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if not 1 <= timeout_ms <= 300_000:
            raise ValueError("timeout_ms must be between 1 and 300000")
        if expected_sources is not None:
            if len(expected_sources) != len(snapshot_ids):
                raise ValueError(
                    "expected_sources must align with snapshot_ids"
                )
            if any(
                source_type not in {item.value for item in SnapshotSourceType}
                or not source_id.strip()
                for source_type, source_id in expected_sources
            ):
                raise ValueError("expected_sources contains an invalid source")

        token = cancellation or CancellationToken()
        deadline = self.clock() + timeout_ms / 1000

        def remaining_timeout_ms() -> int:
            remaining = int((deadline - self.clock()) * 1000)
            if token.cancelled:
                raise TimeoutError("Snapshot search cancelled.")
            if remaining <= 0:
                raise TimeoutError("Snapshot search timed out.")
            return remaining

        with self.session_factory() as session:
            resolved = self.store.get_search_snapshots(
                session,
                snapshot_ids,
                user_id,
                timeout_ms=remaining_timeout_ms(),
                cancellation=token,
            )
            remaining_timeout_ms()
            resolved_by_id = {
                snapshot.snapshot_id: (snapshot, can_access)
                for snapshot, can_access in resolved
            }
            resolved_source_types: list[SnapshotSourceType] = []
            for index, snapshot_id in enumerate(snapshot_ids):
                resolved_snapshot = resolved_by_id.get(snapshot_id)
                if resolved_snapshot is None:
                    raise SnapshotNotFoundError("Snapshot not found.")
                snapshot, can_access = resolved_snapshot
                if expected_sources is not None and (
                    snapshot.source_type.value,
                    snapshot.source_id,
                ) != expected_sources[index]:
                    raise SnapshotNotFoundError("Snapshot not found.")
                if not can_access:
                    raise SnapshotAccessDeniedError("Snapshot not found.")
                if snapshot.source_type not in resolved_source_types:
                    resolved_source_types.append(snapshot.source_type)
            return self.store.search_items(
                session,
                snapshot_ids,
                query,
                limit,
                user_id,
                timeout_ms=remaining_timeout_ms(),
                source_types=tuple(resolved_source_types),
            )


def publish_source_snapshot(
    source_type: str,
    source_id: str,
    *,
    user_id: str | None,
) -> dict[str, Any]:
    """Publish one core source and return its safe metadata."""

    return SnapshotService().publish(
        SnapshotSourceType(source_type),
        source_id,
        user_id=user_id,
    ).to_dict()
