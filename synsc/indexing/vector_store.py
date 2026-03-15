"""Vector store using pgvector for semantic search.

All vector storage is done in PostgreSQL using the pgvector extension.
Embeddings are SHARED for public repos (no per-user duplication).
"""

from typing import Any

import numpy as np
import structlog
from sqlalchemy.orm import Session

from synsc.indexing.pgvector_manager import PgVectorManager

logger = structlog.get_logger(__name__)


class VectorStore:
    """pgvector-based vector store for PostgreSQL.
    
    DEDUPLICATION: Embeddings are stored per-repo, NOT per-user.
    This saves 90%+ storage when multiple users index popular public repos.
    
    Access control is via:
    - Repository.is_public (public repos can be searched by anyone who added them)
    - UserRepository junction table (tracks which users have access)
    """
    
    def __init__(self):
        self._manager = PgVectorManager()
        logger.info("Vector store initialized (pgvector)")
    
    def add(
        self,
        embeddings: np.ndarray,
        chunk_ids: list[str],
        repo_id: str,
        session: Session | None = None,
    ) -> list[str]:
        """Add embeddings to pgvector.
        
        NOTE: No user_id - embeddings are shared for public repos.
        
        Args:
            embeddings: Numpy array of embeddings (N x dimension)
            chunk_ids: List of chunk IDs corresponding to embeddings
            repo_id: Repository ID
            session: Optional database session (creates new if not provided)
            
        Returns:
            List of embedding IDs created
        """
        if session is None:
            from synsc.database.connection import get_session
            with get_session() as sess:
                return self._manager.add_embeddings(
                    sess, embeddings, chunk_ids, repo_id
                )
        else:
            return self._manager.add_embeddings(
                session, embeddings, chunk_ids, repo_id
            )
    
    def search(
        self,
        query_embedding: np.ndarray,
        user_id: str | None = None,
        repo_ids: list[str] | None = None,
        language: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Search pgvector for similar code.
        
        Args:
            query_embedding: Query vector
            user_id: User ID for multi-tenant filtering (required)
            repo_ids: Optional list of repository IDs to search
            language: Optional language filter
            top_k: Number of results to return
            
        Returns:
            List of search results with similarity scores
        """
        if user_id is None:
            raise ValueError("user_id is required for vector search in cloud mode")
        
        return self._manager.search(
            query_embedding,
            user_id=user_id,
            repo_ids=repo_ids,
            language=language,
            top_k=top_k,
        )
    
    def delete_by_repo(self, repo_id: str, session: Session | None = None) -> int:
        """Delete all embeddings for a repository.
        
        Args:
            repo_id: Repository ID
            session: Optional database session
            
        Returns:
            Number of embeddings deleted
        """
        if session is None:
            from synsc.database.connection import get_session
            with get_session() as sess:
                return self._manager.delete_by_repo(sess, repo_id)
        else:
            return self._manager.delete_by_repo(session, repo_id)
    
    def store_batch(
        self,
        chunk_ids: list[str],
        embeddings: np.ndarray,
        repo_id: str,
        session: Session | None = None,
    ) -> list[str]:
        """Store a batch of embeddings — convenience alias for add().
        
        Args:
            chunk_ids: List of chunk IDs
            embeddings: Numpy array of embeddings (N x dimension)
            repo_id: Repository ID
            session: Optional database session
            
        Returns:
            List of embedding IDs created
        """
        return self.add(
            embeddings=embeddings,
            chunk_ids=chunk_ids,
            repo_id=repo_id,
            session=session,
        )
    
    def save(self) -> None:
        """No-op for pgvector (data is persisted in PostgreSQL)."""
        pass
    
    @property
    def total_vectors(self) -> int:
        """Get total number of vectors in the store."""
        return self._manager.get_total_vectors()


# Singleton vector store instance
_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Get the vector store instance."""
    global _vector_store
    
    if _vector_store is None:
        _vector_store = VectorStore()
    
    return _vector_store


def reset_vector_store() -> None:
    """Reset the vector store singleton (for testing or reconfiguration)."""
    global _vector_store
    _vector_store = None
