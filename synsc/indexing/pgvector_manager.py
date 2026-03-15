"""pgvector index management for cloud-based vector search.

This module handles vector storage and search using PostgreSQL's pgvector extension.
Embeddings are SHARED for public repos (no per-user duplication).
"""

import time
from typing import Any

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.orm import Session

from synsc.config import get_config
from synsc.database.connection import get_session

logger = structlog.get_logger(__name__)


class PgVectorManager:
    """Manage pgvector indices for semantic code search in PostgreSQL.
    
    DEDUPLICATION: Embeddings are stored per-repo, NOT per-user.
    Access control is handled via Repository.is_public and UserRepository.
    """

    def __init__(self):
        """Initialize the pgvector manager."""
        config = get_config()
        self.dimension = config.embeddings.dimension

    def add_embeddings(
        self,
        session: Session,
        embeddings: np.ndarray,
        chunk_ids: list[str],
        repo_id: str,
    ) -> list[str]:
        """Add embeddings to the pgvector table.
        
        NOTE: No user_id - embeddings are shared for public repos.
        Access control is via Repository.is_public and UserRepository.
        
        Args:
            session: Database session
            embeddings: numpy array of shape (n, dimension)
            chunk_ids: List of chunk IDs corresponding to embeddings
            repo_id: Repository ID
            
        Returns:
            List of embedding IDs created
        """
        if embeddings.ndim == 1:
            embeddings = embeddings.reshape(1, -1)
        
        # Ensure float32 and contiguous
        embeddings = np.ascontiguousarray(embeddings, dtype=np.float32)
        
        if len(chunk_ids) != embeddings.shape[0]:
            raise ValueError(
                f"Mismatch: {len(chunk_ids)} chunk_ids but {embeddings.shape[0]} embeddings"
            )
        
        embedding_ids = []

        # Batch insert embeddings — larger batches reduce DB round-trips to Supabase.
        # Each embedding is 768 floats (~6KB as text), so 250 per batch ≈ 1.5MB payload.
        batch_size = 250
        total_batches = (len(chunk_ids) + batch_size - 1) // batch_size
        for i in range(0, len(chunk_ids), batch_size):
            batch_chunk_ids = chunk_ids[i:i + batch_size]
            batch_embeddings = embeddings[i:i + batch_size]
            batch_num = i // batch_size + 1

            # Build VALUES clause for batch insert
            values_parts = []
            params: dict[str, Any] = {"rid": repo_id}
            for j, (chunk_id, embedding) in enumerate(
                zip(batch_chunk_ids, batch_embeddings)
            ):
                values_parts.append(f"(:cid_{j}, :rid, :emb_{j})")
                params[f"cid_{j}"] = chunk_id
                params[f"emb_{j}"] = str(embedding.tolist())

            values_sql = ", ".join(values_parts)
            insert_start = time.time()
            result = session.execute(
                text(f"""
                    INSERT INTO chunk_embeddings (chunk_id, repo_id, embedding)
                    VALUES {values_sql}
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        embedding = EXCLUDED.embedding
                    RETURNING embedding_id
                """),
                params,
            )
            embedding_ids.extend(str(row[0]) for row in result.fetchall())
            logger.info(
                "Stored embedding batch",
                batch=f"{batch_num}/{total_batches}",
                size=len(batch_chunk_ids),
                insert_ms=round((time.time() - insert_start) * 1000),
            )

        logger.info(
            "All embeddings stored in pgvector",
            count=len(embedding_ids),
            repo_id=repo_id,
        )

        return embedding_ids

    def search(
        self,
        query_embedding: np.ndarray,
        user_id: str,
        repo_ids: list[str] | None = None,
        language: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Search for similar vectors using pgvector.
        
        ACCESS CONTROL:
        - Only searches repos in user's collection (user_repositories)
        - For public repos: user must have added it to their collection
        - For private repos: only the indexer can search
        
        Args:
            query_embedding: Query vector of shape (dimension,) or (1, dimension)
            user_id: User ID for access control
            repo_ids: Optional list of repo IDs to filter (within user's collection)
            language: Optional language filter
            top_k: Number of results to return
            
        Returns:
            List of search results with chunk info and similarity scores
        """
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)
        
        query_embedding = np.ascontiguousarray(query_embedding, dtype=np.float32)
        query_list = query_embedding[0].tolist()
        
        with get_session() as session:
            # Format the vector as a string for direct SQL embedding
            # This is safe since we control the embedding generation
            vector_str = "[" + ",".join(str(x) for x in query_list) + "]"
            
            # Build the query with access control via user_repositories
            query_params = {
                "user_id": user_id,
                "top_k": top_k,
            }
            
            # Build optional filters
            extra_filters = ""
            if repo_ids:
                extra_filters += " AND ce.repo_id = ANY(CAST(:repo_ids AS uuid[]))"
                query_params["repo_ids"] = repo_ids
            
            if language:
                extra_filters += " AND cc.language = :language"
                query_params["language"] = language
            
            # OPTIMIZED QUERY:
            # - Use JOIN instead of EXISTS subquery (faster with proper indexes)
            # - Pre-filter by user's repos before vector search
            # - Use CTE for better query planning
            result = session.execute(
                text(f"""
                    WITH user_repos AS MATERIALIZED (
                        SELECT ur.repo_id 
                        FROM user_repositories ur
                        WHERE ur.user_id = :user_id
                    )
                    SELECT 
                        cc.chunk_id,
                        cc.repo_id,
                        cc.file_id,
                        cc.content,
                        cc.start_line,
                        cc.end_line,
                        cc.chunk_type,
                        cc.language,
                        cc.token_count,
                        cc.symbol_names,
                        cc.chunk_index,
                        rf.file_path,
                        r.owner,
                        r.name as repo_name,
                        r.is_public,
                        1 - (ce.embedding <=> '{vector_str}'::vector) as similarity
                    FROM chunk_embeddings ce
                    INNER JOIN user_repos urp ON ce.repo_id = urp.repo_id
                    INNER JOIN repositories r ON ce.repo_id = r.repo_id
                        AND (r.is_public = TRUE OR r.indexed_by = :user_id)
                    INNER JOIN code_chunks cc ON ce.chunk_id = cc.chunk_id
                    INNER JOIN repository_files rf ON cc.file_id = rf.file_id
                    WHERE 1=1 {extra_filters}
                    ORDER BY ce.embedding <=> '{vector_str}'::vector
                    LIMIT :top_k
                """),
                query_params
            )
            
            results = []
            for row in result.fetchall():
                results.append({
                    "chunk_id": str(row.chunk_id),
                    "repo_id": str(row.repo_id),
                    "file_id": str(row.file_id),
                    "content": row.content,
                    "start_line": row.start_line,
                    "end_line": row.end_line,
                    "chunk_type": row.chunk_type,
                    "language": row.language,
                    "token_count": row.token_count,
                    "symbol_names": row.symbol_names,
                    "chunk_index": row.chunk_index,
                    "file_path": row.file_path,
                    "repo_name": f"{row.owner}/{row.repo_name}",
                    "is_public": row.is_public,
                    "similarity": float(row.similarity),
                })
            
            return results

    def delete_by_repo(self, session: Session, repo_id: str) -> int:
        """Delete all embeddings for a repository.
        
        Args:
            session: Database session
            repo_id: Repository ID
            
        Returns:
            Number of embeddings deleted
        """
        result = session.execute(
            text("DELETE FROM chunk_embeddings WHERE repo_id = :repo_id"),
            {"repo_id": repo_id}
        )
        count = result.rowcount
        
        logger.info(
            "Deleted embeddings for repository",
            repo_id=repo_id,
            count=count,
        )
        
        return count

    def delete_by_user_repos(self, session: Session, user_id: str) -> int:
        """Delete all embeddings for repos that a user owns (indexed).
        
        NOTE: This deletes the actual embeddings, not just the user's access.
        Only use this for private repos or when the user is the indexer.
        
        Args:
            session: Database session
            user_id: User ID (the indexer)
            
        Returns:
            Number of embeddings deleted
        """
        # Delete embeddings only for repos this user actually indexed
        result = session.execute(
            text("""
                DELETE FROM chunk_embeddings ce
                WHERE ce.repo_id IN (
                    SELECT r.repo_id FROM repositories r 
                    WHERE r.indexed_by = :user_id
                )
            """),
            {"user_id": user_id}
        )
        count = result.rowcount
        
        logger.info(
            "Deleted embeddings for user's indexed repos",
            user_id=user_id,
            count=count,
        )
        
        return count

    def get_total_vectors(self, user_id: str | None = None) -> int:
        """Get total number of vectors in the index.
        
        Args:
            user_id: Optional - count vectors in repos accessible to this user
            
        Returns:
            Total vector count
        """
        with get_session() as session:
            if user_id:
                # Count vectors in repos the user can access
                result = session.execute(
                    text("""
                        SELECT COUNT(*) FROM chunk_embeddings ce
                        JOIN repositories r ON ce.repo_id = r.repo_id
                        WHERE EXISTS (
                            SELECT 1 FROM user_repositories ur 
                            WHERE ur.user_id = :user_id AND ur.repo_id = r.repo_id
                        )
                    """),
                    {"user_id": user_id}
                )
            else:
                result = session.execute(
                    text("SELECT COUNT(*) FROM chunk_embeddings")
                )
            
            row = result.fetchone()
            return row[0] if row else 0


# Singleton instance
_pgvector_manager: PgVectorManager | None = None


def get_pgvector_manager() -> PgVectorManager:
    """Get the singleton pgvector manager instance."""
    global _pgvector_manager
    if _pgvector_manager is None:
        _pgvector_manager = PgVectorManager()
    return _pgvector_manager
