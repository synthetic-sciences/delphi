"""Auto-discover the documentation site for a GitHub repository.

When a user indexes a repo, the queries they later run usually mix code-level
("where is X defined") with concept-level ("how does X work") questions.
Conceptual queries are almost always answered better by the project's
documentation site than by raw source. Competitors like Nia pre-crawl docs
sites alongside repos in their global index — Delphi loses ~15% on
concept-style queries without this.

This module does a best-effort discovery: ping GitHub's REST API for the
repo's ``homepage`` field, scrape the README for ``docs.`` / ``readthedocs``
/ ``rtd.io`` links, and check ``pyproject.toml`` ``[project.urls]`` for a
``Documentation`` entry. The first plausible match wins; the caller can
opt-in via ``index_source(..., options={"auto_index_docs": True})``.

Discovery is best-effort and budget-bounded: a single GitHub request and at
most one raw.githubusercontent.com fetch for the README + pyproject.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
import structlog

logger = structlog.get_logger(__name__)


_TIMEOUT = 8.0
_DOC_DOMAIN_RE = re.compile(
    r"https?://[^\s)>'\"]+",
    re.IGNORECASE,
)
_DOC_HOST_HINTS = (
    "readthedocs.io",
    "readthedocs.org",
    "rtd.io",
    "docs.",
    ".dev/docs",
    "/docs/",
    ".gitbook.io",
    "mintlify.app",
    "tiangolo.com",  # FastAPI / many Tiangolo projects
    "/docs",
)

_NON_DOC_HOSTS = (
    "github.com",
    "github.io",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
    "stackoverflow.com",
    "discord.gg",
    "pypi.org",
    "npmjs.com",
)


def _looks_like_docs(url: str) -> bool:
    u = url.lower()
    if any(h in u for h in _NON_DOC_HOSTS):
        return False
    return any(h in u for h in _DOC_HOST_HINTS)


def _normalize_docs_root(url: str) -> str:
    """Snap a deep docs URL back to its root."""
    p = urlparse(url)
    if not p.netloc:
        return url
    # Common pattern: docs.X.io/en/latest/whatever → docs.X.io/
    return f"{p.scheme}://{p.netloc}/"


def _from_github_homepage(client: httpx.Client, owner: str, name: str) -> str | None:
    try:
        resp = client.get(
            f"https://api.github.com/repos/{owner}/{name}",
            timeout=_TIMEOUT,
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code != 200:
            return None
        hp = (resp.json() or {}).get("homepage") or ""
        hp = hp.strip()
        if hp and _looks_like_docs(hp):
            return _normalize_docs_root(hp)
        if hp and hp.startswith(("http://", "https://")):
            # Homepage is set but doesn't look like docs — still a reasonable
            # candidate if nothing else turns up. Mark it for fallback.
            return _normalize_docs_root(hp) + "#homepage"
    except Exception as exc:
        logger.debug("autodiscover: github homepage failed", error=str(exc))
    return None


def _from_readme(client: httpx.Client, owner: str, name: str, branch: str) -> str | None:
    for fname in ("README.md", "README.rst", "README"):
        try:
            url = f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/{fname}"
            resp = client.get(url, timeout=_TIMEOUT)
            if resp.status_code != 200:
                continue
            body = resp.text[:50000]
            for m in _DOC_DOMAIN_RE.finditer(body):
                candidate = m.group(0).rstrip(".,;)")
                if _looks_like_docs(candidate):
                    return _normalize_docs_root(candidate)
            return None
        except Exception as exc:
            logger.debug("autodiscover: readme failed", fname=fname, error=str(exc))
    return None


def _from_pyproject(client: httpx.Client, owner: str, name: str, branch: str) -> str | None:
    try:
        url = f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/pyproject.toml"
        resp = client.get(url, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None
        body = resp.text
        # Look for [project.urls] Documentation = "..."
        m = re.search(
            r'Documentation\s*=\s*"([^"]+)"', body, re.IGNORECASE
        )
        if m:
            return _normalize_docs_root(m.group(1))
        m = re.search(r'docs?\s*=\s*"([^"]+)"', body, re.IGNORECASE)
        if m and _looks_like_docs(m.group(1)):
            return _normalize_docs_root(m.group(1))
    except Exception as exc:
        logger.debug("autodiscover: pyproject failed", error=str(exc))
    return None


def discover_docs_url(
    repo_url: str,
    branch: str = "main",
) -> str | None:
    """Return a probable docs root URL for ``repo_url``, or None.

    Order:
      1. GitHub homepage field (if it looks like docs)
      2. README link with a docs-y host
      3. pyproject [project.urls] Documentation
      4. GitHub homepage field as fallback even if it doesn't match docs-y heuristics

    Strips a trailing ``#homepage`` marker before returning.
    """
    m = re.match(
        r"^https?://github\.com/([^/]+)/([^/.]+?)(?:\.git)?/?$",
        repo_url.strip(),
        re.IGNORECASE,
    )
    if not m:
        return None
    owner, name = m.group(1), m.group(2)

    with httpx.Client(follow_redirects=True) as client:
        for fn in (_from_github_homepage, _from_readme, _from_pyproject):
            try:
                if fn is _from_github_homepage:
                    found = fn(client, owner, name)
                else:
                    found = fn(client, owner, name, branch)
            except Exception as exc:
                logger.debug("autodiscover: branch failed", fn=fn.__name__, error=str(exc))
                found = None
            if found:
                return found.rstrip("#homepage")
    return None
