"""FAISS index management for vector search."""

from pathlib import Path

import faiss
import numpy as np
import structlog

from synsc.config import get_config

logger = structlog.get_logger(__name__)


class FAISSManager:
    """Manage FAISS indices for semantic code search."""

    def __init__(self, index_path: Path | str | None = None):
        """Initialize the FAISS manager.
        
        Args:
            index_path: Path to store/load the index
        """
        config = get_config()
        self.dimension = config.embeddings.dimension
        self.index_type = config.faiss.index_type
        self.nlist = config.faiss.nlist
        self.nprobe = config.faiss.nprobe
        
        if index_path is None:
            index_path = config.storage.indices_dir / "main.index"
        self.index_path = Path(index_path)
        
        self._index: faiss.Index | None = None

    def _create_index(self) -> faiss.Index:
        """Create a new FAISS index."""
        logger.info(
            "Creating FAISS index",
            type=self.index_type,
            dimension=self.dimension,
        )
        
        if self.index_type == "IndexFlatL2":
            index = faiss.IndexFlatL2(self.dimension)
        elif self.index_type == "IndexFlatIP":
            # Inner Product for cosine similarity (when vectors are normalized)
            index = faiss.IndexFlatIP(self.dimension)
        elif self.index_type == "IndexIVFFlat":
            quantizer = faiss.IndexFlatIP(self.dimension)
            index = faiss.IndexIVFFlat(quantizer, self.dimension, self.nlist)
            index.nprobe = self.nprobe
        else:
            raise ValueError(f"Unknown index type: {self.index_type}")
        
        return index

    @property
    def index(self) -> faiss.Index:
        """Get or create the FAISS index."""
        if self._index is None:
            if self.index_path.exists():
                self._index = self.load()
            else:
                self._index = self._create_index()
        return self._index

    def add(self, embeddings: np.ndarray) -> list[int]:
        """Add embeddings to the index.
        
        Args:
            embeddings: numpy array of shape (n, dimension)
            
        Returns:
            List of vector IDs assigned
        """
        if embeddings.ndim == 1:
            embeddings = embeddings.reshape(1, -1)
        
        # Ensure float32 and contiguous
        embeddings = np.ascontiguousarray(embeddings, dtype=np.float32)
        
        # For IVF indices, need to train first if not trained
        if self.index_type == "IndexIVFFlat" and not self.index.is_trained:
            if embeddings.shape[0] >= self.nlist:
                logger.info("Training IVF index", vectors=embeddings.shape[0])
                self.index.train(embeddings)
            else:
                logger.warning(
                    "Not enough vectors to train IVF index, using flat index",
                    vectors=embeddings.shape[0],
                    required=self.nlist,
                )
                # Fall back to flat index
                self._index = faiss.IndexFlatIP(self.dimension)
        
        start_id = self.index.ntotal
        self.index.add(embeddings)
        
        vector_ids = list(range(start_id, start_id + embeddings.shape[0]))
        
        logger.debug(
            "Added vectors to index",
            count=embeddings.shape[0],
            total=self.index.ntotal,
        )
        
        return vector_ids

    def search(
        self, query_embedding: np.ndarray, top_k: int = 10
    ) -> tuple[np.ndarray, np.ndarray]:
        """Search for similar vectors.
        
        Args:
            query_embedding: Query vector of shape (dimension,) or (1, dimension)
            top_k: Number of results to return
            
        Returns:
            Tuple of (distances, indices) arrays
        """
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)
        
        query_embedding = np.ascontiguousarray(query_embedding, dtype=np.float32)
        
        # Ensure we don't request more than available
        k = min(top_k, self.index.ntotal)
        if k == 0:
            return np.array([[]]), np.array([[]])
        
        distances, indices = self.index.search(query_embedding, k)
        
        return distances[0], indices[0]

    def save(self) -> None:
        """Save the index to disk."""
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(self.index_path))
        logger.info(
            "Saved FAISS index",
            path=str(self.index_path),
            vectors=self.index.ntotal,
        )

    def load(self) -> faiss.Index:
        """Load the index from disk."""
        logger.info("Loading FAISS index", path=str(self.index_path))
        index = faiss.read_index(str(self.index_path))
        
        if self.index_type == "IndexIVFFlat":
            index.nprobe = self.nprobe
        
        return index

    def reset(self) -> None:
        """Reset the index (remove all vectors)."""
        self._index = self._create_index()
        if self.index_path.exists():
            self.index_path.unlink()
        logger.info("Reset FAISS index")

    @property
    def total_vectors(self) -> int:
        """Get the total number of vectors in the index."""
        return self.index.ntotal
