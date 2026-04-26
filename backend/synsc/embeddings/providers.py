"""HTTP-based embedding providers (Gemini, OpenAI).

These mirror the public surface of EmbeddingGenerator so the rest of the
codebase doesn't need to know which backend is in use.

DB schema is fixed at vector(768). Each provider must be requested at 768
dimensions and produce L2-normalized vectors.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Iterable

import numpy as np
import requests

logger = logging.getLogger(__name__)

DEFAULT_DIM = 768


def _l2_normalize(vec: list[float]) -> list[float]:
    """Normalize a vector to unit length. Returns the input on zero norm."""
    s = math.sqrt(sum(v * v for v in vec))
    if s == 0:
        return vec
    return [v / s for v in vec]


class _HttpEmbeddingProvider:
    """Base class for API-based providers.

    Subclasses implement `_embed_batch(texts) -> list[list[float]]`. Everything
    else (single, batched, np conversion) is shared.
    """

    name: str = "http"
    model_name: str
    dimension: int = DEFAULT_DIM
    batch_size: int = 64
    device: str = "remote"

    # Subclasses set these:
    _api_key_env: str = ""

    def __init__(self) -> None:
        # Provider-specific env var wins (GEMINI_API_KEY, OPENAI_API_KEY, ...);
        # fall back to the generic EMBEDDING_API_KEY so users can set one
        # key when they only need a single provider.
        self.api_key = os.getenv(self._api_key_env, "") or os.getenv(
            "EMBEDDING_API_KEY", ""
        )
        if not self.api_key:
            raise RuntimeError(
                f"{self.name}: set {self._api_key_env} (or the generic "
                "EMBEDDING_API_KEY) in the environment."
            )

    # ------------------------------------------------------------------
    # Subclass hook
    # ------------------------------------------------------------------

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Public surface — matches EmbeddingGenerator
    # ------------------------------------------------------------------

    def generate(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            chunk = texts[i : i + self.batch_size]
            out.extend(self._embed_batch(chunk))
        return np.asarray(out, dtype=np.float32)

    def generate_batched(self, texts: list[str], batch_size: int | None = None) -> np.ndarray:
        if batch_size:
            saved = self.batch_size
            self.batch_size = batch_size
            try:
                return self.generate(texts)
            finally:
                self.batch_size = saved
        return self.generate(texts)

    def generate_single(self, text: str) -> np.ndarray:
        out = self._embed_batch([text])
        return np.asarray(out[0], dtype=np.float32)

    # Aliases for compatibility with EmbeddingGenerator
    def embed_batch(self, texts: list[str]) -> np.ndarray:
        return self.generate_batched(texts)

    def embed_text(self, text: str) -> np.ndarray:
        return self.generate_single(text)

    def embed_query(self, query: str) -> np.ndarray:
        return self.generate_single(query)


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


class GeminiEmbeddingProvider(_HttpEmbeddingProvider):
    """Google Gemini embeddings (gemini-embedding-001).

    https://ai.google.dev/gemini-api/docs/embeddings
    """

    name = "gemini"
    model_name = "gemini-embedding-001"
    _api_key_env = "GEMINI_API_KEY"
    _endpoint = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents"

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        body = {
            "requests": [
                {
                    "model": "models/gemini-embedding-001",
                    "content": {"parts": [{"text": t}]},
                    "outputDimensionality": self.dimension,
                }
                for t in texts
            ]
        }
        resp = requests.post(
            f"{self._endpoint}?key={self.api_key}",
            headers={"Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini embeddings HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        embeddings = data.get("embeddings") or []
        # Truncated outputs from Gemini are NOT pre-normalized; do it ourselves.
        return [_l2_normalize(e["values"]) for e in embeddings]


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class OpenAIEmbeddingProvider(_HttpEmbeddingProvider):
    """OpenAI embeddings (text-embedding-3-small by default).

    https://platform.openai.com/docs/api-reference/embeddings
    """

    name = "openai"
    model_name = "text-embedding-3-small"
    _api_key_env = "OPENAI_API_KEY"
    _endpoint = "https://api.openai.com/v1/embeddings"

    def __init__(self) -> None:
        super().__init__()
        # Allow overriding the model (e.g. text-embedding-3-large)
        self.model_name = os.getenv("OPENAI_EMBEDDING_MODEL", self.model_name)

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        body = {
            "model": self.model_name,
            "input": texts,
            "dimensions": self.dimension,
            "encoding_format": "float",
        }
        resp = requests.post(
            self._endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI embeddings HTTP {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
        # OpenAI text-embedding-3-* returns unit vectors at the requested dim.
        return [_l2_normalize(it["embedding"]) for it in items]
