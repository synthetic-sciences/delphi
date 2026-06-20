"""Tests for index freshness / drift detection (the pure, DB-free layers)."""
from __future__ import annotations

import hashlib

from synsc.services.freshness_service import FreshnessService


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_is_stale_sha() -> None:
    assert FreshnessService.is_stale_sha("abc", "def") is True
    assert FreshnessService.is_stale_sha("abc", "abc") is False
    # Unknown current (couldn't reach remote) => not flagged stale.
    assert FreshnessService.is_stale_sha("abc", None) is False
    assert FreshnessService.is_stale_sha(None, "def") is False


def test_hash_drift_detects_added_modified_deleted() -> None:
    existing = {
        "a.py": _hash("print(1)"),
        "b.py": _hash("print(2)"),
        "gone.py": _hash("old"),
    }
    current = [
        {"path": "a.py", "content": "print(1)"},          # unchanged
        {"path": "b.py", "content": "print(2) # edited"},  # modified
        {"path": "c.py", "content": "new file"},           # added
        # gone.py absent -> deleted
    ]
    added, modified, deleted = FreshnessService.compute_hash_drift(current, existing, _hash)
    assert added == ["c.py"]
    assert modified == ["b.py"]
    assert deleted == ["gone.py"]


def test_hash_drift_clean_when_identical() -> None:
    existing = {"a.py": _hash("x"), "b.py": _hash("y")}
    current = [
        {"path": "a.py", "content": "x"},
        {"path": "b.py", "content": "y"},
    ]
    added, modified, deleted = FreshnessService.compute_hash_drift(current, existing, _hash)
    assert (added, modified, deleted) == ([], [], [])


def test_hash_drift_ignores_empty_content() -> None:
    existing = {"a.py": _hash("x")}
    current = [{"path": "a.py", "content": ""}]  # unreadable / empty -> not "modified"
    added, modified, deleted = FreshnessService.compute_hash_drift(current, existing, _hash)
    assert modified == []
    assert added == []
