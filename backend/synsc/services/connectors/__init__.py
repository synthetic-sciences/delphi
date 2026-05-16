"""Pluggable ingestion connectors (Slack, GDrive, spreadsheets, ...).

Each connector implements ``IngestionConnector`` and registers itself in
``CONNECTOR_REGISTRY``. The unified ``index_source`` dispatcher routes
unknown source_types to a registered connector when one matches.

The base protocol is defined here; concrete connectors land as
follow-up PRs. A "url" / generic-PDF connector is provided in v1 so
users can index arbitrary documents alongside arXiv papers without
waiting for the full Slack / Drive pipelines.
"""
from __future__ import annotations

from typing import Any, Protocol


class IngestionConnector(Protocol):
    """Contract every connector implements."""

    source_type: str

    def can_handle(self, url: str) -> bool: ...
    def index(
        self,
        url: str,
        user_id: str,
        options: dict[str, Any] | None = None,
        display_name: str | None = None,
    ) -> dict[str, Any]: ...


CONNECTOR_REGISTRY: dict[str, IngestionConnector] = {}


def register_connector(connector: IngestionConnector) -> None:
    CONNECTOR_REGISTRY[connector.source_type] = connector


def get_connector(source_type: str) -> IngestionConnector | None:
    return CONNECTOR_REGISTRY.get(source_type)


def list_connectors() -> list[str]:
    return sorted(CONNECTOR_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Stubs for the connectors named in the gap list (Slack, GDrive,
# spreadsheets). Each raises ``NotImplementedError`` with a clear message
# so a future implementation has a concrete target and so any agent
# probing the surface gets a useful error today.
# ---------------------------------------------------------------------------


class SlackConnectorStub:
    source_type = "slack"

    def can_handle(self, url: str) -> bool:  # noqa: D401
        return "slack.com" in (url or "").lower()

    def index(self, url, user_id, options=None, display_name=None):  # noqa: ANN001
        raise NotImplementedError(
            "slack connector not implemented — pending SLACK_BOT_TOKEN wiring"
        )


class GoogleDriveConnectorStub:
    source_type = "gdrive"

    def can_handle(self, url: str) -> bool:
        return "drive.google.com" in (url or "").lower() or "docs.google.com" in (
            url or ""
        ).lower()

    def index(self, url, user_id, options=None, display_name=None):  # noqa: ANN001
        raise NotImplementedError(
            "gdrive connector not implemented — pending Google OAuth wiring"
        )


class SpreadsheetConnectorStub:
    source_type = "spreadsheet"

    def can_handle(self, url: str) -> bool:
        u = (url or "").lower()
        return u.endswith((".csv", ".xlsx", ".xls", ".tsv"))

    def index(self, url, user_id, options=None, display_name=None):  # noqa: ANN001
        raise NotImplementedError(
            "spreadsheet connector not implemented — pending pandas/csv ingestion"
        )


register_connector(SlackConnectorStub())
register_connector(GoogleDriveConnectorStub())
register_connector(SpreadsheetConnectorStub())
