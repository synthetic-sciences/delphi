"""Unit tests for the ``classify_failure`` keyword classifier and the
observability helper functions. The DB-write side-effects are mocked.
"""
from __future__ import annotations

from unittest.mock import patch

from synsc.services.observability import (
    FAILURE_MODES,
    classify_failure,
    log_chunk_used,
    log_search_telemetry,
    log_skipped_files,
)


def _disable_db_writes():
    """All observability writers go through ``_write`` — patch it out so
    classifier tests don't touch a real DB.
    """
    return patch("synsc.services.observability._write")


def test_failure_modes_map_complete():
    """Every code we use in classify_failure() must have a message."""
    # Make sure every code that classify_failure can return is in the map.
    desc_codes = {
        "no_hits": "no results found",
        "stale_index": "stale commit",
        "filtered_by_pattern": "file was skipped",
        "rerank_unavailable": "rerank unavailable",
        "small_chunk_dropped": "small chunk dropped",
        "symbol_not_extracted": "parser missing",
        "branch_mismatch": "wrong branch",
        "private_repo_token": "github token expired for private repo",
        "embedding_drift": "embedding model dimension mismatch",
        "no_test_link": "no test found",
        "unknown": "asdf",
    }
    with _disable_db_writes():
        for expected_code, desc in desc_codes.items():
            res = classify_failure(description=desc)
            assert res["code"] == expected_code, (
                f"{desc!r} → got {res['code']!r}, want {expected_code!r}"
            )
            assert res["message"] == FAILURE_MODES[expected_code]


def test_failure_modes_includes_human_readable_strings():
    """A few of the codes have semantic content the agent should see."""
    assert "behind_remote" in FAILURE_MODES["stale_index"]
    assert "private" in FAILURE_MODES["private_repo_token"]
    assert "rerank" in FAILURE_MODES["rerank_unavailable"]
    assert "skipped" in FAILURE_MODES["filtered_by_pattern"]
    assert "branch" in FAILURE_MODES["branch_mismatch"]


def test_classifier_unknown_falls_through():
    with _disable_db_writes():
        res = classify_failure("the cat sat on the mat")
        assert res["code"] == "unknown"
        assert res["message"] == FAILURE_MODES["unknown"]


def test_classifier_handles_empty_description():
    with _disable_db_writes():
        res = classify_failure("")
        assert res["code"] == "unknown"


def test_log_helpers_silent_on_missing_user_id():
    """Logging without a user_id must be a no-op, not raise."""
    log_chunk_used(user_id=None, chunk_id="abc")
    log_skipped_files(
        repo_id="r1", user_id=None,
        skip_reasons={"x": 1}, total_seen=10, total_kept=9,
    )
    log_search_telemetry(
        user_id=None, query="q", quality_mode="agent",
        hybrid_meta=None, top_results=[], elapsed_ms=12.3,
    )


def test_log_chunk_used_writes_metadata_when_user_present():
    with _disable_db_writes() as m_write:
        log_chunk_used(user_id="u1", chunk_id="abc")
        m_write.assert_called_once()
        kwargs = m_write.call_args.kwargs
        assert kwargs["user_id"] == "u1"
        assert kwargs["action"] == "chunk_used"
        assert kwargs["resource_id"] == "abc"


def test_log_search_telemetry_passes_top_to_metadata():
    with _disable_db_writes() as m_write:
        results = [
            {
                "chunk_id": "c1", "file_path": "x.py",
                "relevance_score": 0.9,
                "candidate_sources": {"vector": 0.9, "bm25": 0.3},
            },
        ]
        log_search_telemetry(
            user_id="u1", query="hi", quality_mode="agent",
            hybrid_meta={"candidates": 7}, top_results=results,
            elapsed_ms=42.0,
        )
        m_write.assert_called_once()
        meta = m_write.call_args.kwargs["metadata"]
        assert meta["quality_mode"] == "agent"
        assert meta["hybrid"] == {"candidates": 7}
        assert meta["top"][0]["chunk_id"] == "c1"
        assert meta["top"][0]["candidate_sources"]["vector"] == 0.9


def test_log_skipped_files_summary_shape():
    with _disable_db_writes() as m_write:
        log_skipped_files(
            repo_id="r1", user_id="u1",
            skip_reasons={"pattern_excluded": 12, "extension_not_included": 3},
            total_seen=200, total_kept=185,
        )
        m_write.assert_called_once()
        meta = m_write.call_args.kwargs["metadata"]
        assert meta["total_seen"] == 200
        assert meta["total_kept"] == 185
        assert meta["skip_reasons"]["pattern_excluded"] == 12
