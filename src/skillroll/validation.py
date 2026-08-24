"""Functional orchestration for side-effect-free repository validation."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from skillroll.config import load_config
from skillroll.diagnostics import CommandResult, Diagnostic, JSONValue
from skillroll.discovery import discover_case_files, discover_skills
from skillroll.evals import parse_eval_case
from skillroll.guards import minimum_case_findings
from skillroll.models import (
    EvalCase,
    FindingDisposition,
    GuardFinding,
    Selection,
    SkillRollConfig,
    ValidationReport,
    effective_limits,
)
from skillroll.outcomes import Outcome
from skillroll.paths import is_within
from skillroll.repository_io import readable_utf8


def _ignored_evals_finding(
    root: Path, cases: tuple[EvalCase, ...]
) -> GuardFinding | None:
    """Warn for the common repository-wide ``evals/`` Git ignore rule.

    Full Git ignore semantics belong to Git itself and validation deliberately
    runs no repository commands. This catches the portable rule that caused a
    real adoption failure without pretending to implement Git's matcher.
    """
    if not cases:
        return None
    source = readable_utf8(root / ".gitignore")
    if source is None:
        return None
    ignored = False
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if line in {"evals", "evals/", "**/evals", "**/evals/"}:
            ignored = True
        elif line in {"!evals", "!evals/", "!**/evals", "!**/evals/"}:
            ignored = False
    if not ignored:
        return None
    return _finding(
        Diagnostic(
            "SCG1007",
            "The repository-wide .gitignore rule for evals may hide SkillRoll cases.",
            affected=".gitignore",
            next_action=(
                "Add a later negation rule for the intended skill eval paths, then "
                "confirm the cases appear in version-control status."
            ),
        ),
        disposition="advisory",
    )


def _finding(
    diagnostic: Diagnostic,
    *,
    disposition: FindingDisposition = "blocking",
    is_policy: bool = False,
    is_disabled: bool = False,
) -> GuardFinding:
    """Wrap one diagnostic with an explicit command-gating disposition."""
    return GuardFinding(
        diagnostic.code, is_policy, is_disabled, diagnostic, disposition
    )


def _finding_data(finding: GuardFinding) -> dict[str, JSONValue]:
    """Expose one finding without requiring consumers to decode internals."""
    location = finding.diagnostic.location
    return {
        "code": finding.guard_id,
        "summary": finding.diagnostic.summary,
        "affected": finding.diagnostic.affected,
        "location": (
            None
            if location is None
            else {
                "path": location.path,
                "line": location.line,
                "column": location.column,
            }
        ),
        "details": finding.diagnostic.details,
        "risk": finding.diagnostic.risk,
        "next_action": finding.diagnostic.next_action,
    }


def _selection_error(selection: Selection) -> Diagnostic | None:
    for value in (selection.skill, selection.case):
        if value is not None and (
            value.is_absolute() or ".." in value.parts or "\\" in value.as_posix()
        ):
            return Diagnostic(
                "SCG1002",
                "A selected skill or eval case must stay inside this repository.",
                affected=value.as_posix(),
                next_action=(
                    "Use a relative skill or eval-case path inside skills_path."
                ),
            )
    return None


def _limit_findings(
    config: SkillRollConfig, cases: tuple[EvalCase, ...]
) -> tuple[GuardFinding, ...]:
    """Reject case ceilings above the configured profile before inference."""
    # The local type is narrowed by the caller; keeping this helper independent
    # of discovery makes the no-profile behavior explicit.
    inference = config.inference
    if inference is None:
        return ()
    findings: list[GuardFinding] = []
    for case in cases:
        limits = effective_limits(inference.limits, case.limits)
        if limits is None:
            findings.append(
                _finding(
                    Diagnostic(
                        "SCG1005",
                        "This eval case declares a limit above the configured "
                        "repository inference limit.",
                        affected=case.identity.as_posix(),
                        next_action=(
                            "Lower max_turns, timeout_seconds, or max_output_tokens "
                            "in the eval case, or raise the repository limit."
                        ),
                    )
                )
            )
    return tuple(findings)


def _path_in_scope(scope: Path | None, path: Path) -> bool:
    if scope is None:
        return True
    return is_within(scope, path.resolve())


def _skill_in_scope(scope: Path | None, skill_root: Path) -> bool:
    if scope is None:
        return True
    resolved_skill = skill_root.resolve()
    return is_within(scope, resolved_skill) or is_within(resolved_skill, scope)


def validate_repository(
    repository_root: Path,
    selection: Selection | None = None,
    *,
    scope: Path | None = None,
) -> ValidationReport:
    """Return every independent problem without running commands or a model.

    ``scope`` limits case discovery to a directory inside the repository while
    keeping the repository configuration and skill discovery boundaries intact.
    """
    actual_selection = Selection() if selection is None else selection
    root = repository_root.resolve()
    scope_root = None if scope is None else scope.resolve()
    config_result = load_config(root)
    if config_result.value is None:
        return ValidationReport(
            root,
            None,
            (),
            (),
            tuple(_finding(item) for item in config_result.diagnostics),
            (),
        )
    config = config_result.value
    selected_error = _selection_error(actual_selection)
    discovery = discover_skills(config)
    findings: list[GuardFinding] = [
        _finding(
            item,
            disposition="advisory" if item.code == "SCG1003" else "blocking",
        )
        for item in discovery.diagnostics
    ]
    if scope_root is not None and not is_within(root, scope_root):
        findings.append(
            _finding(
                Diagnostic(
                    "SCG1002",
                    "The validation directory must stay inside this repository.",
                    affected=scope_root.as_posix(),
                    next_action=(
                        "Run validation from the repository or a directory inside it."
                    ),
                )
            )
        )
    if selected_error is not None:
        findings.append(_finding(selected_error))
    selected_skills = tuple(
        skill
        for skill in discovery.skills
        if actual_selection.skill is None or skill.identity == actual_selection.skill
    )
    if actual_selection.skill is not None and not selected_skills:
        diagnostic = Diagnostic(
            "SCG1004",
            "SkillRoll could not find the selected skill.",
            affected=actual_selection.skill.as_posix(),
            next_action="Use a skill path relative to skills_path, such as reviewer.",
        )
        findings.append(_finding(diagnostic))
    candidate_skills = (
        selected_skills if actual_selection.skill is not None else discovery.skills
    )
    scoped_skills = tuple(
        skill for skill in candidate_skills if _skill_in_scope(scope_root, skill.root)
    )
    cases = []
    for skill in scoped_skills:
        for path in discover_case_files(skill):
            if not _path_in_scope(scope_root, path):
                continue
            candidate = parse_eval_case(path, skill)
            if candidate.value is None:
                findings.extend(_finding(item) for item in candidate.diagnostics)
            else:
                cases.append(candidate.value)
    if actual_selection.case is not None:
        selected_cases = tuple(
            case for case in cases if case.identity == actual_selection.case
        )
        if not selected_cases:
            diagnostic = Diagnostic(
                "SCG1004",
                "SkillRoll could not find the selected eval case.",
                affected=actual_selection.case.as_posix(),
                next_action=(
                    "Use an eval-case path relative to skills_path, such as "
                    "reviewer/evals/example.eval.md."
                ),
            )
            findings.append(_finding(diagnostic))
        cases = list(selected_cases)
        scoped_skills = tuple({case.skill for case in cases})
    parsed_cases = tuple(cases)
    findings.extend(_limit_findings(config, parsed_cases))
    ignored_evals = _ignored_evals_finding(root, parsed_cases)
    if ignored_evals is not None:
        findings.append(ignored_evals)
    if actual_selection.case is None:
        findings.extend(minimum_case_findings(config, scoped_skills, parsed_cases))
    reported_skills = discovery.skills if scope_root is None else scoped_skills
    return ValidationReport(
        root,
        config,
        reported_skills,
        parsed_cases,
        tuple(findings),
        discovery.skipped_safe_symlinks,
    )


def command_result(report: ValidationReport) -> CommandResult:
    """Translate a report into the stable CLI envelope."""
    active = tuple(finding for finding in report.findings if not finding.is_disabled)
    diagnostics = tuple(finding.diagnostic for finding in active)
    blocking = tuple(finding for finding in active if finding.is_blocking)
    advice = tuple(finding for finding in active if finding.is_advisory)
    has_error = any(
        finding.guard_id in {"SCG1001", "SCG1002", "SCG1004"} for finding in blocking
    )
    outcome = (
        Outcome.ERROR if has_error else Outcome.FAIL if diagnostics else Outcome.PASS
    )
    if not blocking:
        outcome = Outcome.PASS
    disabled = tuple(
        sorted({finding.guard_id for finding in report.findings if finding.is_disabled})
    )
    if not disabled and report.config is not None:
        disabled = tuple(sorted(report.config.guards.disabled))
    skill_noun = "skill" if len(report.skills) == 1 else "skills"
    eval_noun = "eval" if len(report.cases) == 1 else "evals"
    summary = (
        f"Validated {len(report.skills)} {skill_noun} and "
        f"{len(report.cases)} {eval_noun}."
        if outcome is Outcome.PASS
        else "Validation found a problem."
    )
    if advice:
        noun = "suggestion" if len(advice) == 1 else "suggestions"
        summary += f" {len(advice)} {noun}."
    if disabled:
        summary = f"{summary} Disabled guards: {', '.join(disabled)}."
    data: dict[str, JSONValue] = {
        "skills": tuple(skill.identity.as_posix() for skill in report.skills),
        "cases": tuple(case.identity.as_posix() for case in report.cases),
        "disabled_guards": disabled,
        "blocking_problems": tuple(_finding_data(finding) for finding in blocking),
        "advice": tuple(_finding_data(finding) for finding in advice),
        "skipped_safe_symlinks": tuple(
            path.as_posix() for path in report.skipped_safe_symlinks
        ),
    }
    return CommandResult(outcome, summary, diagnostics, data)


def selection_from_strings(skill: str | None, case: str | None) -> Selection:
    """Parse CLI selections without accepting absolute or backslash forms."""

    def parse(value: str | None) -> PurePosixPath | None:
        if value is None:
            return None
        return PurePosixPath(value)

    return Selection(parse(skill), parse(case))
