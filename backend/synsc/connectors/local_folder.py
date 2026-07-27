"""Fully local incremental connector for a directory of text files."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
import time
from collections.abc import Generator, Iterable, Iterator, Mapping
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
    ".git",
    ".git/*",
    ".venv",
    ".venv/*",
    "node_modules",
    "node_modules/*",
    "__pycache__",
    "__pycache__/*",
)
_ALLOWED_ROOTS_ENV = "SYNSC_LOCAL_CONNECTOR_ALLOWED_ROOTS"


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


def _is_excluded(
    relative: str,
    patterns: tuple[str, ...],
    *,
    directory: bool,
) -> bool:
    if any(fnmatch.fnmatch(relative, pattern) for pattern in patterns):
        return True
    return directory and any(
        fnmatch.fnmatch(f"{relative}/_", pattern)
        for pattern in patterns
    )


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

    def __init__(
        self,
        *,
        allowed_roots: Iterable[str | Path] | None = None,
    ) -> None:
        if allowed_roots is None:
            raw = os.getenv(_ALLOWED_ROOTS_ENV, "")
            allowed_roots = (
                entry for entry in raw.split(os.pathsep) if entry.strip()
            )
        normalized: list[Path] = []
        for raw_root in allowed_roots:
            candidate = Path(raw_root).expanduser()
            if not candidate.is_absolute():
                raise ValueError(
                    "local connector allowed roots must be absolute paths"
                )
            normalized.append(candidate.resolve())
        self.allowed_roots = tuple(normalized)

    def _resolve_root(self, configuration: Mapping[str, Any]) -> Path:
        raw_path = configuration.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("local folder configuration requires a path")
        if not self.allowed_roots:
            raise ValueError(
                "local folder access is not configured; set "
                f"{_ALLOWED_ROOTS_ENV}"
            )
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            raise ValueError("local folder path must be absolute")
        root = candidate.resolve()
        if not any(
            root == allowed or root.is_relative_to(allowed)
            for allowed in self.allowed_roots
        ):
            raise ValueError(
                "local folder path is outside the operator-configured "
                "allowed roots"
            )
        return root

    @staticmethod
    def _directory_open_flags() -> int:
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        return flags

    def _open_root_fd(self, configuration: Mapping[str, Any]) -> int:
        """Open the configured root beneath an allowed-root descriptor."""

        root = self._resolve_root(configuration)
        allowed = max(
            (
                candidate
                for candidate in self.allowed_roots
                if root == candidate or root.is_relative_to(candidate)
            ),
            key=lambda candidate: len(candidate.parts),
        )
        descriptor: int | None = None
        try:
            descriptor = os.open(
                allowed,
                self._directory_open_flags(),
            )
            for component in root.relative_to(allowed).parts:
                next_descriptor = os.open(
                    component,
                    self._directory_open_flags(),
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = next_descriptor
            details = os.fstat(descriptor)
            if not stat.S_ISDIR(details.st_mode):
                raise OSError("configured root is not a directory")
            return descriptor
        except OSError as exc:
            if descriptor is not None:
                os.close(descriptor)
            raise ValueError(
                "local folder directory could not be opened safely"
            ) from exc

    def validate_configuration(
        self,
        configuration: Mapping[str, Any],
    ) -> None:
        """Fail closed before encrypted configuration is persisted."""

        descriptor = self._open_root_fd(configuration)
        os.close(descriptor)
        _patterns(configuration, "include", _DEFAULT_INCLUDE)
        _patterns(configuration, "exclude", _DEFAULT_EXCLUDE)
        _integer_option(
            configuration,
            "max_files",
            10_000,
            minimum=1,
            maximum=1_000_000,
        )
        _integer_option(
            configuration,
            "max_entries",
            100_000,
            minimum=1,
            maximum=2_000_000,
        )
        _integer_option(
            configuration,
            "max_depth",
            64,
            minimum=1,
            maximum=256,
        )
        _integer_option(
            configuration,
            "max_file_bytes",
            2_000_000,
            minimum=1,
            maximum=100_000_000,
        )
        _integer_option(
            configuration,
            "max_total_bytes",
            100_000_000,
            minimum=1,
            maximum=10_000_000_000,
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

    def _walk_files(
        self,
        *,
        root_fd: int,
        exclude: tuple[str, ...],
        max_entries: int,
        max_depth: int,
        request: ConnectorSyncRequest,
        deadline: float,
    ) -> Generator[tuple[int, str, str], None, None]:
        """Walk below an anchored descriptor without reopening path ancestry."""

        entries_seen = 0

        def walk(
            directory_fd: int,
            relative_directory: str,
            depth: int,
        ) -> Iterator[tuple[int, str, str]]:
            nonlocal entries_seen
            try:
                self._check_deadline(request, deadline)
                try:
                    entries = os.scandir(directory_fd)
                except OSError as exc:
                    raise ValueError(
                        "local folder directory could not be scanned"
                    ) from exc
                with entries:
                    for entry in entries:
                        self._check_deadline(request, deadline)
                        entries_seen += 1
                        if entries_seen > max_entries:
                            raise ValueError(
                                "local folder exceeds configured max_entries"
                            )
                        name = entry.name
                        relative = (
                            f"{relative_directory}/{name}"
                            if relative_directory
                            else name
                        )
                        try:
                            if entry.is_symlink():
                                continue
                            is_directory = entry.is_dir(
                                follow_symlinks=False
                            )
                        except OSError:
                            continue
                        if _is_excluded(
                            relative,
                            exclude,
                            directory=is_directory,
                        ):
                            continue
                        if is_directory:
                            if depth >= max_depth:
                                raise ValueError(
                                    "local folder exceeds configured max_depth"
                                )
                            try:
                                child_fd = os.open(
                                    name,
                                    self._directory_open_flags(),
                                    dir_fd=directory_fd,
                                )
                            except OSError:
                                continue
                            yield from walk(
                                child_fd,
                                relative,
                                depth + 1,
                            )
                            continue
                        try:
                            if entry.is_file(follow_symlinks=False):
                                yield directory_fd, name, relative
                        except OSError:
                            continue
            finally:
                os.close(directory_fd)

        yield from walk(root_fd, "", 0)

    @staticmethod
    def _read_bounded_file(
        directory_fd: int,
        name: str,
        *,
        max_file_bytes: int,
    ) -> bytes | None:
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(name, flags, dir_fd=directory_fd)
        except OSError:
            return None
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode):
                return None
            if details.st_size > max_file_bytes:
                raise ValueError(
                    f"{name} exceeds configured max_file_bytes"
                )
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                payload = stream.read(max_file_bytes + 1)
            if len(payload) > max_file_bytes:
                raise ValueError(
                    f"{name} exceeds configured max_file_bytes"
                )
            return payload
        finally:
            os.close(descriptor)

    def sync(self, request: ConnectorSyncRequest) -> ConnectorSyncResponse:
        """Return a deterministic page of additions, updates, and deletions."""

        deadline = time.monotonic() + request.timeout_ms / 1000
        self._check_deadline(request, deadline)
        self.validate_configuration(request.configuration)
        root_fd = self._open_root_fd(request.configuration)

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
        max_entries = _integer_option(
            request.configuration,
            "max_entries",
            100_000,
            minimum=1,
            maximum=2_000_000,
        )
        max_depth = _integer_option(
            request.configuration,
            "max_depth",
            64,
            minimum=1,
            maximum=256,
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
        walker = self._walk_files(
            root_fd=root_fd,
            exclude=exclude,
            max_entries=max_entries,
            max_depth=max_depth,
            request=request,
            deadline=deadline,
        )
        try:
            for directory_fd, name, relative in walker:
                self._check_deadline(request, deadline)
                if not any(
                    fnmatch.fnmatch(relative, pattern)
                    for pattern in include
                ):
                    continue
                matched_files += 1
                if matched_files > max_files:
                    raise ValueError(
                        "local folder exceeds configured max_files"
                    )
                payload = self._read_bounded_file(
                    directory_fd,
                    name,
                    max_file_bytes=max_file_bytes,
                )
                if payload is None:
                    continue
                total_bytes += len(payload)
                if total_bytes > max_total_bytes:
                    raise ValueError(
                        "local folder exceeds configured max_total_bytes"
                    )
                if b"\x00" in payload:
                    continue
                try:
                    content = payload.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                digest = hashlib.sha256(payload).hexdigest()
                current[relative] = (digest, content)
        finally:
            walker.close()

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
