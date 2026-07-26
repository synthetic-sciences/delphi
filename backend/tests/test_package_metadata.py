"""Distribution metadata contracts for Delphi's Python packages."""

from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent
BACKEND_PYPROJECT = BACKEND_ROOT / "pyproject.toml"
BACKEND_INIT = BACKEND_ROOT / "synsc" / "__init__.py"
PROXY_PYPROJECT = PROJECT_ROOT / "packages" / "mcp-proxy" / "pyproject.toml"
BACKEND_LICENSE = BACKEND_ROOT / "LICENSE"


def _quoted_assignment(content: str, field: str) -> str:
    match = re.search(rf"^{field}\s*=\s*\"([^\"]+)\"$", content, re.MULTILINE)
    assert match is not None, f"missing {field} assignment"
    return match.group(1)


def test_backend_license_metadata_matches_repository_license() -> None:
    pyproject = BACKEND_PYPROJECT.read_text()

    assert _quoted_assignment(pyproject, "license") == "Apache-2.0"
    assert "License :: OSI Approved :: Apache Software License" in pyproject
    assert "License :: OSI Approved :: MIT License" not in pyproject
    assert BACKEND_LICENSE.read_bytes() == (PROJECT_ROOT / "LICENSE").read_bytes()


def test_backend_metadata_links_to_canonical_repository() -> None:
    pyproject = BACKEND_PYPROJECT.read_text()

    assert 'Repository = "https://github.com/synthetic-sciences/delphi"' in pyproject
    assert 'Issues = "https://github.com/synthetic-sciences/delphi/issues"' in pyproject


def test_python_distributions_credit_aayam_bansal() -> None:
    expected_author = '{ name = "Aayam Bansal" }'

    assert expected_author in BACKEND_PYPROJECT.read_text()
    assert expected_author in PROXY_PYPROJECT.read_text()
    assert '__author__ = "Aayam Bansal"' in BACKEND_INIT.read_text()


def test_backend_runtime_version_matches_distribution_version() -> None:
    project_version = _quoted_assignment(BACKEND_PYPROJECT.read_text(), "version")
    runtime_version = _quoted_assignment(BACKEND_INIT.read_text(), "__version__")

    assert runtime_version == project_version
