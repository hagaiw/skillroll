"""Small, explicit path rules used at every repository boundary."""

from __future__ import annotations

from pathlib import Path, PurePosixPath


def parse_relative_path(value: str) -> PurePosixPath | None:
    """Return a portable relative path, or ``None`` for an unsafe spelling."""
    if not value or "\x00" in value or "\\" in value:
        return None
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in value.split("/")
    ):
        return None
    return candidate


def is_within(root: Path, candidate: Path) -> bool:
    """Whether a resolved candidate remains within a resolved root."""
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_child(root: Path, relative: PurePosixPath) -> Path | None:
    """Resolve a known-safe path and reject existing links that leave ``root``."""
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(*relative.parts)).resolve(strict=False)
    return candidate if is_within(resolved_root, candidate) else None


def repository_identity(root: Path, path: Path) -> PurePosixPath:
    """Serialize a resolved path as a portable path relative to the root."""
    return PurePosixPath(path.relative_to(root).as_posix())
