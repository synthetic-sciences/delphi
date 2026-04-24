"""Context enrichment for code chunks before embedding.

Inspired by supermemoryai/code-chunk's approach: prepend semantic metadata
(scope chain, defined symbols, imports, siblings) to each chunk so the
embedding model captures structural context, not just raw code.

The raw code stored in the DB is unchanged — only the text sent to the
embedding model gets the context prefix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synsc.parsing.models import ExtractedSymbol


# ---------------------------------------------------------------------------
# Scope tree
# ---------------------------------------------------------------------------

@dataclass
class ScopeNode:
    """A node in the scope tree representing a symbol and its children."""

    symbol: ExtractedSymbol
    children: list[ScopeNode] = field(default_factory=list)
    parent: ScopeNode | None = field(default=None, repr=False)


def build_scope_tree(symbols: list[ExtractedSymbol]) -> list[ScopeNode]:
    """Build a hierarchical scope tree from a flat list of extracted symbols.

    Uses range containment: if symbol A's line range fully contains symbol B's,
    then B is a child of A.  Symbols are sorted by start_line so that parents
    are visited before children.

    Returns the list of root-level scope nodes.
    """
    if not symbols:
        return []

    # Sort by start_line, then widest span first (so parents come before children)
    sorted_syms = sorted(symbols, key=lambda s: (s.start_line, -(s.end_line - s.start_line)))

    roots: list[ScopeNode] = []
    all_nodes: list[ScopeNode] = []

    for sym in sorted_syms:
        node = ScopeNode(symbol=sym)

        # Walk backwards through existing nodes to find deepest parent
        parent_node = None
        for candidate in reversed(all_nodes):
            if (
                candidate.symbol.start_line <= sym.start_line
                and candidate.symbol.end_line >= sym.end_line
                and candidate.symbol is not sym
            ):
                parent_node = candidate
                break

        if parent_node:
            node.parent = parent_node
            parent_node.children.append(node)
        else:
            roots.append(node)

        all_nodes.append(node)

    return roots


# ---------------------------------------------------------------------------
# Scope / sibling lookup
# ---------------------------------------------------------------------------

def find_scope_at_line(roots: list[ScopeNode], line: int) -> list[ScopeNode]:
    """Find the scope chain (innermost → root) for a given line number.

    Returns a list where index 0 is the deepest scope containing ``line``.
    """
    chain: list[ScopeNode] = []

    def _walk(nodes: list[ScopeNode]) -> None:
        for node in nodes:
            if node.symbol.start_line <= line <= node.symbol.end_line:
                chain.append(node)
                _walk(node.children)
                return  # only one branch can contain the line

    _walk(roots)
    chain.reverse()  # innermost first
    return chain


def get_siblings(node: ScopeNode, max_per_side: int = 3) -> tuple[list[str], list[str]]:
    """Get sibling symbol names before and after *node*.

    Returns (before_names, after_names), each limited to *max_per_side*.
    """
    siblings = node.parent.children if node.parent else []
    if len(siblings) <= 1:
        return [], []

    idx = next((i for i, n in enumerate(siblings) if n is node), -1)
    if idx == -1:
        return [], []

    before = [n.symbol.name for n in siblings[max(0, idx - max_per_side):idx]]
    after = [n.symbol.name for n in siblings[idx + 1:idx + 1 + max_per_side]]
    return before, after


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------

_IMPORT_RE = re.compile(
    r"""
    # Python: import X  /  from X import Y
    ^(?:from\s+\S+\s+)?import\s+(.+)$
    """,
    re.MULTILINE | re.VERBOSE,
)


def extract_import_names(content: str, language: str | None = None) -> list[str]:
    """Extract imported names from source code.

    Lightweight regex approach — covers Python, JS/TS ``import`` statements.
    Does not need a full parse; good enough for context prefixes.
    """
    names: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()

        # Python: from X import a, b, c  |  import a, b
        if stripped.startswith("from ") or stripped.startswith("import "):
            # Get the part after "import"
            _, _, after = stripped.partition("import ")
            after = after.strip().rstrip("\\")
            for token in after.split(","):
                token = token.strip()
                # Handle "X as Y" — keep the alias
                if " as " in token:
                    token = token.split(" as ")[-1].strip()
                # Handle "import X.Y.Z" — keep last part
                if "." in token and not token.startswith("("):
                    token = token.rsplit(".", 1)[-1]
                if token and token.isidentifier():
                    names.append(token)

        # JS/TS: import { A, B } from '...'  |  import X from '...'
        elif stripped.startswith("import "):
            # Braces import
            brace_match = re.search(r"\{([^}]+)\}", stripped)
            if brace_match:
                for token in brace_match.group(1).split(","):
                    token = token.strip()
                    if " as " in token:
                        token = token.split(" as ")[-1].strip()
                    if token and token.isidentifier():
                        names.append(token)
            else:
                # Default import: import X from '...'
                m = re.match(r"import\s+(\w+)", stripped)
                if m:
                    names.append(m.group(1))

        # Go: import "pkg" or import ( "pkg" )
        # Rust: use crate::module::Item;
        # C/C++: #include <X> / #include "X"
        # — skip these for now; can add later

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return unique[:10]  # cap at 10 to avoid noisy prefixes


# ---------------------------------------------------------------------------
# Context prefix formatting
# ---------------------------------------------------------------------------

def format_context_prefix(
    file_path: str,
    chunk_start_line: int,
    chunk_end_line: int,
    symbols: list[ExtractedSymbol],
    file_content: str,
    language: str | None = None,
) -> str:
    """Build a context prefix string for a code chunk.

    Args:
        file_path: Relative file path in the repo.
        chunk_start_line: 1-indexed start line of the chunk.
        chunk_end_line: 1-indexed end line of the chunk.
        symbols: All extracted symbols for the file.
        file_content: Full file content (for import extraction).
        language: Programming language identifier.

    Returns:
        A multi-line ``# ...`` comment block to prepend to the chunk text
        before embedding.  Empty string if no useful context is available.
    """
    lines: list[str] = []

    # File path — abbreviated to last 3 segments
    short_path = "/".join(PurePosixPath(file_path).parts[-3:]) if file_path else ""
    if short_path:
        lines.append(f"# {short_path}")

    # Build scope tree and find scope at chunk start
    scope_tree = build_scope_tree(symbols)
    scope_chain = find_scope_at_line(scope_tree, chunk_start_line)

    # Scope chain (innermost → root)
    if scope_chain:
        scope_str = " > ".join(n.symbol.name for n in scope_chain)
        lines.append(f"# Scope: {scope_str}")

    # Defines — symbols whose start_line falls within this chunk
    defines: list[str] = []
    for sym in symbols:
        if chunk_start_line <= sym.start_line <= chunk_end_line:
            sig = sym.signature or sym.name
            defines.append(sig)
    if defines:
        lines.append(f"# Defines: {', '.join(defines[:5])}")

    # Imports — extract from full file, not just chunk
    import_names = extract_import_names(file_content, language)
    if import_names:
        lines.append(f"# Uses: {', '.join(import_names)}")

    # Siblings — if the chunk is inside a scope, show neighboring symbols
    if scope_chain:
        innermost = scope_chain[0]
        before, after = get_siblings(innermost)
        if before:
            lines.append(f"# After: {', '.join(before)}")
        if after:
            lines.append(f"# Before: {', '.join(after)}")

    if len(lines) <= 1:
        # Only file path — not enough context to be useful
        return ""

    return "\n".join(lines) + "\n\n"


def enrich_doc_chunk_for_embedding(
    chunk_content: str,
    file_path: str,
) -> str:
    """Return documentation chunk with a context prefix for embedding.

    Markdown/RST files don't have symbols or scope chains — instead we
    prepend the file path and a "Documentation" tag so the embedding
    model distinguishes docs from code.
    """
    short_path = "/".join(PurePosixPath(file_path).parts[-3:]) if file_path else ""
    if not short_path:
        return chunk_content

    # Extract first heading (# Title) if present
    heading = ""
    for line in chunk_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            break
        # RST-style heading: line followed by === or ---
        if len(stripped) > 2 and all(c in "=-~^" for c in stripped):
            break

    lines = [f"# {short_path}", "# Type: Documentation"]
    if heading:
        lines.append(f"# Section: {heading}")

    return "\n".join(lines) + "\n\n" + chunk_content


def enrich_chunk_for_embedding(
    chunk_content: str,
    file_path: str,
    chunk_start_line: int,
    chunk_end_line: int,
    symbols: list[ExtractedSymbol],
    file_content: str,
    language: str | None = None,
) -> str:
    """Return chunk content with context prefix prepended for embedding.

    The raw ``chunk_content`` is unchanged in the DB — this enriched version
    is only used when generating the embedding vector.
    """
    prefix = format_context_prefix(
        file_path=file_path,
        chunk_start_line=chunk_start_line,
        chunk_end_line=chunk_end_line,
        symbols=symbols,
        file_content=file_content,
        language=language,
    )
    if not prefix:
        return chunk_content
    return prefix + chunk_content
