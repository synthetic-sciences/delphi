"""HTTP-based embedding providers (Gemini, OpenAI, HuggingFace).

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


# ---------------------------------------------------------------------------
# HuggingFace Inference API
# ---------------------------------------------------------------------------


class HuggingFaceEmbeddingProvider(_HttpEmbeddingProvider):
    """HuggingFace Inference API embeddings (any feature-extraction model).

    Driven by two env vars:

      * `EMBEDDING_MODEL` — repo id on the Hub. Default
        `BAAI/bge-base-en-v1.5` (768 dim, served on free serverless inference).
        Other good picks: `sentence-transformers/all-mpnet-base-v2` (768),
        `mixedbread-ai/mxbai-embed-large-v1` (1024 → truncated, Matryoshka),
        `Qwen/Qwen3-Embedding-0.6B` (1024 → truncated, Matryoshka — needs a
        dedicated Inference Endpoint, free serverless does not host it).

      * `HF_INFERENCE_ENDPOINT` — optional override, full URL.  Use this when
        you've deployed the model to a paid HF Inference Endpoint and the
        default `api-inference.huggingface.co` URL would 404.

    Models with native dim > 768 are sliced to 768 via Matryoshka truncation
    (slice + L2 renorm). This is only meaningful for models *trained* with
    Matryoshka representation learning (Qwen3-Embedding, jina-embeddings-v3,
    mxbai-embed-large-v1, OpenAI text-embedding-3-*). For others, prefer a
    768-native model — silently truncating arbitrary embeddings degrades
    semantic quality.

    Models with native dim < 768 raise at first call: pgvector schema is
    fixed at 768 and we don't pad.

    Some models (notably raw transformer encoders) return token-level vectors
    of shape [seq_len, dim] instead of pooled [dim]. We mean-pool over the
    sequence axis to match what sentence-transformers does internally.
    """

    name = "huggingface"
    _api_key_env = "HF_TOKEN"
    _default_model = "BAAI/bge-base-en-v1.5"

    def __init__(self) -> None:
        super().__init__()
        self.model_name = os.getenv("EMBEDDING_MODEL", self._default_model).strip()
        override = os.getenv("HF_INFERENCE_ENDPOINT", "").strip()
        self._endpoint = override or (
            f"https://api-inference.huggingface.co/pipeline/feature-extraction/{self.model_name}"
        )

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = requests.post(
            self._endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            # `wait_for_model` avoids a 503 "model loading" race on the first
            # call after a cold serverless instance.
            json={"inputs": texts, "options": {"wait_for_model": True}},
            timeout=120,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"HuggingFace embeddings HTTP {resp.status_code} for "
                f"{self.model_name}: {resp.text[:500]}"
            )
        data = resp.json()
        out: list[list[float]] = []
        for item in data:
            arr = np.asarray(item, dtype=np.float32)
            if arr.ndim == 2:
                # Token-level output — mean-pool to a single vector.
                arr = arr.mean(axis=0)
            elif arr.ndim != 1:
                raise RuntimeError(
                    f"HuggingFace returned unexpected shape {arr.shape} for "
                    f"{self.model_name}; expected 1-D or 2-D."
                )
            native_dim = arr.shape[0]
            if native_dim < self.dimension:
                raise RuntimeError(
                    f"Model {self.model_name} produced {native_dim}-dim "
                    f"vectors; pgvector schema is fixed at {self.dimension}. "
                    "Pick a model with native dim ≥ 768 (e.g. BAAI/bge-base-en-v1.5)."
                )
            vec = arr[: self.dimension].tolist()
            out.append(_l2_normalize(vec))
        return out
