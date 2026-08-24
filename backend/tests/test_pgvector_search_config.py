from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np

from synsc.indexing import pgvector_manager as manager_module


class _Result:
    def fetchall(self) -> list[object]:
        return []


class _RecordingSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def execute(self, statement, params=None) -> _Result:
        self.calls.append((" ".join(str(statement).split()), params))
        return _Result()


def test_vector_search_uses_configured_hnsw_ef_search(monkeypatch) -> None:
    session = _RecordingSession()

    @contextmanager
    def fake_session():
        yield session

    config = SimpleNamespace(
        search=SimpleNamespace(
            hnsw_ef_search=400,
            vector_exact_scan=False,
        )
    )
    monkeypatch.setattr(manager_module, "get_session", fake_session)
    monkeypatch.setattr(manager_module, "get_config", lambda: config)
    manager = object.__new__(manager_module.PgVectorManager)

    assert manager.search(
        np.array([1.0, 0.0], dtype=np.float32),
        user_id="user-id",
        top_k=1,
    ) == []

    assert (
        "SELECT set_config('hnsw.ef_search', :ef_search, true)",
        {"ef_search": "400"},
    ) in session.calls
