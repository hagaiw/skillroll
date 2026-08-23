"""Predictable, no-follow discovery of skills and their direct case files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from skillroll.diagnostics import Diagnostic, SourceLocation
from skillroll.models import Skill, SkillRollConfig
from skillroll.paths import repository_identity
from skillroll.repository_io import (
    is_directory,
    is_hidden_or_skipped_directory,
    is_regular,
    is_symlink,
    link_is_safe,
    sorted_entries,
)


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    skills: tuple[Skill, ...]
    diagnostics: tuple[Diagnostic, ...]
    skipped_safe_symlinks: tuple[PurePosixPath, ...]


def _issue(code: str, summary: str, path: Path, action: str) -> Diagnostic:
    return Diagnostic(
        code,
        summary,
        affected=path.name,
        location=SourceLocation(path.as_posix()),
        next_action=action,
    )


def _walk(
    config: SkillRollConfig,
) -> tuple[tuple[Path, ...], tuple[Diagnostic, ...], tuple[PurePosixPath, ...]]:
    stack = [config.skills_root]
    skill_files: list[Path] = []
    diagnostics: list[Diagnostic] = []
    skipped: list[PurePosixPath] = []
    while stack:
        directory = stack.pop()
        entries = sorted_entries(directory)
        for entry in reversed(entries):
            if is_symlink(entry):
                identity = repository_identity(config.repository_root, entry)
                if link_is_safe(config.repository_root, entry):
                    skipped.append(identity)
                else:
                    diagnostics.append(
                        _issue(
                            "SCG1003",
                            "A symbolic link under skills_path points outside "
                            "this repository.",
                            entry,
                            "Replace this link with a checked-in file, or move "
                            "it outside skills_path.",
                        )
                    )
                continue
            if is_directory(entry):
                if not is_hidden_or_skipped_directory(entry):
                    stack.append(entry)
                continue
            if entry.name == "SKILL.md" and is_regular(entry):
                skill_files.append(entry)
    return tuple(skill_files), tuple(diagnostics), tuple(sorted(skipped, key=str))


def discover_skills(config: SkillRollConfig) -> DiscoveryResult:
    """Find regular ``SKILL.md`` files below the one configured root."""
    skill_files, diagnostics, skipped = _walk(config)
    skills: list[Skill] = []
    errors = list(diagnostics)
    for skill_file in sorted(skill_files, key=lambda item: item.as_posix().casefold()):
        root = skill_file.parent
        identity = PurePosixPath(root.relative_to(config.skills_root).as_posix())
        name = root.name
        skills.append(Skill(name, identity, root, skill_file, root / "evals"))
    if not skills:
        errors.append(
            Diagnostic(
                "SCG1004",
                "SkillRoll did not find any SKILL.md files below skills_path.",
                affected=config.skills_path.as_posix(),
                next_action="Add a skill directory with SKILL.md below skills_path.",
            )
        )
    return DiscoveryResult(tuple(skills), tuple(errors), skipped)


def discover_case_files(skill: Skill) -> tuple[Path, ...]:
    """Find direct regular ``*.eval.md`` files, never recursing into evals."""
    if not is_directory(skill.evals_directory) or is_symlink(skill.evals_directory):
        return ()
    return tuple(
        entry
        for entry in sorted_entries(skill.evals_directory)
        if entry.name.endswith(".eval.md")
        and is_regular(entry)
        and not is_symlink(entry)
    )
