"""HTTP contracts for provider capabilities and egress evaluation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from synsc.providers.policy import NetworkPolicy


def test_list_providers_requires_auth_when_enabled(auth_client) -> None:
    response = auth_client.get("/v2/providers")

    assert response.status_code == 401


def test_list_providers_returns_safe_catalog(client) -> None:
    provider = {
        "name": "local-test",
        "version": "1",
        "capabilities": ["embedding"],
        "execution": "local",
        "accepted_classifications": ["public"],
        "health": "ready",
        "supports_streaming": False,
        "supports_cancellation": False,
        "supports_retry": False,
        "supports_cost_estimation": False,
        "max_request_bytes": None,
        "max_response_bytes": None,
    }
    with patch(
        "synsc.services.provider_service.list_providers",
        return_value=[provider],
    ):
        response = client.get("/v2/providers")

    assert response.status_code == 200
    assert response.json() == {"providers": [provider]}


def test_policy_evaluate_returns_structured_denial(client) -> None:
    response = client.post(
        "/v2/policy/evaluate",
        json={
            "provider": "gemini-research",
            "capability": "synthesis",
            "network": "offline",
            "classification": "public",
            "purpose": "answer",
            "fields": ["excerpts"],
        },
    )

    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert response.json()["reason_code"] == "network_offline"


def test_policy_evaluate_cannot_broaden_deployment_ceiling(client) -> None:
    with patch(
        "synsc.services.provider_service.get_provider_policy_config",
        return_value=SimpleNamespace(
            network_policy=NetworkPolicy.LOCAL_ONLY,
            allowed_remote_providers=[],
        ),
    ):
        response = client.post(
            "/v2/policy/evaluate",
            json={
                "provider": "gemini-research",
                "capability": "synthesis",
                "network": "online",
                "classification": "public",
                "purpose": "answer",
                "fields": ["excerpts"],
            },
        )

    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert response.json()["reason_code"] == "network_local_only"


def test_policy_evaluate_rejects_unknown_provider(client) -> None:
    response = client.post(
        "/v2/policy/evaluate",
        json={
            "provider": "missing",
            "capability": "synthesis",
            "network": "online",
            "classification": "public",
            "purpose": "answer",
            "fields": ["excerpts"],
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Provider not found."}


def test_policy_evaluate_rejects_invalid_enum(client) -> None:
    response = client.post(
        "/v2/policy/evaluate",
        json={
            "provider": "gemini-research",
            "capability": "not-real",
            "network": "online",
            "classification": "public",
            "purpose": "answer",
            "fields": ["excerpts"],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid provider policy request."


def test_policy_evaluate_rejects_unknown_body_fields(client) -> None:
    response = client.post(
        "/v2/policy/evaluate",
        json={
            "provider": "gemini-research",
            "capability": "synthesis",
            "network": "online",
            "classification": "public",
            "purpose": "answer",
            "fields": ["excerpts"],
            "api_key": "must-not-be-accepted",
        },
    )

    assert response.status_code == 422


def test_provider_routes_are_present_in_openapi(client) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert paths["/v2/providers"]["get"]
    assert paths["/v2/policy/evaluate"]["post"]
