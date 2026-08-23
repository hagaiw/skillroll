"""Small, testable GitHub-facing adapters around the local SkillRoll core.

The evaluation product deliberately does not depend on this module.  It turns
an already checked-out Git diff into ordinary case selection and renders the
files GitHub Actions expects (step summary and action outputs).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from skillroll.diagnostics import CommandResult
from skillroll.models import EvalCase, ValidationReport

type ChangeKind = Literal["added", "modified", "deleted", "renamed", "unknown"]
type ChangedScope = Literal["none", "cases", "all"]


@dataclass(frozen=True, slots=True)
class ChangedPath:
    """One normalized, repository-relative path change."""

    kind: ChangeKind
    old_path: PurePosixPath | None = None
    new_path: PurePosixPath | None = None


@dataclass(frozen=True, slots=True)
class ChangedSelection:
    """A deliberately explainable set of cases selected from a diff."""

    scope: ChangedScope
    cases: tuple[EvalCase, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class GitDiffResult:
    """The bounded result of the sole Git subprocess boundary."""

    changes: tuple[ChangedPath, ...]
    fallback_reason: str | None = None


class GitDiffError(RuntimeError):
    """Git could not provide a safe normalized changed-file list."""


def _safe_path(value: str) -> PurePosixPath | None:
    if not value or "\\" in value or "\x00" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or path == PurePosixPath(".") or ".." in path.parts:
        return None
    return path


def _parse_status(value: bytes) -> ChangeKind:
    if value.startswith(b"A"):
        return "added"
    if value.startswith((b"M", b"T")):
        return "modified"
    if value.startswith(b"D"):
        return "deleted"
    if value.startswith((b"R", b"C")):
        return "renamed"
    return "unknown"


def parse_name_status(payload: bytes) -> tuple[ChangedPath, ...]:
    """Parse Git's NUL-delimited status output without shell/path quoting."""
    if not payload:
        return ()
    tokens = payload.split(b"\0")
    if tokens[-1] != b"":
        raise GitDiffError("Git returned an incomplete changed-file record.")
    values = tokens[:-1]
    result: list[ChangedPath] = []
    index = 0
    while index < len(values):
        status = values[index]
        index += 1
        kind = _parse_status(status)
        if kind == "unknown":
            result.append(ChangedPath("unknown"))
            if index < len(values):
                index += 1
            continue
        count = 2 if kind == "renamed" else 1
        if len(values) - index < count:
            raise GitDiffError("Git returned an incomplete changed-file record.")
        try:
            paths = tuple(
                value.decode("utf-8", "strict")
                for value in values[index : index + count]
            )
        except UnicodeDecodeError as error:
            raise GitDiffError(
                "Git returned a changed filename SkillRoll cannot read safely."
            ) from error
        index += count
        normalized = tuple(_safe_path(value) for value in paths)
        if any(value is None for value in normalized):
            result.append(ChangedPath("unknown"))
        elif kind == "renamed":
            result.append(ChangedPath("renamed", normalized[0], normalized[1]))
        elif kind == "deleted":
            result.append(ChangedPath("deleted", normalized[0], None))
        else:
            result.append(ChangedPath(kind, None, normalized[0]))
    return tuple(result)


