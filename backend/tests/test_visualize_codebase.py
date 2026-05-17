"""Tests for visualize_codebase structural graph builder."""
from __future__ import annotations

from synsc.services import visualization_service


def test_dir_of_normalizes_paths():
    assert visualization_service._dir_of("src/auth/middleware.py") == "src/auth/"
    assert visualization_service._dir_of("README.md") == "(root)"
    assert visualization_service._dir_of("") == ""
    assert visualization_service._dir_of(None) == ""


def test_visualize_codebase_not_found(monkeypatch):
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def first(self):
            return None

    monkeypatch.setattr(
        visualization_service, "get_session", lambda: FakeSession()
    )
    out = visualization_service.visualize_codebase("nope", user_id="u1")
    assert out["success"] is False
    assert out["error_code"] == "not_found"


def test_visualize_codebase_returns_structure(monkeypatch):
    """End-to-end shape test with hand-built fakes for the ORM rows."""

    class FakeRepo:
        repo_id = "r1"
        owner = "owner"
        name = "repo"
        total_lines = 1000

        def can_user_access(self, uid):
            return True

    class FakeFile:
        def __init__(self, file_id, path, lang, lines=10):
            self.file_id = file_id
            self.file_path = path
            self.language = lang
            self.line_count = lines

    class FakeSymbol:
        def __init__(self, sid, name, qn, st, exported, doc=""):
            self.symbol_id = sid
            self.name = name
            self.qualified_name = qn
            self.symbol_type = st
            self.is_exported = exported
            self.is_async = False
            self.language = "python"
            self.file_id = "f1"
            self.start_line = 1
            self.docstring = doc

    files = [
        FakeFile("f1", "src/auth/middleware.py", "python", 100),
        FakeFile("f2", "src/auth/oauth.py", "python", 80),
        FakeFile("f3", "src/db/models.py", "python", 200),
        FakeFile("f4", "tests/test_auth.py", "python", 50),
        FakeFile("f5", "frontend/app.tsx", "typescript", 60),
    ]
    symbols = [
        FakeSymbol("s1", "handle_auth", "auth.handle_auth", "function", True, "Top auth"),
        FakeSymbol("s2", "User", "db.User", "class", True),
        FakeSymbol("s3", "_internal", "auth._internal", "function", False),
    ]

    class FakeQ:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *a, **k):
            return self

        def first(self):
            return self.rows[0] if self.rows else None

        def all(self):
            return self.rows

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def query(self, model):
            from synsc.database.models import (
                Repository as _R,
                RepositoryFile as _F,
                Symbol as _S,
            )

            if model is _R:
                return FakeQ([FakeRepo()])
            if model is _F:
                return FakeQ(files)
            if model is _S:
                return FakeQ(symbols)
            return FakeQ([])

        def execute(self, *a, **k):
            class _R:
                def all(self_inner):
                    return []
            return _R()

    monkeypatch.setattr(
        visualization_service, "get_session", lambda: FakeSession()
    )
    out = visualization_service.visualize_codebase("r1", user_id="u1")
    assert out["success"] is True
    assert out["repo_name"] == "owner/repo"
    assert out["summary"]["files"] == 5
    assert out["summary"]["symbols"] == 3
    # Languages: 4 python + 1 ts → ~0.8 / 0.2
    assert out["summary"]["languages"]["python"] == 0.8
    # Directories rolled up:
    dir_paths = [d["path"] for d in out["directories"]]
    assert "src/auth/" in dir_paths
    assert "src/db/" in dir_paths
    # Top symbols put exported first:
    top_qns = [s["qualified_name"] for s in out["top_symbols"]]
    assert top_qns.index("auth.handle_auth") < top_qns.index("auth._internal")
