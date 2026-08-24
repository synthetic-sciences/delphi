"""Bounded, thread-safe caches for the LLM and embedding stages of search.

Search calls out of process in three places — query expansion, listwise
reranking, and query embedding. All three are pure functions of their inputs
in intent, but none are in practice: hosted chat models resample even at
temperature 0, and hosted embedding APIs return slightly different floats for
the same text. Caching the first answer per exact input makes repeated
searches deterministic within a process lifetime, and it removes the latency
and cost of asking the same question twice — agents re-issue near-identical
queries constantly.

Keys are SHA-256 over a namespace plus every input that affects the output
(model, prompt revision, text), so a config change can never serve a stale
entry.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import Any


class BoundedCache:
    """LRU cache with a hard entry cap. Safe for concurrent use."""

    def __init__(self, max_entries: int) -> None:
        self.max_entries = max(0, int(max_entries))
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, Any] = OrderedDict()

    @staticmethod
    def key(*parts: str) -> str:
        digest = hashlib.sha256()
        for part in parts:
            digest.update(part.encode("utf-8", "replace"))
            digest.update(b"\x1f")
        return digest.hexdigest()

    def get(self, key: str) -> Any | None:
        if self.max_entries == 0:
            return None
        with self._lock:
            value = self._entries.get(key)
            if value is not None:
                self._entries.move_to_end(key)
            return value

    def put(self, key: str, value: Any) -> None:
        if self.max_entries == 0 or value is None:
            return
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_caches: dict[str, BoundedCache] = {}
_caches_lock = threading.Lock()


def get_cache(namespace: str, max_entries: int) -> BoundedCache:
    """Process-wide cache for ``namespace``, created on first use."""
    with _caches_lock:
        cache = _caches.get(namespace)
        if cache is None or cache.max_entries != max_entries:
            cache = BoundedCache(max_entries)
            _caches[namespace] = cache
        return cache
