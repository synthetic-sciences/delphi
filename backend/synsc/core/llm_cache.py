"""Bounded, thread-safe caches for the LLM and embedding stages of search.

Search calls out of process in three places — query expansion, listwise
reranking, and query embedding. All three are pure functions of their inputs
in intent, but none are in practice: hosted chat models resample even at
temperature 0, and hosted embedding APIs return slightly different floats for
the same text. Caching the first answer per exact input makes repeated searches
deterministic, and it removes the latency and cost of asking the same question
twice — agents re-issue near-identical queries constantly. Caches are in-memory
by default; an optional safe SQLite store preserves supported values across
process restarts.

Keys are SHA-256 over a namespace plus every input that affects the output
(model, prompt revision, text), so a config change can never serve a stale
entry.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

_MISSING = object()
_FLIGHT_LEASE_SECONDS = 30.0
_FLIGHT_POLL_SECONDS = 0.01


def _encode_persistent_value(value: Any) -> str | None:
    if isinstance(value, str):
        return json.dumps({"kind": "str", "value": value})
    if isinstance(value, np.ndarray) and not value.dtype.hasobject:
        array = np.ascontiguousarray(value)
        return json.dumps(
            {
                "kind": "ndarray",
                "dtype": array.dtype.str,
                "shape": list(array.shape),
                "data": base64.b64encode(array.tobytes()).decode("ascii"),
            }
        )
    return None


def _decode_persistent_value(payload: str) -> Any:
    envelope = json.loads(payload)
    if envelope.get("kind") == "str":
        return str(envelope["value"])
    if envelope.get("kind") != "ndarray":
        raise ValueError("unsupported persistent cache value")
    dtype = np.dtype(envelope["dtype"])
    if dtype.hasobject:
        raise ValueError("object arrays are not valid cache values")
    shape = tuple(int(size) for size in envelope["shape"])
    if any(size < 0 for size in shape):
        raise ValueError("negative array dimension")
    raw = base64.b64decode(envelope["data"], validate=True)
    array = np.frombuffer(raw, dtype=dtype)
    expected_size = int(np.prod(shape, dtype=np.int64))
    if array.size != expected_size:
        raise ValueError("cached array shape does not match its data")
    return array.copy().reshape(shape)


class _SQLiteStore:
    """Safe, process-restart persistence for supported cache values."""

    def __init__(
        self,
        path: Path,
        *,
        namespace: str,
        max_entries: int,
    ) -> None:
        self.path = path
        self.namespace = namespace
        self.max_entries = max_entries
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS search_stage_cache (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    accessed_at REAL NOT NULL,
                    PRIMARY KEY (namespace, cache_key)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_search_stage_cache_lru
                ON search_stage_cache (namespace, accessed_at, cache_key)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS search_stage_flights (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY (namespace, cache_key)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def get(self, key: str) -> Any:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload
                FROM search_stage_cache
                WHERE namespace = ? AND cache_key = ?
                """,
                (self.namespace, key),
            ).fetchone()
            if row is None:
                return _MISSING
            try:
                value = _decode_persistent_value(str(row[0]))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                conn.execute(
                    """
                    DELETE FROM search_stage_cache
                    WHERE namespace = ? AND cache_key = ?
                    """,
                    (self.namespace, key),
                )
                return _MISSING
            conn.execute(
                """
                UPDATE search_stage_cache
                SET accessed_at = ?
                WHERE namespace = ? AND cache_key = ?
                """,
                (time.time(), self.namespace, key),
            )
            return value

    def put(self, key: str, value: Any) -> None:
        payload = _encode_persistent_value(value)
        if payload is None:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO search_stage_cache
                    (namespace, cache_key, payload, accessed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, cache_key) DO UPDATE SET
                    payload = excluded.payload,
                    accessed_at = excluded.accessed_at
                """,
                (self.namespace, key, payload, time.time()),
            )
            excess = conn.execute(
                """
                SELECT MAX(COUNT(*) - ?, 0)
                FROM search_stage_cache
                WHERE namespace = ?
                """,
                (self.max_entries, self.namespace),
            ).fetchone()
            remove_count = int(excess[0]) if excess else 0
            if remove_count:
                conn.execute(
                    """
                    DELETE FROM search_stage_cache
                    WHERE namespace = ? AND cache_key IN (
                        SELECT cache_key
                        FROM search_stage_cache
                        WHERE namespace = ?
                        ORDER BY accessed_at ASC, cache_key ASC
                        LIMIT ?
                    )
                    """,
                    (self.namespace, self.namespace, remove_count),
                )

    def try_acquire_flight(
        self,
        key: str,
        owner: str,
        *,
        lease_seconds: float,
    ) -> bool:
        now = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO search_stage_flights
                    (namespace, cache_key, owner, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, cache_key) DO UPDATE SET
                    owner = excluded.owner,
                    expires_at = excluded.expires_at
                WHERE search_stage_flights.expires_at <= ?
                """,
                (
                    self.namespace,
                    key,
                    owner,
                    now + lease_seconds,
                    now,
                ),
            )
            return cursor.rowcount == 1

    def renew_flight(
        self,
        key: str,
        owner: str,
        *,
        lease_seconds: float,
    ) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE search_stage_flights
                SET expires_at = ?
                WHERE namespace = ? AND cache_key = ? AND owner = ?
                """,
                (
                    time.time() + lease_seconds,
                    self.namespace,
                    key,
                    owner,
                ),
            )
            return cursor.rowcount == 1

    def release_flight(self, key: str, owner: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM search_stage_flights
                WHERE namespace = ? AND cache_key = ? AND owner = ?
                """,
                (self.namespace, key, owner),
            )

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM search_stage_cache WHERE namespace = ?",
                (self.namespace,),
            )
            conn.execute(
                "DELETE FROM search_stage_flights WHERE namespace = ?",
                (self.namespace,),
            )


