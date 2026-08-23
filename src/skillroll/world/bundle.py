"""The sole filesystem reader for a selected skill's packaged files."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from skillroll.diagnostics import JSONValue
from skillroll.paths import parse_relative_path
from skillroll.repository_io import sorted_entries

MAX_FILES = 512
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_BINARY_BYTES = 64 * 1024 * 1024
MAX_READABLE_BYTES = 64 * 1024

# These paths are harness metadata or generated/dependency output, not packaged
# skill resources. This policy is intentionally independent of repository
# .gitignore files, which are user-controlled input.
EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".skillroll",
        ".tox",
        ".venv",
        "build",
        "dist",
        "evals",
        "generated",
        "node_modules",
        "__pycache__",
        "venv",
        "vendor",
    }
)
EXCLUDED_FILE_SUFFIXES = frozenset({".pyc", ".pyo"})


class BundleError(Exception):
    """A selected skill bundle is unsafe or too large to evaluate."""


@dataclass(frozen=True, slots=True)
class BundleFile:
    """One safely indexed regular file beneath the selected skill root."""

    path: PurePosixPath
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class BundleIndex:
    """An immutable manifest of files the world may serve to the skill."""

    root: Path
    files: tuple[BundleFile, ...]

    def file(self, path: PurePosixPath) -> BundleFile | None:
        """Find one pre-indexed file without reading the filesystem."""
        return next((item for item in self.files if item.path == path), None)


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except OSError:
        return False


def _excluded(entry: Path) -> bool:
    """Return whether a path is harness metadata or generated output."""
    name = getattr(entry, "name", "")
    suffix = getattr(entry, "suffix", "")
    return (
        name.startswith(".")
        or name in EXCLUDED_DIRECTORY_NAMES
        or suffix in EXCLUDED_FILE_SUFFIXES
    )


def _walk(root: Path, directory: Path) -> tuple[Path, ...]:
    """Walk ordinary directories without ever following directory symlinks."""
    files: list[Path] = []
    for entry in sorted_entries(directory):
        if _excluded(entry):
            continue
        try:
            mode = entry.lstat().st_mode
        except OSError:
            continue
        if stat.S_ISLNK(mode):
            continue
        if stat.S_ISDIR(mode):
            files.extend(_walk(root, entry))
        elif stat.S_ISREG(mode):
            files.append(entry)
    return tuple(files)


def build_bundle(root: Path) -> BundleIndex:
    """Index bounded, non-symlink skill files in canonical POSIX order."""
    try:
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise BundleError("SkillRoll could not open this skill folder.") from error
    if root.is_symlink() or not resolved.is_dir():
        raise BundleError("The selected skill folder must be an ordinary directory.")
    entries: list[BundleFile] = []
    text_total = 0
    binary_total = 0
    for path in sorted(
        _walk(resolved, resolved),
        key=lambda item: item.relative_to(resolved).as_posix(),
    ):
        relative = PurePosixPath(path.relative_to(resolved).as_posix())
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise BundleError(
                f"SkillRoll could not read bundled file {relative}."
            ) from error
        if b"\x00" in raw:
            binary_total += len(raw)
        else:
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                binary_total += len(raw)
            else:
                text_total += len(raw)
        entries.append(BundleFile(relative, len(raw), hashlib.sha256(raw).hexdigest()))
        if len(entries) > MAX_FILES:
            raise BundleError(
                f"This skill contains {len(entries)} files; the limit is {MAX_FILES}."
            )
        if text_total > MAX_TOTAL_BYTES:
            raise BundleError(
                f"This skill contains {text_total} readable text bytes; the bundle "
                "limit is "
                f"{MAX_TOTAL_BYTES} bytes."
            )
        if binary_total > MAX_BINARY_BYTES:
            raise BundleError(
                f"This skill contains {binary_total} binary asset bytes; the bundle "
                f"limit is {MAX_BINARY_BYTES} bytes."
            )
    return BundleIndex(resolved, tuple(entries))


def bundle_read(
    bundle: BundleIndex, tool_name: str, arguments: Mapping[str, JSONValue]
) -> str | None:
    """Return the stable text envelope for a safe bundled ``Read`` request."""
    if tool_name != "Read":
        return None
    value = arguments.get("path", arguments.get("file_path"))
    if not isinstance(value, str):
        return None
    relative = parse_relative_path(value)
    if relative is None:
        return None
    record = bundle.file(relative)
    if record is None or record.size > MAX_READABLE_BYTES:
        return None
    path = bundle.root.joinpath(*relative.parts)
    if not _regular_file(path):
        return None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as opened:
            raw = opened.read(MAX_READABLE_BYTES + 1)
        if (
            len(raw) > MAX_READABLE_BYTES
            or hashlib.sha256(raw).hexdigest() != record.sha256
        ):
            return None
        content = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return json.dumps(
        {"content": content, "path": relative.as_posix(), "source": "skill_bundle"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
