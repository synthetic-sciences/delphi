"""Local provider adapters used by the query executor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from synsc.providers.contracts import (
    ProviderSearchHit,
    ProviderSearchRequest,
    ProviderSearchResponse,
)
from synsc.snapshots.service import SnapshotService

_RetrieveFn = Callable[..., list[dict[str, Any]]]


def _bounded_score(value: object) -> float:
    if not isinstance(value, (int, float, str)):
        return 0.0
    try:
        score = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(score, 1.0))


def _bounded_response(
    hits: list[ProviderSearchHit],
    *,
    max_response_bytes: int,
) -> ProviderSearchResponse:
    """Build the largest ordered provider response inside its byte ceiling."""

    accepted: list[ProviderSearchHit] = []
    for hit in hits:
        candidate = ProviderSearchResponse(hits=(*accepted, hit))
        if candidate.consumed_bytes > max_response_bytes:
            continue
        accepted.append(hit)
    return ProviderSearchResponse(hits=tuple(accepted))


class LocalIndexSearchProvider:
    """Adapt current-index and exact-snapshot retrieval to one provider contract."""

    def __init__(
        self,
        *,
        user_id: str | None,
        current_retrieve_fn: _RetrieveFn | None = None,
        snapshot_service: SnapshotService | None = None,
    ) -> None:
        self.user_id = user_id
        if current_retrieve_fn is None:
            from synsc.services.source_service import unified_retrieve

            current_retrieve_fn = unified_retrieve
        self.current_retrieve_fn = current_retrieve_fn
        self.snapshot_service = snapshot_service or SnapshotService()

    @staticmethod
    def _current_hit(raw: dict[str, Any]) -> ProviderSearchHit:
        source_id = str(raw.get("source_id") or "")
        chunk_id = str(raw.get("chunk_id") or "")
        locator = raw.get("path")
        line_no = raw.get("line_no")
        if locator and line_no is not None:
            locator = f"{locator}:{line_no}"
        metadata = dict(raw.get("metadata") or {})
        if raw.get("trust_score") is not None:
            metadata["trust_score"] = raw["trust_score"]
        raw_title = metadata.get("repo_name") or metadata.get("paper_title")
        return ProviderSearchHit(
            hit_id=chunk_id or f"{source_id}:{locator or 'result'}",
            text=str(raw.get("text") or ""),
            score=_bounded_score(raw.get("score")),
            title=str(raw_title) if raw_title is not None else None,
            source_type=str(raw.get("source_type") or "") or None,
            source_id=source_id or None,
            locator=str(locator) if locator else None,
            metadata=metadata,
        )

    @staticmethod
    def _snapshot_hit(raw: dict[str, Any]) -> ProviderSearchHit:
        return ProviderSearchHit(
            hit_id=str(raw["origin_item_id"]),
            text=str(raw.get("content") or ""),
            score=_bounded_score(raw.get("score")),
            source_type=str(raw.get("source_type") or "") or None,
            source_id=str(raw.get("source_id") or "") or None,
            snapshot_id=str(raw.get("snapshot_id") or "") or None,
            locator=str(raw.get("locator") or "") or None,
            metadata=dict(raw.get("metadata") or {}),
        )

    def search(self, request: ProviderSearchRequest) -> ProviderSearchResponse:
        if request.cancellation.cancelled:
            return ProviderSearchResponse()
        if request.snapshot_ids:
            raw_hits = self.snapshot_service.search(
                request.snapshot_ids,
                request.query,
                user_id=self.user_id,
                limit=request.limit,
                expected_sources=tuple(
                    zip(
                        request.source_types,
                        request.source_ids,
                        strict=True,
                    )
                ),
                timeout_ms=request.timeout_ms,
                cancellation=request.cancellation,
            )
            hits = [self._snapshot_hit(raw) for raw in raw_hits]
        else:
            if not request.source_types:
                return ProviderSearchResponse()
            binding_sequence = (
                tuple(
                    zip(
                        request.source_types,
                        request.source_ids,
                        strict=True,
                    )
                )
                if request.source_ids
                else ()
            )
            requested_bindings = set(binding_sequence)
            requested_source_types = set(request.source_types)
            raw_hits = self.current_retrieve_fn(
                query=request.query,
                source_bindings=list(binding_sequence) or None,
                source_types=list(dict.fromkeys(request.source_types)),
                k=request.limit,
                user_id=self.user_id,
                timeout_ms=request.timeout_ms,
                cancellation=request.cancellation,
            )
            if requested_bindings:
                raw_hits = [
                    raw
                    for raw in raw_hits
                    if (
                        str(raw.get("source_type") or ""),
                        str(raw.get("source_id") or ""),
                    )
                    in requested_bindings
                ]
            if requested_source_types:
                raw_hits = [
                    raw
                    for raw in raw_hits
                    if str(raw.get("source_type") or "") in requested_source_types
                ]
            raw_hits = raw_hits[: request.limit]
            hits = [self._current_hit(raw) for raw in raw_hits]
        return _bounded_response(
            hits,
            max_response_bytes=request.max_response_bytes,
        )
