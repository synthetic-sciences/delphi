"""Embedding generation for Delphi.

Single backend: sentence-transformers (runs locally, no API key required).
Used for code repositories, research papers, and datasets.
"""

import os
import logging
import time
from typing import Optional

import numpy as np

from synsc.config import get_config

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """Generate embeddings using a local sentence-transformers model.

    Used for all content types (code, papers, datasets) — runs locally, no API key required.
    """

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
    ):
        # Suppress tokenizers parallelism warnings
        os.environ["TOKENIZERS_PARALLELISM"] = "false"

        from sentence_transformers import SentenceTransformer

        config = get_config()
        self.model_name = model_name or config.embeddings.model_name
        self.batch_size = config.embeddings.batch_size
        self.dimension = config.embeddings.dimension
        self.device = device or config.embeddings.device

        # Auto-detect GPU
        if self.device == "cpu":
            try:
                import torch
                if torch.cuda.is_available():
                    self.device = "cuda"
                elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    self.device = "mps"
            except ImportError:
                pass

        logger.info(
            "Loading sentence-transformers model: %s on %s",
            self.model_name,
            self.device,
        )
        self.model = SentenceTransformer(self.model_name, device=self.device)

        # Verify dimension
        test_embedding = self.model.encode("test", convert_to_numpy=True)
        actual_dim = len(test_embedding)
        if actual_dim != self.dimension:
            logger.warning(
                "Configured dimension (%d) doesn't match model dimension (%d). Using actual.",
                self.dimension,
                actual_dim,
            )
            self.dimension = actual_dim

        logger.info(
            "Embedding generator ready: model=%s, dim=%d, device=%s",
            self.model_name,
            self.dimension,
            self.device,
        )

    def generate(self, texts: list[str]) -> np.ndarray:
        """Generate embeddings for a list of texts."""
        if not texts:
            return np.array([]).reshape(0, self.dimension)

        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embeddings

    def generate_single(self, text: str) -> np.ndarray:
        """Generate embedding for a single text."""
        embedding = self.model.encode(
            text,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embedding

    def generate_batched(
        self, texts: list[str], batch_size: int | None = None
    ) -> np.ndarray:
        """Generate embeddings in batches with progress logging."""
        if not texts:
            return np.array([]).reshape(0, self.dimension)

        batch_size = batch_size or self.batch_size

        # For small sets, do it in one call
        if len(texts) <= batch_size:
            return self.generate(texts)

        all_embeddings = []
        total_batches = (len(texts) + batch_size - 1) // batch_size

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_num = i // batch_size + 1

            start = time.time()
            embeddings = self.generate(batch)
            elapsed = time.time() - start

            all_embeddings.append(embeddings)
            logger.debug(
                "Batch %d/%d done (%.1fs, %d texts)",
                batch_num,
                total_batches,
                elapsed,
                len(batch),
            )

        return np.vstack(all_embeddings)

    # Aliases for compatibility
    def embed_batch(self, texts: list[str]) -> np.ndarray:
        return self.generate_batched(texts)

    def embed_text(self, text: str) -> np.ndarray:
        return self.generate_single(text)

    def embed_query(self, query: str) -> np.ndarray:
        return self.generate_single(query)


# Alias for backward compatibility
PaperEmbeddingGenerator = EmbeddingGenerator


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Singletons
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_embedding_generator: Optional[EmbeddingGenerator] = None


def get_embedding_generator() -> EmbeddingGenerator:
    """Get global embedding generator."""
    global _embedding_generator
    if _embedding_generator is None:
        logger.info("Loading sentence-transformers model...")
        _embedding_generator = EmbeddingGenerator()
        logger.info("Embedding model ready")
    return _embedding_generator


# Alias — papers and code now use the same local model
get_paper_embedding_generator = get_embedding_generator


def set_embedding_generator(generator: EmbeddingGenerator) -> None:
    """Set global embedding generator."""
    global _embedding_generator
    _embedding_generator = generator


def cleanup_embedding_generator() -> None:
    """Clean up global generator to release resources."""
    global _embedding_generator
    if _embedding_generator is not None:
        del _embedding_generator.model
        _embedding_generator = None


# Convenience functions
def embed_chunks(texts: list[str]) -> np.ndarray:
    """Embed text chunks (for code/papers/datasets)."""
    return get_embedding_generator().generate_batched(texts)


def embed_query(query: str) -> np.ndarray:
    """Embed a search query."""
    return get_embedding_generator().generate_single(query)
