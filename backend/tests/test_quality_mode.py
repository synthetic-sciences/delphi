"""Quality-mode + agent-quality indexing behavior.

Covers:
- ``quality_mode`` defaults (global + MCP) and env override.
- ``include_basenames`` matching against `_should_include`.
- agent-mode disables fast-skip patterns even when fast_mode is on globally.
- agent-mode chunker uses the lower min-chunk threshold.
- language detector recognizes basename-only files.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest


def _fresh_config():
    """Reload the config singleton so env-var overrides take effect."""
    import synsc.config as cfg
    cfg._config = None
    return cfg.get_config()


def test_quality_mode_defaults_to_agent():
    config = _fresh_config()
    assert config.quality.quality_mode == "agent"
    assert config.quality.mcp_default_mode == "agent"


def test_quality_mode_env_override():
    old = os.environ.get("SYNSC_QUALITY_MODE")
    os.environ["SYNSC_QUALITY_MODE"] = "fast"
    try:
        config = _fresh_config()
        assert config.quality.quality_mode == "fast"
    finally:
        if old is None:
            os.environ.pop("SYNSC_QUALITY_MODE", None)
        else:
            os.environ["SYNSC_QUALITY_MODE"] = old
        _fresh_config()


def test_quality_mode_invalid_env_falls_back_silently():
    os.environ["SYNSC_QUALITY_MODE"] = "extreme"
    try:
        config = _fresh_config()
        # Invalid value is ignored, default 'agent' kept.
        assert config.quality.quality_mode == "agent"
    finally:
        os.environ.pop("SYNSC_QUALITY_MODE", None)
        _fresh_config()


def test_min_chunk_tokens_agent_lower_than_default():
    config = _fresh_config()
    assert config.chunking.min_chunk_tokens_agent < config.chunking.min_chunk_tokens


def test_chunker_uses_agent_threshold_in_agent_mode():
    from synsc.core.chunker import CodeChunker

    agent = CodeChunker(quality_mode="agent")
    default = CodeChunker(quality_mode="fast")
    assert agent.min_chunk_tokens < default.min_chunk_tokens


def test_include_basenames_present():
    config = _fresh_config()
    # The spec calls these out explicitly.
    for must_have in (
        "Dockerfile", "Makefile", "go.mod", ".env.example",
        "Procfile", "package.json", "Cargo.toml", "pyproject.toml",
        "CODEOWNERS", "README", "LICENSE",
    ):
        assert must_have in config.git.include_basenames, (
            f"Missing basename {must_have!r} from include_basenames"
        )


def test_should_include_matches_basename_files(tmp_path):
    from synsc.core.git_client import GitClient

    client = GitClient(repos_dir=tmp_path, quality_mode="agent")
    # Basename-only files
    assert client._should_include(tmp_path / "Dockerfile") is True
    assert client._should_include(tmp_path / "Makefile") is True
    assert client._should_include(tmp_path / "go.mod") is True
    assert client._should_include(tmp_path / ".env.example") is True
    # Variants — agent mode covers these
    assert client._should_include(tmp_path / "Dockerfile.prod") is True
    assert client._should_include(tmp_path / "Makefile.alpine") is True
    # Extensions still work
    assert client._should_include(tmp_path / "main.py") is True
    # Garbage doesn't sneak through
    assert client._should_include(tmp_path / "random.xyz") is False


def test_should_include_iac_only_in_agent_mode(tmp_path):
    from synsc.core.git_client import GitClient

    agent = GitClient(repos_dir=tmp_path, quality_mode="agent")
    fast = GitClient(repos_dir=tmp_path, quality_mode="fast")

    # IaC files (terraform/hcl/bicep) — agent yes, fast no
    assert agent._should_include(tmp_path / "main.tf") is True
    assert agent._should_include(tmp_path / "main.bicep") is True
    assert fast._should_include(tmp_path / "main.tf") is False


def test_should_exclude_keeps_tests_in_agent_mode(tmp_path):
    from synsc.core.git_client import GitClient

    # Set up a fake repo tree so relative_to() works.
    (tmp_path / "tests").mkdir()
    test_file = tmp_path / "tests" / "test_x.py"
    test_file.write_text("# fake")

    agent = GitClient(repos_dir=tmp_path, quality_mode="agent")
    fast = GitClient(repos_dir=tmp_path, quality_mode="fast")

    # Fast mode skips test dirs; agent mode keeps them.
    assert fast._should_exclude(test_file, tmp_path) is True
    assert agent._should_exclude(test_file, tmp_path) is False


def test_language_detector_recognizes_basenames():
    from synsc.core.language_detector import detect_language

    assert detect_language("Dockerfile") == "dockerfile"
    assert detect_language("Containerfile") == "dockerfile"
    assert detect_language("Makefile") == "makefile"
    assert detect_language("go.mod") == "go-mod"
    assert detect_language("Procfile") == "yaml"
    assert detect_language(".env.example") == "shell"
    assert detect_language("CODEOWNERS") == "text"
    # Variants
    assert detect_language("Dockerfile.dev") == "dockerfile"
    assert detect_language("Makefile.alpine") == "makefile"
    # Suffix path still works
    assert detect_language("foo.py") == "python"


def test_env_override_chunk_tokens():
    os.environ["SYNSC_CHUNK_MAX_TOKENS"] = "1024"
    os.environ["SYNSC_CHUNK_MIN_TOKENS"] = "30"
    try:
        config = _fresh_config()
        assert config.chunking.max_tokens == 1024
        assert config.chunking.min_chunk_tokens == 30
    finally:
        del os.environ["SYNSC_CHUNK_MAX_TOKENS"]
        del os.environ["SYNSC_CHUNK_MIN_TOKENS"]
        _fresh_config()


def test_env_override_include_patterns_extends_list():
    os.environ["SYNSC_INCLUDE_PATTERNS"] = ".tex,.adoc"
    try:
        config = _fresh_config()
        assert ".tex" in config.git.include_extensions
        assert ".adoc" in config.git.include_extensions
        # Existing defaults still present.
        assert ".py" in config.git.include_extensions
    finally:
        del os.environ["SYNSC_INCLUDE_PATTERNS"]
        _fresh_config()


def test_env_override_quality_mode_recognized():
    """SYNSC_QUALITY_MODE accepts fast, balanced, agent."""
    for mode in ("fast", "balanced", "agent"):
        os.environ["SYNSC_QUALITY_MODE"] = mode
        try:
            config = _fresh_config()
            assert config.quality.quality_mode == mode
        finally:
            os.environ.pop("SYNSC_QUALITY_MODE", None)
            _fresh_config()