def git_changes(repository_root: Path, base_sha: str, head_sha: str) -> GitDiffResult:
    """Read one committed diff with a list-form subprocess invocation only."""
    if not _valid_sha(base_sha) or not _valid_sha(head_sha):
        return GitDiffResult(
            (), "The supplied Git revisions were not immutable commit IDs."
        )
    try:
        completed = subprocess.run(
            [
                "git",
                "diff",
                "--name-status",
                "-z",
                "--find-renames",
                base_sha,
                head_sha,
            ],
            cwd=repository_root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return GitDiffResult(
            (), "SkillRoll could not safely read the changed files from Git."
        )
    if completed.returncode != 0:
        return GitDiffResult(
            (), "SkillRoll could not safely compare the selected Git revisions."
        )
    try:
        return GitDiffResult(parse_name_status(completed.stdout))
    except GitDiffError as error:
        return GitDiffResult((), str(error))


def _valid_sha(value: str) -> bool:
    return len(value) in {40, 64} and all(
        character in "0123456789abcdef" for character in value.lower()
    )


def _relative(root: Path, value: Path) -> PurePosixPath | None:
    try:
        return PurePosixPath(value.relative_to(root).as_posix())
    except ValueError:
        return None


def _skill_for_path(
    report: ValidationReport, path: PurePosixPath
) -> tuple[EvalCase, ...] | None:
    matched: list[EvalCase] = []
    for skill in report.skills:
        relative = _relative(report.repository_root, skill.root)
        if (
            relative is not None
            and path == relative
            or (relative is not None and relative in path.parents)
        ):
            matched.extend(case for case in report.cases if case.skill == skill)
    return tuple(matched) if matched else None


def _is_docs_only(path: PurePosixPath, skills_root: PurePosixPath) -> bool:
    return (
        skills_root not in path.parents
        and path != skills_root
        and path.suffix.lower() in {".md", ".mdx", ".txt"}
    )


def select_changed(
    report: ValidationReport, changes: Sequence[ChangedPath]
) -> ChangedSelection:
    """Select cases conservatively; every uncertain path intentionally widens."""
    if not changes:
        return ChangedSelection("none", (), "No skill or eval files changed.")
    if report.config is None:
        return ChangedSelection(
            "all", report.cases, "Repository configuration could not be read safely."
        )
    root = report.repository_root
    config_path = _relative(root, report.config.config_path)
    selected: list[EvalCase] = []
    docs = 0
    for change in changes:
        if change.kind in {"deleted", "renamed", "unknown"}:
            return ChangedSelection(
                "all",
                report.cases,
                "A renamed, deleted, or uncertain file change requires a "
                "complete evaluation.",
            )
        path = change.new_path
        if path is None:
            return ChangedSelection(
                "all", report.cases, "A changed file could not be mapped safely."
            )
        if (
            path == config_path
            or path.parts[:2] == (".github", "workflows")
            or path.name == "action.yml"
        ):
            return ChangedSelection(
                "all",
                report.cases,
                "SkillRoll configuration or automation changed, so every skill "
                "is evaluated.",
            )
        exact_cases = tuple(
            case for case in report.cases if _relative(root, case.path) == path
        )
        if exact_cases:
            selected.extend(exact_cases)
            continue
        skill_cases = _skill_for_path(report, path)
        if skill_cases is not None:
            selected.extend(skill_cases)
            continue
        if _is_docs_only(path, report.config.skills_path):
            docs += 1
            continue
        return ChangedSelection(
            "all",
            report.cases,
            "A changed file is outside a known skill, so SkillRoll cannot "
            "safely narrow the evaluation.",
        )
    unique = tuple({case.identity: case for case in selected}.values())
    ordered = tuple(sorted(unique, key=lambda case: case.identity.as_posix()))
    if ordered:
        return ChangedSelection(
            "cases", ordered, "Only the changed skills or eval cases are evaluated."
        )
    return ChangedSelection(
        "none",
        (),
        f"{docs} documentation-only file(s) did not change a skill or eval case.",
    )


def valid_reviewed_ref(value: str) -> bool:
    """Accept only an immutable SHA or the documented pull-request head form."""
    if _valid_sha(value):
        return True
    prefix = "refs/pull/"
    suffix = "/head"
    number = (
        value[len(prefix) : -len(suffix)]
        if value.startswith(prefix) and value.endswith(suffix)
        else ""
    )
    return bool(number) and number.isdecimal() and str(int(number)) == number


def _one_line(value: object, limit: int = 500) -> str:
    return (
        str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")[:limit]
    )


def render_summary(
    result: CommandResult,
    selection: ChangedSelection | None = None,
    *,
    fork_notice: bool = False,
    command_notice: bool = False,
    artifact_uploaded: bool = False,
    retention_days: int = 7,
) -> str:
    """Render a safe, novice-friendly GitHub job summary from normalized facts."""
    lines = [
        "## SkillRoll",
        "",
        f"**{result.outcome.name}** — {_one_line(result.summary)}",
    ]
    if selection is not None:
        lines.extend(
            ("", f"Selection: **{selection.scope}** — {_one_line(selection.reason)}")
        )
    if command_notice:
        lines.extend(
            (
                "",
                "### Repository commands are off in this job",
                "",
                "If this repository declares checks, SkillRoll inspected them "
                "but did not execute repository commands automatically. A "
                "declared command is "
                "ordinary repository code: it may change the disposable runner, "
                "use its network, or access accounts available to the job.",
                "",
                "After reviewing the exact revision, enable **Run repository "
                "checks** in the manual SkillRoll workflow, or run the local "
                "command with `--run-commands`. The check job is separate and "
                "does not receive the inference key.",
            )
        )
    for diagnostic in result.diagnostics:
        lines.extend(("", f"- **{diagnostic.code}:** {_one_line(diagnostic.summary)}"))
        if diagnostic.affected:
            lines.append(f"  - Affected: `{_one_line(diagnostic.affected)}`")
        if diagnostic.next_action:
            lines.append(f"  - Next: {_one_line(diagnostic.next_action)}")
    if fork_notice:
        lines.extend(
            (
                "",
                "### Model evaluation was intentionally skipped",
                "",
                "This pull request is from another repository. SkillRoll ran "
                "validation without the repository's model key. After you review "
                "this exact revision, use **Actions → SkillRoll → Run workflow**, "
                "enter the reviewed commit SHA (or `refs/pull/NUMBER/head`), and "
                "choose what to evaluate. That manual run executes the reviewed "
                "repository files while the model key is available, so do not use "
                "it for code you have not reviewed.",
            )
        )
    if artifact_uploaded:
        lines.extend(
            (
                "",
                f"Evidence was uploaded for {retention_days} day(s). It is "
                "redacted, but may include skill input, world text, final output, "
                "and bounded repository-check output.",
            )
        )
    return "\n".join(lines) + "\n"


def annotation_lines(result: CommandResult, maximum: int = 20) -> tuple[str, ...]:
    """Return bounded GitHub annotations without allowing workflow-command injection."""
    level = "error" if result.outcome.name in {"FAIL", "ERROR"} else "warning"
    values: list[str] = []
    for diagnostic in result.diagnostics[:maximum]:
        properties = ""
        if diagnostic.location is not None and diagnostic.location.path is not None:
            candidate = _safe_path(diagnostic.location.path)
            if candidate is not None:
                properties = f" file={_one_line(candidate.as_posix())}"
                if diagnostic.location.line is not None:
                    properties += f",line={diagnostic.location.line}"
        values.append(f"::{level}{properties}::{_one_line(diagnostic.summary)}")
    return tuple(values)


def write_github_report(
    result: CommandResult,
    selection: ChangedSelection | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    fork_notice: bool = False,
    command_notice: bool = False,
    artifact_uploaded: bool = False,
    retention_days: int = 7,
) -> tuple[str, ...]:
    """Append a summary/output safely and return annotations for the caller to print."""
    values = os.environ if environment is None else environment
    summary_path = values.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(
            render_summary(
                result,
                selection,
                fork_notice=fork_notice,
                command_notice=command_notice,
                artifact_uploaded=artifact_uploaded,
                retention_days=retention_days,
            ),
            encoding="utf-8",
        )
    output_path = values.get("GITHUB_OUTPUT")
    if output_path:
        selected = 0 if selection is None else len(selection.cases)
        reason = "" if selection is None else selection.reason
        cases = result.data.get("cases")
        artifact = ""
        if isinstance(cases, tuple):
            for item in cases:
                if isinstance(item, Mapping):
                    candidate = item.get("artifact_directory")
                    if isinstance(candidate, str):
                        artifact = candidate
                        break
        Path(output_path).write_text(
            f"outcome={_one_line(result.outcome.name)}\n"
            f"selected-case-count={selected}\n"
            f"selection-reason={_one_line(reason)}\n"
            f"artifact-path={_one_line(artifact)}\n",
            encoding="utf-8",
        )
    return annotation_lines(result)


def changes_from_iterable(values: Iterable[ChangedPath]) -> tuple[ChangedPath, ...]:
    """Freeze a potentially one-shot adapter result at the pure boundary."""
    return tuple(values)
