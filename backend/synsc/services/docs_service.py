"""Documentation site indexing.

Pipeline:
  1. Fetch sitemap.xml (or sitemap_index.xml recursively)
  2. For each page URL: fetch HTML, convert to markdown, extract heading
  3. Character-approximate chunk each page's markdown
  4. Generate embeddings via the shared paper embedder (768-dim,
     all-mpnet-base-v2) so the schema matches paper_chunk_embeddings
  5. Batch-insert source row + chunks + embeddings via SQLAlchemy

Politeness defaults: 1 req/sec, 200 pages max, 30s per fetch, 10 MB per page.
Dedupe: documentation_sources.url is UNIQUE — re-indexing the same URL
reuses the existing source.

Translation from upstream synsc-context b2a251d: Supabase REST swapped
for SQLAlchemy session writes; raw SQL handles the pgvector embedding
column.
"""
from __future__ import annotations

import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from urllib.parse import urlparse

import httpx
import structlog
from markdownify import markdownify
from sqlalchemy import text

from synsc.database.connection import get_session
from synsc.database.models import (
    DocumentationChunk,
    DocumentationSource,
    UserDocumentationSource,
)

logger = structlog.get_logger(__name__)

_DEFAULT_MAX_PAGES = 200
_DEFAULT_REQ_TIMEOUT = 30.0
_DEFAULT_REQ_DELAY_S = 1.0
_DEFAULT_MAX_PAGE_BYTES = 10 * 1024 * 1024  # 10 MB
_CHUNK_TOKENS = 800
_CHUNK_OVERLAP = 80

_SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


