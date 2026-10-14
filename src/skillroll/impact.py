"""Reviewed repository impact declarations; never import repository code."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class ImpactPolicy:
    """Explicit exemptions and reverse dependencies for changed-case selection."""

    offline: tuple[str, ...] = ()
    full: tuple[str, ...] = ()
    dependencies: tuple[tuple[str, tuple[str, ...]], ...] = ()


def _patterns(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str)
        or not item
        or item.startswith("/")
        or "\\" in item
        or ":" in item
        or ".." in PurePosixPath(item).parts
        or any(ord(char) < 32 for char in item)
        for item in value
    ):
        raise ValueError("Impact patterns must be safe relative path globs.")
    return tuple(value)


def load_impact_policy(root: Path, relative: str) -> ImpactPolicy:
    """Read only a regular in-root TOML policy named explicitly by the caller."""
    root = root.resolve()
    path = root / relative
    if (
        not relative
        or PurePosixPath(relative).is_absolute()
        or ".." in PurePosixPath(relative).parts
        or "\\" in relative
        or ":" in relative
    ):
        raise ValueError("Impact policy must be a repository-relative path.")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Impact policy cannot follow symlinks.")
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError("Impact policy could not be read as TOML.") from error
    if (
        set(value) != {"schema_version", "offline", "full", "dependencies"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise ValueError("Impact policy requires schema_version = 1 and known fields.")
    dependencies = value["dependencies"]
    if not isinstance(dependencies, list):
        raise ValueError("Impact dependencies must be an array.")
    parsed: list[tuple[str, tuple[str, ...]]] = []
    for item in dependencies:
        if not isinstance(item, dict) or set(item) != {"changed", "affected"}:
            raise ValueError("Each impact dependency requires changed and affected.")
        source = _patterns([item["changed"]])[0]
        if any(source == existing for existing, _ in parsed):
            raise ValueError("Impact dependency sources must be unique.")
        targets = _patterns(item["affected"])
        if not targets:
            raise ValueError("Each impact dependency needs at least one affected path.")
        parsed.append((source, targets))
    return ImpactPolicy(
        _patterns(value["offline"]), _patterns(value["full"]), tuple(parsed)
    )
