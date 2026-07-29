from __future__ import annotations

import time
from unittest.mock import Mock

import pytest
import requests
import tiktoken

from synsc.embeddings.providers import (
    GeminiEmbeddingProvider,
    HuggingFaceEmbeddingProvider,
    OpenAIEmbeddingProvider,
)

_UNIT_VECTOR = [1.0] + [0.0] * 767
_PROVIDER_CASES = (
    pytest.param(
        OpenAIEmbeddingProvider,
        {"data": [{"index": 0, "embedding": _UNIT_VECTOR}]},
        "OpenAI embeddings HTTP 500",
        id="openai",
    ),
    pytest.param(
        GeminiEmbeddingProvider,
        {"embeddings": [{"values": _UNIT_VECTOR}]},
        "Gemini embeddings HTTP 500",
        id="gemini",
    ),
    pytest.param(
        HuggingFaceEmbeddingProvider,
        [_UNIT_VECTOR],
        "HuggingFace embeddings HTTP 500",
        id="huggingface",
    ),
)


def _response(
    status: int,
    *,
    headers: dict[str, str] | None = None,
    payload: object | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    response._content = b'{"error":"temporary"}'
    if payload is not None:
        response.json = Mock(return_value=payload)  # type: ignore[method-assign]
    return response


def _configure_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("HF_TOKEN", "test-key")
    monkeypatch.delenv("HF_INFERENCE_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)


def test_openai_embeddings_retry_transient_statuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider_keys(monkeypatch)
    monkeypatch.setenv("EMBEDDING_HTTP_MAX_ATTEMPTS", "4")
    sleep = Mock()
    monkeypatch.setattr(time, "sleep", sleep)
    post = Mock(
        side_effect=[
            _response(429, headers={"Retry-After": "0.25"}),
            _response(503),
            _response(
                200,
                payload={
                    "data": [
                        {
                            "index": 0,
                            "embedding": [1.0] + [0.0] * 767,
                        }
                    ]
                },
            ),
        ]
    )
    monkeypatch.setattr("synsc.embeddings.providers.requests.post", post)

    vector = OpenAIEmbeddingProvider().generate_single("retry me")

    assert vector.shape == (768,)
    assert post.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [0.25, 2.0]


def test_openai_embeddings_do_not_retry_non_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider_keys(monkeypatch)
    monkeypatch.setenv("EMBEDDING_HTTP_MAX_ATTEMPTS", "5")
    post = Mock(return_value=_response(400))
    monkeypatch.setattr("synsc.embeddings.providers.requests.post", post)

    with pytest.raises(RuntimeError, match="OpenAI embeddings HTTP 400"):
        OpenAIEmbeddingProvider().generate_single("bad request")

    post.assert_called_once()


@pytest.mark.parametrize(
    "oversized",
    [
        pytest.param("token " * 9_000, id="ascii"),
        pytest.param("a " * 8_190 + "раба", id="unicode-boundary"),
    ],
)
def test_openai_embeddings_bound_each_input_to_model_limit(
    oversized: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider_keys(monkeypatch)
    post = Mock(
        return_value=_response(
            200,
            payload={"data": [{"index": 0, "embedding": _UNIT_VECTOR}]},
        )
    )
    monkeypatch.setattr("synsc.embeddings.providers.requests.post", post)
    provider = OpenAIEmbeddingProvider()

    provider.generate_single(oversized)

    sent = post.call_args.kwargs["json"]["input"][0]
    encoding = tiktoken.encoding_for_model(provider.model_name)
    assert len(encoding.encode(sent, disallowed_special=())) <= 8_191
    assert sent != oversized


def test_openai_embeddings_retry_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider_keys(monkeypatch)
    monkeypatch.setenv("EMBEDDING_HTTP_MAX_ATTEMPTS", "2")
    sleep = Mock()
    monkeypatch.setattr(time, "sleep", sleep)
    post = Mock(
        side_effect=[
            requests.ConnectionError("connection reset"),
            _response(
                200,
                payload={
                    "data": [
                        {
                            "index": 0,
                            "embedding": [1.0] + [0.0] * 767,
                        }
                    ]
                },
            ),
        ]
    )
    monkeypatch.setattr("synsc.embeddings.providers.requests.post", post)

    vector = OpenAIEmbeddingProvider().generate_single("retry connection")

    assert vector.shape == (768,)
    assert post.call_count == 2
    assert [call.args[0] for call in sleep.call_args_list] == [1.0]


def test_embedding_provider_does_not_retry_permanent_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider_keys(monkeypatch)
    monkeypatch.setenv("EMBEDDING_HTTP_MAX_ATTEMPTS", "5")
    sleep = Mock()
    monkeypatch.setattr(time, "sleep", sleep)
    post = Mock(
        side_effect=requests.exceptions.MissingSchema("missing URL scheme")
    )
    monkeypatch.setattr("synsc.embeddings.providers.requests.post", post)

    with pytest.raises(
        requests.exceptions.MissingSchema,
        match="missing URL scheme",
    ):
        OpenAIEmbeddingProvider().generate_single("bad configuration")

    post.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize(
    "retry_after",
    [
        pytest.param("NaN", id="non-finite"),
        pytest.param("-1", id="negative"),
        pytest.param("tomorrow", id="non-numeric"),
    ],
)
def test_embedding_provider_rejects_invalid_retry_after(
    retry_after: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider_keys(monkeypatch)
    monkeypatch.setenv("EMBEDDING_HTTP_MAX_ATTEMPTS", "2")
    sleep = Mock()
    monkeypatch.setattr(time, "sleep", sleep)
    post = Mock(
        side_effect=[
            _response(503, headers={"Retry-After": retry_after}),
            _response(
                200,
                payload={
                    "data": [
                        {
                            "index": 0,
                            "embedding": _UNIT_VECTOR,
                        }
                    ]
                },
            ),
        ]
    )
    monkeypatch.setattr("synsc.embeddings.providers.requests.post", post)

    OpenAIEmbeddingProvider().generate_single("retry safely")

    assert [call.args[0] for call in sleep.call_args_list] == [1.0]


@pytest.mark.parametrize(
    "status",
    [429, 500, 502, 503, 504],
)
@pytest.mark.parametrize(
    ("provider_class", "success_payload", "_terminal_error"),
    _PROVIDER_CASES,
)
def test_embedding_providers_retry_each_transient_status(
    provider_class: type,
    success_payload: object,
    _terminal_error: str,
    status: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider_keys(monkeypatch)
    monkeypatch.setenv("EMBEDDING_HTTP_MAX_ATTEMPTS", "2")
    sleep = Mock()
    monkeypatch.setattr(time, "sleep", sleep)
    post = Mock(
        side_effect=[
            _response(status),
            _response(200, payload=success_payload),
        ]
    )
    monkeypatch.setattr("synsc.embeddings.providers.requests.post", post)

    vector = provider_class().generate_single("retry all providers")

    assert vector.shape == (768,)
    assert post.call_count == 2
    assert [call.args[0] for call in sleep.call_args_list] == [1.0]


@pytest.mark.parametrize(
    ("provider_class", "_success_payload", "terminal_error"),
    _PROVIDER_CASES,
)
def test_embedding_providers_preserve_terminal_http_error(
    provider_class: type,
    _success_payload: object,
    terminal_error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider_keys(monkeypatch)
    monkeypatch.setenv("EMBEDDING_HTTP_MAX_ATTEMPTS", "1")
    post = Mock(return_value=_response(500))
    monkeypatch.setattr("synsc.embeddings.providers.requests.post", post)

    with pytest.raises(RuntimeError, match=terminal_error):
        provider_class().generate_single("terminal error")


@pytest.mark.parametrize(
    ("configured_attempts", "expected_attempts"),
    [
        pytest.param("0", 1, id="minimum"),
        pytest.param("not-an-integer", 5, id="safe-default"),
        pytest.param("99", 10, id="maximum"),
    ],
)
def test_embedding_provider_bounds_configured_attempts(
    configured_attempts: str,
    expected_attempts: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_provider_keys(monkeypatch)
    monkeypatch.setenv(
        "EMBEDDING_HTTP_MAX_ATTEMPTS",
        configured_attempts,
    )
    sleep = Mock()
    monkeypatch.setattr(time, "sleep", sleep)
    post = Mock(return_value=_response(503))
    monkeypatch.setattr("synsc.embeddings.providers.requests.post", post)

    with pytest.raises(RuntimeError, match="OpenAI embeddings HTTP 503"):
        OpenAIEmbeddingProvider().generate_single("bounded attempts")

    assert post.call_count == expected_attempts
    assert sleep.call_count == expected_attempts - 1
