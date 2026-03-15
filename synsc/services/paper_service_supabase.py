"""
Paper Service (Supabase) - Main orchestrator for paper indexing workflow.

Uses Supabase for ALL storage including vectors (pgvector).
100% stateless - no local files except temporary uploads.

Coordinates:
- PDF processing
- Deduplication (via Supabase)
- Feature extraction (citations, equations, code)
- Chunking
- Embedding generation (stored in pgvector)
- Supabase storage
"""

import time
import uuid
from typing import Any, Optional

import structlog

from synsc.supabase_auth import get_supabase_client, SupabaseREST

logger = structlog.get_logger(__name__)

class PaperServiceSupabase:
    """Service for paper indexing and management using Supabase + pgvector."""

    def __init__(self, user_id: str | None = None):
        self.client: SupabaseREST = get_supabase_client()
        self.user_id = user_id

    def _get_embedding_generator(self):
        """Return the shared paper embedding generator (thread-safe singleton)."""
        from synsc.embeddings.generator import get_paper_embedding_generator
        return get_paper_embedding_generator()

    def _generate_paper_id(self) -> str:
        """Generate a unique paper ID."""
        return str(uuid.uuid4())

    def _check_duplicate_by_arxiv(self, arxiv_id: str) -> Optional[dict]:
        """Check if paper with this arXiv ID already exists."""
        try:
            papers = self.client.select("papers", "*", {"arxiv_id": arxiv_id})
            if papers:
                return papers[0]
        except Exception as e:
            logger.warning(f"Failed to check arXiv duplicate: {e}")
        return None

    def _check_duplicate_by_hash(self, pdf_hash: str) -> Optional[dict]:
        """Check if paper with this PDF hash already exists."""
        try:
            papers = self.client.select("papers", "*", {"pdf_hash": pdf_hash})
            if papers:
                return papers[0]
        except Exception as e:
            logger.warning(f"Failed to check hash duplicate: {e}")
        return None

    def _user_has_paper(self, paper_id: str) -> bool:
        """Check if user already has access to this paper."""
        if not self.user_id:
            return False
        try:
            links = self.client.select("user_papers", "*", {
                "user_id": self.user_id,
                "paper_id": paper_id
            })
            return len(links) > 0
        except Exception as e:
            logger.warning(f"Failed to check user paper access: {e}")
        return False

    def _grant_user_access(self, paper_id: str) -> bool:
        """Grant user access to a paper."""
        if not self.user_id:
            return False
        try:
            self.client.insert("user_papers", {
                "user_id": self.user_id,
                "paper_id": paper_id,
            })
            return True
        except Exception as e:
            logger.warning(f"Failed to grant user access: {e}")
        return False

    def _paper_has_embeddings(self, paper_id: str) -> bool:
        """Check if a paper has any embeddings stored."""
        try:
            embeddings = self.client.select(
                "paper_chunk_embeddings", "embedding_id", {"paper_id": paper_id}
            )
            return len(embeddings) > 0
        except Exception:
            return False

    def _delete_paper_fully(self, paper_id: str) -> bool:
        """Fully delete a paper and all related data (chunks, embeddings, user links).
        
        Used to clean up stale records that have no embeddings so they can be re-indexed.
        """
        try:
            # Order matters due to FK constraints:
            # embeddings → chunks → user_papers → papers
            self.client.delete("paper_chunk_embeddings", {"paper_id": paper_id})
            self.client.delete("paper_chunks", {"paper_id": paper_id})
            self.client.delete("user_papers", {"paper_id": paper_id})
            self.client.delete("papers", {"paper_id": paper_id})
            logger.info("Deleted stale paper record", paper_id=paper_id)
            return True
        except Exception as e:
            logger.error(f"Failed to fully delete paper: {e}")
            return False

    def index_paper(
        self,
        pdf_path: str,
        source: str = "upload",
        arxiv_id: str | None = None,
        arxiv_metadata: dict | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """
        Index a paper from PDF.

        Args:
            pdf_path: Path to PDF file
            source: Source type (arxiv, upload)
            arxiv_id: Optional arXiv ID
            arxiv_metadata: Optional arXiv metadata (title, authors, abstract)
            title: Optional title override

        Returns:
            Dictionary with indexing results
        """
        start_time = time.time()

        if not self.user_id:
            return {"success": False, "error": "User ID is required"}

        try:
            # Step 1: Check deduplication by arXiv ID
            if arxiv_id:
                existing = self._check_duplicate_by_arxiv(arxiv_id)
                if existing:
                    paper_id = existing["paper_id"]
                    has_embeddings = self._paper_has_embeddings(paper_id)
                    
                    if self._user_has_paper(paper_id) and has_embeddings:
                        logger.info("Paper already indexed", arxiv_id=arxiv_id, paper_id=paper_id)
                        elapsed = (time.time() - start_time) * 1000
                        return {
                            "success": True,
                            "status": "already_indexed",
                            "paper_id": paper_id,
                            "title": existing.get("title", "Unknown"),
                            "message": "Paper already indexed in your library.",
                            "time_ms": round(elapsed, 1),
                        }
                    
                    if has_embeddings:
                        # Paper exists with embeddings, just grant access
                        self._grant_user_access(paper_id)
                        elapsed = (time.time() - start_time) * 1000
                        return {
                            "success": True,
                            "status": "access_granted",
                            "paper_id": paper_id,
                            "title": existing.get("title", "Unknown"),
                            "message": "Access granted to existing paper.",
                            "time_ms": round(elapsed, 1),
                        }
                    
                    # Paper exists but has NO embeddings - delete stale record and re-index
                    logger.info("Re-indexing stale paper", arxiv_id=arxiv_id, paper_id=paper_id)
                    self._delete_paper_fully(paper_id)

            # Step 2: Process PDF if provided
            pdf_hash = None
            extracted = None
            
            if pdf_path:
                from synsc.core.pdf_processor import process_pdf
                extracted = process_pdf(pdf_path)
                pdf_hash = extracted.pdf_hash

                # Check deduplication by hash
                existing = self._check_duplicate_by_hash(pdf_hash)
                if existing:
                    paper_id = existing["paper_id"]
                    has_embeddings = self._paper_has_embeddings(paper_id)
                    
                    if self._user_has_paper(paper_id) and has_embeddings:
                        elapsed = (time.time() - start_time) * 1000
                        return {
                            "success": True,
                            "status": "already_indexed",
                            "paper_id": paper_id,
                            "title": existing.get("title", "Unknown"),
                            "message": "Paper already indexed (same PDF).",
                            "time_ms": round(elapsed, 1),
                        }
                    
                    if has_embeddings:
                        self._grant_user_access(paper_id)
                        elapsed = (time.time() - start_time) * 1000
                        return {
                            "success": True,
                            "status": "access_granted",
                            "paper_id": paper_id,
                            "title": existing.get("title", "Unknown"),
                            "message": "Access granted to existing paper.",
                            "time_ms": round(elapsed, 1),
                        }
                    
                    # Paper exists but has NO embeddings - delete stale record and re-index
                    logger.info("Re-indexing stale paper", pdf_hash=pdf_hash[:16], paper_id=paper_id)
                    self._delete_paper_fully(paper_id)
            else:
                # No PDF - create hash from arxiv_id
                import hashlib
                pdf_hash = hashlib.sha256(f"arxiv:{arxiv_id}".encode()).hexdigest()

            # Step 3: Generate paper ID
            paper_id = self._generate_paper_id()
            logger.info(f"Indexing new paper: {paper_id}")

            # Step 4: Determine final metadata
            # Priority: arXiv metadata > extracted > title param
            if arxiv_metadata:
                final_title = arxiv_metadata.get("title") or (extracted.title if extracted else None) or title or "Unknown Title"
                final_authors = arxiv_metadata.get("authors") or (extracted.authors if extracted else []) or []
                final_abstract = arxiv_metadata.get("abstract") or (extracted.abstract if extracted else None)
            elif extracted:
                final_title = extracted.title or title or "Unknown Title"
                final_authors = extracted.authors or []
                final_abstract = extracted.abstract
            else:
                final_title = title or f"arXiv:{arxiv_id}" if arxiv_id else "Unknown Title"
                final_authors = []
                final_abstract = None

            page_count = extracted.page_count if extracted else 0

            # Step 5: Create chunks from extracted content
            chunks = []
            if extracted:
                from synsc.core.paper_chunker import chunk_paper
                chunk_objects = chunk_paper(extracted)
                chunks = [c.to_dict() for c in chunk_objects]

            # Step 6: Save paper to Supabase FIRST (before chunks/embeddings)
            paper_data = {
                "paper_id": paper_id,
                "title": final_title,
                "authors": final_authors,
                "abstract": final_abstract,
                "arxiv_id": arxiv_id,
                "pdf_hash": pdf_hash,
                "page_count": page_count,
                "chunk_count": len(chunks),
                "indexed_by": self.user_id,
                "is_public": False,
            }

            result = self.client.insert("papers", paper_data)
            if not result or not result.get("paper_id"):
                logger.error("Failed to insert paper", result=result, paper_id=paper_id)
                return {"success": False, "error": "Failed to create paper record"}

            # Step 7: Batch-save chunks to paper_chunks table and collect chunk_ids
            def _sanitize_text(text: str | None) -> str | None:
                """Remove null bytes and other problematic characters for PostgreSQL text columns."""
                if text is None:
                    return None
                # PostgreSQL text columns cannot contain \u0000 (null byte)
                return text.replace("\x00", "")

            chunk_rows = [
                {
                    "paper_id": paper_id,
                    "chunk_index": chunk["chunk_index"],
                    "content": _sanitize_text(chunk["content"]),
                    "section_title": _sanitize_text(chunk.get("section_title")),
                    "chunk_type": chunk.get("chunk_type", "section"),
                    "page_number": chunk.get("page_number"),
                    "token_count": chunk.get("token_count"),
                }
                for chunk in chunks
            ]
            
            saved_chunks = self.client.insert_batch("paper_chunks", chunk_rows)
            chunk_ids = [c["chunk_id"] for c in saved_chunks if c.get("chunk_id")]
            
            if not chunk_ids and chunks:
                logger.error("Failed to save chunks", paper_id=paper_id, rows_sent=len(chunk_rows), rows_returned=len(saved_chunks))
            else:
                logger.info("Saved chunks", count=len(chunk_ids), paper_id=paper_id)

            # Step 8: Generate embeddings and batch-store in pgvector
            embeddings_stored = False
            if chunk_ids:
                try:
                    embedding_gen = self._get_embedding_generator()
                    chunk_texts = [c.get("content", "") for c in chunks[:len(chunk_ids)]]
                    embeddings = embedding_gen.generate_batched(chunk_texts)
                    
                    # Build batch rows with pgvector string format
                    embedding_rows = []
                    for chunk_id, embedding in zip(chunk_ids, embeddings):
                        embedding_list = embedding.tolist() if hasattr(embedding, 'tolist') else list(embedding)
                        embedding_str = "[" + ",".join(str(x) for x in embedding_list) + "]"
                        embedding_rows.append({
                            "paper_id": paper_id,
                            "chunk_id": chunk_id,
                            "embedding": embedding_str,
                        })
                    
                    # Batch insert in groups of 50 (embeddings are large payloads)
                    batch_size = 50
                    stored_count = 0
                    for i in range(0, len(embedding_rows), batch_size):
                        batch = embedding_rows[i:i + batch_size]
                        result = self.client.insert_batch(
                            "paper_chunk_embeddings", batch,
                            timeout=120, return_rows=False,
                        )
                        if result:
                            stored_count += len(batch)
                        else:
                            logger.error("Failed to store embedding batch", batch_num=i//batch_size + 1)
                    
                    embeddings_stored = stored_count > 0
                    logger.info("Stored embeddings", stored=stored_count, total=len(embeddings), paper_id=paper_id)
                except Exception as e:
                    logger.exception("Failed to generate/store embeddings", error=str(e))
            else:
                logger.warning("Skipping embeddings — no chunk_ids", paper_id=paper_id, chunks=len(chunks))

            # Step 9: Grant user access
            self._grant_user_access(paper_id)

            elapsed = (time.time() - start_time) * 1000

            return {
                "success": True,
                "status": "indexed",
                "paper_id": paper_id,
                "title": final_title,
                "authors": final_authors,
                "abstract": final_abstract[:300] + "..." if final_abstract and len(final_abstract) > 300 else final_abstract,
                "chunks": len(chunks),
                "pages": page_count,
                "figures": len(extracted.figures) if extracted else 0,
                "tables": len(extracted.tables) if extracted else 0,
                "embeddings_stored": embeddings_stored,
                "pdf_hash": pdf_hash,
                "arxiv_id": arxiv_id,
                "message": "Paper indexed successfully",
                "time_ms": round(elapsed, 1),
            }

        except Exception as e:
            logger.exception("Failed to index paper")
            return {
                "success": False,
                "error": f"Failed to index paper: {str(e)}",
            }

    def get_paper(self, paper_id: str) -> Optional[dict]:
        """Get a specific paper by ID."""
        try:
            # Check user has access
            if self.user_id and not self._user_has_paper(paper_id):
                return None
            
            papers = self.client.select("papers", "*", {"paper_id": paper_id})
            if papers:
                paper = papers[0]
                # Get chunks
                chunks = self.client.select_advanced(
                    "paper_chunks",
                    columns="*",
                    filters={"paper_id": paper_id},
                    order_by="chunk_index",
                    order_desc=False,
                )
                paper["chunks"] = chunks
                return paper
        except Exception as e:
            logger.error(f"Failed to get paper: {e}")
        return None

    def list_papers(self, limit: int = 50) -> list[dict]:
        """List papers for the current user."""
        if not self.user_id:
            return []

        try:
            # Get user's papers via user_papers join
            user_papers = self.client.select_advanced(
                "user_papers",
                columns="paper_id",
                filters={"user_id": self.user_id},
                order_by="added_at",
                order_desc=True,
                limit=limit,
            )

            if not user_papers:
                return []

            # Fetch paper details
            papers = []
            for up in user_papers:
                paper_id = up["paper_id"]
                paper_data = self.client.select("papers", "*", {"paper_id": paper_id})
                if paper_data:
                    papers.append(paper_data[0])

            return papers

        except Exception as e:
            logger.error(f"Failed to list papers: {e}")
            return []

    def delete_paper(self, paper_id: str) -> dict[str, Any]:
        """Fully delete a paper and all associated data."""
        if not self.user_id:
            return {"success": False, "error": "User ID required"}

        try:
            # Delete everything: embeddings → chunks → user links → paper
            # Order matters due to foreign key constraints
            self.client.delete("paper_chunk_embeddings", {"paper_id": paper_id})
            self.client.delete("paper_chunks", {"paper_id": paper_id})
            self.client.delete("user_papers", {"paper_id": paper_id})
            self.client.delete("papers", {"paper_id": paper_id})
            
            logger.info("Fully deleted paper", paper_id=paper_id, user_id=self.user_id)
            return {"success": True, "message": "Paper fully deleted"}
        except Exception as e:
            logger.error(f"Failed to delete paper: {e}")
            return {"success": False, "error": str(e)}

    def search_papers(
        self,
        query: str,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Search papers using pgvector semantic similarity."""
        if not self.user_id:
            return {"success": False, "error": "User ID required", "results": []}

        try:
            import time as _time
            start = _time.time()

            # Generate query embedding
            embedding_gen = self._get_embedding_generator()
            query_embedding = embedding_gen.generate_single(query)

            # Format as pgvector string
            embedding_list = query_embedding.tolist() if hasattr(query_embedding, 'tolist') else list(query_embedding)
            embedding_str = "[" + ",".join(str(x) for x in embedding_list) + "]"

            # Call the search_papers RPC function (or match_paper_chunks fallback)
            results = self.client.rpc("match_paper_chunks", {
                "query_embedding": embedding_str,
                "match_user_id": self.user_id,
                "match_count": top_k,
            })

            # If match_paper_chunks fails, try the built-in search_papers function
            if not results:
                results = self.client.rpc("search_papers", {
                    "query_embedding": embedding_str,
                    "p_user_id": self.user_id,
                    "p_limit": top_k,
                })

            elapsed = (_time.time() - start) * 1000

            return {
                "success": True,
                "query": query,
                "results": [
                    {
                        "chunk_id": r.get("chunk_id"),
                        "paper_id": r.get("paper_id"),
                        "paper_title": r.get("paper_title"),
                        "paper_authors": r.get("paper_authors"),
                        "content": r.get("content"),
                        "section_title": r.get("section_title"),
                        "chunk_type": r.get("chunk_type"),
                        "page_number": r.get("page_number"),
                        "similarity": round(r.get("similarity", 0), 4),
                    }
                    for r in results
                ],
                "count": len(results),
                "search_time_ms": round(elapsed, 1),
            }
        except Exception as e:
            logger.exception("Paper search failed")
            return {"success": False, "error": str(e), "results": []}

    def get_citations(self, paper_id: str) -> list[dict]:
        """Get citations for a paper."""
        try:
            return self.client.select("citations", "*", {"paper_id": paper_id})
        except Exception as e:
            logger.error(f"Failed to get citations: {e}")
            return []

    def get_equations(self, paper_id: str) -> list[dict]:
        """Get equations for a paper."""
        try:
            return self.client.select("equations", "*", {"paper_id": paper_id})
        except Exception as e:
            logger.error(f"Failed to get equations: {e}")
            return []


# Singleton cache
_services: dict[str, PaperServiceSupabase] = {}


def get_paper_service(user_id: str | None = None) -> PaperServiceSupabase:
    """Get paper service instance for a user."""
    key = user_id or "_default"
    if key not in _services:
        _services[key] = PaperServiceSupabase(user_id=user_id)
    return _services[key]
