"""A request that quotes a file's evidence should not get that file back.

The reviewer pasting a diff hunk has the reviewed file open; the missing
context is on the other side (the implementation behind a reviewed test, the
config consuming a changed schema). These tests pin the envelope detection,
the path extraction, and the stable demotion.
"""
from __future__ import annotations

import json

from synsc.services.search_service import _demote_anchor_paths, _query_anchor_paths

REVIEW_ENVELOPE = json.dumps({
    "diff_hunk_context": "@@ -108,3 +116,30 @@ def test(i):\n    assert x",
    "given_file": "tests/cover/test_seed_printing.py",
    "line": 145,
    "path": "tests/cover/test_seed_printing.py",
    "pr_title": "Print the seed when shrinking is slow",
    "review_comment": "let's assert that seed appears exactly once",
})


def test_review_envelope_yields_its_quoted_path():
    assert _query_anchor_paths(REVIEW_ENVELOPE) == {
        "tests/cover/test_seed_printing.py"
    }


def test_plain_intent_plus_file_is_not_an_anchor():
    # No quoted evidence: the file is the subject of the request, and the
    # caller genuinely wants it ranked.
    query = json.dumps({
        "intent": "explain what this module does",
        "path": "src/synsc/config.py",
    })
    assert _query_anchor_paths(query) == set()


def test_free_text_queries_never_anchor():
    assert _query_anchor_paths("why does the retry loop give up early") == set()


def test_absolute_and_traversal_paths_are_ignored():
    query = json.dumps({
        "review_comment": "check the helper",
        "path": "/etc/passwd",
        "given_file": "../outside/of/repo.py",
    })
    assert _query_anchor_paths(query) == set()


def _result(path: str, similarity: float) -> dict:
    return {"file_path": path, "similarity": similarity}


def test_demotion_moves_anchor_chunks_to_the_tail_stably():
    results = [
        _result("tests/test_a.py", 0.9),
        _result("src/core.py", 0.8),
        _result("tests/test_a.py", 0.7),
        _result("src/engine.py", 0.6),
    ]
    out = _demote_anchor_paths(results, {"tests/test_a.py"})
    assert [r["file_path"] for r in out] == [
        "src/core.py", "src/engine.py", "tests/test_a.py", "tests/test_a.py",
    ]


def test_demotion_is_a_no_op_without_anchors_or_alternatives():
    results = [_result("a.py", 0.9), _result("b.py", 0.8)]
    assert _demote_anchor_paths(results, set()) == results
    only_anchor = [_result("a.py", 0.9)]
    assert _demote_anchor_paths(only_anchor, {"a.py"}) == only_anchor
