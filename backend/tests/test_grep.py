"""Unit tests for GrepService."""
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_grep_service_matches_pattern_in_reconstructed_file():
    from synsc.services.grep_service import GrepService

    svc = GrepService()

    fake_files = {
        "src/auth.py": (
            "def login(user):\n"
            "    # TODO: handle MFA\n"
            "    if user.is_active:\n"
            "        return True\n"
            "    return False\n"
        ),
        "src/utils.py": "def noop():\n    pass\n",
    }

    with patch.object(svc, "_iter_source_files", return_value=list(fake_files.items())):
        matches = svc.grep_source(
            source_id="r1",
            source_type="repo",
            pattern=r"TODO.*MFA",
            path_prefix=None,
            max_matches=10,
            context_lines=1,
            user_id="u1",
        )

    assert len(matches) == 1
    m = matches[0]
    assert m["path"] == "src/auth.py"
    assert m["line_no"] == 2
    assert "MFA" in m["line"]
    assert m["context_before"] == ["def login(user):"]
    assert m["context_after"] == ["    if user.is_active:"]


def test_grep_service_respects_path_prefix():
    from synsc.services.grep_service import GrepService

    svc = GrepService()
    fake_files = {
        "src/a.py": "match_here\n",
        "tests/a.py": "match_here\n",
    }
    with patch.object(svc, "_iter_source_files", return_value=list(fake_files.items())):
        matches = svc.grep_source(
            source_id="r1",
            source_type="repo",
            pattern="match_here",
            path_prefix="src/",
            max_matches=10,
            context_lines=0,
            user_id="u1",
        )
    assert len(matches) == 1
    assert matches[0]["path"] == "src/a.py"


def test_grep_service_caps_at_max_matches():
    from synsc.services.grep_service import GrepService

    svc = GrepService()
    fake_files = {"a.py": "\n".join(["x"] * 500)}
    with patch.object(svc, "_iter_source_files", return_value=list(fake_files.items())):
        matches = svc.grep_source(
            source_id="r1",
            source_type="repo",
            pattern="x",
            path_prefix=None,
            max_matches=50,
            context_lines=0,
            user_id="u1",
        )
    assert len(matches) == 50


def test_grep_service_rejects_invalid_regex():
    from synsc.services.grep_service import GrepService

    svc = GrepService()
    with pytest.raises(ValueError, match="invalid regex"):
        svc.grep_source(
            source_id="r1",
            source_type="repo",
            pattern="(unclosed",
            path_prefix=None,
            max_matches=10,
            context_lines=0,
            user_id="u1",
        )


def test_grep_service_unsupported_source_type():
    """source_type outside {'repo', 'paper'} must raise ValueError."""
    from synsc.services.grep_service import GrepService

    svc = GrepService()
    with pytest.raises(ValueError, match="unsupported source_type"):
        svc.grep_source(
            source_id="x",
            source_type="dataset",
            pattern=".",
            user_id="u1",
        )
