"""Unit tests for research service + Gemini provider."""
from __future__ import annotations

import concurrent.futures
from unittest.mock import MagicMock, patch

import pytest

from synsc.services.research_providers.base import GeneratedAnswer


def test_gemini_provider_generates_answer():
    """GeminiResearchProvider uses google.genai Client and returns a GeneratedAnswer."""
    from synsc.services.research_providers.gemini import GeminiResearchProvider

    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.text = "The answer is 42."
    fake_response.usage_metadata.prompt_token_count = 100
    fake_response.usage_metadata.candidates_token_count = 20
    fake_client.models.generate_content.return_value = fake_response

    with patch("synsc.services.research_providers.gemini.genai") as mock_genai:
        mock_genai.Client.return_value = fake_client

        provider = GeminiResearchProvider(api_key="test-key")
        answer = provider.generate(
            prompt="Ultimate question?",
            context_blocks=[{"text": "42 is the answer.", "source_id": "s1", "chunk_id": "c1"}],
            model="gemini-2.5-flash",
        )

    assert isinstance(answer, GeneratedAnswer)
    assert answer.text == "The answer is 42."
    assert answer.tokens_in == 100
    assert answer.tokens_out == 20
    mock_genai.Client.assert_called_once_with(api_key="test-key")
    _, kwargs = fake_client.models.generate_content.call_args
    assert kwargs["model"] == "gemini-2.5-flash"


def test_gemini_provider_rejects_empty_api_key():
    from synsc.services.research_providers.gemini import GeminiResearchProvider

    with pytest.raises(ValueError, match="non-empty api_key"):
        GeminiResearchProvider(api_key="")


def test_shared_research_service_isolates_user_credentials_under_concurrency(
    monkeypatch,
):
    """Even one concurrently reused service never caches another user's key."""
    from synsc.config import get_config
    from synsc.services import research_service as rs_mod

    config = get_config()
    monkeypatch.setattr(config.research, "api_key", "server-fallback")
    monkeypatch.setattr(
        rs_mod,
        "get_user_research_api_key",
        lambda user_id, provider: {
            "user-a": "key-a",
            "user-b": "key-b",
        }.get(user_id),
    )

    created_keys: list[str] = []

    class FakeProvider:
        def __init__(self, api_key: str):
            self.api_key = api_key
            created_keys.append(api_key)

    monkeypatch.setattr(
        "synsc.services.research_providers.gemini.GeminiResearchProvider",
        FakeProvider,
    )
    service = rs_mod.ResearchService()

    def resolve(user_id: str) -> str:
        return service._provider_for_user(user_id).api_key

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        resolved = list(pool.map(resolve, ["user-a", "user-b"]))

    assert resolved == ["key-a", "key-b"]
    assert sorted(created_keys) == ["key-a", "key-b"]
    assert config.research.api_key == "server-fallback"


def test_research_service_falls_back_to_server_credential(monkeypatch):
    from synsc.config import get_config
    from synsc.services import research_service as rs_mod

    monkeypatch.setattr(get_config().research, "api_key", "server-key")
    monkeypatch.setattr(
        rs_mod,
        "get_user_research_api_key",
        lambda user_id, provider: None,
    )

    with patch("synsc.services.research_providers.gemini.GeminiResearchProvider") as provider_cls:
        service = rs_mod.ResearchService(user_id="user-without-key")
        resolved_provider = service.provider

    assert resolved_provider is provider_cls.return_value
    provider_cls.assert_called_once_with(api_key="server-key")


def test_research_service_raises_structured_error_without_any_credential(monkeypatch):
    from synsc.config import get_config
    from synsc.services import research_service as rs_mod

    monkeypatch.setattr(get_config().research, "api_key", "")
    monkeypatch.setattr(
        rs_mod,
        "get_user_research_api_key",
        lambda user_id, provider: None,
    )

    service = rs_mod.ResearchService(user_id="user-without-key")
    with pytest.raises(rs_mod.ResearchProviderNotConfiguredError) as exc_info:
        _ = service.provider

    assert exc_info.value.provider == "gemini"


def test_research_credential_lookup_failure_does_not_use_server_key(monkeypatch):
    from synsc.services import research_service as rs_mod
    from synsc.services.research_credentials import ResearchCredentialLookupError

    def unavailable(user_id, provider):
        raise ResearchCredentialLookupError(provider)

    monkeypatch.setattr(rs_mod, "get_user_research_api_key", unavailable)

    with (
        patch(
            "synsc.services.research_providers.gemini.GeminiResearchProvider"
        ) as provider_cls,
        pytest.raises(ResearchCredentialLookupError),
    ):
        _ = rs_mod.ResearchService(user_id="user-a").provider

    provider_cls.assert_not_called()


