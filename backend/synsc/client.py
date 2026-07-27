"""Small typed HTTP client for local or hosted Synsc Context deployments."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Any
from urllib.parse import quote

import httpx


class SynscAPIError(RuntimeError):
    """A safe, structured API failure that never retains credentials."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class SynscClient:
    """Synchronous client for workspace, connector, and context workflows."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        allow_insecure_http: bool = False,
    ) -> None:
        resolved_url = (
            base_url
            or os.environ.get("SYNSC_API_URL")
            or "http://localhost:8742"
        ).rstrip("/")
        resolved_key = api_key or os.environ.get("SYNSC_API_KEY")
        parsed_url = httpx.URL(resolved_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.host:
            raise ValueError("context service URL must be an absolute HTTP URL")
        loopback_hosts = frozenset({"localhost", "127.0.0.1", "::1"})
        if (
            parsed_url.scheme == "http"
            and parsed_url.host not in loopback_hosts
            and not allow_insecure_http
        ):
            raise ValueError(
                "HTTPS is required for non-loopback context service URLs"
            )
        headers = {"Accept": "application/json"}
        if resolved_key:
            headers["Authorization"] = f"Bearer {resolved_key}"
        self._client = httpx.Client(
            base_url=resolved_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> SynscClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Release the underlying connection pool."""

        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        transport_failed = False
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                json=json_body,
            )
        except httpx.HTTPError:
            transport_failed = True
        if transport_failed:
            # Raise after leaving the handler so Python does not retain the
            # original httpx request (and its Authorization header) through
            # either ``__cause__`` or ``__context__``.
            raise SynscAPIError(0, "Unable to reach the context service.")

        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.is_error:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            message = (
                str(detail)
                if detail
                else f"Context service returned HTTP {response.status_code}."
            )
            raise SynscAPIError(response.status_code, message)
        if not isinstance(payload, dict):
            raise SynscAPIError(
                response.status_code,
                "Context service returned an invalid response.",
            )
        return payload

    def list_providers(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/v2/providers").get("providers") or [])

    def list_connector_providers(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/v2/connectors/providers")
        return list(payload.get("providers") or [])

    def list_connectors(
        self,
        *,
        provider: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if provider is not None:
            params["provider"] = provider
        payload = self._request("GET", "/v2/connectors", params=params)
        return list(payload.get("sources") or [])

    def sync_connector(
        self,
        source_id: str,
        *,
        priority: int = 0,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v2/connectors/{quote(source_id, safe='')}/sync",
            json_body={"priority": priority},
        )

    def list_research_sessions(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        payload = self._request("GET", "/v2/research", params=params)
        return list(payload.get("sessions") or [])

    def list_context_sessions(
        self,
        *,
        limit: int = 100,
        include_expired: bool = False,
    ) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            "/v2/context-sessions",
            params={
                "limit": limit,
                "include_expired": str(include_expired).lower(),
            },
        )
        return list(payload.get("sessions") or [])

    def get_context_session(
        self,
        session_id: str,
        *,
        revision: int | None = None,
    ) -> dict[str, Any]:
        params = {"revision": revision} if revision is not None else None
        return self._request(
            "GET",
            f"/v2/context-sessions/{quote(session_id, safe='')}",
            params=params,
        )

    def create_context_session(
        self,
        *,
        name: str,
        objective: str,
        snapshot_ids: Sequence[str] = (),
        token_budget: int = 8_000,
        task_state: Mapping[str, Any] | None = None,
        sharing_policy: str = "private",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name,
            "objective": objective,
            "snapshot_ids": list(snapshot_ids),
            "token_budget": token_budget,
        }
        if task_state is not None:
            body["task_state"] = dict(task_state)
        if sharing_policy != "private":
            body["sharing_policy"] = sharing_policy
        return self._request("POST", "/v2/context-sessions", json_body=body)

    def revise_context_session(
        self,
        session_id: str,
        *,
        expected_version: int,
        task_state: Mapping[str, Any] | None = None,
        decisions: Sequence[Mapping[str, Any]] | None = None,
        unresolved_questions: Sequence[str] | None = None,
        token_budget: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"expected_version": expected_version}
        if task_state is not None:
            body["task_state"] = dict(task_state)
        if decisions is not None:
            body["decisions"] = [dict(item) for item in decisions]
        if unresolved_questions is not None:
            body["unresolved_questions"] = list(unresolved_questions)
        if token_budget is not None:
            body["token_budget"] = token_budget
        return self._request(
            "POST",
            f"/v2/context-sessions/{quote(session_id, safe='')}/revisions",
            json_body=body,
        )

    def handoff_context_session(
        self,
        session_id: str,
        *,
        name: str,
        objective: str,
        handoff_note: str,
        token_budget: int | None = None,
        sharing_policy: str = "private",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name,
            "objective": objective,
            "handoff_note": handoff_note,
            "sharing_policy": sharing_policy,
        }
        if token_budget is not None:
            body["token_budget"] = token_budget
        return self._request(
            "POST",
            f"/v2/context-sessions/{quote(session_id, safe='')}/handoffs",
            json_body=body,
        )

    def export_context_session(
        self,
        session_id: str,
        *,
        revision: int | None = None,
    ) -> dict[str, Any]:
        params = {"revision": revision} if revision is not None else None
        return self._request(
            "GET",
            f"/v2/context-sessions/{quote(session_id, safe='')}/export",
            params=params,
        )

    def workspace(self) -> dict[str, list[dict[str, Any]]]:
        """Return one safe control-plane snapshot for human interfaces."""

        return {
            "providers": self.list_providers(),
            "connector_providers": self.list_connector_providers(),
            "connectors": self.list_connectors(),
            "research_sessions": self.list_research_sessions(),
            "context_sessions": self.list_context_sessions(),
        }