class _Flight:
    """Outcome shared by every waiter on one concurrent computation."""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.value: Any = None
        self.error: BaseException | None = None


class BoundedCache:
    """LRU cache with a hard entry cap. Safe for concurrent use."""

    def __init__(
        self,
        max_entries: int,
        *,
        namespace: str | None = None,
        persistent_path: str | Path | None = None,
    ) -> None:
        self.max_entries = max(0, int(max_entries))
        self.namespace = namespace
        self.persistent_path = (
            Path(persistent_path).expanduser().resolve()
            if persistent_path is not None
            else None
        )
        if self.persistent_path is not None and not namespace:
            raise ValueError("persistent caches require a namespace")
        self._store: _SQLiteStore | None = None
        if self.persistent_path is not None and self.max_entries > 0:
            assert namespace is not None
            self._store = _SQLiteStore(
                self.persistent_path,
                namespace=namespace,
                max_entries=self.max_entries,
            )
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, Any] = OrderedDict()
        self._inflight: dict[str, _Flight] = {}

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
        if self._store is None:
            return None
        value = self._store.get(key)
        if value is _MISSING:
            return None
        with self._lock:
            self._put_memory(key, value)
        return value

    def put(self, key: str, value: Any) -> None:
        if self.max_entries == 0 or value is None:
            return
        if self._store is not None:
            self._store.put(key, value)
        with self._lock:
            self._put_memory(key, value)

    def _put_memory(self, key: str, value: Any) -> None:
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def get_or_compute(self, key: str, compute: Callable[[], Any]) -> Any:
        """Return one shared computation for concurrent misses of ``key``."""
        if self.max_entries == 0:
            return compute()

        with self._lock:
            if key in self._entries:
                value = self._entries[key]
                self._entries.move_to_end(key)
                return value
            pending = self._inflight.get(key)
            if pending is None:
                pending = _Flight()
                self._inflight[key] = pending
                leader = True
            else:
                leader = False

        if not leader:
            pending.event.wait()
            if pending.error is not None:
                raise pending.error
            return pending.value

        persistent_owner: str | None = None
        heartbeat_stop: threading.Event | None = None
        heartbeat: threading.Thread | None = None
        if self._store is not None:
            try:
                persistent_owner = uuid.uuid4().hex
                while True:
                    persisted = self._store.get(key)
                    if persisted is not _MISSING:
                        with self._lock:
                            self._put_memory(key, persisted)
                            pending.value = persisted
                            self._inflight.pop(key, None)
                            pending.event.set()
                        return persisted
                    if self._store.try_acquire_flight(
                        key,
                        persistent_owner,
                        lease_seconds=_FLIGHT_LEASE_SECONDS,
                    ):
                        # The prior owner may have published between our read
                        # and lease acquisition. Recheck before calling out.
                        persisted = self._store.get(key)
                        if persisted is not _MISSING:
                            self._store.release_flight(
                                key,
                                persistent_owner,
                            )
                            with self._lock:
                                self._put_memory(key, persisted)
                                pending.value = persisted
                                self._inflight.pop(key, None)
                                pending.event.set()
                            return persisted
                        break
                    time.sleep(_FLIGHT_POLL_SECONDS)

                heartbeat_stop = threading.Event()

                def renew_persistent_flight() -> None:
                    assert self._store is not None
                    assert persistent_owner is not None
                    while not heartbeat_stop.wait(
                        _FLIGHT_LEASE_SECONDS / 3
                    ):
                        if not self._store.renew_flight(
                            key,
                            persistent_owner,
                            lease_seconds=_FLIGHT_LEASE_SECONDS,
                        ):
                            return

                heartbeat = threading.Thread(
                    target=renew_persistent_flight,
                    name="search-stage-cache-flight",
                    daemon=True,
                )
                heartbeat.start()
            except BaseException as exc:
                with self._lock:
                    pending.error = exc
                    self._inflight.pop(key, None)
                    pending.event.set()
                raise

        try:
            value = compute()
            if value is not None and self._store is not None:
                self._store.put(key, value)
        except BaseException as exc:
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            if heartbeat is not None:
                heartbeat.join()
            if self._store is not None and persistent_owner is not None:
                self._store.release_flight(key, persistent_owner)
            with self._lock:
                pending.error = exc
                self._inflight.pop(key, None)
                pending.event.set()
            raise

        if heartbeat_stop is not None:
            heartbeat_stop.set()
        if heartbeat is not None:
            heartbeat.join()
        if self._store is not None and persistent_owner is not None:
            self._store.release_flight(key, persistent_owner)

        with self._lock:
            if key in self._entries:
                value = self._entries[key]
                self._entries.move_to_end(key)
            elif value is not None:
                self._put_memory(key, value)
            pending.value = value
            self._inflight.pop(key, None)
            pending.event.set()
        return value

    def clear(self) -> None:
        if self._store is not None:
            self._store.clear()
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_caches: dict[str, BoundedCache] = {}
_caches_lock = threading.Lock()


def get_cache(
    namespace: str,
    max_entries: int,
    *,
    persistent_path: str | Path | None = None,
) -> BoundedCache:
    """Process-wide cache for ``namespace``, created on first use."""
    resolved_path = (
        Path(persistent_path).expanduser().resolve()
        if persistent_path is not None
        else None
    )
    with _caches_lock:
        cache = _caches.get(namespace)
        if (
            cache is None
            or cache.max_entries != max_entries
            or cache.persistent_path != resolved_path
        ):
            cache = BoundedCache(
                max_entries,
                namespace=namespace,
                persistent_path=resolved_path,
            )
            _caches[namespace] = cache
        return cache