def test_render_prompt_includes_question_and_blocks():
    from synsc.services.research_providers.gemini import GeminiResearchProvider

    rendered = GeminiResearchProvider._render_prompt(
        "What is X?",
        [
            {"source_id": "s1", "chunk_id": "c1", "text": "X is a thing."},
            {"source_id": "s2", "chunk_id": "c2", "text": "X relates to Y."},
        ],
    )
    assert "Question: What is X?" in rendered
    assert "X is a thing." in rendered
    assert "X relates to Y." in rendered
    assert "[chunk:<chunk_id>]" in rendered
    assert "Answer:" in rendered.split("\n")[-1]


def test_research_quick_mode_calls_provider_once():
    from synsc.services.research_providers.base import GeneratedAnswer
    from synsc.services.research_service import ResearchService

    fake_provider = MagicMock()
    fake_provider.generate.return_value = GeneratedAnswer(
        text="# Answer\nSome text.",
        tokens_in=50,
        tokens_out=10,
    )

    fake_retrieval = MagicMock(return_value=[
        {"chunk_id": "c1", "source_id": "r1", "source_type": "repo",
         "text": "code snippet", "score": 0.9, "path": "a.py", "line_no": 10},
        {"chunk_id": "c2", "source_id": "p1", "source_type": "paper",
         "text": "paper bit", "score": 0.8},
    ])

    svc = ResearchService(provider=fake_provider, retrieve_fn=fake_retrieval)
    result = svc.run(
        query="how does X work?",
        mode="quick",
        source_ids=None,
        source_types=None,
        user_id="u1",
    )

    assert fake_provider.generate.call_count == 1
    assert result["answer_markdown"].startswith("# Answer")
    assert len(result["citations"]) == 2
    assert result["citations"][0]["chunk_id"] == "c1"
    assert result["usage"]["tokens_in"] == 50
    assert result["usage"]["tokens_out"] == 10
    assert result["usage"]["mode"] == "quick"
    assert result["usage"]["latency_ms"] >= 0


def test_research_deep_mode_iterates_up_to_max_hops():
    from synsc.services.research_providers.base import GeneratedAnswer
    from synsc.services.research_service import ResearchService

    fake_provider = MagicMock()
    fake_provider.generate.side_effect = [
        GeneratedAnswer(text="REFINE: need more on Y", tokens_in=100, tokens_out=10),
        GeneratedAnswer(text="REFINE: need more on Z", tokens_in=120, tokens_out=10),
        GeneratedAnswer(text="# Final\nOK.", tokens_in=150, tokens_out=20),
    ]
    fake_retrieval = MagicMock(return_value=[
        {"chunk_id": "c1", "source_id": "r1", "source_type": "repo",
         "text": "snippet", "score": 0.9},
    ])

    svc = ResearchService(provider=fake_provider, retrieve_fn=fake_retrieval)
    result = svc.run(query="deep q", mode="deep", source_ids=None,
                     source_types=None, user_id="u1")

    assert fake_provider.generate.call_count == 3
    assert result["answer_markdown"].startswith("# Final")
    assert result["usage"]["tokens_in"] == 370
    assert result["usage"]["tokens_out"] == 40


def test_unified_retrieve_merges_code_and_papers(monkeypatch):
    from synsc.services import source_service

    fake_code_service = MagicMock()
    fake_code_service.search_code.return_value = {
        "results": [
            {"chunk_id": "cc1", "repo_id": "r1", "content": "code A",
             "relevance_score": 0.9, "file_path": "a.py", "start_line": 10},
        ],
    }
    fake_paper_service = MagicMock()
    fake_paper_service.search_papers.return_value = {
        "results": [
            {"chunk_id": "pp1", "paper_id": "p1", "content": "paper B",
             "similarity": 0.8, "section_title": "Introduction"},
        ],
    }

    monkeypatch.setattr(
        source_service, "_get_search_service", lambda user_id: fake_code_service
    )
    monkeypatch.setattr(
        source_service, "_get_paper_service", lambda user_id: fake_paper_service
    )

    hits = source_service.unified_retrieve(
        query="q", source_ids=None, source_types=["repo", "paper"], k=10, user_id="u1",
    )

    assert len(hits) == 2
    by_type = {h["source_type"]: h for h in hits}
    assert by_type["repo"]["source_id"] == "r1"
    assert by_type["repo"]["path"] == "a.py"
    assert by_type["repo"]["line_no"] == 10
    assert by_type["paper"]["source_id"] == "p1"
    assert by_type["paper"]["path"] == "Introduction"
    assert hits[0]["score"] >= hits[1]["score"]


