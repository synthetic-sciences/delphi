"""Compatibility contracts for the arXiv client integration."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from synsc.core import arxiv_client


def test_get_arxiv_metadata_uses_client_results(monkeypatch):
    captured = {}
    result = SimpleNamespace(
        title="A Paper",
        authors=[SimpleNamespace(name="Ada")],
        summary="Abstract",
        published=datetime(2026, 1, 2, tzinfo=timezone.utc),
        entry_id="https://arxiv.org/abs/2601.00001",
        pdf_url="https://arxiv.org/pdf/2601.00001",
        categories=["cs.AI"],
        doi=None,
        primary_category="cs.AI",
        comment=None,
        journal_ref=None,
    )

    class FakeClient:
        def results(self, search):
            captured["search"] = search
            return iter([result])

    monkeypatch.setattr(arxiv_client.arxiv, "Client", FakeClient)

    metadata = arxiv_client.get_arxiv_metadata("2601.00001")

    assert captured["search"].id_list == ["2601.00001"]
    assert metadata["title"] == "A Paper"
    assert metadata["authors"] == ["Ada"]


def test_get_arxiv_metadata_reports_missing_result(monkeypatch):
    class FakeClient:
        def results(self, search):
            return iter(())

    monkeypatch.setattr(arxiv_client.arxiv, "Client", FakeClient)

    with pytest.raises(
        arxiv_client.ArxivNotFoundError,
        match="2601.00001",
    ):
        arxiv_client.get_arxiv_metadata("2601.00001")
