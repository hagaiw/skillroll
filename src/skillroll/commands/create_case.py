"""Create one editable eval case beside an existing skill."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from skillroll.config import load_config
from skillroll.diagnostics import CommandResult, Diagnostic
from skillroll.initialization.templates import render_starter_case
from skillroll.initialization.transaction import PlannedWrite, TransactionError, commit
from skillroll.outcomes import Outcome
from skillroll.paths import parse_relative_path, resolve_child
from skillroll.repository_io import current_directory

_CASE_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _error(summary: str, action: str, *, affected: str | None = None) -> CommandResult:
    return CommandResult(
        Outcome.ERROR,
        summary,
        (Diagnostic("SCN1001", summary, affected=affected, next_action=action),),
    )


def _target(value: str) -> tuple[PurePosixPath, str] | None:
    parsed = parse_relative_path(value)
    if parsed is None or len(parsed.parts) < 2:
        return None
    name = parsed.name.removesuffix(".eval.md")
    if _CASE_NAME.fullmatch(name) is None:
        return None
    return parsed.parent, name


def run(*, target: str, repo: str | None = None) -> CommandResult:
    """Create one no-overwrite case template under ``SKILL/evals``."""
    root = current_directory() if repo is None else Path(repo)
    parsed_config = load_config(root)
    if parsed_config.value is None:
        return CommandResult(
            Outcome.ERROR,
            "SkillRoll needs a valid local setup before it can create a case.",
            parsed_config.diagnostics,
        )
    selected = _target(target)
    if selected is None:
        return _error(
            "The new eval target must look like SKILL/NAME.",
            "Use a lowercase name such as refund/eligible-order.",
            affected=target,
        )
    skill_path, case_name = selected
    config = parsed_config.value
    skill_directory = resolve_child(config.skills_root, skill_path)
    if (
        skill_directory is None
        or not skill_directory.is_dir()
        or skill_directory.is_symlink()
        or not (skill_directory / "SKILL.md").is_file()
    ):
        return _error(
            "The selected skill has no readable SKILL.md file.",
            "Choose an existing skill relative to skills_path.",
            affected=skill_path.as_posix(),
        )
    evals = skill_directory / "evals"
    if evals.is_symlink():
        return _error(
            "SkillRoll will not create an eval through a symbolic-link evals folder.",
            "Replace the link with a folder, then try again.",
            affected=(skill_path / "evals").as_posix(),
        )
    case_path = evals / f"{case_name}.eval.md"
    try:
        result = commit(
            (PlannedWrite(case_path, render_starter_case(case_name)),),
            root=config.repository_root,
        )
    except TransactionError as error:
        return _error(
            str(error),
            "Choose another eval name or keep the existing eval.",
            affected=(skill_path / "evals" / case_path.name).as_posix(),
        )
    relative = result.changed[0].relative_to(config.skills_root).as_posix()
    return CommandResult(
        Outcome.PASS,
        f"Created {relative}. Edit it, then run skillroll eval --case {relative}.",
        data={"case": relative},
    )
