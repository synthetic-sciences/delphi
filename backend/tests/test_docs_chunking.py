"""Tests for the upgraded docs chunker + HTML noise stripping."""
from __future__ import annotations

from synsc.services.docs_service import DocsService


HTML = b"""
<html>
<head><title>FastAPI - Background Tasks</title></head>
<body>
  <nav class="md-header">SHOULD BE STRIPPED nav</nav>
  <aside class="md-sidebar">SHOULD BE STRIPPED sidebar</aside>
  <main>
    <h1>Background Tasks</h1>
    <p>You can define background tasks to be run after returning a response.</p>
    <h2>Add the background task</h2>
    <p>Inside of your <i>path operation function</i>, pass your task function.</p>
    <pre><code>tasks.add_task(write_log, message)</code></pre>
    <h2>Caveat</h2>
    <p>Background tasks run after the response is sent.</p>
    <h3>Asyncio specifics</h3>
    <p>Use async functions if the work is awaitable.</p>
  </main>
  <footer>SHOULD BE STRIPPED footer</footer>
</body></html>
"""


def test_html_to_markdown_strips_nav_sidebar_footer():
    md, heading = DocsService._html_to_markdown(HTML)
    assert "STRIPPED" not in md
    assert "Background Tasks" in md
    assert heading == "Background Tasks"


def test_html_to_markdown_strips_permalink_anchors():
    raw = b"""
    <html><body><main>
      <h1>Section</h1>
      <h2>Foo <a href="#foo" class="headerlink">[ ]</a></h2>
      <p>Body.</p>
    </main></body></html>
    """
    md, _ = DocsService._html_to_markdown(raw)
    assert "[ ]" not in md
    assert "Foo" in md


def test_chunk_markdown_heading_aware():
    md = (
        "# Background Tasks\n\n"
        "You can define background tasks.\n\n"
        "## Add the background task\n\n"
        "Inside of your path operation function, pass your task function. " * 5
        + "\n\n"
        "## Caveat\n\n"
        "Background tasks run after the response is sent. " * 3
    )
    chunks = DocsService._chunk_markdown(md)
    assert len(chunks) >= 2
    # Each chunk has a (heading_path, text) shape.
    for path, txt in chunks:
        assert isinstance(path, str)
        assert isinstance(txt, str)
        assert path  # non-empty
        # The text starts with the heading path (so embedding sees it).
        assert txt.split("\n", 1)[0].startswith(path)


def test_chunk_markdown_attaches_heading_path():
    md = (
        "# Page Title\n\n"
        "## Section A\n\n"
        "Section A content here, long enough to stand on its own. "
        * 10 + "\n\n"
        "### Subsection A1\n\n"
        "More detail about A1. " * 10
    )
    chunks = DocsService._chunk_markdown(md)
    paths = [p for p, _ in chunks]
    # Both 'Page Title > Section A' and 'Page Title > Section A > Subsection A1'
    # should appear.
    assert any("Section A" in p for p in paths)
    assert any("Subsection A1" in p for p in paths)


def test_chunk_markdown_empty_returns_empty():
    assert DocsService._chunk_markdown("") == []
    assert DocsService._chunk_markdown("   \n\n  ") == []


def test_chunk_markdown_oversized_section_splits_at_paragraphs():
    para = "Word " * 600  # ~3000 chars
    md = f"# Title\n\n## Long\n\n{para}\n\n{para}\n\n{para}"
    chunks = DocsService._chunk_markdown(md, chunk_tokens=200)  # ~800 char budget
    # Should split the long section into multiple chunks.
    long_section_chunks = [c for p, c in chunks if "Long" in p]
    assert len(long_section_chunks) >= 2


def test_clean_markdown_removes_consecutive_blank_lines():
    md = "Line 1\n\n\n\nLine 2\n\n\n\n\nLine 3"
    out = DocsService._clean_markdown(md)
    assert "\n\n\n" not in out
    assert "Line 1" in out and "Line 2" in out and "Line 3" in out
