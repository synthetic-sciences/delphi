"""
Paper Service - Main orchestrator for paper indexing workflow.

Uses SQLAlchemy + pgvector for ALL storage.
100% stateless - no local files except temporary uploads.

Coordinates:
- PDF processing
- Deduplication (via PostgreSQL)
- Feature extraction (citations, equations, code)
- Chunking
- Embedding generation (stored in pgvector)
- PostgreSQL storage
"""

import json
import time
import uuid
from typing import Any, Optional

import structlog
from sqlalchemy import text

from synsc.database.connection import get_session
from synsc.database.models import (
    Citation,
    Equation,
    Paper,
    PaperChunk,
    PaperCodeSnippet,
    UserPaper,
)

logger = structlog.get_logger(__name__)


class PaperService:
    """Service for paper indexing and management using SQLAlchemy + pgvector."""

    def __init__(self, user_id: str):
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
            with get_session() as session:
                paper = session.query(Paper).filter(Paper.arxiv_id == arxiv_id).first()
                if paper:
                    return {
                        "paper_id": paper.paper_id,
                        "title": paper.title,
                        "arxiv_id": paper.arxiv_id,
                    }
        except Exception as e:
            logger.warning(f"Failed to check arXiv duplicate: {e}")
        return None

    def _check_duplicate_by_hash(self, pdf_hash: str) -> Optional[dict]:
        """Check if paper with this PDF hash already exists."""
        try:
            with get_session() as session:
                paper = session.query(Paper).filter(Paper.pdf_hash == pdf_hash).first()
                if paper:
                    return {
                        "paper_id": paper.paper_id,
                        "title": paper.title,
                    }
        except Exception as e:
            logger.warning(f"Failed to check hash duplicate: {e}")
        return None

    def _user_has_paper(self, paper_id: str) -> bool:
        """Check if user already has access to this paper."""
        try:
            with get_session() as session:
                link = session.query(UserPaper).filter(
                    UserPaper.user_id == self.user_id,
                    UserPaper.paper_id == paper_id,
                ).first()
                return link is not None
        except Exception as e:
            logger.warning(f"Failed to check user paper access: {e}")
        return False

    def _grant_user_access(self, paper_id: str) -> bool:
        """Grant user access to a paper."""
        try:
            with get_session() as session:
                # Check if link already exists
                existing = session.query(UserPaper).filter(
                    UserPaper.user_id == self.user_id,
                    UserPaper.paper_id == paper_id,
                ).first()
                if not existing:
                    link = UserPaper(
                        user_id=self.user_id,
                        paper_id=paper_id,
                    )
                    session.add(link)
            return True
        except Exception as e:
            logger.warning(f"Failed to grant user access: {e}")
        return False

    def _paper_has_embeddings(self, paper_id: str) -> bool:
        """Check if a paper has any embeddings stored."""
        try:
            with get_session() as session:
                result = session.execute(
                    text("SELECT 1 FROM paper_chunk_embeddings WHERE paper_id = :pid LIMIT 1"),
                    {"pid": paper_id},
                ).fetchone()
                return result is not None
        except Exception:
            return False

    def _delete_paper_fully(self, paper_id: str) -> bool:
        """Fully delete a paper and all related data (chunks, embeddings, user links).

        Used to clean up stale records that have no embeddings so they can be re-indexed.
        """
        try:
            with get_session() as session:
                # Order matters due to FK constraints:
                # embeddings -> chunks -> citations/equations/snippets -> user_papers -> papers
                session.execute(
                    text("DELETE FROM paper_chunk_embeddings WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                session.execute(
                    text("DELETE FROM paper_code_snippets WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                session.execute(
                    text("DELETE FROM equations WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                session.execute(
                    text("DELETE FROM citations WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                session.execute(
                    text("DELETE FROM paper_chunks WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                session.execute(
                    text("DELETE FROM user_papers WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                session.execute(
                    text("DELETE FROM papers WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
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
                    logger.info(
                        "Re-indexing stale paper", pdf_hash=pdf_hash[:16], paper_id=paper_id
                    )
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
                final_title = (
                    arxiv_metadata.get("title")
                    or (extracted.title if extracted else None)
                    or title
                    or "Unknown Title"
                )
                final_authors = (
                    arxiv_metadata.get("authors")
                    or (extracted.authors if extracted else [])
                    or []
                )
                final_abstract = arxiv_metadata.get("abstract") or (
                    extracted.abstract if extracted else None
                )
            elif extracted:
                final_title = extracted.title or title or "Unknown Title"
                final_authors = extracted.authors or []
                final_abstract = extracted.abstract
            else:
                final_title = title or (f"arXiv:{arxiv_id}" if arxiv_id else "Unknown Title")
                final_authors = []
                final_abstract = None

            page_count = extracted.page_count if extracted else 0

            # Step 5: Create chunks from extracted content
            chunks = []
            if extracted:
                from synsc.core.paper_chunker import chunk_paper
                chunk_objects = chunk_paper(extracted)
                chunks = [c.to_dict() for c in chunk_objects]

            # Step 6: Save paper to database
            def _sanitize_text(txt: str | None) -> str | None:
                """Remove null bytes for PostgreSQL text columns."""
                if txt is None:
                    return None
                return txt.replace("\x00", "")

            with get_session() as session:
                paper = Paper(
                    paper_id=paper_id,
                    title=final_title,
                    authors=final_authors or None,
                    abstract=final_abstract,
                    arxiv_id=arxiv_id,
                    pdf_hash=pdf_hash,
                    page_count=page_count,
                    is_public=False,
                )
                session.add(paper)
                session.flush()

                # Step 7: Save chunks to paper_chunks table
                chunk_ids = []
                for chunk in chunks:
                    db_chunk = PaperChunk(
                        paper_id=paper_id,
                        chunk_index=chunk["chunk_index"],
                        content=_sanitize_text(chunk["content"]),
                        section_title=_sanitize_text(chunk.get("section_title")),
                        chunk_type=chunk.get("chunk_type", "section"),
                        page_number=chunk.get("page_number"),
                        token_count=chunk.get("token_count"),
                    )
                    session.add(db_chunk)
                    session.flush()
                    chunk_ids.append(db_chunk.chunk_id)

                if not chunk_ids and chunks:
                    logger.error(
                        "Failed to save chunks",
                        paper_id=paper_id,
                        rows_sent=len(chunks),
                    )
                else:
                    logger.info("Saved chunks", count=len(chunk_ids), paper_id=paper_id)

                # Step 8: Generate embeddings and store in pgvector
                embeddings_stored = False
                if chunk_ids:
                    try:
                        embedding_gen = self._get_embedding_generator()
                        chunk_texts = [c.get("content", "") for c in chunks[: len(chunk_ids)]]
                        embeddings = embedding_gen.generate_batched(chunk_texts)

                        # Store embeddings using raw SQL for pgvector
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
                                    "INSERT INTO paper_chunk_embeddings "
                                    "(paper_id, chunk_id, embedding) "
                                    "VALUES (:paper_id, :chunk_id, :embedding)"
                                ),
                                {
                                    "paper_id": paper_id,
                                    "chunk_id": chunk_id,
                                    "embedding": embedding_str,
                                },
                            )

                        embeddings_stored = True
                        logger.info(
                            "Stored embeddings",
                            stored=len(chunk_ids),
                            total=len(embeddings),
                            paper_id=paper_id,
                        )
                    except Exception as e:
                        logger.exception(
                            "Failed to generate/store embeddings", error=str(e)
                        )
                else:
                    logger.warning(
                        "Skipping embeddings -- no chunk_ids",
                        paper_id=paper_id,
                        chunks=len(chunks),
                    )

                # Step 9: Extract citations, equations, and code snippets
                if extracted and extracted.normalized_text:
                    full_text = extracted.normalized_text
                    try:
                        from synsc.extractors.citations import CitationExtractor
                        from synsc.extractors.equations import EquationExtractor
                        from synsc.extractors.code_snippets import CodeSnippetExtractor

                        # Citations
                        raw_citations = CitationExtractor().extract(full_text)
                        for c in raw_citations:
                            ct = c.get("citation_text", "") or ""
                            if not ct:
                                continue
                            session.add(Citation(
                                paper_id=paper_id,
                                citation_text=ct[:2000],
                                citation_context=(c.get("citation_context") or "")[:2000] or None,
                                citation_number=int(c["citation_number"]) if c.get("citation_number") and str(c["citation_number"]).isdigit() else None,
                                page_number=c.get("page_number"),
                                external_reference={"type": c.get("citation_type"), "author": c.get("author"), "year": c.get("year")} if c.get("author") else None,
                            ))

                        # Equations (LaTeX-based extractor)
                        raw_equations = EquationExtractor().extract(full_text)

                        # Also extract plain-text equations from PDF text
                        # (PDF extraction strips LaTeX, leaving rendered equations)
                        import re as _re
                        _math_chars = set('∑∏√σαβγδεζηθλμπρτφψω∈∀∃∞±×÷∝∂∇≈≠≤≥')
                        _math_words = {'softmax', 'argmax', 'argmin', 'log', 'exp', 'max', 'min',
                                       'sqrt', 'relu', 'gelu', 'sigmoid', 'tanh', 'cos', 'sin'}
                        # Skip equations that look like dollar amounts or examples
                        _false_positive_markers = {'$', '<<', '####', 'dollars', 'cents', 'price'}

                        def _is_math(t):
                            tl = t.lower()
                            if any(fp in tl for fp in _false_positive_markers):
                                return False
                            return (
                                any(c in t for c in _math_chars)
                                or any(w in tl for w in _math_words)
                                or _re.search(r'[_^]|W\d|b\d|d[_a-z]', t)  # weight/bias/dim notation
                            )

                        _eq_patterns = [
                            # Uppercase FunctionName(vars) = expression
                            _re.compile(r'([A-Z][a-zA-Z]{2,}\s*\([^)]{1,60}\)\s*=\s*[^\n]{5,200})'),
                            # Common ML functions: softmax(...), attention(...), etc.
                            _re.compile(r'((?:softmax|attention|relu|gelu|sigmoid|tanh)\s*\([^)]+\)\s*=?\s*[^\n]{5,200})', _re.IGNORECASE),
                            # MultiHead, Concat, LayerNorm patterns
                            _re.compile(r'((?:MultiHead|Concat|LayerNorm|PE)\s*\([^)]{1,80}\)\s*=\s*[^\n]{5,300})'),
                            # Multiline: FunctionName(vars) = ... across up to 3 lines
                            _re.compile(r'([A-Z][a-zA-Z]{2,}\s*\([^)]{1,60}\)\s*=\s*(?:[^\n]*\n){0,2}[^\n]+)', _re.MULTILINE),
                            # Equation with number at end of line: "expression (1)"
                            _re.compile(r'([^\n]{15,300})\s+\((\d{1,2})\)\s*(?:\n|$)', _re.MULTILINE),
                            # Equation with number on next line: "expression\n(1)"
                            _re.compile(r'([^\n]{10,200})\n\s*\((\d{1,2})\)\s*$', _re.MULTILINE),
                        ]
                        _seen_eq = set()
                        for pat in _eq_patterns:
                            for m in pat.finditer(full_text):
                                eq_text = ' '.join(m.group(0).split())  # normalize whitespace
                                if not _is_math(eq_text) or len(eq_text) < 15:
                                    continue
                                # Dedup by checking substring overlap
                                is_dup = any(eq_text in existing or existing in eq_text for existing in _seen_eq)
                                if is_dup:
                                    # Keep the longer version
                                    _seen_eq = {s for s in _seen_eq if s not in eq_text}
                                _seen_eq.add(eq_text)
                                eq_num = None
                                if m.lastindex and m.lastindex >= 2:
                                    g2 = m.group(2)
                                    if g2 and g2.isdigit():
                                        eq_num = g2
                                raw_equations.append({
                                    "equation_text": eq_text,
                                    "equation_type": "inline",
                                    "equation_number": eq_num,
                                    "context": full_text[max(0, m.start()-80):m.end()+80].strip(),
                                })

                        for eq in raw_equations:
                            et = eq.get("equation_text", "") or ""
                            if not et:
                                continue
                            session.add(Equation(
                                paper_id=paper_id,
                                equation_text=et[:5000],
                                equation_number=eq.get("equation_number"),
                                equation_type=eq.get("equation_type", "display"),
                                context=(eq.get("context") or "")[:2000] or None,
                                page_number=eq.get("page_number"),
                            ))

                        # Code snippets
                        raw_snippets = CodeSnippetExtractor().extract(full_text)
                        for s in raw_snippets:
                            ct = s.get("code_text", s.get("text", "")) or ""
                            if not ct:
                                continue
                            session.add(PaperCodeSnippet(
                                paper_id=paper_id,
                                code_text=ct[:10000],
                                language=s.get("language"),
                                page_number=s.get("page_number"),
                                section_title=s.get("section_title"),
                            ))

                        logger.info(
                            "Extracted paper features",
                            paper_id=paper_id,
                            citations=len(raw_citations),
                            equations=len(raw_equations),
                            code_snippets=len(raw_snippets),
                        )
                    except Exception as e:
                        logger.warning("Feature extraction failed (non-fatal)", error=str(e))

                # Step 10: Grant user access
                existing_link = session.query(UserPaper).filter(
                    UserPaper.user_id == self.user_id,
                    UserPaper.paper_id == paper_id,
                ).first()
                if not existing_link:
                    link = UserPaper(user_id=self.user_id, paper_id=paper_id)
                    session.add(link)

            elapsed = (time.time() - start_time) * 1000

            return {
                "success": True,
                "status": "indexed",
                "paper_id": paper_id,
                "title": final_title,
                "authors": final_authors,
                "abstract": (
                    final_abstract[:300] + "..."
                    if final_abstract and len(final_abstract) > 300
                    else final_abstract
                ),
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
            with get_session() as session:
                # Check user has access
                link = session.query(UserPaper).filter(
                    UserPaper.user_id == self.user_id,
                    UserPaper.paper_id == paper_id,
                ).first()
                if not link:
                    return None

                paper = session.query(Paper).filter(Paper.paper_id == paper_id).first()
                if not paper:
                    return None

                # Get chunks
                chunks = (
                    session.query(PaperChunk)
                    .filter(PaperChunk.paper_id == paper_id)
                    .order_by(PaperChunk.chunk_index)
                    .all()
                )

                return {
                    "paper_id": paper.paper_id,
                    "title": paper.title,
                    "authors": paper.get_authors(),
                    "abstract": paper.abstract,
                    "arxiv_id": paper.arxiv_id,
                    "pdf_hash": paper.pdf_hash,
                    "page_count": paper.page_count,
                    "indexed_at": (
                        paper.indexed_at.isoformat() if paper.indexed_at else None
                    ),
                    "chunks": [
                        {
                            "chunk_id": c.chunk_id,
                            "chunk_index": c.chunk_index,
                            "content": c.content,
                            "section_title": c.section_title,
                            "chunk_type": c.chunk_type,
                            "page_number": c.page_number,
                            "token_count": c.token_count,
                        }
                        for c in chunks
                    ],
                }
        except Exception as e:
            logger.error(f"Failed to get paper: {e}")
        return None

    def list_papers(self, limit: int = 50) -> list[dict]:
        """List papers for the current user."""
        try:
            with get_session() as session:
                # Get user's papers via user_papers join
                user_papers = (
                    session.query(UserPaper)
                    .filter(UserPaper.user_id == self.user_id)
                    .order_by(UserPaper.added_at.desc())
                    .limit(limit)
                    .all()
                )

                if not user_papers:
                    return []

                papers = []
                for up in user_papers:
                    paper = (
                        session.query(Paper)
                        .filter(Paper.paper_id == up.paper_id)
                        .first()
                    )
                    if paper:
                        papers.append({
                            "paper_id": paper.paper_id,
                            "title": paper.title,
                            "authors": paper.get_authors(),
                            "abstract": paper.abstract,
                            "arxiv_id": paper.arxiv_id,
                            "page_count": paper.page_count,
                            "indexed_at": (
                                paper.indexed_at.isoformat()
                                if paper.indexed_at
                                else None
                            ),
                        })

                return papers

        except Exception as e:
            logger.error(f"Failed to list papers: {e}")
            return []

    def delete_paper(self, paper_id: str) -> dict[str, Any]:
        """Fully delete a paper and all associated data."""
        try:
            with get_session() as session:
                # Delete everything in FK order
                session.execute(
                    text("DELETE FROM paper_chunk_embeddings WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                session.execute(
                    text("DELETE FROM paper_code_snippets WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                session.execute(
                    text("DELETE FROM equations WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                session.execute(
                    text("DELETE FROM citations WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                session.execute(
                    text("DELETE FROM paper_chunks WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                session.execute(
                    text("DELETE FROM user_papers WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )
                session.execute(
                    text("DELETE FROM papers WHERE paper_id = :pid"),
                    {"pid": paper_id},
                )

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
        try:
            import time as _time
            start = _time.time()

            # Generate query embedding
            embedding_gen = self._get_embedding_generator()
            query_embedding = embedding_gen.generate_single(query)

            # Format as pgvector string
            embedding_list = (
                query_embedding.tolist()
                if hasattr(query_embedding, "tolist")
                else list(query_embedding)
            )
            embedding_str = "[" + ",".join(str(x) for x in embedding_list) + "]"

            with get_session() as session:
                # Use raw SQL with pgvector <=> operator for cosine distance
                results = session.execute(
                    text("""
                        SELECT
                            pc.chunk_id,
                            pc.paper_id,
                            p.title AS paper_title,
                            p.authors AS paper_authors,
                            pc.content,
                            pc.section_title,
                            pc.chunk_type,
                            pc.page_number,
                            1 - (pce.embedding <=> CAST(:embedding AS vector)) AS similarity
                        FROM paper_chunk_embeddings pce
                        JOIN paper_chunks pc ON pc.chunk_id = pce.chunk_id
                        JOIN papers p ON p.paper_id = pc.paper_id
                        JOIN user_papers up ON up.paper_id = p.paper_id
                        WHERE up.user_id = :user_id
                        ORDER BY pce.embedding <=> CAST(:embedding AS vector)
                        LIMIT :top_k
                    """),
                    {
                        "embedding": embedding_str,
                        "user_id": self.user_id,
                        "top_k": top_k,
                    },
                ).fetchall()

            elapsed = (_time.time() - start) * 1000

            return {
                "success": True,
                "query": query,
                "results": [
                    {
                        "chunk_id": r.chunk_id,
                        "paper_id": r.paper_id,
                        "paper_title": r.paper_title,
                        "paper_authors": r.paper_authors,
                        "content": r.content,
                        "section_title": r.section_title,
                        "chunk_type": r.chunk_type,
                        "page_number": r.page_number,
                        "similarity": round(r.similarity, 4) if r.similarity else 0,
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
            with get_session() as session:
                citations = (
                    session.query(Citation)
                    .filter(Citation.paper_id == paper_id)
                    .all()
                )
                return [
                    {
                        "citation_id": c.citation_id,
                        "paper_id": c.paper_id,
                        "citation_text": c.citation_text,
                        "citation_context": c.citation_context,
                        "page_number": c.page_number,
                        "citation_number": c.citation_number,
                        "external_reference": c.external_reference,
                    }
                    for c in citations
                ]
        except Exception as e:
            logger.error(f"Failed to get citations: {e}")
            return []

    def get_equations(self, paper_id: str) -> list[dict]:
        """Get equations for a paper."""
        try:
            with get_session() as session:
                equations = (
                    session.query(Equation)
                    .filter(Equation.paper_id == paper_id)
                    .all()
                )
                return [
                    {
                        "equation_id": e.equation_id,
                        "paper_id": e.paper_id,
                        "equation_text": e.equation_text,
                        "equation_number": e.equation_number,
                        "section_title": e.section_title,
                        "page_number": e.page_number,
                        "context": e.context,
                        "equation_type": e.equation_type,
                    }
                    for e in equations
                ]
        except Exception as e:
            logger.error(f"Failed to get equations: {e}")
            return []


def get_paper_service(user_id: str | None = None) -> PaperService:
    """Get paper service instance for the given user."""
    return PaperService(user_id=user_id or "anonymous")
