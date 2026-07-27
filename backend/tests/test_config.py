"""Tests for configuration loading and defaults."""

import os

import pytest


def test_default_cors_is_localhost():
    """Default CORS origins should be localhost:3000, NOT wildcard."""
    from synsc.config import APIConfig

    cfg = APIConfig()
    assert cfg.cors_origins == ["http://localhost:3000"]
    assert "*" not in cfg.cors_origins


def test_cors_from_env_variable():
    """SYNSC_CORS_ORIGINS should be parsed as a comma-separated list."""
    os.environ["SYNSC_CORS_ORIGINS"] = "https://app.synsc.dev, https://synsc.dev"

    from synsc.config import SynscConfig

    config = SynscConfig.from_env()
    assert config.api.cors_origins == ["https://app.synsc.dev", "https://synsc.dev"]

    del os.environ["SYNSC_CORS_ORIGINS"]


def test_require_auth_defaults_true():
    """require_auth should default to True (safe for production)."""
    from synsc.config import APIConfig

    cfg = APIConfig()
    assert cfg.require_auth is True


def test_require_auth_false_from_env():
    """SYNSC_REQUIRE_AUTH=false should disable authentication."""
    os.environ["SYNSC_REQUIRE_AUTH"] = "false"

    from synsc.config import SynscConfig

    config = SynscConfig.from_env()
    assert config.api.require_auth is False

    os.environ["SYNSC_REQUIRE_AUTH"] = "false"  # restore test default


def test_database_pool_defaults():
    """Connection pool settings should have sane defaults."""
    from synsc.config import DatabaseConfig

    cfg = DatabaseConfig()
    assert cfg.pool_size == 5
    assert cfg.max_overflow == 10
    assert cfg.pool_timeout == 30
    assert cfg.pool_recycle == 1800


def test_version_is_semver():
    """__version__ should be a valid semver string."""
    from synsc import __version__

    parts = __version__.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_provider_policy_defaults_to_local_only(monkeypatch):
    from synsc.config import SynscConfig
    from synsc.providers.policy import NetworkPolicy

    monkeypatch.delenv("SYNSC_NETWORK_POLICY", raising=False)
    monkeypatch.delenv("SYNSC_ALLOWED_REMOTE_PROVIDERS", raising=False)

    config = SynscConfig.from_env()

    assert config.provider_policy.network_policy is NetworkPolicy.LOCAL_ONLY
    assert config.provider_policy.allowed_remote_providers == []


def test_provider_policy_parses_and_deduplicates_allowlist(monkeypatch):
    from synsc.config import SynscConfig
    from synsc.providers.policy import NetworkPolicy

    monkeypatch.setenv("SYNSC_NETWORK_POLICY", "allowlisted")
    monkeypatch.setenv(
        "SYNSC_ALLOWED_REMOTE_PROVIDERS",
        " gemini-research,openai-embeddings,gemini-research ,,",
    )

    config = SynscConfig.from_env()

    assert config.provider_policy.network_policy is NetworkPolicy.ALLOWLISTED
    assert config.provider_policy.allowed_remote_providers == [
        "gemini-research",
        "openai-embeddings",
    ]


def test_provider_policy_rejects_invalid_network_policy(monkeypatch):
    from synsc.config import SynscConfig

    monkeypatch.setenv("SYNSC_NETWORK_POLICY", "sometimes-online")

    with pytest.raises(ValueError, match="SYNSC_NETWORK_POLICY"):
        SynscConfig.from_env()


def test_provider_policy_model_contains_no_credential_fields():
    from synsc.config import ProviderPolicyConfig

    policy = ProviderPolicyConfig()

    assert "key" not in repr(policy).lower()
    assert "credential" not in repr(policy).lower()
