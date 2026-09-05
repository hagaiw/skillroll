"""Private entry point used only by SkillRoll's composite GitHub Action."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Never

from skillroll.commands import evaluate, validate
from skillroll.diagnostics import CommandResult, render_json
from skillroll.github import (
    ChangedSelection,
    git_changes,
    select_changed,
    valid_reviewed_ref,
    write_github_report,
)
from skillroll.outcomes import Outcome
from skillroll.validation import (
    command_result,
    selection_from_strings,
    validate_repository,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise ValueError(message)


def _parser() -> _Parser:
    parser = _Parser(prog="skillroll GitHub Action")
    parser.add_argument(
        "--mode", choices=("validate", "eval", "validate-ref"), required=True
    )
    parser.add_argument(
        "--scope", choices=("changed", "all", "skill", "case"), required=True
    )
    parser.add_argument("--base-sha")
    parser.add_argument("--head-sha")
    parser.add_argument("--selection-path")
    parser.add_argument("--reviewed-ref")
    parser.add_argument("--run-commands", choices=("true", "false"), default="false")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument(
        "--with-skill-control", choices=("true", "false"), default="false"
    )
    parser.add_argument("--command-notice", choices=("true", "false"), default="false")
    parser.add_argument("--fork-notice", choices=("true", "false"), default="false")
    parser.add_argument("--upload-artifact", choices=("true", "false"), default="false")
    parser.add_argument("--artifact-retention-days", type=int, default=7)
    return parser


def _error(message: str) -> CommandResult:
    return (
        CommandResult(
            Outcome.ERROR,
            "SkillRoll could not safely start this GitHub Actions job.",
        )
        if not message
        else CommandResult(
            Outcome.ERROR,
            "SkillRoll could not safely start this GitHub Actions job.",
            (),
            {"action_error": message},
        )
    )


def _selection(
    args: argparse.Namespace, root: Path
) -> tuple[ChangedSelection | None, CommandResult | None]:
    if args.scope == "changed":
        if not args.base_sha or not args.head_sha:
            return None, _error("Changed scope needs both base-sha and head-sha.")
        report = validate_repository(root)
        initial = command_result(report)
        if initial.outcome is not Outcome.PASS:
            return None, initial
        diff = git_changes(root, args.base_sha, args.head_sha)
        if diff.fallback_reason is not None:
            return ChangedSelection("all", report.cases, diff.fallback_reason), None
        return select_changed(report, diff.changes), None
    if args.scope in {"skill", "case"}:
        if not args.selection_path:
            return None, _error("This selected scope needs a skill or eval-case path.")
        report = validate_repository(root)
        initial = command_result(report)
        if initial.outcome is not Outcome.PASS:
            return None, initial
        selection = selection_from_strings(
            args.selection_path if args.scope == "skill" else None,
            args.selection_path if args.scope == "case" else None,
        )
        selected_report = validate_repository(root, selection)
        selected_initial = command_result(selected_report)
        if selected_initial.outcome is not Outcome.PASS:
            return None, selected_initial
        return ChangedSelection(
            "cases", selected_report.cases, "The maintainer selected this path."
        ), None
    if args.selection_path or args.base_sha or args.head_sha:
        return None, _error(
            "All scope does not accept a path or changed Git revisions."
        )
    report = validate_repository(root)
    initial = command_result(report)
    if initial.outcome is not Outcome.PASS:
        return None, initial
    return ChangedSelection(
        "all", report.cases, "The maintainer selected every skill and eval case."
    ), None


def main(argv: Sequence[str] | None = None) -> int:
    """Run one already-reviewed Action request and write GitHub-safe reporting."""
    try:
        args = _parser().parse_args(argv)
    except ValueError as error:
        result = _error(str(error))
        print(render_json(result), end="")
        return result.outcome.exit_code
    if not 1 <= args.artifact_retention_days <= 90:
        result = _error("Artifact retention must be between 1 and 90 days.")
        print(render_json(result), end="")
        return result.outcome.exit_code
    if not 1 <= args.samples <= 10:
        result = _error("Sample count must be between 1 and 10.")
        print(render_json(result), end="")
        return result.outcome.exit_code
    root = Path.cwd()
    selected: ChangedSelection | None = None
    if args.mode == "validate-ref":
        if not args.reviewed_ref or not valid_reviewed_ref(args.reviewed_ref):
            result = _error(
                "A reviewed model-backed run needs an exact commit SHA or "
                "refs/pull/NUMBER/head."
            )
        elif (
            args.scope != "all" or args.selection_path or args.base_sha or args.head_sha
        ):
            result = _error("Reference validation does not accept an evaluation scope.")
        else:
            result = CommandResult(
                Outcome.PASS, "The reviewed revision format is safe to check out."
            )
        failure = None
    else:
        selected, failure = _selection(args, root)
    if args.mode == "validate-ref":
        pass
    elif failure is not None:
        result = failure
    elif selected is not None and selected.scope == "none":
        result = CommandResult(
            Outcome.PASS, "No selected skill or eval case needs a model evaluation."
        )
    elif args.mode == "validate":
        result = validate.run(
            repo=str(root),
            run_commands=args.run_commands == "true",
            selected_cases=None if selected is None else selected.cases,
        )
    else:
        result = evaluate.run(
            repo=str(root),
            run_commands=args.run_commands == "true",
            selected_cases=None if selected is None else selected.cases,
            samples=args.samples,
            with_skill_control=args.with_skill_control == "true",
        )
    annotations = write_github_report(
        result,
        selected,
        fork_notice=args.fork_notice == "true",
        command_notice=args.command_notice == "true",
        artifact_uploaded=args.upload_artifact == "true",
        retention_days=args.artifact_retention_days,
    )
    for annotation in annotations:
        print(annotation)
    print(render_json(result), end="")
    return result.outcome.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