def test_unified_retrieve_skips_paper_dataset_branches_without_user_id(monkeypatch):
    """Without user_id, the paper / dataset branches are skipped (not even
    constructed) — they require user-scoped access; the code branch may
    still run for public-repo callers."""
    from synsc.services import source_service

    fake_code_service = MagicMock()
    fake_code_service.search_code.return_value = {"results": []}
    paper_called = MagicMock()
    dataset_called = MagicMock()

    monkeypatch.setattr(
        source_service, "_get_search_service", lambda user_id: fake_code_service
    )
    monkeypatch.setattr(source_service, "_get_paper_service", paper_called)
    monkeypatch.setattr(source_service, "_get_dataset_service", dataset_called)

    hits = source_service.unified_retrieve(query="q", k=5, user_id=None)

    assert hits == []
    assert not paper_called.called
    assert not dataset_called.called


def test_unified_retrieve_preserves_exact_typed_source_bindings(monkeypatch):
    from synsc.services import docs_service as docs_service_module
    from synsc.services import source_service

    calls: dict[str, dict[str, object]] = {}

    class CodeService:
        def search_code(self, **kwargs):
            calls["repo"] = kwargs
            return {"results": []}

    class PaperService:
        def search_papers(self, **kwargs):
            calls["paper"] = kwargs
            return {"results": []}

    class DatasetService:
        def search_datasets(self, **kwargs):
            calls["dataset"] = kwargs
            return {"results": []}

    class DocsService:
        def search_docs(self, **kwargs):
            calls["docs"] = kwargs
            return {"results": []}

    monkeypatch.setattr(
        source_service,
        "_get_search_service",
        lambda _user_id: CodeService(),
    )
    monkeypatch.setattr(
        source_service,
        "_get_paper_service",
        lambda _user_id: PaperService(),
    )
    monkeypatch.setattr(
        source_service,
        "_get_dataset_service",
        lambda _user_id: DatasetService(),
    )
    monkeypatch.setattr(
        docs_service_module,
        "get_docs_service",
        lambda user_id=None: DocsService(),
    )

    source_service.unified_retrieve(
        query="bounded",
        source_bindings=[
            ("repo", "00000000-0000-0000-0000-000000000001"),
            ("paper", "paper-1"),
            ("dataset", "dataset-1"),
            ("docs", "docs-1"),
        ],
        source_types=["repo", "paper", "dataset", "docs"],
        k=5,
        user_id="u1",
        timeout_ms=900,
    )

    assert calls["repo"]["repo_ids"] == [
        "00000000-0000-0000-0000-000000000001"
    ]
    assert calls["paper"]["paper_ids"] == ["paper-1"]
    assert calls["dataset"]["dataset_ids"] == ["dataset-1"]
    assert calls["docs"]["docs_ids"] == ["docs-1"]
    assert all(
        1 <= int(call["timeout_ms"]) <= 900
        for call in calls.values()
    )


def test_unified_retrieve_skips_postprocessing_after_cancellation(
    monkeypatch,
) -> None:
    from synsc.providers.contracts import CancellationToken
    from synsc.services import source_service

    token = CancellationToken()

    class CancellingSearchService:
        def search_code(self, **_kwargs):
            token.cancel()
            return {
                "results": [
                    {
                        "chunk_id": "chunk-1",
                        "repo_id": "repo-1",
                        "content": "bounded result",
                        "relevance_score": 0.8,
                    }
                ]
            }

    monkeypatch.setattr(
        source_service,
        "_get_search_service",
        lambda _user_id: CancellingSearchService(),
    )
    monkeypatch.setattr(
        source_service,
        "_attach_trust_scores",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("trust lookup must not run after cancellation")
        ),
    )
    monkeypatch.setattr(
        source_service,
        "_maybe_cross_source_rerank",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("rerank must not run after cancellation")
        ),
    )

    hits = source_service.unified_retrieve(
        query="bounded",
        source_types=["repo"],
        k=5,
        user_id="u1",
        timeout_ms=1000,
        cancellation=token,
    )

    assert [hit["source_id"] for hit in hits] == ["repo-1"]


