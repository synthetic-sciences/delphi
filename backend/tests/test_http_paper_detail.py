"""HTTP contract tests for paper-detail retrieval."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def test_get_paper_returns_user_scoped_paper(client: TestClient) -> None:
    paper = {
        "paper_id": "paper-1",
        "title": "A Useful Paper",
        "chunks": [{"content": "body"}],
    }

    with patch(
        "synsc.services.paper_service.get_paper_service"
    ) as get_paper_service:
        service = get_paper_service.return_value
        service.get_paper.return_value = paper

        response = client.get("/v1/papers/paper-1")

    assert response.status_code == 200
    assert response.json() == {"success": True, **paper}
    get_paper_service.assert_called_once_with(
        user_id="00000000-0000-0000-0000-000000000000"
    )
    service.get_paper.assert_called_once_with("paper-1")


def test_get_paper_returns_404_when_not_in_users_library(
    client: TestClient,
) -> None:
    with patch(
        "synsc.services.paper_service.get_paper_service"
    ) as get_paper_service:
        get_paper_service.return_value.get_paper.return_value = None

        response = client.get("/v1/papers/missing")

    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "error": "Paper not found",
    }


def test_get_paper_requires_authentication(auth_client: TestClient) -> None:
    response = auth_client.get("/v1/papers/paper-1")

    assert response.status_code == 401


def test_get_paper_returns_500_for_service_failure(client: TestClient) -> None:
    with patch(
        "synsc.services.paper_service.get_paper_service"
    ) as get_paper_service:
        get_paper_service.return_value.get_paper.side_effect = RuntimeError(
            "database password must not leak"
        )

        response = client.get("/v1/papers/paper-1")

    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "error": "Failed to retrieve paper.",
    }
    assert "password" not in response.text


def test_paper_service_does_not_conflate_database_failure_with_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from synsc.services import paper_service

    @contextmanager
    def failing_session():
        raise RuntimeError("database unavailable")
        yield

    monkeypatch.setattr(paper_service, "get_session", failing_session)

    with pytest.raises(RuntimeError, match="database unavailable"):
        paper_service.PaperService(user_id="user-1").get_paper("paper-1")
