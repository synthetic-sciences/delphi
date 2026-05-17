"""Tests for the connector registry + generic PDF URL ingestion."""
from __future__ import annotations

import pytest

from synsc.services import connectors


def test_registry_has_stubs():
    names = connectors.list_connectors()
    assert "slack" in names
    assert "gdrive" in names
    assert "spreadsheet" in names


def test_slack_stub_can_handle_urls():
    c = connectors.get_connector("slack")
    assert c is not None
    assert c.can_handle("https://acme.slack.com/messages/x")
    assert not c.can_handle("https://github.com/x/y")


def test_slack_stub_raises_not_implemented():
    c = connectors.get_connector("slack")
    with pytest.raises(NotImplementedError):
        c.index(url="https://acme.slack.com/", user_id="u1")


def test_gdrive_handles_drive_and_docs():
    c = connectors.get_connector("gdrive")
    assert c.can_handle("https://drive.google.com/file/abc")
    assert c.can_handle("https://docs.google.com/document/abc")
    assert not c.can_handle("https://drop.box/x")


def test_spreadsheet_detects_extensions():
    c = connectors.get_connector("spreadsheet")
    assert c.can_handle("https://example.com/data.csv")
    assert c.can_handle("local/path.xlsx")
    assert not c.can_handle("readme.md")


def test_register_and_get_custom_connector():
    class Toy:
        source_type = "toy"

        def can_handle(self, url):
            return True

        def index(self, url, user_id, options=None, display_name=None):
            return {"success": True, "toy_id": "t1", "status": "indexed"}

    connectors.register_connector(Toy())
    c = connectors.get_connector("toy")
    assert c is not None
    out = c.index(url="x", user_id="u1")
    assert out["status"] == "indexed"


def test_index_source_routes_to_connector(monkeypatch):
    from synsc.services import source_service

    class Toy:
        source_type = "toy"

        def can_handle(self, url):
            return True

        def index(self, url, user_id, options=None, display_name=None):
            return {"success": True, "toy_id": "t1", "status": "indexed"}

    monkeypatch.setattr(
        connectors,
        "get_connector",
        lambda st: Toy() if st == "toy" else None,
    )
    out = source_service.index_source(
        source_type="toy",
        url="anything",
        user_id="u1",
    )
    assert out["source_type"] == "toy"
    assert out["status"] == "indexed"
    assert out["source_id"] == "t1"


def test_index_source_unknown_still_raises(monkeypatch):
    from synsc.services import source_service

    monkeypatch.setattr(connectors, "get_connector", lambda st: None)
    with pytest.raises(ValueError, match="unsupported source_type"):
        source_service.index_source(
            source_type="mystery", url="x", user_id="u1"
        )


def test_index_source_routes_generic_pdf_url(monkeypatch):
    """A non-arXiv PDF URL is downloaded and indexed via PaperService."""
    from synsc.services import source_service

    seen = {}

    class FakePaperService:
        def index_paper(self, pdf_path, source, **kw):
            seen["pdf_bytes"] = open(pdf_path, "rb").read()[:4]
            seen["source"] = source
            seen["metadata"] = kw.get("arxiv_metadata")
            return {
                "success": True,
                "paper_id": "p-new",
                "status": "indexed",
            }

    monkeypatch.setattr(
        source_service,
        "_get_paper_service",
        lambda uid: FakePaperService(),
    )

    class FakeResp:
        content = b"%PDF-1.4 fake pdf bytes"

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return FakeResp()

    import httpx

    monkeypatch.setattr(httpx, "Client", FakeClient)

    out = source_service.index_source(
        source_type="paper",
        url="https://example.com/whitepaper.pdf",
        user_id="u1",
    )
    assert out["source_type"] == "paper"
    assert out["status"] == "indexed"
    assert seen["pdf_bytes"] == b"%PDF"
    assert seen["source"] == "url"


def test_index_source_rejects_non_pdf_response(monkeypatch):
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "_get_paper_service",
        lambda uid: None,
    )

    class FakeResp:
        content = b"<html>not a pdf</html>"

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return FakeResp()

    import httpx

    monkeypatch.setattr(httpx, "Client", FakeClient)
    out = source_service.index_source(
        source_type="paper",
        url="https://example.com/not-a-pdf.pdf",
        user_id="u1",
    )
    assert out["status"] == "error"
    assert "PDF" in out["error"]
