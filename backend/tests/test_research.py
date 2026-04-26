"""Unit tests for research service + Gemini provider."""
from __future__ import annotations

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


def test_research_config_defaults():
    """ResearchConfig has sensible defaults that don't require env vars to read."""
    from synsc.config import ResearchConfig

    cfg = ResearchConfig()
    assert cfg.provider == "gemini"
    assert cfg.model_quick.startswith("gemini-")
    assert cfg.model_deep.startswith("gemini-")
    assert cfg.quick_rpm > cfg.deep_rpm > cfg.oracle_rpm  # tighter caps for heavier modes
