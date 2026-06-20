"""Tests for the zero-download hash embedding provider (lite mode)."""
from __future__ import annotations

import numpy as np

from synsc.embeddings.providers import DEFAULT_DIM, HashEmbeddingProvider


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # vectors are L2-normalized


def test_dimension_and_normalization() -> None:
    provider = HashEmbeddingProvider()
    vec = provider.generate_single("def authenticate_user(name): pass")
    assert vec.shape == (DEFAULT_DIM,)
    # L2-normalized → unit length (within float tolerance).
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-5


def test_deterministic_across_calls() -> None:
    p1 = HashEmbeddingProvider()
    p2 = HashEmbeddingProvider()
    text = "class CacheStore: def evict(self): ..."
    assert np.allclose(p1.generate_single(text), p2.generate_single(text))


def test_overlap_drives_similarity() -> None:
    provider = HashEmbeddingProvider()
    base = provider.generate_single("validate token signature and expiry")
    similar = provider.generate_single("token validation checks the signature")
    different = provider.generate_single("render the html template in the browser")
    # Shared tokens should make the related text more similar than the unrelated.
    assert _cosine(base, similar) > _cosine(base, different)


def test_generate_batch_shapes() -> None:
    provider = HashEmbeddingProvider()
    out = provider.generate(["alpha beta", "gamma delta", "alpha gamma"])
    assert out.shape == (3, DEFAULT_DIM)
    empty = provider.generate([])
    assert empty.shape == (0, DEFAULT_DIM)


def test_identifier_subword_expansion_matches() -> None:
    provider = HashEmbeddingProvider()
    # snake_case / camelCase identifiers should overlap with their subwords.
    snake = provider.generate_single("get_user_token")
    words = provider.generate_single("user token")
    assert _cosine(snake, words) > 0.0


def test_provider_surface_matches_generator() -> None:
    # The provider must expose the same public surface the codebase relies on.
    provider = HashEmbeddingProvider()
    for method in ("generate", "generate_batched", "generate_single", "embed_batch", "embed_text", "embed_query"):
        assert callable(getattr(provider, method))
    assert provider.dimension == DEFAULT_DIM
    assert provider.model_name
