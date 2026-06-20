"""String helpers."""

import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Convert arbitrary text into a URL-safe slug."""
    lowered = text.strip().lower()
    slug = _SLUG_RE.sub("-", lowered)
    return slug.strip("-")


def truncate(text: str, length: int = 80, suffix: str = "…") -> str:
    """Truncate text to a maximum length, appending a suffix if cut."""
    if len(text) <= length:
        return text
    return text[: length - len(suffix)].rstrip() + suffix
