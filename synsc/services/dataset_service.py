"""
Dataset Service - Main orchestrator for HuggingFace dataset indexing workflow.

Uses Supabase for ALL storage including vectors (pgvector).
100% stateless — no local files.

Coordinates:
- HuggingFace Hub metadata fetching
- Deduplication (via Supabase)
- Dataset card chunking
- Embedding generation (sentence-transformers)
- Supabase storage
"""

import time
import uuid
from typing import Any, Optional

import structlog

from synsc.supabase_auth import get_supabase_client, SupabaseREST

logger = structlog.get_logger(__name__)


class DatasetService:
    """Service for HuggingFace dataset indexing and management using Supabase + pgvector."""

    def __init__(self, user_id: str | None = None):
        self.client: SupabaseREST = get_supabase_client()
        self.user_id = user_id

    def _check_duplicate_by_hf_id(self, hf_id: str) -> Optional[dict]:
        """Check if dataset with this HF ID already exists."""
        try:
            datasets = self.client.select("datasets", "*", {"hf_id": hf_id})
            if datasets:
                return datasets[0]
        except Exception as e:
            logger.warning(f"Failed to check HF duplicate: {e}")
        return None

    def _user_has_dataset(self, dataset_id: str) -> bool:
        """Check if user already has access to this dataset."""
        if not self.user_id:
            return False
        try:
            links = self.client.select("user_datasets", "*", {
                "user_id": self.user_id,
                "dataset_id": dataset_id,
            })
            return len(links) > 0
        except Exception as e:
            logger.warning(f"Failed to check user dataset access: {e}")
        return False

    def _grant_user_access(self, dataset_id: str) -> bool:
        """Grant user access to a dataset."""
        if not self.user_id:
            return False
        try:
            self.client.insert("user_datasets", {
                "user_id": self.user_id,
                "dataset_id": dataset_id,
            })
            return True
        except Exception as e:
            logger.warning(f"Failed to grant user access: {e}")
        return False

    def _dataset_has_embeddings(self, dataset_id: str) -> bool:
        """Check if a dataset has any embeddings stored."""
        try:
            embeddings = self.client.select(
                "dataset_chunk_embeddings", "embedding_id", {"dataset_id": dataset_id}
            )
            return len(embeddings) > 0
        except Exception:
            return False

    def _delete_dataset_fully(self, dataset_id: str) -> bool:
        """Fully delete a dataset and all related data.

        Used to clean up stale records that have no embeddings so they can be re-indexed.
        """
        try:
            # Order matters due to FK constraints:
            # embeddings → chunks → user_datasets → datasets
            self.client.delete("dataset_chunk_embeddings", {"dataset_id": dataset_id})
            self.client.delete("dataset_chunks", {"dataset_id": dataset_id})
            self.client.delete("user_datasets", {"dataset_id": dataset_id})
            self.client.delete("datasets", {"dataset_id": dataset_id})
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

        if not self.user_id:
            return {"success": False, "error": "User ID is required"}

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
                    logger.info("Dataset already indexed", hf_id=hf_id, dataset_id=dataset_id)
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

                # Dataset exists but has NO embeddings — delete stale and re-index
                logger.info("Re-indexing stale dataset", hf_id=hf_id, dataset_id=dataset_id)
                self._delete_dataset_fully(dataset_id)

            # Step 3: Fetch metadata from HuggingFace Hub
            from synsc.core.huggingface_client import get_dataset_info
            from synsc.config import get_config
            config = get_config()

            info = get_dataset_info(hf_id, hf_token=hf_token or config.dataset.hf_token or None)

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

            # Step 6: Save dataset to Supabase FIRST (before chunks/embeddings)
            is_public = not (info.get("is_private") or info.get("is_gated"))
            dataset_data = {
                "dataset_id": dataset_id,
                "hf_id": hf_id,
                "owner": info.get("owner", ""),
                "name": info.get("name", hf_id),
                "description": info.get("description"),
                "card_content": card_content.replace("\x00", "") if card_content else None,
                "tags": info.get("tags", []),
                "languages": info.get("languages", []),
                "license": info.get("license"),
                "downloads": info.get("downloads", 0),
                "likes": info.get("likes", 0),
                "features": info.get("features", {}),
                "splits": info.get("splits", {}),
                "dataset_size_bytes": info.get("dataset_size_bytes"),
                "is_public": is_public,
                "indexed_by": self.user_id,
                "chunk_count": len(chunks),
            }

            result = self.client.insert("datasets", dataset_data)
            if not result or not result.get("dataset_id"):
                logger.error("Failed to insert dataset", result=result, dataset_id=dataset_id)
                return {"success": False, "error": "Failed to create dataset record"}

            # Step 7: Batch-save chunks
            def _sanitize(text: str | None) -> str | None:
                if text is None:
                    return None
                return text.replace("\x00", "")

            chunk_rows = [
                {
                    "dataset_id": dataset_id,
                    "chunk_index": chunk["chunk_index"],
                    "content": _sanitize(chunk["content"]),
                    "section_title": _sanitize(chunk.get("section_title")),
                    "chunk_type": chunk.get("chunk_type", "section"),
                    "token_count": chunk.get("token_count"),
                }
                for chunk in chunks
            ]

            chunk_ids = []
            if chunk_rows:
                saved_chunks = self.client.insert_batch("dataset_chunks", chunk_rows)
                chunk_ids = [c["chunk_id"] for c in saved_chunks if c.get("chunk_id")]

                if not chunk_ids and chunks:
                    logger.error("Failed to save chunks", dataset_id=dataset_id)
                else:
                    logger.info("Saved chunks", count=len(chunk_ids), dataset_id=dataset_id)

            # Step 8: Generate embeddings and batch-store in pgvector
            embeddings_stored = False
            if chunk_ids:
                try:
                    from synsc.embeddings.generator import get_paper_embedding_generator
                    embedding_gen = get_paper_embedding_generator()
                    chunk_texts = [c.get("content", "") for c in chunks[:len(chunk_ids)]]
                    embeddings = embedding_gen.generate_batched(chunk_texts)

                    # Build batch rows with pgvector string format
                    embedding_rows = []
                    for chunk_id, embedding in zip(chunk_ids, embeddings):
                        embedding_list = embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)
                        embedding_str = "[" + ",".join(str(x) for x in embedding_list) + "]"
                        embedding_rows.append({
                            "dataset_id": dataset_id,
                            "chunk_id": chunk_id,
                            "embedding": embedding_str,
                        })

                    # Batch insert in groups of 50
                    batch_size = 50
                    stored_count = 0
                    for i in range(0, len(embedding_rows), batch_size):
                        batch = embedding_rows[i : i + batch_size]
                        result = self.client.insert_batch(
                            "dataset_chunk_embeddings",
                            batch,
                            timeout=120,
                            return_rows=False,
                        )
                        if result:
                            stored_count += len(batch)
                        else:
                            logger.error("Failed to store embedding batch", batch_num=i // batch_size + 1)

                    embeddings_stored = stored_count > 0
                    logger.info("Stored embeddings", stored=stored_count, total=len(embeddings), dataset_id=dataset_id)
                except Exception as e:
                    logger.exception("Failed to generate/store embeddings", error=str(e))
            else:
                logger.warning("Skipping embeddings — no chunk_ids", dataset_id=dataset_id, chunks=len(chunks))

            # Step 9: Grant user access
            self._grant_user_access(dataset_id)

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
            if self.user_id and not self._user_has_dataset(dataset_id):
                return None

            datasets = self.client.select("datasets", "*", {"dataset_id": dataset_id})
            if datasets:
                dataset = datasets[0]
                # Get chunks
                chunks = self.client.select_advanced(
                    "dataset_chunks",
                    columns="*",
                    filters={"dataset_id": dataset_id},
                    order_by="chunk_index",
                    order_desc=False,
                )
                dataset["chunks"] = chunks
                return dataset
        except Exception as e:
            logger.error(f"Failed to get dataset: {e}")
        return None

    def list_datasets(self, limit: int = 50) -> list[dict]:
        """List datasets for the current user."""
        if not self.user_id:
            return []

        try:
            user_datasets = self.client.select_advanced(
                "user_datasets",
                columns="dataset_id",
                filters={"user_id": self.user_id},
                order_by="added_at",
                order_desc=True,
                limit=limit,
            )

            if not user_datasets:
                return []

            datasets = []
            for ud in user_datasets:
                dataset_id = ud["dataset_id"]
                dataset_data = self.client.select("datasets", "*", {"dataset_id": dataset_id})
                if dataset_data:
                    datasets.append(dataset_data[0])

            return datasets

        except Exception as e:
            logger.error(f"Failed to list datasets: {e}")
            return []

    def search_datasets(
        self,
        query: str,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Search datasets using sentence-transformers embeddings + pgvector semantic similarity."""
        if not self.user_id:
            return {"success": False, "error": "User ID required", "results": []}

        try:
            start = time.time()

            # Generate query embedding using sentence-transformers
            from synsc.embeddings.generator import get_paper_embedding_generator
            embedding_gen = get_paper_embedding_generator()
            query_embedding = embedding_gen.generate_single(query)

            # Format as pgvector string
            embedding_list = query_embedding.tolist() if hasattr(query_embedding, "tolist") else list(query_embedding)
            embedding_str = "[" + ",".join(str(x) for x in embedding_list) + "]"

            # Call the match_dataset_chunks RPC function
            results = self.client.rpc("match_dataset_chunks", {
                "query_embedding": embedding_str,
                "match_user_id": self.user_id,
                "match_count": top_k,
            })

            elapsed = (time.time() - start) * 1000

            return {
                "success": True,
                "query": query,
                "results": [
                    {
                        "chunk_id": r.get("chunk_id"),
                        "dataset_id": r.get("dataset_id"),
                        "dataset_name": r.get("dataset_name"),
                        "hf_id": r.get("hf_id"),
                        "content": r.get("content"),
                        "section_title": r.get("section_title"),
                        "chunk_type": r.get("chunk_type"),
                        "similarity": round(r.get("similarity", 0), 4),
                    }
                    for r in (results or [])
                ],
                "count": len(results or []),
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
        if not self.user_id:
            return {"success": False, "error": "User ID required"}

        try:
            # Check the dataset exists and user has access
            datasets = self.client.select("datasets", "*", {"dataset_id": dataset_id})
            if not datasets:
                return {"success": False, "error": "Dataset not found"}

            dataset = datasets[0]
            is_public = dataset.get("is_public", True)

            if is_public:
                # Public dataset: only unmap from user's collection
                self.client.delete("user_datasets", {
                    "user_id": self.user_id,
                    "dataset_id": dataset_id,
                })
                logger.info("Unmapped public dataset from user", dataset_id=dataset_id, user_id=self.user_id)
                return {"success": True, "message": "Dataset removed from your collection"}
            else:
                # Private/gated dataset: full delete
                self.client.delete("dataset_chunk_embeddings", {"dataset_id": dataset_id})
                self.client.delete("dataset_chunks", {"dataset_id": dataset_id})
                self.client.delete("user_datasets", {"dataset_id": dataset_id})
                self.client.delete("datasets", {"dataset_id": dataset_id})
                logger.info("Fully deleted private dataset", dataset_id=dataset_id, user_id=self.user_id)
                return {"success": True, "message": "Dataset fully deleted"}

        except Exception as e:
            logger.error(f"Failed to delete dataset: {e}")
            return {"success": False, "error": str(e)}


# Singleton cache
_services: dict[str, DatasetService] = {}


def get_dataset_service(user_id: str | None = None) -> DatasetService:
    """Get dataset service instance for a user."""
    key = user_id or "_default"
    if key not in _services:
        _services[key] = DatasetService(user_id=user_id)
    return _services[key]
