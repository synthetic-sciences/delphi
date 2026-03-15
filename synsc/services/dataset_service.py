"""
Dataset Service - Main orchestrator for HuggingFace dataset indexing workflow.

Uses SQLAlchemy + pgvector for ALL storage.
100% stateless -- no local files.

Coordinates:
- HuggingFace Hub metadata fetching
- Deduplication (via PostgreSQL)
- Dataset card chunking
- Embedding generation (sentence-transformers)
- PostgreSQL storage
"""

import json
import time
import uuid
from typing import Any, Optional

import structlog
from sqlalchemy import text

from synsc.database.connection import get_session

logger = structlog.get_logger(__name__)


class DatasetService:
    """Service for HuggingFace dataset indexing and management using SQLAlchemy + pgvector."""

    def __init__(self, user_id: str):
        self.user_id = user_id

    def _check_duplicate_by_hf_id(self, hf_id: str) -> Optional[dict]:
        """Check if dataset with this HF ID already exists."""
        try:
            with get_session() as session:
                row = session.execute(
                    text("SELECT * FROM datasets WHERE hf_id = :hf_id LIMIT 1"),
                    {"hf_id": hf_id},
                ).fetchone()
                if row:
                    return dict(row._mapping)
        except Exception as e:
            logger.warning(f"Failed to check HF duplicate: {e}")
        return None

    def _user_has_dataset(self, dataset_id: str) -> bool:
        """Check if user already has access to this dataset."""
        try:
            with get_session() as session:
                row = session.execute(
                    text(
                        "SELECT 1 FROM user_datasets "
                        "WHERE user_id = :uid AND dataset_id = :did LIMIT 1"
                    ),
                    {"uid": self.user_id, "did": dataset_id},
                ).fetchone()
                return row is not None
        except Exception as e:
            logger.warning(f"Failed to check user dataset access: {e}")
        return False

    def _grant_user_access(self, dataset_id: str) -> bool:
        """Grant user access to a dataset."""
        try:
            with get_session() as session:
                existing = session.execute(
                    text(
                        "SELECT 1 FROM user_datasets "
                        "WHERE user_id = :uid AND dataset_id = :did LIMIT 1"
                    ),
                    {"uid": self.user_id, "did": dataset_id},
                ).fetchone()
                if not existing:
                    session.execute(
                        text(
                            "INSERT INTO user_datasets (user_id, dataset_id) "
                            "VALUES (:uid, :did)"
                        ),
                        {"uid": self.user_id, "did": dataset_id},
                    )
            return True
        except Exception as e:
            logger.warning(f"Failed to grant user access: {e}")
        return False

    def _dataset_has_embeddings(self, dataset_id: str) -> bool:
        """Check if a dataset has any embeddings stored."""
        try:
            with get_session() as session:
                row = session.execute(
                    text(
                        "SELECT 1 FROM dataset_chunk_embeddings "
                        "WHERE dataset_id = :did LIMIT 1"
                    ),
                    {"did": dataset_id},
                ).fetchone()
                return row is not None
        except Exception:
            return False

    def _delete_dataset_fully(self, dataset_id: str) -> bool:
        """Fully delete a dataset and all related data.

        Used to clean up stale records that have no embeddings so they can be re-indexed.
        """
        try:
            with get_session() as session:
                # Order matters due to FK constraints:
                # embeddings -> chunks -> user_datasets -> datasets
                session.execute(
                    text("DELETE FROM dataset_chunk_embeddings WHERE dataset_id = :did"),
                    {"did": dataset_id},
                )
                session.execute(
                    text("DELETE FROM dataset_chunks WHERE dataset_id = :did"),
                    {"did": dataset_id},
                )
                session.execute(
                    text("DELETE FROM user_datasets WHERE dataset_id = :did"),
                    {"did": dataset_id},
                )
                session.execute(
                    text("DELETE FROM datasets WHERE dataset_id = :did"),
                    {"did": dataset_id},
                )
            logger.info("Deleted stale dataset record", dataset_id=dataset_id)
            return True
        except Exception as e:
            logger.error(f"Failed to fully delete dataset: {e}")
            return False

    def index_dataset(self, hf_id: str, hf_token: str | None = None) -> dict[str, Any]:
        """Index a HuggingFace dataset.

        Args:
            hf_id: HuggingFace dataset identifier (e.g. "imdb", "openai/gsm8k")
            hf_token: Optional HuggingFace API token for authenticated access

        Returns:
            Dictionary with indexing results
        """
        start_time = time.time()

        try:
            # Step 1: Parse and normalize hf_id
            from synsc.core.huggingface_client import parse_hf_dataset_id, HuggingFaceError
            try:
                hf_id = parse_hf_dataset_id(hf_id)
            except HuggingFaceError as e:
                return {"success": False, "error": str(e)}

            # Step 2: Check deduplication
            existing = self._check_duplicate_by_hf_id(hf_id)
            if existing:
                dataset_id = existing["dataset_id"]
                has_embeddings = self._dataset_has_embeddings(dataset_id)

                if self._user_has_dataset(dataset_id) and has_embeddings:
                    logger.info(
                        "Dataset already indexed", hf_id=hf_id, dataset_id=dataset_id
                    )
                    elapsed = (time.time() - start_time) * 1000
                    return {
                        "success": True,
                        "status": "already_indexed",
                        "dataset_id": dataset_id,
                        "name": existing.get("name", hf_id),
                        "hf_id": hf_id,
                        "message": "Dataset already indexed in your library.",
                        "time_ms": round(elapsed, 1),
                    }

                if has_embeddings:
                    # Dataset exists with embeddings, just grant access
                    self._grant_user_access(dataset_id)
                    elapsed = (time.time() - start_time) * 1000
                    return {
                        "success": True,
                        "status": "access_granted",
                        "dataset_id": dataset_id,
                        "name": existing.get("name", hf_id),
                        "hf_id": hf_id,
                        "message": "Access granted to existing dataset.",
                        "time_ms": round(elapsed, 1),
                    }

                # Dataset exists but has NO embeddings -- delete stale and re-index
                logger.info(
                    "Re-indexing stale dataset", hf_id=hf_id, dataset_id=dataset_id
                )
                self._delete_dataset_fully(dataset_id)

            # Step 3: Fetch metadata from HuggingFace Hub
            from synsc.core.huggingface_client import get_dataset_info
            from synsc.config import get_config
            config = get_config()

            info = get_dataset_info(
                hf_id, hf_token=hf_token or config.dataset.hf_token or None
            )

            # Step 4: Generate dataset ID
            dataset_id = str(uuid.uuid4())
            logger.info(f"Indexing new dataset: {dataset_id} ({hf_id})")

            # Step 5: Chunk the card content
            chunks = []
            card_content = info.get("card_content", "")
            if card_content:
                from synsc.core.paper_chunker import chunk_markdown
                chunk_objects = chunk_markdown(
                    card_content,
                    max_tokens=config.dataset.chunk_size_tokens,
                    overlap_tokens=config.dataset.chunk_overlap_tokens,
                    description=info.get("description"),
                )
                chunks = [c.to_dict() for c in chunk_objects]

            # Step 6: Save dataset to database
            is_public = not (info.get("is_private") or info.get("is_gated"))

            def _sanitize(txt: str | None) -> str | None:
                if txt is None:
                    return None
                return txt.replace("\x00", "")

            with get_session() as session:
                session.execute(
                    text("""
                        INSERT INTO datasets (
                            dataset_id, hf_id, owner, name, description,
                            card_content, tags, languages, license,
                            downloads, likes, features, splits,
                            dataset_size_bytes, is_public, indexed_by, chunk_count
                        ) VALUES (
                            :dataset_id, :hf_id, :owner, :name, :description,
                            :card_content, :tags, :languages, :license,
                            :downloads, :likes, :features, :splits,
                            :dataset_size_bytes, :is_public, :indexed_by, :chunk_count
                        )
                    """),
                    {
                        "dataset_id": dataset_id,
                        "hf_id": hf_id,
                        "owner": info.get("owner", ""),
                        "name": info.get("name", hf_id),
                        "description": info.get("description"),
                        "card_content": (
                            _sanitize(card_content) if card_content else None
                        ),
                        "tags": json.dumps(info.get("tags", [])),
                        "languages": json.dumps(info.get("languages", [])),
                        "license": info.get("license"),
                        "downloads": info.get("downloads", 0),
                        "likes": info.get("likes", 0),
                        "features": json.dumps(info.get("features", {})),
                        "splits": json.dumps(info.get("splits", {})),
                        "dataset_size_bytes": info.get("dataset_size_bytes"),
                        "is_public": is_public,
                        "indexed_by": self.user_id,
                        "chunk_count": len(chunks),
                    },
                )

                # Step 7: Batch-save chunks
                chunk_ids = []
                for chunk in chunks:
                    result = session.execute(
                        text("""
                            INSERT INTO dataset_chunks (
                                dataset_id, chunk_index, content,
                                section_title, chunk_type, token_count
                            ) VALUES (
                                :dataset_id, :chunk_index, :content,
                                :section_title, :chunk_type, :token_count
                            ) RETURNING chunk_id
                        """),
                        {
                            "dataset_id": dataset_id,
                            "chunk_index": chunk["chunk_index"],
                            "content": _sanitize(chunk["content"]),
                            "section_title": _sanitize(chunk.get("section_title")),
                            "chunk_type": chunk.get("chunk_type", "section"),
                            "token_count": chunk.get("token_count"),
                        },
                    )
                    row = result.fetchone()
                    if row:
                        chunk_ids.append(row[0])

                if not chunk_ids and chunks:
                    logger.error("Failed to save chunks", dataset_id=dataset_id)
                elif chunk_ids:
                    logger.info(
                        "Saved chunks", count=len(chunk_ids), dataset_id=dataset_id
                    )

                # Step 8: Generate embeddings and store in pgvector
                embeddings_stored = False
                if chunk_ids:
                    try:
                        from synsc.embeddings.generator import get_paper_embedding_generator
                        embedding_gen = get_paper_embedding_generator()
                        chunk_texts = [
                            c.get("content", "") for c in chunks[: len(chunk_ids)]
                        ]
                        embeddings = embedding_gen.generate_batched(chunk_texts)

                        for chunk_id, embedding in zip(chunk_ids, embeddings):
                            embedding_list = (
                                embedding.tolist()
                                if hasattr(embedding, "tolist")
                                else list(embedding)
                            )
                            embedding_str = (
                                "[" + ",".join(str(x) for x in embedding_list) + "]"
                            )
                            session.execute(
                                text(
                                    "INSERT INTO dataset_chunk_embeddings "
                                    "(dataset_id, chunk_id, embedding) "
                                    "VALUES (:did, :cid, :emb)"
                                ),
                                {
                                    "did": dataset_id,
                                    "cid": chunk_id,
                                    "emb": embedding_str,
                                },
                            )

                        embeddings_stored = True
                        logger.info(
                            "Stored embeddings",
                            stored=len(chunk_ids),
                            total=len(embeddings),
                            dataset_id=dataset_id,
                        )
                    except Exception as e:
                        logger.exception(
                            "Failed to generate/store embeddings", error=str(e)
                        )
                else:
                    logger.warning(
                        "Skipping embeddings -- no chunk_ids",
                        dataset_id=dataset_id,
                        chunks=len(chunks),
                    )

                # Step 9: Grant user access
                session.execute(
                    text(
                        "INSERT INTO user_datasets (user_id, dataset_id) "
                        "VALUES (:uid, :did) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"uid": self.user_id, "did": dataset_id},
                )

            elapsed = (time.time() - start_time) * 1000

            return {
                "success": True,
                "status": "indexed",
                "dataset_id": dataset_id,
                "hf_id": hf_id,
                "name": info.get("name", hf_id),
                "description": (info.get("description") or "")[:300],
                "chunks": len(chunks),
                "downloads": info.get("downloads", 0),
                "license": info.get("license"),
                "embeddings_stored": embeddings_stored,
                "message": "Dataset indexed successfully",
                "time_ms": round(elapsed, 1),
            }

        except Exception as e:
            logger.exception("Failed to index dataset")
            return {
                "success": False,
                "error": f"Failed to index dataset: {str(e)}",
            }

    def get_dataset(self, dataset_id: str) -> Optional[dict]:
        """Get a specific dataset by ID."""
        try:
            with get_session() as session:
                if not self._user_has_dataset(dataset_id):
                    return None

                row = session.execute(
                    text("SELECT * FROM datasets WHERE dataset_id = :did"),
                    {"did": dataset_id},
                ).fetchone()
                if not row:
                    return None

                dataset = dict(row._mapping)

                # Get chunks
                chunk_rows = session.execute(
                    text(
                        "SELECT * FROM dataset_chunks "
                        "WHERE dataset_id = :did ORDER BY chunk_index"
                    ),
                    {"did": dataset_id},
                ).fetchall()
                dataset["chunks"] = [dict(c._mapping) for c in chunk_rows]
                return dataset
        except Exception as e:
            logger.error(f"Failed to get dataset: {e}")
        return None

    def list_datasets(self, limit: int = 50) -> list[dict]:
        """List datasets for the current user."""
        try:
            with get_session() as session:
                user_datasets = session.execute(
                    text(
                        "SELECT dataset_id FROM user_datasets "
                        "WHERE user_id = :uid ORDER BY added_at DESC LIMIT :lim"
                    ),
                    {"uid": self.user_id, "lim": limit},
                ).fetchall()

                if not user_datasets:
                    return []

                datasets = []
                for ud in user_datasets:
                    row = session.execute(
                        text("SELECT * FROM datasets WHERE dataset_id = :did"),
                        {"did": ud.dataset_id},
                    ).fetchone()
                    if row:
                        datasets.append(dict(row._mapping))

                return datasets

        except Exception as e:
            logger.error(f"Failed to list datasets: {e}")
            return []

    def search_datasets(
        self,
        query: str,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Search datasets using sentence-transformers embeddings + pgvector."""
        try:
            start = time.time()

            # Generate query embedding using sentence-transformers
            from synsc.embeddings.generator import get_paper_embedding_generator
            embedding_gen = get_paper_embedding_generator()
            query_embedding = embedding_gen.generate_single(query)

            # Format as pgvector string
            embedding_list = (
                query_embedding.tolist()
                if hasattr(query_embedding, "tolist")
                else list(query_embedding)
            )
            embedding_str = "[" + ",".join(str(x) for x in embedding_list) + "]"

            with get_session() as session:
                results = session.execute(
                    text("""
                        SELECT
                            dc.chunk_id,
                            dc.dataset_id,
                            d.name AS dataset_name,
                            d.hf_id,
                            dc.content,
                            dc.section_title,
                            dc.chunk_type,
                            1 - (dce.embedding <=> CAST(:embedding AS vector)) AS similarity
                        FROM dataset_chunk_embeddings dce
                        JOIN dataset_chunks dc ON dc.chunk_id = dce.chunk_id
                        JOIN datasets d ON d.dataset_id = dc.dataset_id
                        JOIN user_datasets ud ON ud.dataset_id = d.dataset_id
                        WHERE ud.user_id = :user_id
                        ORDER BY dce.embedding <=> CAST(:embedding AS vector)
                        LIMIT :top_k
                    """),
                    {
                        "embedding": embedding_str,
                        "user_id": self.user_id,
                        "top_k": top_k,
                    },
                ).fetchall()

            elapsed = (time.time() - start) * 1000

            return {
                "success": True,
                "query": query,
                "results": [
                    {
                        "chunk_id": r.chunk_id,
                        "dataset_id": r.dataset_id,
                        "dataset_name": r.dataset_name,
                        "hf_id": r.hf_id,
                        "content": r.content,
                        "section_title": r.section_title,
                        "chunk_type": r.chunk_type,
                        "similarity": round(r.similarity, 4) if r.similarity else 0,
                    }
                    for r in results
                ],
                "count": len(results),
                "search_time_ms": round(elapsed, 1),
            }
        except Exception as e:
            logger.exception("Dataset search failed")
            return {"success": False, "error": str(e), "results": []}

    def delete_dataset(self, dataset_id: str) -> dict[str, Any]:
        """Smart delete: unmap public datasets, fully delete private ones.

        Public datasets only remove the user's collection link (data stays for others).
        Private/gated datasets are fully removed (data + chunks + embeddings).
        """
        try:
            with get_session() as session:
                # Check the dataset exists and user has access
                row = session.execute(
                    text("SELECT * FROM datasets WHERE dataset_id = :did"),
                    {"did": dataset_id},
                ).fetchone()
                if not row:
                    return {"success": False, "error": "Dataset not found"}

                dataset = dict(row._mapping)
                is_public = dataset.get("is_public", True)

                if is_public:
                    # Public dataset: only unmap from user's collection
                    session.execute(
                        text(
                            "DELETE FROM user_datasets "
                            "WHERE user_id = :uid AND dataset_id = :did"
                        ),
                        {"uid": self.user_id, "did": dataset_id},
                    )
                    logger.info(
                        "Unmapped public dataset from user",
                        dataset_id=dataset_id,
                        user_id=self.user_id,
                    )
                    return {
                        "success": True,
                        "message": "Dataset removed from your collection",
                    }
                else:
                    # Private/gated dataset: full delete
                    session.execute(
                        text(
                            "DELETE FROM dataset_chunk_embeddings "
                            "WHERE dataset_id = :did"
                        ),
                        {"did": dataset_id},
                    )
                    session.execute(
                        text("DELETE FROM dataset_chunks WHERE dataset_id = :did"),
                        {"did": dataset_id},
                    )
                    session.execute(
                        text("DELETE FROM user_datasets WHERE dataset_id = :did"),
                        {"did": dataset_id},
                    )
                    session.execute(
                        text("DELETE FROM datasets WHERE dataset_id = :did"),
                        {"did": dataset_id},
                    )
                    logger.info(
                        "Fully deleted private dataset",
                        dataset_id=dataset_id,
                        user_id=self.user_id,
                    )
                    return {"success": True, "message": "Dataset fully deleted"}

        except Exception as e:
            logger.error(f"Failed to delete dataset: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_service: DatasetService | None = None


def get_dataset_service(user_id: str | None = None) -> DatasetService:
    """Get dataset service instance."""
    global _service
    if _service is None:
        _service = DatasetService()
    return _service
