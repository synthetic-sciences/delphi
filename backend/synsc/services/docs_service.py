"""Documentation site indexing.

Pipeline:
  1. Fetch sitemap.xml (or sitemap_index.xml recursively), falling back to
     a bounded same-origin crawl when an auto-discovered sitemap is absent
  2. For each page URL: fetch HTML → strip nav/sidebar/footer →
     markdownify → strip permalink-anchors → heading-aware chunk
  3. Generate embeddings via the shared paper embedder (768-dim,
     all-mpnet-base-v2) so the schema matches paper_chunk_embeddings
  4. Batch-insert source row + chunks + embeddings via SQLAlchemy

Politeness defaults: 1 req/sec, 200 pages max, 30s per fetch, 10 MB per page.
Dedupe: documentation_sources (url, version) is UNIQUE — re-indexing the
same URL+version reuses the existing source.

Bench-driven refinements (May 2026):
  - **Strip navigation, sidebar, footer, breadcrumb, ToC, and TOC-link
    elements before markdownify** so chunks contain content text only,
    not boilerplate that dilutes per-chunk signal.
  - **Strip ``[ ](url)`` permalink anchors** that mkdocs-material injects
    on every heading. They polluted ~30% of every chunk with noise.
  - **Heading-aware chunking**: split on H2/H3 boundaries and attach the
    full heading path (``# Page > ## Section > ### Subsection``) to each
    chunk so retrieval surfaces the section title alongside content.
    Tiny sections get merged; oversized sections get paragraph-split.
"""
from __future__ import annotations

import re
import time
import uuid
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Iterator, Sequence
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx
import numpy as np
import structlog
from markdownify import markdownify
from sqlalchemy import bindparam, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from synsc.database.connection import get_session
from synsc.database.models import (
    DocumentationChunk,
    DocumentationSource,
    UserDocumentationSource,
)
from synsc.network.public_http import (
    PublicHTTPTransport as _PublicHTTPTransport,
)
from synsc.network.public_http import (
    PublicNetworkBackend as _PublicNetworkBackend,  # noqa: F401
)
from synsc.network.public_http import (
    resolve_public_addresses as _resolve_public_addresses,  # noqa: F401
)
from synsc.network.public_http import (
    validate_public_http_url as _validate_public_url,
)
from synsc.providers.contracts import CancellationToken

logger = structlog.get_logger(__name__)

_DEFAULT_MAX_PAGES = 200
_DEFAULT_REQ_TIMEOUT = 30.0
_DEFAULT_REQ_DELAY_S = 1.0
_DEFAULT_MAX_PAGE_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_REDIRECTS = 5
_CHUNK_TOKENS = 800
_CHUNK_OVERLAP = 80

_SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_DOC_PAGE_SUFFIXES = frozenset(
    {
        ".asp",
        ".aspx",
        ".htm",
        ".html",
        ".md",
        ".php",
        ".rst",
        ".txt",
        ".xhtml",
    }
)


def _safe_scope_path(path: str) -> str | None:
    decoded = path
    for _ in range(8):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    else:
        return None

    decoded = decoded.replace("\\", "/")
    if any(ord(character) < 32 for character in decoded):
        return None
    if any(segment in {".", ".."} for segment in decoded.split("/")):
        return None
    return re.sub(r"/+", "/", decoded) or "/"


def _in_documentation_scope(start_url: str, candidate_url: str) -> bool:
    """Return whether a page belongs to the requested documentation tree."""
    start = urlparse(start_url)
    candidate = urlparse(candidate_url)
    if (
        candidate.scheme.casefold() != start.scheme.casefold()
        or candidate.netloc.casefold() != start.netloc.casefold()
    ):
        return False

    start_path = _safe_scope_path(start.path or "/")
    candidate_path = _safe_scope_path(candidate.path or "/")
    if start_path is None or candidate_path is None:
        return False
    if start_path.endswith("/"):
        return candidate_path.startswith(start_path)

    terminal = start_path.rsplit("/", 1)[-1]
    suffix = "." + terminal.rsplit(".", 1)[-1].casefold() if "." in terminal else ""
    if suffix in _DOC_PAGE_SUFFIXES:
        parent = start_path.rsplit("/", 1)[0] + "/"
        return candidate_path.startswith(parent)

    return (
        candidate_path == start_path
        or candidate_path.startswith(start_path + "/")
    )


