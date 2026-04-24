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
        # Prevent CUDA memory fragmentation on small GPUs
        if "PYTORCH_CUDA_ALLOC_CONF" not in os.environ:
            os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

        from sentence_transformers import SentenceTransformer

        config = get_config()
        self.model_name = model_name or config.embeddings.model_name
        self.batch_size = config.embeddings.batch_size
        self.dimension = config.embeddings.dimension
        self.device = device or config.embeddings.device

        # Auto-detect GPU only when no explicit device was configured
        explicit_device = device or os.getenv("EMBEDDING_DEVICE")
        if not explicit_device:
            try:
                import torch
                if torch.cuda.is_available():
                    self.device = "cuda"
                elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    self.device = "mps"
            except ImportError:
                pass

        # Scale batch size to available VRAM on CUDA
        if self.device == "cuda":
            try:
                import torch
                free_gb = torch.cuda.mem_get_info()[0] / (1024 ** 3)
                # ~0.5 GB per 64 batch for all-mpnet-base-v2
                # Conservative: leave headroom for model weights + activations
                vram_batch = max(16, min(int(free_gb * 128), 512))
                if vram_batch < self.batch_size:
                    logger.info(
                        "Scaling batch_size to fit VRAM: %d → %d (%.1f GiB free)",
                        self.batch_size, vram_batch, free_gb,
                    )
                    self.batch_size = vram_batch
            except Exception:
                pass

        logger.info(
            "Loading sentence-transformers model: %s on %s",
            self.model_name,
            self.device,
        )
        # trust_remote_code needed for models like jina-embeddings-v2-base-code
        self.model = SentenceTransformer(
            self.model_name, device=self.device, trust_remote_code=True
        )

        # Verify dimension matches DB schema (vector(768) in setup_local.sql)
        test_embedding = self.model.encode("test", convert_to_numpy=True)
        actual_dim = len(test_embedding)
        if actual_dim != self.dimension:
            logger.warning(
                "Configured dimension (%d) doesn't match model dimension (%d). Using actual.",
                self.dimension,
                actual_dim,
            )
            self.dimension = actual_dim
        if actual_dim != 768:
            logger.error(
                "Model dimension (%d) != DB schema dimension (768). "
                "Update setup_local.sql vector columns or choose a 768-dim model. "
                "Indexing will fail with a dimension mismatch error.",
                actual_dim,
            )

        logger.info(
            "Embedding generator ready: model=%s, dim=%d, device=%s, batch_size=%d",
            self.model_name,
            self.dimension,
            self.device,
            self.batch_size,
        )

    def generate(self, texts: list[str]) -> np.ndarray:
        """Generate embeddings for a list of texts.

        On CUDA OOM, halves the batch size and retries (down to 8).
        """
        if not texts:
            return np.array([]).reshape(0, self.dimension)

        # Free cached CUDA memory before each encode to prevent fragmentation
        if self.device == "cuda":
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass

        batch_size = self.batch_size
        while batch_size >= 8:
            try:
                embeddings = self.model.encode(
                    texts,
                    batch_size=batch_size,
                    convert_to_numpy=True,
                    show_progress_bar=len(texts) > 10,
                    normalize_embeddings=True,
                )
                # If we had to reduce, keep the smaller size for future calls
                if batch_size < self.batch_size:
                    logger.info("Reducing batch_size for future calls: %d", batch_size)
                    self.batch_size = batch_size
                return embeddings
            except RuntimeError as e:
                if "out of memory" in str(e).lower() and batch_size > 8:
                    import torch
                    torch.cuda.empty_cache()
                    batch_size //= 2
                    logger.warning(
                        "CUDA OOM, retrying with smaller batch: %d", batch_size,
                    )
                else:
                    raise
        raise RuntimeError("CUDA OOM even at batch_size=8")

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
        """Generate embeddings in batches with progress bar."""
        if not texts:
            return np.array([]).reshape(0, self.dimension)

        batch_size = batch_size or self.batch_size

        # Let sentence-transformers handle batching + tqdm internally
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            show_progress_bar=len(texts) > 10,
            normalize_embeddings=True,
        )
        return embeddings

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
