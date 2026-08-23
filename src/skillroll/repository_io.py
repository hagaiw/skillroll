"""Filesystem observations kept separate from parser and guard logic."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from skillroll.paths import is_within

_SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".github",
        ".skillroll",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
    }
)


def sorted_entries(path: Path) -> tuple[Path, ...]:
    """Return directory entries in portable deterministic order."""
    try:
        return tuple(
            sorted(path.iterdir(), key=lambda item: (item.name.casefold(), item.name))
        )
    except OSError:
        return ()


def is_regular(path: Path) -> bool:
    """Check a regular file without following symlinks."""
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def is_directory(path: Path) -> bool:
    """Check a directory without following symlinks."""
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def is_symlink(path: Path) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        return False


def is_hidden_or_skipped_directory(path: Path) -> bool:
    return path.name.startswith(".") or path.name in _SKIPPED_DIRECTORIES


def link_is_safe(root: Path, link: Path) -> bool:
    """True only when a symlink target resolves inside the selected repository."""
    try:
        return is_within(root.resolve(), link.resolve(strict=False))
    except OSError:
        return False


def readable_utf8(path: Path) -> str | None:
    """Read an ordinary text file without making any write or network request."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def current_directory() -> Path:
    """Boundary to make the CLI default root easy to control in tests."""
    return Path(os.getcwd())