class DocsService:
    """Crawl + index a documentation site."""

    def __init__(self, user_id: str | None = None):
        self.user_id = user_id
        self._last_embedding_model = "unknown"

    # ------------------------------------------------------------------
    # Embedding helper (lazy — same singleton as papers)
    # ------------------------------------------------------------------

    def _embed(self, texts: list[str]) -> np.ndarray:
        from synsc.embeddings.generator import get_paper_embedding_generator

        gen = get_paper_embedding_generator()
        self._last_embedding_model = str(gen.model_name)
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
        current_url = url
        redirect_statuses = {301, 302, 303, 307, 308}
        for _ in range(_MAX_REDIRECTS + 1):
            _validate_public_url(current_url)
            resp = client.get(
                current_url,
                timeout=_DEFAULT_REQ_TIMEOUT,
                follow_redirects=False,
            )
            if resp.status_code not in redirect_statuses:
                resp.raise_for_status()
                return resp.content[:_DEFAULT_MAX_PAGE_BYTES]

            location = resp.headers.get("location")
            if not location:
                raise ValueError("Documentation redirect is missing a location")
            current_url = urljoin(current_url, location)

        raise ValueError("Documentation URL exceeded the redirect limit")

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

    def _iter_crawl_pages(
        self,
        client: httpx.Client,
        start_url: str,
        max_pages: int,
    ) -> Iterator[tuple[str, bytes]]:
        """Yield a bounded, same-origin documentation crawl with page bodies."""

        parsed_start = urlparse(start_url)

        canonical_start = parsed_start._replace(
            query="",
            fragment="",
        ).geturl()
        queue = deque([canonical_start])
        queued = {canonical_start}
        skipped_suffixes = (
            ".css",
            ".gif",
            ".gz",
            ".ico",
            ".jpeg",
            ".jpg",
            ".js",
            ".json",
            ".pdf",
            ".png",
            ".svg",
            ".tar",
            ".tgz",
            ".webp",
            ".woff",
            ".woff2",
            ".xml",
            ".zip",
        )
        yielded = 0

        while queue and yielded < max_pages:
            page_url = queue.popleft()
            try:
                body = self._fetch(client, page_url)
            except Exception as exc:
                logger.warning(
                    "docs: skip crawl page",
                    url=page_url,
                    error=str(exc),
                )
                continue

            yielded += 1
            yield page_url, body

            try:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(body, "html.parser")
                hrefs = (
                    str(anchor.get("href") or "")
                    for anchor in soup.find_all("a")
                )
            except Exception:
                decoded = body.decode("utf-8", errors="ignore")
                hrefs = (
                    match.group(1)
                    for match in re.finditer(
                        r"""href=["']([^"'#]+)["']""",
                        decoded,
                        flags=re.IGNORECASE,
                    )
                )

            for href in hrefs:
                if not href or href.startswith(("#", "mailto:", "javascript:")):
                    continue
                parsed = urlparse(urljoin(page_url, href))
                if (
                    not _in_documentation_scope(start_url, parsed.geturl())
                    or parsed.path.lower().endswith(skipped_suffixes)
                ):
                    continue
                candidate = parsed._replace(query="", fragment="").geturl()
                if candidate not in queued:
                    queued.add(candidate)
                    queue.append(candidate)

    def _resolve_pages(
        self,
        client: httpx.Client,
        url: str,
        *,
        sitemap_url: str | None,
        max_pages: int,
    ) -> list[tuple[str, bytes | None]]:
        """Resolve sitemap pages or safely fall back to a scoped crawl."""

        explicit_sitemap = sitemap_url is not None or url.lower().endswith(
            (".xml", ".xml.gz")
        )
        sitemap = sitemap_url or self._discover_sitemap(url)
        try:
            sitemap_pages = list(
                self._iter_sitemap_urls(client, sitemap, max_pages)
            )
        except Exception:
            if explicit_sitemap:
                raise
            logger.info(
                "docs: auto-discovered sitemap unavailable; "
                "falling back to scoped crawl",
                sitemap=sitemap,
                url=url,
            )
        else:
            if not explicit_sitemap:
                sitemap_pages = [
                    page_url
                    for page_url in sitemap_pages
                    if _in_documentation_scope(url, page_url)
                ]
            if sitemap_pages or explicit_sitemap:
                return [(page_url, None) for page_url in sitemap_pages]
            logger.info(
                "docs: auto-discovered sitemap empty or outside scope; "
                "falling back to scoped crawl",
                sitemap=sitemap,
                url=url,
            )

        crawled = list(self._iter_crawl_pages(client, url, max_pages))
        if not crawled:
            raise ValueError("No documentation pages could be discovered")
        return [(page_url, body) for page_url, body in crawled]

    # ------------------------------------------------------------------
    # Page extraction + chunking
    # ------------------------------------------------------------------

    # CSS classes / element names that are almost always navigation,
    # sidebar, footer, breadcrumb, or table-of-contents UI rather than
    # content. Filtering these before markdownify strips ~30% of the
    # boilerplate that previously bled into every chunk.
    _NOISE_ELEMENTS = ("nav", "aside", "footer", "script", "style", "noscript", "header")
    _NOISE_CLASS_HINTS = (
        "navbar", "navigation", "sidebar", "side-bar", "toc",
        "table-of-contents", "breadcrumb", "footer", "menu",
        "search", "edit-this-page", "skip-link", "pagination",
        "md-sidebar", "md-header", "md-footer", "md-search",
    )
    _NOISE_ROLES = ("navigation", "search", "banner", "contentinfo")

    @classmethod
    def _strip_noise(cls, html: bytes) -> str:
        """Strip nav/sidebar/footer/search/breadcrumb before markdownify.

        Falls back to a string-decode pass when BeautifulSoup isn't
        available — the rest of the pipeline still functions.
        """
        try:
            from bs4 import BeautifulSoup
        except Exception:
            try:
                return html.decode("utf-8", errors="ignore")
            except Exception:
                return ""
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            return html.decode("utf-8", errors="ignore")

        for tag in soup(list(cls._NOISE_ELEMENTS)):
            tag.decompose()
        for el in list(soup.find_all(True)):
            # Element may have been removed already when its parent was
            # decomposed in an earlier iteration. Skip safely.
            if not hasattr(el, "get") or el.parent is None:
                continue
            try:
                cls_attr = " ".join(el.get("class") or []).lower()
                role_attr = str(el.get("role") or "").lower()
            except Exception:
                continue
            if any(hint in cls_attr for hint in cls._NOISE_CLASS_HINTS):
                el.decompose()
                continue
            if role_attr in cls._NOISE_ROLES:
                el.decompose()
                continue
        # Prefer <main> / <article> when present — the page content lives
        # there. Falling back to the full body otherwise.
        main = soup.find("main") or soup.find("article")
        if main is not None:
            return str(main)
        return str(soup)

    # Regexes used to scrub markdownify output of mkdocs-material noise.
    # Matches markdownify's permalink output, which can come in two forms:
    #   [ ](url#anchor)                — bare anchor link
    #   [[ ]](url#anchor)              — extra brackets from headerlink span
    # Tolerate newlines inside the URL (markdownify sometimes wraps mid-link)
    # by using re.DOTALL via inline-flag.
    _PERMALINK_RE = re.compile(r"\[+\s*\]+\(\s*[^)\n]*?\)", re.DOTALL)
    _BROKEN_LINK_RE = re.compile(r"\[+\s*\]+\(\s*\n", re.DOTALL)
    _MULTI_BLANK_RE = re.compile(r"\n{3,}")
    _TRAILING_HASH_RE = re.compile(r"\s*\\?#[^\s]*$")
    _EMPTY_LIST_RE = re.compile(r"^\s*[-*]\s*$", re.MULTILINE)

    @classmethod
    def _clean_markdown(cls, md: str) -> str:
        """Remove permalink anchors and collapse blank runs."""
        md = cls._PERMALINK_RE.sub("", md)
        # Mid-line broken links like ``[ ](\n\nBody.`` happen when the
        # heading anchor wraps; collapse the leftover ``[ ](`` fragment.
        md = cls._BROKEN_LINK_RE.sub("", md)
        # Also kill stray dangling ``[[ ]](`` fragments that survive the
        # permalink regex (markdownify quirk).
        md = re.sub(r"\[+\s*\]+\(", "", md)
        md = cls._EMPTY_LIST_RE.sub("", md)
        md = cls._MULTI_BLANK_RE.sub("\n\n", md)
        # Strip trailing hash-link markers like "Section\#section" that
        # mkdocs-material leaves after permalink removal.
        lines = []
        for line in md.splitlines():
            lines.append(cls._TRAILING_HASH_RE.sub("", line).rstrip())
        return "\n".join(lines).strip()

    @classmethod
    def _html_to_markdown(cls, html: bytes) -> tuple[str, str | None]:
        cleaned_html = cls._strip_noise(html)
        if not cleaned_html:
            return "", None
        md = markdownify(cleaned_html, heading_style="ATX") or ""
        md = cls._clean_markdown(md)
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
        heading_prefix: str | None = None,
    ) -> list[tuple[str, str]]:
        """Heading-aware chunker.

        Splits the page at every H2 / H3 boundary so each chunk is one
        tutorial section. The chunk text is prefixed with the full
        heading path (``# Page > ## Section``) so embeddings see the
        section title alongside content. Tiny sections (< 200 chars)
        get glued onto the next section; oversized sections fall back
        to the legacy character-window split.

        Returns ``[(heading_path, text), ...]`` so callers can persist
        the heading on the chunk row alongside the content.
        """
        if not md.strip():
            return []
        approx_chars = max(1, chunk_tokens * 4)
        # Walk lines tracking current heading stack.
        sections: list[tuple[str, list[str]]] = []  # (heading_path, body_lines)
        h1: str | None = heading_prefix
        h2: str | None = None
        h3: str | None = None
        current_path = h1 or ""
        current_body: list[str] = []

        def flush() -> None:
            if current_body or current_path:
                sections.append((current_path, current_body[:]))

        for raw in md.splitlines():
            if raw.startswith("# "):
                flush()
                h1 = raw[2:].strip()
                h2 = h3 = None
                current_path = h1
                current_body = []
            elif raw.startswith("## "):
                flush()
                h2 = raw[3:].strip()
                h3 = None
                current_path = " > ".join(p for p in (h1, h2) if p)
                current_body = []
            elif raw.startswith("### "):
                flush()
                h3 = raw[4:].strip()
                current_path = " > ".join(p for p in (h1, h2, h3) if p)
                current_body = []
            else:
                current_body.append(raw)
        flush()

        # Drop the (heading_path, body) entries with no body. Then merge
        # tiny adjacent sections; split oversized ones.
        merged: list[tuple[str, str]] = []
        buffer_path: str | None = None
        buffer_body: list[str] = []
        for path, body in sections:
            joined = "\n".join(body).strip()
            if not joined:
                continue
            if buffer_path and len(("\n".join(buffer_body)).strip()) < 200:
                buffer_body.append(joined)
                buffer_path = buffer_path or path
                continue
            if buffer_path is not None:
                merged.append(
                    (buffer_path, "\n".join(buffer_body).strip())
                )
            buffer_path = path
            buffer_body = [joined]
        if buffer_path is not None:
            merged.append((buffer_path, "\n".join(buffer_body).strip()))

        # Now produce final chunks, prefixed with the heading path so the
        # embedding sees the section title.
        chunks: list[tuple[str, str]] = []
        def append_bounded(
            path: str,
            prefix: str,
            content: str,
            body_budget: int,
        ) -> None:
            """Append content without ever exceeding the body budget."""
            stripped = content.strip()
            if not stripped:
                return
            for start in range(0, len(stripped), body_budget):
                piece = stripped[start : start + body_budget].strip()
                if piece:
                    chunks.append((path, prefix + piece))

        for path, body_text in merged:
            text = body_text
            prefix_path = path[: approx_chars // 4].rstrip()
            prefix = prefix_path + "\n\n" if prefix_path else ""
            body_budget = max(1, approx_chars - len(prefix))
            if len(text) <= body_budget:
                chunks.append((path, prefix + text))
                continue
            # Oversized — pack normal paragraphs up to the character budget.
            # Flush giant paragraphs through append_bounded immediately:
            # waiting until the end used to let every non-final giant
            # paragraph escape as a single unbounded embedding input.
            paragraphs = re.split(r"\n\s*\n", text)
            buf: list[str] = []
            buf_len = 0
            for p in paragraphs:
                if len(p) > body_budget:
                    if buf:
                        append_bounded(
                            path,
                            prefix,
                            "\n\n".join(buf),
                            body_budget,
                        )
                        buf = []
                        buf_len = 0
                    append_bounded(path, prefix, p, body_budget)
                elif buf_len + len(p) + (2 if buf else 0) > body_budget:
                    append_bounded(
                        path,
                        prefix,
                        "\n\n".join(buf),
                        body_budget,
                    )
                    buf = [p]
                    buf_len = len(p)
                else:
                    buf.append(p)
                    buf_len += len(p) + (2 if len(buf) > 1 else 0)
            if buf:
                append_bounded(
                    path,
                    prefix,
                    "\n\n".join(buf),
                    body_budget,
                )
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
        version: str | None = None,
    ) -> dict[str, Any]:
        """Crawl + index a docs site. Returns the canonical index-response shape.

        ``version`` lets the caller pin a specific release (Context7 parity).
        The same URL can be indexed multiple times at different versions; each
        becomes its own ``docs_id``. NULL version is the legacy "rolling" snapshot.
        """
        t0 = time.time()

        if not self.user_id:
            return {"success": False, "error": "User ID is required"}

        # Dedup by (url, version).
        with get_session() as session:
            existing = (
                session.query(DocumentationSource)
                .filter(
                    DocumentationSource.url == url,
                    DocumentationSource.version == version,
                )
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

        all_chunks: list[dict[str, Any]] = []
        pages_seen = 0

        with httpx.Client(
            timeout=_DEFAULT_REQ_TIMEOUT,
            follow_redirects=False,
            transport=_PublicHTTPTransport(),
        ) as client:
            try:
                pages = self._resolve_pages(
                    client,
                    url,
                    sitemap_url=sitemap_url,
                    max_pages=max_pages,
                )
            except Exception as exc:
                logger.error(
                    "docs: failed to discover pages",
                    url=url,
                    sitemap=sitemap_url,
                    error=str(exc),
                )
                return {
                    "success": False,
                    "error": f"documentation discovery failed: {exc}",
                }

            for page_url, crawled_html in pages:
                if crawled_html is None:
                    try:
                        html = self._fetch(client, page_url)
                    except Exception as exc:
                        logger.warning(
                            "docs: skip page", url=page_url, error=str(exc)
                        )
                        continue
                else:
                    html = crawled_html

                md, page_heading = self._html_to_markdown(html)
                for chunk_path, chunk_text in self._chunk_markdown(
                    md, heading_prefix=page_heading
                ):
                    all_chunks.append(
                        {
                            "chunk_id": str(uuid.uuid4()),
                            "docs_id": docs_id,
                            "chunk_index": len(all_chunks),
                            "page_url": page_url,
                            # Heading column stores the full path so the
                            # row carries the section context even when
                            # the user reads it back without the body.
                            "heading": chunk_path or page_heading,
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
                    version=version,
                    display_name=display_name,
                    sitemap_url=sitemap,
                    indexed_by=self.user_id,
                    is_public=True,
                    embedding_model=self._last_embedding_model,
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

    def _grant_user_access(self, session: Session, docs_id: str) -> bool:
        if not self.user_id:
            return False
        uid = str(self.user_id)
        existing = (
            session.query(UserDocumentationSource)
            .filter(
                UserDocumentationSource.user_id == uid,
                UserDocumentationSource.docs_id == docs_id,
            )
            .first()
        )
        if existing:
            return True
        session.add(
            UserDocumentationSource(user_id=uid, docs_id=docs_id)
        )
        return True

    def search_docs(
        self,
        query: str,
        top_k: int = 10,
        docs_ids: list[str] | None = None,
        timeout_ms: int = 120_000,
        cancellation: CancellationToken | None = None,
    ) -> dict[str, Any]:
        """Hybrid docs search: vector + BM25 full-text fused, then sorted.

        Scoped to docs the current user has in their collection. The full-
        text branch uses ``content_tsv`` (added by migration 009); if the
        column / GIN index isn't present yet (older DB) the BM25 piece
        returns zero rows and the vector branch alone serves the query.
        """
        if not self.user_id:
            return {"success": False, "error": "User ID required", "results": []}

        try:
            token = cancellation or CancellationToken()
            if not 1 <= timeout_ms <= 300_000:
                raise ValueError("timeout_ms must be between 1 and 300000")
            deadline_monotonic = time.monotonic() + timeout_ms / 1000

            def remaining_timeout_ms() -> int:
                return max(
                    1,
                    int(
                        (deadline_monotonic - time.monotonic()) * 1000
                    ),
                )

            def stopped() -> bool:
                return (
                    token.cancelled
                    or time.monotonic() >= deadline_monotonic
                )

            if stopped():
                return {
                    "success": False,
                    "error": "Search cancelled",
                    "results": [],
                }
            from synsc.embeddings.generator import get_paper_embedding_generator

            gen = get_paper_embedding_generator()
            q_emb = gen.generate_single(query)
            if stopped():
                return {
                    "success": False,
                    "error": "Search cancelled",
                    "results": [],
                }
            emb_list = (
                q_emb.tolist() if hasattr(q_emb, "tolist") else list(q_emb)
            )
            emb_str = "[" + ",".join(str(x) for x in emb_list) + "]"

            # Force user_id to a plain str — auth may hand us a UUID object,
            # and the join column is VARCHAR, so Postgres refuses uuid = varchar.
            uid = str(self.user_id)
            # Fetch more candidates per branch so fusion has material to
            # work with. 3x final-k is the same heuristic hybrid_retrieval
            # uses for code.
            fetch_k = max(top_k * 3, 30)
            docs_clause = (
                "AND c.docs_id IN :docs_ids"
                if docs_ids
                else ""
            )
            vector_statement = text(
                f"""
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
                {docs_clause}
                ORDER BY e.embedding <=> CAST(:q AS vector)
                LIMIT :k
                """
            )
            bm25_statement = text(
                f"""
                SELECT c.chunk_id AS chunk_id,
                       c.docs_id AS docs_id,
                       c.page_url,
                       c.heading,
                       c.content,
                       ts_rank_cd(
                           c.content_tsv,
                           plainto_tsquery('english', :q_text)
                       ) AS similarity,
                       ds.url AS docs_url,
                       ds.display_name
                FROM documentation_chunks c
                JOIN documentation_sources ds ON ds.docs_id = c.docs_id
                JOIN user_documentation_sources uds ON uds.docs_id = ds.docs_id
                WHERE uds.user_id = :uid
                  AND c.content_tsv @@ plainto_tsquery('english', :q_text)
                {docs_clause}
                ORDER BY ts_rank_cd(
                    c.content_tsv,
                    plainto_tsquery('english', :q_text)
                ) DESC
                LIMIT :k
                """
            )
            if docs_ids:
                vector_statement = vector_statement.bindparams(
                    bindparam("docs_ids", expanding=True)
                )
                bm25_statement = bm25_statement.bindparams(
                    bindparam("docs_ids", expanding=True)
                )

            with get_session() as session:
                session.execute(
                    text(
                        "SELECT set_config("
                        "'statement_timeout', :timeout, true)"
                    ),
                    {"timeout": f"{remaining_timeout_ms()}ms"},
                )
                vector_params: dict[str, Any] = {
                    "q": emb_str,
                    "uid": uid,
                    "k": fetch_k,
                }
                if docs_ids:
                    vector_params["docs_ids"] = docs_ids
                vec_rows: Sequence[RowMapping] = (
                    session.execute(
                        vector_statement,
                        vector_params,
                    )
                    .mappings()
                    .all()
                )

                # BM25 branch — falls back gracefully when content_tsv
                # column isn't present (older bench DBs).
                bm25_rows: Sequence[RowMapping] = []
                try:
                    if stopped():
                        return {
                            "success": False,
                            "error": "Search cancelled",
                            "results": [],
                        }
                    session.execute(
                        text(
                            "SELECT set_config("
                            "'statement_timeout', :timeout, true)"
                        ),
                        {
                            "timeout": (
                                f"{remaining_timeout_ms()}ms"
                            )
                        },
                    )
                    bm25_params: dict[str, Any] = {
                        "q_text": query,
                        "uid": uid,
                        "k": fetch_k,
                    }
                    if docs_ids:
                        bm25_params["docs_ids"] = docs_ids
                    bm25_rows = (
                        session.execute(
                            bm25_statement,
                            bm25_params,
                        )
                        .mappings()
                        .all()
                    )
                except Exception as exc:
                    # Column missing or query parse failure → continue with
                    # vector-only results. Logged at debug.
                    logger.debug(
                        "docs.search_docs BM25 branch skipped", error=str(exc)
                    )

                # Fuse: normalize each branch's score in [0,1], then sum
                # (weighted: vector 0.7, BM25 0.3) and dedupe by chunk_id.
                def _normed(
                    rows: Sequence[RowMapping],
                    weight: float,
                ) -> dict[str, dict[str, Any]]:
                    if not rows:
                        return {}
                    scores = [float(r["similarity"] or 0.0) for r in rows]
                    lo, hi = min(scores), max(scores)
                    span = (hi - lo) or 1.0
                    out: dict[str, dict[str, Any]] = {}
                    for r in rows:
                        norm = ((float(r["similarity"] or 0.0) - lo) / span) * weight
                        rd = dict(r)
                        rd["_branch_score"] = norm
                        out[str(r["chunk_id"])] = rd
                    return out

                vec_idx = _normed(vec_rows, 0.7)
                bm25_idx = _normed(bm25_rows, 0.3)
                fused: dict[str, dict[str, Any]] = {}
                for cid, r in vec_idx.items():
                    fused[cid] = r
                    fused[cid]["similarity"] = r["_branch_score"]
                for cid, r in bm25_idx.items():
                    if cid in fused:
                        fused[cid]["similarity"] = (
                            float(fused[cid]["similarity"]) + r["_branch_score"]
                        )
                    else:
                        fused[cid] = r
                        fused[cid]["similarity"] = r["_branch_score"]
                rows = sorted(
                    fused.values(),
                    key=lambda r: float(r.get("similarity") or 0.0),
                    reverse=True,
                )[:top_k]

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

    def list_docs(self) -> list[dict[str, Any]]:
        if not self.user_id:
            return []
        try:
            uid = str(self.user_id)
            with get_session() as session:
                rows = (
                    session.query(DocumentationSource)
                    .join(
                        UserDocumentationSource,
                        UserDocumentationSource.docs_id == DocumentationSource.docs_id,
                    )
                    .filter(UserDocumentationSource.user_id == uid)
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
