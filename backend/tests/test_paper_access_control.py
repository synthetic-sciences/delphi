"""Regression tests for paper-resource ownership boundaries."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from synsc.services import paper_service


def _sqlite_session(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE papers (paper_id TEXT PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE user_papers ("
                "user_id TEXT NOT NULL, paper_id TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE citations ("
                "citation_id TEXT PRIMARY KEY, paper_id TEXT NOT NULL, "
                "citation_text TEXT NOT NULL, citation_context TEXT, "
                "page_number INTEGER, citation_number INTEGER, "
                "external_reference TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE equations ("
                "equation_id TEXT PRIMARY KEY, paper_id TEXT NOT NULL, "
                "equation_text TEXT NOT NULL, equation_number TEXT, "
                "section_title TEXT, page_number INTEGER, context TEXT, "
                "equation_type TEXT)"
            )
        )
        for table in (
            "paper_chunk_embeddings",
            "paper_code_snippets",
            "paper_chunks",
        ):
            connection.execute(
                text(f"CREATE TABLE {table} (paper_id TEXT NOT NULL)")
            )
        connection.execute(text("INSERT INTO papers (paper_id) VALUES ('paper-1')"))
        connection.execute(
            text(
                "INSERT INTO user_papers (user_id, paper_id) "
                "VALUES ('owner', 'paper-1')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO citations "
                "(citation_id, paper_id, citation_text) "
                "VALUES ('citation-1', 'paper-1', 'private citation')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO equations "
                "(equation_id, paper_id, equation_text) "
                "VALUES ('equation-1', 'paper-1', 'private equation')"
            )
        )
        for table in (
            "paper_chunk_embeddings",
            "paper_code_snippets",
            "paper_chunks",
        ):
            connection.execute(
                text(f"INSERT INTO {table} (paper_id) VALUES ('paper-1')")
            )

    @contextmanager
    def get_test_session():
        with Session(engine) as session, session.begin():
            yield session

    monkeypatch.setattr(paper_service, "get_session", get_test_session)
    return engine


def test_citations_and_equations_require_user_paper_link(monkeypatch):
    _sqlite_session(monkeypatch)

    owner = paper_service.PaperService(user_id="owner")
    stranger = paper_service.PaperService(user_id="stranger")

    assert [row["citation_id"] for row in owner.get_citations("paper-1")] == [
        "citation-1"
    ]
    assert [row["equation_id"] for row in owner.get_equations("paper-1")] == [
        "equation-1"
    ]
    assert stranger.get_citations("paper-1") == []
    assert stranger.get_equations("paper-1") == []


def test_delete_paper_cannot_remove_another_users_paper(monkeypatch):
    engine = _sqlite_session(monkeypatch)

    result = paper_service.PaperService(user_id="stranger").delete_paper("paper-1")

    assert result == {"success": False, "error": "Paper not found"}
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM papers WHERE paper_id = 'paper-1'")
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM user_papers "
                    "WHERE user_id = 'owner' AND paper_id = 'paper-1'"
                )
            ).scalar_one()
            == 1
        )


def test_delete_shared_paper_only_removes_callers_link(monkeypatch):
    engine = _sqlite_session(monkeypatch)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO user_papers (user_id, paper_id) "
                "VALUES ('reader', 'paper-1')"
            )
        )

    result = paper_service.PaperService(user_id="reader").delete_paper("paper-1")

    assert result == {
        "success": True,
        "message": "Paper removed from your library",
    }
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM papers WHERE paper_id = 'paper-1'")
            ).scalar_one()
            == 1
        )
        remaining_users = connection.execute(
            text(
                "SELECT user_id FROM user_papers "
                "WHERE paper_id = 'paper-1' ORDER BY user_id"
            )
        ).scalars().all()
    assert remaining_users == ["owner"]


def test_delete_final_paper_link_removes_unreferenced_data(monkeypatch):
    engine = _sqlite_session(monkeypatch)

    result = paper_service.PaperService(user_id="owner").delete_paper("paper-1")

    assert result == {"success": True, "message": "Paper fully deleted"}
    with engine.connect() as connection:
        for table in (
            "papers",
            "user_papers",
            "citations",
            "equations",
            "paper_chunk_embeddings",
            "paper_code_snippets",
            "paper_chunks",
        ):
            assert connection.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar_one() == 0
