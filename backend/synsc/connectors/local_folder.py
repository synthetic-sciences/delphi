"""Fully local incremental connector for a directory of text files."""

from __future__ import annotations

import fnmatch
import hashlib
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from synsc.connectors.contracts import (
    ConnectorRecord,
    ConnectorSyncRequest,
    ConnectorSyncResponse,
)
from synsc.providers.contracts import (
    ContentClassification,
    ExecutionLocation,
    ProviderCapability,
    ProviderDescriptor,
)

_DEFAULT_INCLUDE = (
    "*.c",
    "*.cc",
    "*.cpp",
    "*.cs",
    "*.css",
    "*.csv",
    "*.go",
    "*.h",
    "*.hpp",
    "*.html",
    "*.java",
    "*.js",
    "*.json",
    "*.jsx",
    "*.md",
    "*.mdx",
    "*.php",
    "*.py",
    "*.rb",
    "*.rs",
    "*.rst",
    "*.sql",
    "*.toml",
    "*.ts",
    "*.tsx",
    "*.txt",
    "*.xml",
    "*.yaml",
    "*.yml",
)
_DEFAULT_EXCLUDE = (
    ".git/*",
    ".venv/*",
    "node_modules/*",
    "__pycache__/*",
)


def _integer_option(
    configuration: Mapping[str, Any],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = configuration.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return int(value)


def _patterns(
    configuration: Mapping[str, Any],
    name: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    raw = configuration.get(name)
    if raw is None:
        return default
    if not isinstance(raw, (list, tuple)) or any(
        not isinstance(item, str) or not item.strip() for item in raw
    ):
        raise ValueError(f"{name} must be a list of non-empty glob patterns")
    return tuple(raw)


class LocalFolderConnector:
    """Read bounded text-file changes without sending data off-machine."""

    descriptor = ProviderDescriptor(
        name="local-folder",
        version="1",
        capabilities=frozenset(
            {ProviderCapability.CONNECTOR, ProviderCapability.SYNC}
        ),
        execution=ExecutionLocation.LOCAL,
        accepted_classifications=frozenset(ContentClassification),
        supports_cancellation=True,
        supports_retry=True,
        max_response_bytes=100_000_000,
    )

    @staticmethod
    def _check_deadline(
        request: ConnectorSyncRequest,
        deadline: float,
    ) -> None:
        if request.cancellation.cancelled:
            raise TimeoutError("Local folder sync cancelled.")
        if time.monotonic() >= deadline:
            raise TimeoutError("Local folder sync timed out.")

    def sync(self, request: ConnectorSyncRequest) -> ConnectorSyncResponse:
        """Return a deterministic page of additions, updates, and deletions."""

        deadline = time.monotonic() + request.timeout_ms / 1000
        self._check_deadline(request, deadline)
        raw_path = request.configuration.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("local folder configuration requires a path")
        root = Path(raw_path).expanduser()
        if not root.exists() or not root.is_dir():
            raise ValueError("local folder path must be an existing directory")
        root = root.resolve()

        include = _patterns(
            request.configuration,
            "include",
            _DEFAULT_INCLUDE,
        )
        exclude = _patterns(
            request.configuration,
            "exclude",
            _DEFAULT_EXCLUDE,
        )
        max_files = _integer_option(
            request.configuration,
            "max_files",
            10_000,
            minimum=1,
            maximum=1_000_000,
        )
        max_file_bytes = _integer_option(
            request.configuration,
            "max_file_bytes",
            2_000_000,
            minimum=1,
            maximum=100_000_000,
        )
        max_total_bytes = _integer_option(
            request.configuration,
            "max_total_bytes",
            100_000_000,
            minimum=1,
            maximum=10_000_000_000,
        )

        current: dict[str, tuple[str, str]] = {}
        total_bytes = 0
        matched_files = 0
        for candidate in sorted(root.rglob("*")):
            self._check_deadline(request, deadline)
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                relative = candidate.relative_to(root).as_posix()
            except ValueError:
                continue
            if any(fnmatch.fnmatch(relative, pattern) for pattern in exclude):
                continue
            if not any(fnmatch.fnmatch(relative, pattern) for pattern in include):
                continue
            matched_files += 1
            if matched_files > max_files:
                raise ValueError("local folder exceeds configured max_files")
            size = candidate.stat().st_size
            if size > max_file_bytes:
                raise ValueError(
                    f"{relative} exceeds configured max_file_bytes"
                )
            total_bytes += size
            if total_bytes > max_total_bytes:
                raise ValueError(
                    "local folder exceeds configured max_total_bytes"
                )
            payload = candidate.read_bytes()
            if b"\x00" in payload:
                continue
            try:
                content = payload.decode("utf-8")
            except UnicodeDecodeError:
                continue
            digest = hashlib.sha256(payload).hexdigest()
            current[relative] = (digest, content)

        old_files: dict[str, str] = {}
        if request.cursor is not None:
            raw_files = request.cursor.get("files", {})
            if not isinstance(raw_files, Mapping) or any(
                not isinstance(path, str) or not isinstance(digest, str)
                for path, digest in raw_files.items()
            ):
                raise ValueError("local folder cursor is invalid")
            old_files = {
                str(path): str(digest) for path, digest in raw_files.items()
            }

        changed_paths = sorted(
            path
            for path, (digest, _) in current.items()
            if old_files.get(path) != digest
        )
        deleted_paths = sorted(set(old_files) - set(current))
        pending = [
            (path, False) for path in changed_paths
        ] + [
            (path, True) for path in deleted_paths
        ]
        pending.sort(key=lambda item: item[0])
        page = pending[: request.limit]

        next_files = dict(old_files)
        records: list[ConnectorRecord] = []
        for relative, deleted in page:
            self._check_deadline(request, deadline)
            if deleted:
                next_files.pop(relative, None)
                records.append(
                    ConnectorRecord(
                        external_id=relative,
                        locator=relative,
                        deleted=True,
                        accessible_principals=(request.user_id,),
                    )
                )
                continue
            digest, content = current[relative]
            next_files[relative] = digest
            records.append(
                ConnectorRecord(
                    external_id=relative,
                    locator=relative,
                    content=content,
                    accessible_principals=(request.user_id,),
                    metadata={
                        "content_sha256": digest,
                        "size_bytes": len(content.encode("utf-8")),
                    },
                )
            )

        return ConnectorSyncResponse(
            records=tuple(records),
            next_cursor={"files": next_files},
            has_more=len(pending) > len(page),
        )