def test_unified_retrieve_preserves_explicitly_empty_source_types(
    monkeypatch,
) -> None:
    from synsc.services import source_service

    monkeypatch.setattr(
        source_service,
        "_get_search_service",
        lambda _user_id: (_ for _ in ()).throw(
            AssertionError("no source branch should run")
        ),
    )

    assert source_service.unified_retrieve(
        query="no local sources",
        source_types=[],
        user_id="u1",
    ) == []


def test_post_v1_research_quick_returns_answer_and_citations(client, monkeypatch):
    """POST /v1/research returns the synthesized answer + citations."""
    from synsc.config import get_config
    from synsc.services import research_service as rs_mod

    monkeypatch.setattr(get_config().research, "api_key", "test-key")

    def fake_run(self, **kwargs):
        return {
            "answer_markdown": "# Hi",
            "citations": [
                {
                    "source_id": "r1",
                    "chunk_id": "c1",
                    "text": "x",
                    "score": 0.9,
                    "path": "a.py",
                    "line_no": 1,
                }
            ],
            "usage": {
                "tokens_in": 10,
                "tokens_out": 5,
                "mode": kwargs.get("mode", "quick"),
                "latency_ms": 1,
            },
        }

    monkeypatch.setattr(rs_mod.ResearchService, "run", fake_run)

    r = client.post(
        "/v1/research",
        json={
            "query": "explain state management",
            "mode": "quick",
            "source_ids": None,
            "source_types": ["repo"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["answer_markdown"] == "# Hi"
    assert body["citations"][0]["chunk_id"] == "c1"
    assert body["usage"]["mode"] == "quick"


def test_post_v1_research_rejects_invalid_mode(client):
    """Modes outside quick/deep/oracle return 400 with a stable error_code."""
    r = client.post("/v1/research", json={"query": "x", "mode": "zoomzoom"})
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False
    assert body["error_code"] == "invalid_mode"
    assert "quick" in body["message"].lower()


def test_post_v1_research_503_when_provider_unconfigured(client, monkeypatch):
    """Without GEMINI_API_KEY, the endpoint surfaces a structured 503 with
    error_code='provider_not_configured' so MCP / API agents can pattern-match
    on it and tell the user to configure their key (rather than parsing
    English error strings)."""
    from synsc.config import get_config
    from synsc.services import research_service as rs_mod

    monkeypatch.setattr(get_config().research, "provider", "gemini")
    monkeypatch.setattr(get_config().research, "api_key", "")
    monkeypatch.setattr(
        rs_mod,
        "get_user_research_api_key",
        lambda user_id, provider: None,
    )

    r = client.post("/v1/research", json={"query": "x", "mode": "quick"})
    assert r.status_code == 503
    body = r.json()
    assert body["success"] is False
    assert body["error_code"] == "provider_not_configured"
    assert body["provider"] == "gemini"
    assert body["action_required"] == "configure_api_key"
    assert "GEMINI_API_KEY" in body["message"]


def test_post_v1_research_uses_per_user_credential(client, monkeypatch):
    """A stored user key enables research even without a server-wide key."""
    from synsc.config import get_config
    from synsc.services import research_service as rs_mod

    monkeypatch.setattr(get_config().research, "api_key", "")
    monkeypatch.setattr(
        rs_mod,
        "get_user_research_api_key",
        lambda user_id, provider: "user-key",
    )

    fake_provider = MagicMock()
    monkeypatch.setattr(
        rs_mod.ResearchService,
        "provider",
        property(lambda self: fake_provider),
    )
    monkeypatch.setattr(
        rs_mod.ResearchService,
        "run",
        lambda self, **kwargs: {
            "answer_markdown": "# User answer",
            "citations": [],
            "usage": {
                "tokens_in": 1,
                "tokens_out": 1,
                "mode": kwargs["mode"],
                "latency_ms": 1,
            },
        },
    )

    response = client.post(
        "/v1/research",
        json={"query": "isolated?", "mode": "quick"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["answer_markdown"] == "# User answer"


def test_post_v1_research_503_when_user_credential_lookup_is_unavailable(
    client,
    monkeypatch,
):
    from synsc.services import research_service as rs_mod
    from synsc.services.research_credentials import ResearchCredentialLookupError

    def unavailable(self, **kwargs):
        raise ResearchCredentialLookupError("gemini")

    monkeypatch.setattr(rs_mod.ResearchService, "run", unavailable)

    response = client.post(
        "/v1/research",
        json={"query": "isolated?", "mode": "quick"},
    )

    assert response.status_code == 503
    assert response.json()["error_code"] == "credential_lookup_unavailable"


def test_research_per_mode_rate_check_blocks_after_quota():
    """The per-mode sliding window blocks after rpm hits the cap."""
    from synsc.api.http_server import _RESEARCH_RATE_BUCKETS, _research_rate_check

    _RESEARCH_RATE_BUCKETS.clear()
    api_key = "k1"
    assert _research_rate_check(api_key, "quick", rpm=2) is True
    assert _research_rate_check(api_key, "quick", rpm=2) is True
    assert _research_rate_check(api_key, "quick", rpm=2) is False
    # Different mode bucket is independent.
    assert _research_rate_check(api_key, "deep", rpm=1) is True
    assert _research_rate_check(api_key, "deep", rpm=1) is False


def test_mcp_research_tool_is_registered(monkeypatch):
    """The MCP server exposes a `research` tool with the expected signature."""
    monkeypatch.setenv("SYNSC_MCP_PROFILE", "all")
    from synsc.api.mcp_server import create_server

    server = create_server()
    tool_mgr = getattr(server, "_tool_manager", None)
    assert tool_mgr is not None and hasattr(tool_mgr, "_tools")

    research_tool = tool_mgr._tools.get("research")
    assert research_tool is not None, "research tool not registered"

    # Signature shape: (query, mode, source_ids, source_types, k).
    import inspect

    params = inspect.signature(research_tool.fn).parameters
    assert list(params) == ["query", "mode", "source_ids", "source_types", "k"]


def test_mcp_research_tool_rejects_invalid_mode(monkeypatch):
    """Calling the tool function directly with a bad mode returns a stable
    structured error rather than raising."""
    monkeypatch.setenv("SYNSC_MCP_PROFILE", "all")
    from synsc.api.mcp_server import create_server

    server = create_server()
    tool = server._tool_manager._tools["research"]
    result = tool.fn(query="x", mode="zoomzoom")
    assert result["success"] is False
    assert result["error_code"] == "invalid_mode"
    assert "zoomzoom" in result["message"]


def test_mcp_research_tool_returns_structured_error_when_provider_unconfigured(
    monkeypatch,
):
    """Without GEMINI_API_KEY, the tool returns
    error_code='provider_not_configured' so the LLM can pattern-match and
    tell the user what to fix instead of retrying blindly."""
    from synsc.api.mcp_server import create_server
    from synsc.config import get_config

    monkeypatch.setenv("SYNSC_MCP_PROFILE", "all")
    monkeypatch.setattr(get_config().research, "provider", "gemini")
    monkeypatch.setattr(get_config().research, "api_key", "")

    server = create_server()
    tool = server._tool_manager._tools["research"]
    result = tool.fn(query="x", mode="quick")
    assert result["success"] is False
    assert result["error_code"] == "provider_not_configured"
    assert result["provider"] == "gemini"
    assert result["action_required"] == "configure_api_key"
    # The description must mention the env var so the agent can name it.
    assert "GEMINI_API_KEY" in result["message"]


def test_mcp_research_tool_description_mentions_provider_requirement(monkeypatch):
    """The tool docstring (which becomes the MCP description shown to the LLM
    at tool-list time) must flag the provider-key requirement so the agent
    knows the tool may be unavailable on a fresh Delphi instance."""
    monkeypatch.setenv("SYNSC_MCP_PROFILE", "all")
    from synsc.api.mcp_server import create_server

    server = create_server()
    tool = server._tool_manager._tools["research"]
    desc = (tool.fn.__doc__ or "").lower()
    assert "provider" in desc
    assert "gemini" in desc or "api key" in desc


def test_research_config_defaults():
    """ResearchConfig has sensible defaults that don't require env vars to read."""
    from synsc.config import ResearchConfig

    cfg = ResearchConfig()
    assert cfg.provider == "gemini"
    assert cfg.model_quick.startswith("gemini-")
    assert cfg.model_deep.startswith("gemini-")
    assert cfg.quick_rpm > cfg.deep_rpm > cfg.oracle_rpm  # tighter caps for heavier modes
