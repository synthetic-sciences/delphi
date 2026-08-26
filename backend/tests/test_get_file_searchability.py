from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace


def test_get_file_reports_searchable_chunk_count(monkeypatch, tmp_path) -> None:
    import synsc.services.search_service as search_module

    file_path = "src/example.py"
    source_path = tmp_path / file_path
    source_path.parent.mkdir(parents=True)
    source_path.write_text("value = 1\n")

    repo = SimpleNamespace(
        is_public=False,
        local_path=str(tmp_path),
        can_user_access=lambda _user_id: True,
    )
    db_file = SimpleNamespace(file_id="file-id", language="python")

    class Query:
        def __init__(self, model) -> None:
            self.model = model

        def filter(self, *_args):
            return self

        def first(self):
            if self.model is search_module.Repository:
                return repo
            if self.model is search_module.RepositoryFile:
                return db_file
            raise AssertionError(f"unexpected first() model: {self.model}")

        def count(self):
            if self.model is search_module.CodeChunk:
                return 2
            raise AssertionError(f"unexpected count() model: {self.model}")

    class Rows:
        def fetchall(self):
            return []

    class Session:
        def query(self, model):
            return Query(model)

        def execute(self, *_args, **_kwargs):
            return Rows()

    @contextmanager
    def fake_session():
        yield Session()

    monkeypatch.setattr(search_module, "get_session", fake_session)
    service = search_module.SearchService.__new__(search_module.SearchService)
    service.user_id = None

    result = service.get_file(repo_id="repo-id", file_path=file_path)

    assert result["success"] is True
    assert result["indexed_chunks"] == 2
