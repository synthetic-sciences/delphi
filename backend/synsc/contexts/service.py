"""Reproducible context revisions built from authorized immutable snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4


class ContextSessionNotFoundError(LookupError):
    """Raised when a context session is absent or hidden from the caller."""


class ContextRevisionConflictError(RuntimeError):
    """Raised when a writer uses a stale session write version."""


class ContextSessionExpiredError(RuntimeError):
    """Raised when an expired context is used."""


class ContextSnapshotUnavailableError(ValueError):
    """Raised when a requested pinned snapshot or evidence item is unavailable."""


class SnapshotReader(Protocol):
    def get(
        self,
        snapshot_id: str,
        *,
        user_id: str | None,
        include_items: bool = False,
        item_offset: int = 0,
        item_limit: int = 100,
        locator_prefix: str | None = None,
    ) -> dict[str, Any]: ...


class ContextSessionStore(Protocol):
    def create(
        self,
        *,
        session: dict[str, Any],
        revision: dict[str, Any],
        parent_expected_version: int | None = None,
    ) -> dict[str, Any]: ...

    def append(
        self,
        session_id: str,
        *,
        user_id: str,
        expected_version: int,
        revision: dict[str, Any],
    ) -> dict[str, Any]: ...

    def get(
        self,
        session_id: str,
        *,
        user_id: str,
        revision_number: int | None = None,
    ) -> dict[str, Any]: ...

    def list(
        self,
        *,
        user_id: str,
        limit: int,
        include_expired: bool,
    ) -> list[dict[str, Any]]: ...

    def update_policy(
        self,
        session_id: str,
        *,
        user_id: str,
        expected_version: int,
        sharing_policy: str,
        expires_at: datetime | None,
        status: str,
    ) -> dict[str, Any]: ...


_MAX_SNAPSHOTS = 100
_MAX_ITEMS = 10_000
_MAX_STATE_BYTES = 2_000_000
_SHARING_POLICIES = frozenset({"private", "shared"})
_SESSION_STATUSES = frozenset({"active", "completed", "archived"})
_UNSET = object()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _json_copy(value: Any, *, label: str) -> Any:
    try:
        encoded = _canonical_json(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be JSON-compatible") from exc
    if len(encoded.encode("utf-8")) > _MAX_STATE_BYTES:
        raise ValueError(f"{label} exceeds the maximum encoded size")
    return json.loads(encoded)


def _iso_or_none(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None:
        return result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _validate_summary(
    summary: str | None,
    model: str | None,
    version: str | None,
) -> None:
    provided = (summary is not None, model is not None, version is not None)
    if any(provided) and not all(provided):
        raise ValueError(
            "model-generated summary requires content, model and version"
        )
    for label, value, limit in (
        ("summary", summary, 200_000),
        ("summary_model", model, 200),
        ("summary_version", version, 200),
    ):
        if value is not None and (not value.strip() or len(value) > limit):
            raise ValueError(f"{label} is invalid")


class ContextSessionService:
    """Build, persist, rehydrate, and hand off immutable context revisions."""

    def __init__(
        self,
        *,
        store: ContextSessionStore | None = None,
        snapshots: SnapshotReader | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if store is None:
            from synsc.contexts.postgres import PostgresContextSessionStore

            store = PostgresContextSessionStore()
        if snapshots is None:
            from synsc.snapshots.service import SnapshotService

            snapshots = SnapshotService()
        self.store = store
        self.snapshots = snapshots
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _read_snapshot(
        self,
        snapshot_id: str,
        *,
        user_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        items: list[dict[str, Any]] = []
        offset = 0
        metadata: dict[str, Any] | None = None
        while True:
            try:
                page = self.snapshots.get(
                    snapshot_id,
                    user_id=user_id,
                    include_items=True,
                    item_offset=offset,
                    item_limit=500,
                )
            except Exception as exc:
                raise ContextSnapshotUnavailableError(
                    "Pinned snapshot is unavailable."
                ) from exc
            if metadata is None:
                metadata = {
                    key: value
                    for key, value in page.items()
                    if key not in {"items", "item_offset", "item_limit"}
                }
                if not metadata.get("sealed_at"):
                    raise ContextSnapshotUnavailableError(
                        "Pinned snapshot is not sealed."
                    )
            batch = list(page.get("items") or [])
            items.extend(batch)
            if len(items) > _MAX_ITEMS:
                raise ValueError(
                    f"context snapshots can contain at most {_MAX_ITEMS} items"
                )
            if len(batch) < 500:
                break
            offset += len(batch)
        assert metadata is not None
        items.sort(
            key=lambda item: (
                int(item.get("ordinal") or 0),
                str(item.get("locator") or ""),
                str(item.get("content_hash") or ""),
            )
        )
        return metadata, items

    def _snapshot_material(
        self,
        snapshot_ids: Sequence[str],
        *,
        user_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        normalized = [str(item).strip() for item in snapshot_ids]
        if any(not item for item in normalized):
            raise ValueError("snapshot_ids cannot contain empty values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("snapshot_ids cannot contain duplicates")
        if len(normalized) > _MAX_SNAPSHOTS:
            raise ValueError(
                f"snapshot_ids can contain at most {_MAX_SNAPSHOTS} entries"
            )

        pinned: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        for snapshot_id in normalized:
            metadata, items = self._read_snapshot(
                snapshot_id,
                user_id=user_id,
            )
            pinned.append(
                {
                    "snapshot_id": snapshot_id,
                    "source_id": str(metadata.get("source_id") or ""),
                    "source_type": str(metadata.get("source_type") or ""),
                    "version": str(metadata.get("version") or ""),
                    "content_hash": str(metadata.get("content_hash") or ""),
                    "display_name": str(metadata.get("display_name") or ""),
                }
            )
            for item in items:
                content = str(item.get("content") or "")
                token_count = item.get("token_count")
                if not isinstance(token_count, int) or token_count < 0:
                    token_count = max(1, (len(content) + 3) // 4)
                candidates.append(
                    {
                        "snapshot_id": snapshot_id,
                        "source_id": str(metadata.get("source_id") or ""),
                        "source_type": str(metadata.get("source_type") or ""),
                        "ordinal": int(item.get("ordinal") or 0),
                        "locator": str(item.get("locator") or ""),
                        "content_hash": str(item.get("content_hash") or ""),
                        "token_count": token_count,
                        "_content": content,
                    }
                )
        return pinned, candidates

    @staticmethod
    def _normalize_evidence(
        values: Sequence[Mapping[str, Any]],
        *,
        candidates: Sequence[dict[str, Any]],
        rejected: bool,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        lookup: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for candidate in candidates:
            lookup.setdefault(
                (candidate["snapshot_id"], candidate["locator"]),
                [],
            ).append(candidate)
        normalized: list[dict[str, Any]] = []
        matched: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for raw in values:
            snapshot_id = str(raw.get("snapshot_id") or "").strip()
            locator = str(raw.get("locator") or "").strip("/")
            if not snapshot_id or not locator:
                raise ValueError(
                    "evidence requires snapshot_id and locator"
                )
            matches = list(lookup.get((snapshot_id, locator), ()))
            requested_hash = str(raw.get("content_hash") or "").strip()
            if requested_hash:
                matches = [
                    item
                    for item in matches
                    if item["content_hash"] == requested_hash
                ]
            if len(matches) != 1:
                raise ContextSnapshotUnavailableError(
                    "Evidence item is unavailable or ambiguous."
                )
            item = matches[0]
            key = (
                item["snapshot_id"],
                item["locator"],
                item["content_hash"],
            )
            if key in seen:
                raise ValueError("evidence references cannot contain duplicates")
            seen.add(key)
            result = {
                field: item[field]
                for field in (
                    "snapshot_id",
                    "source_id",
                    "source_type",
                    "locator",
                    "content_hash",
                    "token_count",
                )
            }
            note = raw.get("note")
            if note is not None:
                if not isinstance(note, str) or len(note) > 10_000:
                    raise ValueError("evidence note is invalid")
                result["note"] = note
            if rejected:
                reason = raw.get("reason")
                if (
                    not isinstance(reason, str)
                    or not reason.strip()
                    or len(reason) > 10_000
                ):
                    raise ValueError(
                        "rejected evidence requires a reason"
                    )
                result["reason"] = reason
            normalized.append(result)
            matched.append(item)
        return normalized, matched

    def _build_revision(
        self,
        *,
        user_id: str,
        snapshot_ids: Sequence[str],
        token_budget: int,
        task_state: Mapping[str, Any] | None,
        accepted_evidence: Sequence[Mapping[str, Any]],
        rejected_evidence: Sequence[Mapping[str, Any]],
        decisions: Sequence[Mapping[str, Any]],
        unresolved_questions: Sequence[str],
        summary: str | None,
        summary_model: str | None,
        summary_version: str | None,
    ) -> dict[str, Any]:
        if not 1 <= token_budget <= 200_000:
            raise ValueError("token_budget must be between 1 and 200000")
        _validate_summary(summary, summary_model, summary_version)
        pinned, candidates = self._snapshot_material(
            snapshot_ids,
            user_id=user_id,
        )
        accepted, accepted_items = self._normalize_evidence(
            accepted_evidence,
            candidates=candidates,
            rejected=False,
        )
        rejected, rejected_items = self._normalize_evidence(
            rejected_evidence,
            candidates=candidates,
            rejected=True,
        )
        accepted_keys = {
            (
                item["snapshot_id"],
                item["locator"],
                item["content_hash"],
            )
            for item in accepted_items
        }
        rejected_keys = {
            (
                item["snapshot_id"],
                item["locator"],
                item["content_hash"],
            )
            for item in rejected_items
        }
        if accepted_keys & rejected_keys:
            raise ValueError(
                "an evidence item cannot be both accepted and rejected"
            )

        ordered = list(accepted_items)
        ordered.extend(
            item
            for item in candidates
            if (
                item["snapshot_id"],
                item["locator"],
                item["content_hash"],
            )
            not in accepted_keys | rejected_keys
        )
        selected: list[dict[str, Any]] = []
        tokens_used = 0
        for item in ordered:
            next_total = tokens_used + int(item["token_count"])
            if next_total > token_budget:
                break
            selected.append(
                {
                    key: item[key]
                    for key in (
                        "snapshot_id",
                        "source_id",
                        "source_type",
                        "ordinal",
                        "locator",
                        "content_hash",
                        "token_count",
                    )
                }
            )
            tokens_used = next_total

        questions = list(unresolved_questions)
        if any(
            not isinstance(item, str)
            or not item.strip()
            or len(item) > 10_000
            for item in questions
        ):
            raise ValueError(
                "unresolved_questions must contain non-empty strings"
            )
        state = _json_copy(
            {
                "task_state": dict(task_state or {}),
                "accepted_evidence": accepted,
                "rejected_evidence": rejected,
                "decisions": list(decisions),
                "unresolved_questions": questions,
                "summary": summary,
            },
            label="context state",
        )
        context_manifest = {
            "schema_version": 1,
            "items": selected,
            "tokens_used": tokens_used,
        }
        hash_payload = {
            "schema_version": 1,
            "token_budget": token_budget,
            "state": state,
            "pinned_snapshots": pinned,
            "context_manifest": context_manifest,
            "summary_model": summary_model,
            "summary_version": summary_version,
        }
        return {
            "token_budget": token_budget,
            "tokens_used": tokens_used,
            "state": state,
            "pinned_snapshots": pinned,
            "context_manifest": context_manifest,
            "content_hash": hashlib.sha256(
                _canonical_json(hash_payload).encode("utf-8")
            ).hexdigest(),
            "summary_model": summary_model,
            "summary_version": summary_version,
        }

    @staticmethod
    def _validate_session_fields(
        *,
        user_id: str,
        name: str,
        objective: str,
        sharing_policy: str,
        status: str,
        expires_at: datetime | None,
        now: datetime,
    ) -> None:
        if not user_id.strip():
            raise ValueError("user_id must not be empty")
        if not name.strip() or len(name) > 255:
            raise ValueError("name must be between 1 and 255 characters")
        if not objective.strip() or len(objective) > 100_000:
            raise ValueError("objective must not be empty")
        if sharing_policy not in _SHARING_POLICIES:
            raise ValueError("sharing_policy must be private or shared")
        if status not in _SESSION_STATUSES:
            raise ValueError("context status is invalid")
        if expires_at is not None:
            normalized = _as_datetime(expires_at)
            if normalized is None or normalized <= now:
                raise ValueError("expires_at must be in the future")

    def create_session(
        self,
        *,
        user_id: str,
        name: str,
        objective: str,
        snapshot_ids: Sequence[str],
        token_budget: int,
        task_state: Mapping[str, Any] | None = None,
        accepted_evidence: Sequence[Mapping[str, Any]] = (),
        rejected_evidence: Sequence[Mapping[str, Any]] = (),
        decisions: Sequence[Mapping[str, Any]] = (),
        unresolved_questions: Sequence[str] = (),
        summary: str | None = None,
        summary_model: str | None = None,
        summary_version: str | None = None,
        sharing_policy: str = "private",
        expires_at: datetime | None = None,
        status: str = "active",
        parent_session_id: str | None = None,
        parent_revision_id: str | None = None,
        handoff_note: str | None = None,
        parent_expected_version: int | None = None,
    ) -> dict[str, Any]:
        now = self.clock().astimezone(timezone.utc)
        normalized_expires_at = (
            _as_datetime(expires_at) if expires_at is not None else None
        )
        self._validate_session_fields(
            user_id=user_id,
            name=name,
            objective=objective,
            sharing_policy=sharing_policy,
            status=status,
            expires_at=normalized_expires_at,
            now=now,
        )
        if handoff_note is not None and len(handoff_note) > 100_000:
            raise ValueError("handoff_note is too long")
        revision_data = self._build_revision(
            user_id=user_id,
            snapshot_ids=snapshot_ids,
            token_budget=token_budget,
            task_state=task_state,
            accepted_evidence=accepted_evidence,
            rejected_evidence=rejected_evidence,
            decisions=decisions,
            unresolved_questions=unresolved_questions,
            summary=summary,
            summary_model=summary_model,
            summary_version=summary_version,
        )
        session_id = str(uuid4())
        revision_id = str(uuid4())
        session = {
            "session_id": session_id,
            "user_id": user_id,
            "name": name.strip(),
            "objective": objective,
            "status": status,
            "sharing_policy": sharing_policy,
            "expires_at": normalized_expires_at,
            "parent_session_id": parent_session_id,
            "parent_revision_id": parent_revision_id,
            "handoff_note": handoff_note,
        }
        revision = {
            "revision_id": revision_id,
            "session_id": session_id,
            "revision_number": 1,
            "parent_revision_id": parent_revision_id,
            **revision_data,
        }
        created = self.store.create(
            session=session,
            revision=revision,
            parent_expected_version=parent_expected_version,
        )
        return self._hydrate_bundle(created, user_id=user_id)

    def revise_session(
        self,
        session_id: str,
        *,
        user_id: str,
        expected_version: int,
        snapshot_ids: Sequence[str] | None = None,
        token_budget: int | None = None,
        task_state: Mapping[str, Any] | None = None,
        accepted_evidence: Sequence[Mapping[str, Any]] | None = None,
        rejected_evidence: Sequence[Mapping[str, Any]] | None = None,
        decisions: Sequence[Mapping[str, Any]] | None = None,
        unresolved_questions: Sequence[str] | None = None,
        summary: str | None = None,
        summary_model: str | None = None,
        summary_version: str | None = None,
    ) -> dict[str, Any]:
        current = self.store.get(session_id, user_id=user_id)
        self._require_active(current["session"])
        previous = current["revision"]
        if int(current["session"]["write_version"]) != expected_version:
            raise ContextRevisionConflictError("Context session changed.")
        state = previous["state"]
        existing_summary = state.get("summary")
        if (
            summary is None
            and summary_model is None
            and summary_version is None
        ):
            summary = existing_summary
            summary_model = previous.get("summary_model")
            summary_version = previous.get("summary_version")
        revision_data = self._build_revision(
            user_id=user_id,
            snapshot_ids=(
                snapshot_ids
                if snapshot_ids is not None
                else [
                    item["snapshot_id"]
                    for item in previous["pinned_snapshots"]
                ]
            ),
            token_budget=(
                token_budget
                if token_budget is not None
                else int(previous["token_budget"])
            ),
            task_state=(
                task_state
                if task_state is not None
                else state.get("task_state") or {}
            ),
            accepted_evidence=(
                accepted_evidence
                if accepted_evidence is not None
                else state.get("accepted_evidence") or []
            ),
            rejected_evidence=(
                rejected_evidence
                if rejected_evidence is not None
                else state.get("rejected_evidence") or []
            ),
            decisions=(
                decisions
                if decisions is not None
                else state.get("decisions") or []
            ),
            unresolved_questions=(
                unresolved_questions
                if unresolved_questions is not None
                else state.get("unresolved_questions") or []
            ),
            summary=summary,
            summary_model=summary_model,
            summary_version=summary_version,
        )
        revision = {
            "revision_id": str(uuid4()),
            "session_id": session_id,
            "revision_number": int(previous["revision_number"]) + 1,
            "parent_revision_id": previous["revision_id"],
            **revision_data,
        }
        updated = self.store.append(
            session_id,
            user_id=user_id,
            expected_version=expected_version,
            revision=revision,
        )
        return self._hydrate_bundle(updated, user_id=user_id)

    def _require_active(self, session: Mapping[str, Any]) -> None:
        expires_at = _as_datetime(session.get("expires_at"))
        if expires_at is not None and expires_at <= self.clock().astimezone(
            timezone.utc
        ):
            raise ContextSessionExpiredError("Context session has expired.")
        if session.get("status") == "archived":
            raise ContextSessionExpiredError("Context session is archived.")

    def _hydrate_bundle(
        self,
        bundle: dict[str, Any],
        *,
        user_id: str,
    ) -> dict[str, Any]:
        session = deepcopy(bundle["session"])
        session.pop("user_id", None)
        revision = deepcopy(bundle["revision"])
        selected = list(revision["context_manifest"].get("items") or [])
        by_snapshot: dict[str, list[dict[str, Any]]] = {}
        unavailable_snapshots: set[str] = set()
        for ref in revision.get("pinned_snapshots") or []:
            snapshot_id = str(ref["snapshot_id"])
            try:
                _, items = self._read_snapshot(
                    snapshot_id,
                    user_id=user_id,
                )
            except ContextSnapshotUnavailableError:
                unavailable_snapshots.add(snapshot_id)
                continue
            by_snapshot[snapshot_id] = items
        lookup = {
            (
                snapshot_id,
                str(item.get("locator") or ""),
                str(item.get("content_hash") or ""),
            ): item
            for snapshot_id, items in by_snapshot.items()
            for item in items
        }
        context_items: list[dict[str, Any]] = []
        unavailable_items: list[dict[str, Any]] = []
        for ref in selected:
            key = (
                str(ref["snapshot_id"]),
                str(ref["locator"]),
                str(ref["content_hash"]),
            )
            item = lookup.get(key)
            if item is None or key[0] in unavailable_snapshots:
                unavailable_items.append(
                    {
                        "snapshot_id": key[0],
                        "locator": key[1],
                        "content_hash": key[2],
                    }
                )
                continue
            context_items.append(
                {
                    **ref,
                    "content": str(item.get("content") or ""),
                    "metadata": _json_copy(
                        item.get("metadata") or {},
                        label="snapshot item metadata",
                    ),
                }
            )
        return {
            "session": session,
            "revision": revision,
            "context_items": context_items,
            "unavailable_items": unavailable_items,
        }

    def get_session(
        self,
        session_id: str,
        *,
        user_id: str,
        revision_number: int | None = None,
    ) -> dict[str, Any]:
        try:
            bundle = self.store.get(
                session_id,
                user_id=user_id,
                revision_number=revision_number,
            )
        except ContextSessionNotFoundError:
            raise
        except LookupError as exc:
            raise ContextSessionNotFoundError(
                "Context session not found."
            ) from exc
        self._require_active(bundle["session"])
        return self._hydrate_bundle(bundle, user_id=user_id)

    def list_sessions(
        self,
        *,
        user_id: str,
        limit: int = 100,
        include_expired: bool = False,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        rows = self.store.list(
            user_id=user_id,
            limit=limit,
            include_expired=include_expired,
        )
        public_rows = []
        for row in rows:
            public_row = deepcopy(row)
            public_row.pop("user_id", None)
            public_rows.append(public_row)
        if include_expired:
            return public_rows[:limit]
        now = self.clock().astimezone(timezone.utc)
        active_rows = []
        for row in public_rows:
            expires_at = _as_datetime(row.get("expires_at"))
            if (
                (expires_at is None or expires_at > now)
                and row.get("status") != "archived"
            ):
                active_rows.append(row)
        return active_rows[:limit]

    def update_policy(
        self,
        session_id: str,
        *,
        user_id: str,
        expected_version: int,
        sharing_policy: str | None = None,
        expires_at: object = _UNSET,
        status: str | None = None,
    ) -> dict[str, Any]:
        if (
            sharing_policy is None
            and expires_at is _UNSET
            and status is None
        ):
            raise ValueError("at least one context policy field is required")
        current = self.store.get(session_id, user_id=user_id)
        self._require_active(current["session"])
        if int(current["session"]["write_version"]) != expected_version:
            raise ContextRevisionConflictError("Context session changed.")
        if sharing_policy is not None and sharing_policy not in _SHARING_POLICIES:
            raise ValueError("sharing_policy must be private or shared")
        if status is not None and status not in _SESSION_STATUSES:
            raise ValueError("context status is invalid")
        next_sharing_policy = (
            sharing_policy
            if sharing_policy is not None
            else str(current["session"]["sharing_policy"])
        )
        next_status = (
            status
            if status is not None
            else str(current["session"]["status"])
        )
        if expires_at is _UNSET:
            normalized_expires_at = _as_datetime(
                current["session"].get("expires_at")
            )
        elif expires_at is None:
            normalized_expires_at = None
        else:
            normalized_expires_at = _as_datetime(expires_at)
            if normalized_expires_at is None:
                raise ValueError("expires_at is invalid")
        if (
            normalized_expires_at is not None
            and normalized_expires_at <= self.clock().astimezone(timezone.utc)
        ):
            raise ValueError("expires_at must be in the future")
        updated = self.store.update_policy(
            session_id,
            user_id=user_id,
            expected_version=expected_version,
            sharing_policy=next_sharing_policy,
            expires_at=normalized_expires_at,
            status=next_status,
        )
        result = deepcopy(updated)
        result.pop("user_id", None)
        return result

    def handoff(
        self,
        parent_session_id: str,
        *,
        user_id: str,
        name: str,
        objective: str,
        handoff_note: str,
        token_budget: int | None = None,
        sharing_policy: str = "private",
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        parent = self.store.get(parent_session_id, user_id=user_id)
        self._require_active(parent["session"])
        revision = parent["revision"]
        state = revision["state"]
        return self.create_session(
            user_id=user_id,
            name=name,
            objective=objective,
            snapshot_ids=[
                item["snapshot_id"]
                for item in revision["pinned_snapshots"]
            ],
            token_budget=(
                token_budget
                if token_budget is not None
                else int(revision["token_budget"])
            ),
            task_state=state.get("task_state") or {},
            accepted_evidence=state.get("accepted_evidence") or [],
            rejected_evidence=state.get("rejected_evidence") or [],
            decisions=state.get("decisions") or [],
            unresolved_questions=state.get("unresolved_questions") or [],
            summary=state.get("summary"),
            summary_model=revision.get("summary_model"),
            summary_version=revision.get("summary_version"),
            sharing_policy=sharing_policy,
            expires_at=expires_at,
            parent_session_id=parent_session_id,
            parent_revision_id=revision["revision_id"],
            handoff_note=handoff_note,
            parent_expected_version=int(
                parent["session"]["write_version"]
            ),
        )

    def export_session(
        self,
        session_id: str,
        *,
        user_id: str,
        revision_number: int | None = None,
    ) -> dict[str, Any]:
        loaded = self.get_session(
            session_id,
            user_id=user_id,
            revision_number=revision_number,
        )
        session = {
            key: _iso_or_none(value) if key == "expires_at" else value
            for key, value in loaded["session"].items()
            if key != "user_id"
        }
        payload = {
            "schema_version": 1,
            "session": _json_copy(session, label="export session"),
            "revision": _json_copy(
                loaded["revision"],
                label="export revision",
            ),
            "selected_content": _json_copy(
                loaded["context_items"],
                label="selected content",
            ),
            "unavailable_items": loaded["unavailable_items"],
        }
        payload["export_hash"] = hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()
        return payload


_context_session_service: ContextSessionService | None = None


def get_context_session_service() -> ContextSessionService:
    """Return the process context-session service."""

    global _context_session_service
    if _context_session_service is None:
        _context_session_service = ContextSessionService()
    return _context_session_service
