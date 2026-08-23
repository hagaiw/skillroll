"""Small filesystem transaction for init's deliberately narrow write set."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


class TransactionError(RuntimeError):
    """A write failed after a plan had been preflighted."""


@dataclass(frozen=True, slots=True)
class PlannedWrite:
    path: Path
    content: bytes
    replace: bool = False


@dataclass(frozen=True, slots=True)
class TransactionResult:
    changed: tuple[Path, ...]


def _write_new(path: Path, content: bytes) -> None:
    """Publish a new file without ever replacing a concurrent user file."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(content)
        target.flush()
        os.fsync(target.fileno())


def _replace(path: Path, content: bytes) -> None:
    """Atomically replace the sole deliberately mergeable init file."""
    descriptor, temporary = tempfile.mkstemp(prefix=".skillroll-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, path)
    finally:
        with suppress(FileNotFoundError):
            temporary_path.unlink()


def _display(path: Path, root: Path | None) -> str:
    if root is None:
        return str(path)
    return path.relative_to(root).as_posix()


def _safe_under_root(writes: tuple[PlannedWrite, ...], root: Path) -> None:
    """Reject links and non-directories before an init write reaches a parent.

    ``init`` supplies one resolved repository root.  This check deliberately
    walks the lexical path below it instead of resolving each target: resolving
    would hide a parent link that could redirect a later create outside the
    selected repository.  A simultaneous hostile filesystem change cannot be
    made fully transactional on every supported operating system, but every
    observed link is rejected before any output is touched.
    """
    if root.is_symlink() or not root.is_dir():
        raise TransactionError(
            "SkillRoll cannot safely write outside a regular repository."
        )
    for item in writes:
        try:
            relative = item.path.relative_to(root)
        except ValueError as error:
            raise TransactionError(
                "SkillRoll refused a setup file outside the selected repository."
            ) from error
        parent = root
        for part in relative.parts[:-1]:
            parent /= part
            if parent.is_symlink():
                raise TransactionError(
                    "SkillRoll will not write through a symbolic-link folder: "
                    f"{_display(parent, root)}"
                )
            if parent.exists() and not parent.is_dir():
                raise TransactionError(
                    "SkillRoll cannot create a setup file because this parent is "
                    f"not a folder: {_display(parent, root)}"
                )
        if item.path.is_symlink():
            raise TransactionError(
                "SkillRoll will not replace a symbolic-link file: "
                f"{_display(item.path, root)}"
            )


def commit(
    writes: tuple[PlannedWrite, ...], *, root: Path | None = None
) -> TransactionResult:
    """Preflight, publish complete files, and undo only this invocation's work."""
    resolved_root = None if root is None else root.resolve()
    if resolved_root is not None:
        _safe_under_root(writes, resolved_root)
    conflicts = [
        item.path for item in writes if item.path.exists() and not item.replace
    ]
    if conflicts:
        names = ", ".join(_display(item, resolved_root) for item in conflicts)
        raise TransactionError(f"SkillRoll will not replace existing work: {names}")
    backups = {item.path: item.path.read_bytes() for item in writes if item.replace}
    changed: list[Path] = []
    try:
        for item in writes:
            item.path.parent.mkdir(parents=True, exist_ok=True)
            if item.replace:
                _replace(item.path, item.content)
            else:
                _write_new(item.path, item.content)
            changed.append(item.path)
    except OSError as error:
        cleanup_errors: list[str] = []
        for path in reversed(changed):
            try:
                if path in backups:
                    _replace(path, backups[path])
                else:
                    path.unlink()
            except OSError:
                cleanup_errors.append(_display(path, resolved_root))
        extra = (
            ""
            if not cleanup_errors
            else f" Review these files: {', '.join(cleanup_errors)}."
        )
        raise TransactionError(
            f"SkillRoll could not safely finish setup: {error}.{extra}"
        ) from error
    return TransactionResult(tuple(changed))
