"""HTTP-based embedding providers (Gemini, OpenAI, HuggingFace).

These mirror the public surface of EmbeddingGenerator so the rest of the
codebase doesn't need to know which backend is in use.

DB schema is fixed at vector(768). Each provider must be requested at 768
dimensions and produce L2-normalized vectors.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from collections.abc import Iterable

import numpy as np
import requests

logger = logging.getLogger(__name__)

DEFAULT_DIM = 768

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SUBWORD_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


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
# Hash (zero-download, dependency-free) — for lite/CI/air-gapped deployments
# ---------------------------------------------------------------------------


class HashEmbeddingProvider:
    """A deterministic feature-hashing embedder — no model, no download.

    Hashes token (and identifier-subword) occurrences into a fixed 768-dim
    vector, signed to reduce collisions, then L2-normalizes. Cosine similarity
    therefore reflects shared-token overlap: a lightweight, semantic-free vector
    that still complements the lexical/symbol branches of hybrid retrieval.

    The point is footprint: ``EMBEDDING_PROVIDER=hash`` skips the ~1.2 GB
    sentence-transformers model download and its RAM, so Delphi boots in seconds
    on a laptop, in CI, or air-gapped. You trade embedding-level semantic recall
    for zero setup; BM25 + exact-symbol + trigram retrieval still carry most of
    the quality (see bench/). Switch to a real model when you want semantic
    recall.
    """

    name = "hash"
    dimension = DEFAULT_DIM
    batch_size = 256
    device = "cpu"

    def __init__(self) -> None:
        self.model_name = f"hashing-vectorizer-{self.dimension}"
        logger.info(
            "Using hash embedding provider (no model download, %d-dim)",
            self.dimension,
        )

    @staticmethod
    def _tokens(text: str) -> Iterable[str]:
        for tok in _TOKEN_RE.findall(text.lower()):
            yield tok
            subs = _SUBWORD_RE.findall(tok)
            if len(subs) > 1:
                yield from (s.lower() for s in subs)

    def _vectorize(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dimension, dtype=np.float32)
        for tok in self._tokens(text):
            digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
            h = int.from_bytes(digest, "little")
            idx = h % self.dimension
            sign = 1.0 if (h >> 63) & 1 else -1.0
            vec[idx] += sign
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec

    def generate(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        return np.vstack([self._vectorize(t) for t in texts])

    def generate_batched(self, texts: list[str], batch_size: int | None = None) -> np.ndarray:
        return self.generate(texts)

    def generate_single(self, text: str) -> np.ndarray:
        return self._vectorize(text)

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        return self.generate(texts)

    def embed_text(self, text: str) -> np.ndarray:
        return self._vectorize(text)

    def embed_query(self, query: str) -> np.ndarray:
        return self._vectorize(query)


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
