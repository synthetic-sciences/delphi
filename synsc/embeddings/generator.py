"""Embedding generation for Synsc Context.

Two backends:
- EmbeddingGenerator: Google Gemini API (for code repository indexing)
- PaperEmbeddingGenerator: Local sentence-transformers (for research papers)
"""

import os
import logging
import time
from typing import Optional

import numpy as np

from synsc.config import get_config

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Gemini API backend (for code repos)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class EmbeddingGenerator:
    """Generate embeddings for code chunks using Google Gemini API."""

    def __init__(self, model_name: str | None = None, api_key: str | None = None):
        """Initialize the embedding generator.

        Args:
            model_name: Gemini embedding model name (default from config)
            api_key: Google AI API key (default from config/env)
        """
        from google import genai
        
        config = get_config()
        self.model_name = model_name or config.embeddings.gemini_model_name
        self.batch_size = config.embeddings.batch_size
        self.dimension = config.embeddings.dimension

        # Get API key from: parameter > config > environment
        api_key = (
            api_key
            or config.embeddings.gemini_api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )

        if not api_key:
            raise ValueError(
                "Gemini API key is required for embeddings. "
                "Please set GEMINI_API_KEY or GOOGLE_API_KEY in your environment."
            )

        self.client = genai.Client(api_key=api_key)
        logger.info(
            "Initialized Gemini embedding generator: model=%s, dim=%d, batch_size=%d",
            self.model_name,
            self.dimension,
            self.batch_size,
        )

    def generate(self, texts: list[str]) -> np.ndarray:
        """Generate embeddings for a list of texts.

        Args:
            texts: List of text strings to embed

        Returns:
            numpy array of shape (len(texts), dimension)
        """
        from google.genai import types
        
        if not texts:
            return np.array([]).reshape(0, self.dimension)

        logger.debug("Generating Gemini embeddings for %d texts", len(texts))

        result = self.client.models.embed_content(
            model=self.model_name,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=self.dimension,
            ),
        )

        embeddings = np.array([emb.values for emb in result.embeddings])

        # Normalize for cosine similarity
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        embeddings = embeddings / norms

        return embeddings

    def generate_single(self, text: str) -> np.ndarray:
        """Generate embedding for a single text (used for search queries).

        Args:
            text: Text string to embed

        Returns:
            numpy array of shape (dimension,)
        """
        from google.genai import types
        
        result = self.client.models.embed_content(
            model=self.model_name,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=self.dimension,
            ),
        )

        [embedding_obj] = result.embeddings
        embedding = np.array(embedding_obj.values)

        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        return embedding

    def generate_batched(
        self, texts: list[str], batch_size: int | None = None
    ) -> np.ndarray:
        """Generate embeddings in batches with retry logic.

        Args:
            texts: List of text strings to embed
            batch_size: Batch size (default from config, max 100 for Gemini)

        Returns:
            numpy array of shape (len(texts), dimension)
        """
        if not texts:
            return np.array([]).reshape(0, self.dimension)

        batch_size = min(batch_size or self.batch_size, 100)  # Gemini max is 100
        all_embeddings = []
        total_batches = (len(texts) + batch_size - 1) // batch_size

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_num = i // batch_size + 1

            # Retry logic for rate limiting
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    embeddings = self.generate(batch)
                    all_embeddings.append(embeddings)
                    break
                except Exception as e:
                    if "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower():
                        wait_time = 2 ** attempt
                        logger.warning(
                            "Rate limited, waiting %ds (attempt %d/%d)",
                            wait_time,
                            attempt + 1,
                            max_retries,
                        )
                        time.sleep(wait_time)
                        if attempt == max_retries - 1:
                            raise
                    else:
                        raise

            logger.debug(
                "Batch %d/%d done (%d texts)",
                batch_num,
                total_batches,
                len(batch),
            )

        return np.vstack(all_embeddings)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Sentence-transformers backend (for research papers)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class PaperEmbeddingGenerator:
    """Generate embeddings using a local sentence-transformers model.
    
    Used for research paper indexing — runs locally, no API key required.
    """

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
    ):
        """Initialize the paper embedding generator.

        Args:
            model_name: HuggingFace model name (default from config)
            device: Device for inference ('cpu', 'cuda', 'mps')
        """
        # Suppress tokenizers parallelism warnings
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        
        from sentence_transformers import SentenceTransformer

        config = get_config()
        self.model_name = model_name or config.embeddings.sentence_transformer_model
        self.batch_size = config.embeddings.paper_batch_size
        self.dimension = config.embeddings.dimension
        self.device = device or config.embeddings.paper_device

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
            "Paper embedding generator ready: model=%s, dim=%d, device=%s",
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Singletons
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_embedding_generator: Optional[EmbeddingGenerator] = None
_paper_embedding_generator: Optional[PaperEmbeddingGenerator] = None


def get_embedding_generator() -> EmbeddingGenerator:
    """Get global Gemini embedding generator (for code repos)."""
    global _embedding_generator
    if _embedding_generator is None:
        _embedding_generator = EmbeddingGenerator()
    return _embedding_generator


def get_paper_embedding_generator() -> PaperEmbeddingGenerator:
    """Get global sentence-transformers embedding generator (for papers/datasets).

    With Gunicorn ``--preload``, this is called once in the master process
    during ``create_app()``.  Workers inherit the loaded model via
    copy-on-write memory after fork — no per-worker reload needed.
    """
    global _paper_embedding_generator
    if _paper_embedding_generator is None:
        logger.info("Loading sentence-transformers model...")
        _paper_embedding_generator = PaperEmbeddingGenerator()
        logger.info("Sentence-transformers model ready")
    return _paper_embedding_generator


def set_embedding_generator(generator: EmbeddingGenerator) -> None:
    """Set global Gemini embedding generator."""
    global _embedding_generator
    _embedding_generator = generator


def cleanup_embedding_generator() -> None:
    """Clean up global generators to release resources."""
    global _embedding_generator, _paper_embedding_generator
    _embedding_generator = None
    if _paper_embedding_generator is not None:
        del _paper_embedding_generator.model
        _paper_embedding_generator = None


# Convenience functions
def embed_chunks(texts: list[str]) -> np.ndarray:
    """Embed text chunks using Gemini (for code)."""
    return get_embedding_generator().generate_batched(texts)


def embed_query(query: str) -> np.ndarray:
    """Embed a query using Gemini (for code search)."""
    return get_embedding_generator().generate_single(query)
