"""Bounded, no-follow discovery used before a repository is configured."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from skillroll.paths import is_within
from skillroll.repository_io import (
    is_directory,
    is_hidden_or_skipped_directory,
    is_regular,
    is_symlink,
    sorted_entries,
)

_MAX_ENTRIES = 10_000
_MAX_DEPTH = 32


@dataclass(frozen=True, slots=True)
class InitialSkill:
    """A regular skill file represented relative to the selected repository."""

    skill_file: PurePosixPath

    @property
    def directory(self) -> PurePosixPath:
        return self.skill_file.parent


class ScanError(ValueError):
    """A scan could not safely produce a bounded, useful answer."""


def scan_skills(root: Path) -> tuple[InitialSkill, ...]:
    """Find regular ``SKILL.md`` files below ``root`` without following links."""
    resolved_root = root.resolve()
    stack: list[tuple[Path, int]] = [(resolved_root, 0)]
    found: list[InitialSkill] = []
    entries_seen = 0
    while stack:
        directory, depth = stack.pop()
        if depth > _MAX_DEPTH:
            raise ScanError(
                "The skills scan is deeper than 32 folders; choose a narrower path."
            )
        for entry in reversed(sorted_entries(directory)):
            entries_seen += 1
            if entries_seen > _MAX_ENTRIES:
                raise ScanError(
                    "The skills scan found more than 10,000 entries; choose "
                    "a narrower path."
                )
            if is_symlink(entry):
                continue
            if is_directory(entry):
                if not is_hidden_or_skipped_directory(entry):
                    stack.append((entry, depth + 1))
                continue
            if entry.name == "SKILL.md" and is_regular(entry):
                try:
                    relative = entry.relative_to(resolved_root)
                except ValueError as error:
                    raise ScanError(
                        "A discovered skill is outside the selected repository."
                    ) from error
                if not is_within(resolved_root, entry.resolve()):
                    continue
                found.append(InitialSkill(PurePosixPath(relative.as_posix())))
    return tuple(sorted(found, key=lambda item: item.skill_file.as_posix().casefold()))


def suggest_skills_path(skills: tuple[InitialSkill, ...]) -> PurePosixPath | None:
    """Return the transparent common root used as init's conservative default."""
    if not skills:
        return None
    directories = [item.directory for item in skills]
    if len(directories) == 1:
        directory = directories[0]
        return (
            PurePosixPath(".") if directory == PurePosixPath(".") else directory.parent
        )
    shared = list(directories[0].parts)
    for directory in directories[1:]:
        # A common path is a *prefix*: once two directory names differ, a
        # later matching name must not be pulled back into the suggestion.
        # (``a/one/shared`` and ``a/two/shared`` share only ``a``.)
        prefix: list[str] = []
        for left, right in zip(shared, directory.parts, strict=False):
            if left != right:
                break
            prefix.append(left)
        shared = prefix
    return PurePosixPath(*shared) if shared else PurePosixPath(".")
