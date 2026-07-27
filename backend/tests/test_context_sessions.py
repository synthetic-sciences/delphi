"""Deterministic context revision, lifecycle, and handoff contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from synsc.contexts.service import (
    ContextRevisionConflictError,
    ContextSessionExpiredError,
    ContextSessionService,
)


def _snapshot(
    snapshot_id: str,
    *,
    items: list[tuple[str, str, int]],
) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot_id,
        "source_id": f"source-{snapshot_id}",
        "source_type": "repo",
        "version": f"version-{snapshot_id}",
        "content_hash": (snapshot_id[-1] * 64),
        "display_name": snapshot_id,
        "sealed_at": "2026-07-27T00:00:00+00:00",
        "items": [
            {
                "ordinal": ordinal,
                "locator": locator,
                "content": content,
                "content_hash": __import__("hashlib")
                .sha256(content.encode())
                .hexdigest(),
                "token_count": token_count,
                "metadata": {},
            }
            for ordinal, (locator, content, token_count) in enumerate(items)
        ],
    }


class FakeSnapshots:
    def __init__(self) -> None:
        self.snapshots = {
            "snapshot-a": _snapshot(
                "snapshot-a",
                items=[
                    ("a.md", "alpha", 2),
                    ("b.md", "beta", 3),
                    ("c.md", "gamma", 4),
                ],
            )
        }

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
        if user_id != "user-1" or snapshot_id not in self.snapshots:
            raise LookupError("snapshot not found")
        result = deepcopy(self.snapshots[snapshot_id])
        items = result.pop("items")
        if include_items:
            if locator_prefix is not None:
                items = [
                    item
                    for item in items
                    if item["locator"] == locator_prefix
                    or item["locator"].startswith(f"{locator_prefix}/")
                ]
            result["items"] = items[item_offset : item_offset + item_limit]
        return result


class FakeContextStore:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.revisions: dict[str, list[dict[str, Any]]] = {}

    def create(
        self,
        *,
        session: dict[str, Any],
        revision: dict[str, Any],
    ) -> dict[str, Any]:
        self.sessions[session["session_id"]] = deepcopy(session)
        self.sessions[session["session_id"]]["current_revision"] = 1
        self.sessions[session["session_id"]]["current_revision_id"] = revision[
            "revision_id"
        ]
        self.revisions[session["session_id"]] = [deepcopy(revision)]
        return self.get(
            session["session_id"],
            user_id=session["user_id"],
        )

    def append(
        self,
        session_id: str,
        *,
        user_id: str,
        expected_revision: int,
        revision: dict[str, Any],
    ) -> dict[str, Any]:
        session = self.sessions[session_id]
        if session["user_id"] != user_id:
            raise LookupError("context not found")
        if session["current_revision"] != expected_revision:
            raise ContextRevisionConflictError("revision changed")
        self.revisions[session_id].append(deepcopy(revision))
        session["current_revision"] = revision["revision_number"]
        session["current_revision_id"] = revision["revision_id"]
        return self.get(session_id, user_id=user_id)

    def get(
        self,
        session_id: str,
        *,
        user_id: str,
        revision_number: int | None = None,
    ) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session is None or session["user_id"] != user_id:
            raise LookupError("context not found")
        number = revision_number or int(session["current_revision"])
        revision = next(
            item
            for item in self.revisions[session_id]
            if item["revision_number"] == number
        )
        return {
            "session": deepcopy(session),
            "revision": deepcopy(revision),
        }

    def list(
        self,
        *,
        user_id: str,
        limit: int,
        include_expired: bool,
    ) -> list[dict[str, Any]]:
        rows = [
            deepcopy(session)
            for session in self.sessions.values()
            if session["user_id"] == user_id
        ]
        if not include_expired:
            now = datetime.now(UTC)
            rows = [
                row
                for row in rows
                if row.get("expires_at") is None
                or row["expires_at"] > now
            ]
        return rows[:limit]

    def update_policy(
        self,
        session_id: str,
        *,
        user_id: str,
        expected_revision: int,
        sharing_policy: str,
        expires_at: datetime | None,
        status: str,
    ) -> dict[str, Any]:
        session = self.sessions[session_id]
        if (
            session["user_id"] != user_id
            or session["current_revision"] != expected_revision
        ):
            raise ContextRevisionConflictError("revision changed")
        session.update(
            sharing_policy=sharing_policy,
            expires_at=expires_at,
            status=status,
        )
        return deepcopy(session)


def _service(
    *,
    now: datetime | None = None,
) -> tuple[ContextSessionService, FakeContextStore, FakeSnapshots]:
    store = FakeContextStore()
    snapshots = FakeSnapshots()
    instant = now or datetime(2026, 7, 27, tzinfo=UTC)
    return (
        ContextSessionService(
            store=store,
            snapshots=snapshots,
            clock=lambda: instant,
        ),
        store,
        snapshots,
    )


def test_revision_build_is_deterministic_and_budget_monotonic() -> None:
    service, _, _ = _service()

    small = service.create_session(
        user_id="user-1",
        name="small",
        objective="Understand the source",
        snapshot_ids=["snapshot-a"],
        token_budget=5,
    )
    large = service.create_session(
        user_id="user-1",
        name="large",
        objective="Understand the source",
        snapshot_ids=["snapshot-a"],
        token_budget=9,
    )
    repeated = service.create_session(
        user_id="user-1",
        name="repeat",
        objective="Understand the source",
        snapshot_ids=["snapshot-a"],
        token_budget=5,
    )

    small_items = small["revision"]["context_manifest"]["items"]
    large_items = large["revision"]["context_manifest"]["items"]
    assert [item["locator"] for item in small_items] == ["a.md", "b.md"]
    assert large_items[: len(small_items)] == small_items
    assert small["revision"]["content_hash"] == repeated["revision"][
        "content_hash"
    ]


def test_accepted_evidence_is_prioritized_and_rejected_is_excluded() -> None:
    service, _, _ = _service()

    created = service.create_session(
        user_id="user-1",
        name="evidence",
        objective="Build an evidence set",
        snapshot_ids=["snapshot-a"],
        token_budget=6,
        accepted_evidence=[
            {"snapshot_id": "snapshot-a", "locator": "c.md", "note": "key"}
        ],
        rejected_evidence=[
            {
                "snapshot_id": "snapshot-a",
                "locator": "b.md",
                "reason": "out of scope",
            }
        ],
    )

    assert [
        item["locator"]
        for item in created["revision"]["context_manifest"]["items"]
    ] == ["c.md", "a.md"]
    assert created["revision"]["state"]["accepted_evidence"][0]["note"] == "key"
    assert (
        created["revision"]["state"]["rejected_evidence"][0]["reason"]
        == "out of scope"
    )


def test_revision_conflict_prevents_lost_update() -> None:
    service, _, _ = _service()
    created = service.create_session(
        user_id="user-1",
        name="work",
        objective="Ship the task",
        snapshot_ids=["snapshot-a"],
        token_budget=5,
    )

    revised = service.revise_session(
        created["session"]["session_id"],
        user_id="user-1",
        expected_revision=1,
        task_state={"status": "in_progress", "next": "verify"},
    )
    assert revised["revision"]["revision_number"] == 2

    with pytest.raises(ContextRevisionConflictError):
        service.revise_session(
            created["session"]["session_id"],
            user_id="user-1",
            expected_revision=1,
            task_state={"status": "stale writer"},
        )


def test_handoff_links_parent_and_preserves_frozen_manifest() -> None:
    service, _, _ = _service()
    parent = service.create_session(
        user_id="user-1",
        name="parent",
        objective="Original objective",
        snapshot_ids=["snapshot-a"],
        token_budget=5,
        decisions=[{"decision": "keep immutable references"}],
        unresolved_questions=["What remains?"],
    )

    child = service.handoff(
        parent["session"]["session_id"],
        user_id="user-1",
        name="child",
        objective="Continue the remaining work",
        handoff_note="Take over verification",
    )

    assert child["session"]["parent_session_id"] == parent["session"][
        "session_id"
    ]
    assert child["session"]["parent_revision_id"] == parent["revision"][
        "revision_id"
    ]
    assert child["revision"]["context_manifest"] == parent["revision"][
        "context_manifest"
    ]
    assert child["revision"]["state"]["decisions"] == [
        {"decision": "keep immutable references"}
    ]


def test_get_rehydrates_selected_content_and_hides_unavailable_items() -> None:
    service, _, snapshots = _service()
    created = service.create_session(
        user_id="user-1",
        name="rehydrate",
        objective="Read selected content",
        snapshot_ids=["snapshot-a"],
        token_budget=5,
    )
    session_id = created["session"]["session_id"]

    loaded = service.get_session(session_id, user_id="user-1")
    assert [item["content"] for item in loaded["context_items"]] == [
        "alpha",
        "beta",
    ]

    snapshots.snapshots["snapshot-a"]["items"] = [
        item
        for item in snapshots.snapshots["snapshot-a"]["items"]
        if item["locator"] != "b.md"
    ]
    filtered = service.get_session(session_id, user_id="user-1")
    assert [item["locator"] for item in filtered["context_items"]] == ["a.md"]
    assert filtered["unavailable_items"] == [
        {
            "snapshot_id": "snapshot-a",
            "locator": "b.md",
            "content_hash": created["revision"]["context_manifest"]["items"][1][
                "content_hash"
            ],
        }
    ]


def test_expired_session_fails_closed_but_can_be_listed_explicitly() -> None:
    now = datetime(2026, 7, 27, tzinfo=UTC)
    service, store, _ = _service(now=now)
    created = service.create_session(
        user_id="user-1",
        name="expired",
        objective="Temporary work",
        snapshot_ids=[],
        token_budget=10,
        expires_at=now + timedelta(hours=1),
    )
    store.sessions[created["session"]["session_id"]]["expires_at"] = (
        now - timedelta(seconds=1)
    )

    with pytest.raises(ContextSessionExpiredError):
        service.get_session(
            created["session"]["session_id"],
            user_id="user-1",
        )
    assert service.list_sessions(user_id="user-1") == []
    assert len(
        service.list_sessions(user_id="user-1", include_expired=True)
    ) == 1


def test_session_output_hides_owner_and_normalizes_naive_expiry() -> None:
    service, store, _ = _service()

    created = service.create_session(
        user_id="user-1",
        name="normalized",
        objective="Keep the owner private",
        snapshot_ids=[],
        token_budget=10,
        expires_at=datetime(2026, 7, 28),
    )

    assert "user_id" not in created["session"]
    stored = store.sessions[created["session"]["session_id"]]
    assert stored["expires_at"] == datetime(2026, 7, 28, tzinfo=UTC)

    updated = service.update_policy(
        created["session"]["session_id"],
        user_id="user-1",
        expected_revision=1,
        sharing_policy="shared",
        expires_at=datetime(2026, 7, 29),
        status="active",
    )
    assert updated["expires_at"] == datetime(2026, 7, 29, tzinfo=UTC)
    assert "user_id" not in updated


def test_model_summary_requires_explicit_model_and_version() -> None:
    service, _, _ = _service()

    with pytest.raises(ValueError, match="model and version"):
        service.create_session(
            user_id="user-1",
            name="summary",
            objective="Summarize",
            snapshot_ids=[],
            token_budget=10,
            summary="generated text",
        )

    created = service.create_session(
        user_id="user-1",
        name="versioned-summary",
        objective="Summarize",
        snapshot_ids=[],
        token_budget=10,
        summary="generated text",
        summary_model="local-model",
        summary_version="prompt-v1",
    )
    assert created["revision"]["state"]["summary"] == "generated text"
    assert created["revision"]["summary_model"] == "local-model"
    assert created["revision"]["summary_version"] == "prompt-v1"


def test_export_contains_only_selected_authorized_content() -> None:
    service, _, _ = _service()
    created = service.create_session(
        user_id="user-1",
        name="portable",
        objective="Hand off selected evidence",
        snapshot_ids=["snapshot-a"],
        token_budget=2,
        sharing_policy="shared",
    )

    exported = service.export_session(
        created["session"]["session_id"],
        user_id="user-1",
    )

    assert exported["schema_version"] == 1
    assert exported["session"]["sharing_policy"] == "shared"
    assert [item["locator"] for item in exported["selected_content"]] == [
        "a.md"
    ]
    assert "beta" not in repr(exported)