class DocsService:
    """Crawl + index a documentation site."""

    def __init__(self, user_id: str | None = None):
        self.user_id = user_id

    # ------------------------------------------------------------------
    # Embedding helper (lazy — same singleton as papers)
    # ------------------------------------------------------------------

    def _embed(self, texts: list[str]):
        from synsc.embeddings.generator import get_paper_embedding_generator

        gen = get_paper_embedding_generator()
        return gen.generate_batched(texts)

    # ------------------------------------------------------------------
    # Sitemap discovery
    # ------------------------------------------------------------------

    def _discover_sitemap(self, url: str) -> str:
        if url.lower().endswith((".xml", ".xml.gz")):
            return url
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"

    def _fetch(self, client: httpx.Client, url: str) -> bytes:
        resp = client.get(url, timeout=_DEFAULT_REQ_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp.content[:_DEFAULT_MAX_PAGE_BYTES]

    def _iter_sitemap_urls(
        self,
        client: httpx.Client,
        sitemap_url: str,
        max_pages: int,
    ) -> Iterator[str]:
        """Yield page URLs from a sitemap or sitemap index (one level deep)."""
        body = self._fetch(client, sitemap_url)
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            logger.warning(
                "docs: sitemap not valid XML", url=sitemap_url, error=str(exc)
            )
            return

        tag = root.tag.rsplit("}", 1)[-1]
        seen = 0

        if tag == "sitemapindex":
            for sm_el in root.findall("sm:sitemap", _SM_NS):
                loc = sm_el.findtext("sm:loc", namespaces=_SM_NS)
                if not loc:
                    continue
                try:
                    for page_url in self._iter_sitemap_urls(
                        client, loc, max_pages - seen
                    ):
                        if seen >= max_pages:
                            return
                        seen += 1
                        yield page_url
                except Exception as exc:
                    logger.warning(
                        "docs: nested sitemap failed", url=loc, error=str(exc)
                    )
        else:
            for url_el in root.findall("sm:url", _SM_NS):
                loc = url_el.findtext("sm:loc", namespaces=_SM_NS)
                if not loc:
                    continue
                if seen >= max_pages:
                    return
                seen += 1
                yield loc

    # ------------------------------------------------------------------
    # Page extraction + chunking
    # ------------------------------------------------------------------

    @staticmethod
    def _html_to_markdown(html: bytes) -> tuple[str, str | None]:
        try:
            txt = html.decode("utf-8", errors="ignore")
        except Exception:
            return "", None
        md = markdownify(txt, heading_style="ATX") or ""
        heading = None
        for line in md.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                heading = stripped[2:].strip()
                break
        return md, heading

    @staticmethod
    def _chunk_markdown(
        md: str,
        chunk_tokens: int = _CHUNK_TOKENS,
        overlap: int = _CHUNK_OVERLAP,
    ) -> list[str]:
        """Dependency-free character-approx chunker (~4 chars / token)."""
        if not md.strip():
            return []
        approx_chars = chunk_tokens * 4
        overlap_chars = overlap * 4
        chunks: list[str] = []
        start = 0
        while start < len(md):
            end = min(len(md), start + approx_chars)
            chunk = md[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(md):
                break
            start = end - overlap_chars
            if start < 0:
                start = 0
        return chunks

    # ------------------------------------------------------------------
    # Top-level indexing entry point
    # ------------------------------------------------------------------

    def index_docs(
        self,
        url: str,
        display_name: str | None = None,
        sitemap_url: str | None = None,
        max_pages: int = _DEFAULT_MAX_PAGES,
        req_delay_s: float = _DEFAULT_REQ_DELAY_S,
    ) -> dict:
        """Crawl + index a docs site. Returns the canonical index-response shape."""
        t0 = time.time()

        if not self.user_id:
            return {"success": False, "error": "User ID is required"}

        # Dedup by URL.
        with get_session() as session:
            existing = (
                session.query(DocumentationSource)
                .filter(DocumentationSource.url == url)
                .first()
            )
            if existing:
                self._grant_user_access(session, existing.docs_id)
                session.commit()
                elapsed = (time.time() - t0) * 1000
                return {
                    "success": True,
                    "status": "already_indexed",
                    "docs_id": existing.docs_id,
                    "url": url,
                    "pages": existing.pages_count,
                    "chunks": existing.chunks_count,
                    "time_ms": round(elapsed, 1),
                }

        sitemap = sitemap_url or self._discover_sitemap(url)
        docs_id = str(uuid.uuid4())

        all_chunks: list[dict] = []
        pages_seen = 0

        with httpx.Client(
            timeout=_DEFAULT_REQ_TIMEOUT, follow_redirects=True
        ) as client:
            try:
                page_urls = list(
                    self._iter_sitemap_urls(client, sitemap, max_pages)
                )
            except Exception as exc:
                logger.error(
                    "docs: failed to read sitemap",
                    sitemap=sitemap,
                    error=str(exc),
                )
                return {
                    "success": False,
                    "error": f"sitemap fetch failed: {exc}",
                }

            for page_url in page_urls:
                try:
                    html = self._fetch(client, page_url)
                except Exception as exc:
                    logger.warning(
                        "docs: skip page", url=page_url, error=str(exc)
                    )
                    continue

                md, heading = self._html_to_markdown(html)
                for chunk_text in self._chunk_markdown(md):
                    all_chunks.append(
                        {
                            "chunk_id": str(uuid.uuid4()),
                            "docs_id": docs_id,
                            "chunk_index": len(all_chunks),
                            "page_url": page_url,
                            "heading": heading,
                            "content": _sanitize_text(chunk_text),
                            "token_count": max(1, len(chunk_text) // 4),
                        }
                    )
                pages_seen += 1
                if req_delay_s > 0:
                    time.sleep(req_delay_s)

        if not all_chunks:
            return {
                "success": False,
                "error": "no crawlable pages found",
                "url": url,
                "sitemap_url": sitemap,
            }

        # Embed.
        texts = [c["content"] for c in all_chunks]
        embeddings = self._embed(texts)

        with get_session() as session:
            session.add(
                DocumentationSource(
                    docs_id=docs_id,
                    url=url,
                    display_name=display_name,
                    sitemap_url=sitemap,
                    indexed_by=self.user_id,
                    is_public=True,
                    pages_count=pages_seen,
                    chunks_count=len(all_chunks),
                )
            )
            session.flush()

            session.add_all(
                DocumentationChunk(**c) for c in all_chunks
            )
            session.flush()

            # Embedding rows: vector column lives in raw SQL — insert via text.
            for chunk, emb in zip(all_chunks, embeddings, strict=False):
                emb_list = (
                    emb.tolist() if hasattr(emb, "tolist") else list(emb)
                )
                emb_str = "[" + ",".join(str(x) for x in emb_list) + "]"
                session.execute(
                    text(
                        "INSERT INTO documentation_chunk_embeddings "
                        "(embedding_id, docs_id, chunk_id, embedding) "
                        "VALUES (:eid, :did, :cid, CAST(:emb AS vector))"
                    ),
                    {
                        "eid": str(uuid.uuid4()),
                        "did": docs_id,
                        "cid": chunk["chunk_id"],
                        "emb": emb_str,
                    },
                )

            self._grant_user_access(session, docs_id)
            session.commit()

        elapsed = (time.time() - t0) * 1000
        return {
            "success": True,
            "status": "indexed",
            "docs_id": docs_id,
            "url": url,
            "pages": pages_seen,
            "chunks": len(all_chunks),
            "time_ms": round(elapsed, 1),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _grant_user_access(self, session, docs_id: str) -> bool:
        if not self.user_id:
            return False
        existing = (
            session.query(UserDocumentationSource)
            .filter(
                UserDocumentationSource.user_id == self.user_id,
                UserDocumentationSource.docs_id == docs_id,
            )
            .first()
        )
        if existing:
            return True
        session.add(
            UserDocumentationSource(user_id=self.user_id, docs_id=docs_id)
        )
        return True

    def search_docs(self, query: str, top_k: int = 10) -> dict:
        """Semantic search over indexed docs via pgvector cosine similarity.

        Scoped to docs the current user has in their collection. Uses raw
        SQL against ``documentation_chunk_embeddings`` — no new RPC required.
        """
        if not self.user_id:
            return {"success": False, "error": "User ID required", "results": []}

        try:
            from synsc.embeddings.generator import get_paper_embedding_generator

            gen = get_paper_embedding_generator()
            q_emb = gen.generate_single(query)
            emb_list = (
                q_emb.tolist() if hasattr(q_emb, "tolist") else list(q_emb)
            )
            emb_str = "[" + ",".join(str(x) for x in emb_list) + "]"

            with get_session() as session:
                rows = (
                    session.execute(
                        text(
                            """
                            SELECT c.chunk_id AS chunk_id,
                                   c.docs_id AS docs_id,
                                   c.page_url,
                                   c.heading,
                                   c.content,
                                   1 - (e.embedding <=> CAST(:q AS vector)) AS similarity,
                                   ds.url AS docs_url,
                                   ds.display_name
                            FROM documentation_chunk_embeddings e
                            JOIN documentation_chunks c ON c.chunk_id = e.chunk_id
                            JOIN documentation_sources ds ON ds.docs_id = c.docs_id
                            JOIN user_documentation_sources uds ON uds.docs_id = ds.docs_id
                            WHERE uds.user_id = :uid
                            ORDER BY e.embedding <=> CAST(:q AS vector)
                            LIMIT :k
                            """
                        ),
                        {"q": emb_str, "uid": self.user_id, "k": top_k},
                    )
                    .mappings()
                    .all()
                )

            results = [dict(r) for r in rows]
            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
            }
        except Exception as exc:
            logger.exception("docs: search failed")
            return {"success": False, "error": str(exc), "results": []}

    def list_docs(self) -> list[dict]:
        if not self.user_id:
            return []
        try:
            with get_session() as session:
                rows = (
                    session.query(DocumentationSource)
                    .join(
                        UserDocumentationSource,
                        UserDocumentationSource.docs_id == DocumentationSource.docs_id,
                    )
                    .filter(UserDocumentationSource.user_id == self.user_id)
                    .order_by(UserDocumentationSource.added_at.desc())
                    .all()
                )
                return [
                    {
                        "docs_id": r.docs_id,
                        "url": r.url,
                        "display_name": r.display_name,
                        "sitemap_url": r.sitemap_url,
                        "is_public": r.is_public,
                        "pages_count": r.pages_count,
                        "chunks_count": r.chunks_count,
                        "indexed_at": (
                            r.indexed_at.isoformat() if r.indexed_at else None
                        ),
                    }
                    for r in rows
                ]
        except Exception as exc:
            logger.error("docs: list failed", error=str(exc))
            return []


def _sanitize_text(text: str | None) -> str:
    """PostgreSQL text columns cannot contain \\x00."""
    if text is None:
        return ""
    return text.replace("\x00", "")


_services: dict[str, DocsService] = {}


def get_docs_service(user_id: str | None = None) -> DocsService:
    """Return a cached DocsService instance per user."""
    key = user_id or "_default"
    if key not in _services:
        _services[key] = DocsService(user_id=user_id)
    return _services[key]
