"""SkillRoll command-line parsing and result delivery."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from io import StringIO
from typing import Never, TextIO

from skillroll import __version__
from skillroll.commands import initialize
from skillroll.diagnostics import CommandResult, Diagnostic, render_json, render_text
from skillroll.outcomes import Outcome

Command = Callable[[], CommandResult]


@dataclass(frozen=True, slots=True)
class ParseFailure(Exception):
    message: str


class SkillRollParser(argparse.ArgumentParser):
    """An argument parser that leaves output and exit handling to SkillRoll."""

    def error(self, message: str) -> Never:
        raise ParseFailure(message)


def _parser() -> SkillRollParser:
    parser = SkillRollParser(
        prog="skillroll",
        description="Set up, validate, and evaluate agent skills.",
        epilog=(
            "init creates local setup files. Add --github-workflow only when "
            "you want a visible GitHub Actions workflow."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    commands = parser.add_subparsers(dest="command")
    init_parser = commands.add_parser(
        "init", help="Create safe local SkillRoll setup files for a repository."
    )
    init_parser.add_argument(
        "--repo", metavar="PATH", help="Repository directory to set up."
    )
    init_parser.add_argument(
        "--skills-path",
        metavar="PATH",
        help="Folder to scan, relative to the repository (use . for its root).",
    )
    init_parser.add_argument(
        "--base-url", metavar="URL", help="Generic model endpoint URL."
    )
    init_parser.add_argument(
        "--model", metavar="MODEL", help="Model name for that endpoint."
    )
    init_parser.add_argument(
        "--api-key-env",
        metavar="NAME",
        help="Environment-variable name holding the endpoint key.",
    )
    init_parser.add_argument(
        "--starter-evals",
        metavar="SKILL_PATH",
        help=(
            "Create two editable starter cases for this skill relative to skills_path."
        ),
    )
    init_parser.add_argument(
        "--yes",
        action="store_true",
        help="Accept only the safe detected folder and never prompt.",
    )
    init_parser.add_argument(
        "--openrouter-free",
        action="store_true",
        help=(
            "Explicitly configure OpenRouter's free inference defaults; "
            "never reads the key."
        ),
    )
    init_parser.add_argument(
        "--github-workflow",
        action="store_true",
        help=(
            "Add one visible GitHub Actions workflow without replacing existing files."
        ),
    )
    init_parser.add_argument(
        "--action-ref",
        metavar="OWNER/REPOSITORY@TAG",
        help="Released SkillRoll Action reference for --github-workflow.",
    )
    doctor_parser = commands.add_parser(
        "doctor", help="Check whether configured inference can run SkillRoll."
    )
    doctor_parser.add_argument(
        "--repo", metavar="PATH", help="Repository directory to inspect."
    )
    doctor_parser.add_argument(
        "--model-profile",
        metavar="NAME",
        help="Named ranked model profile to use during preflight and evaluation.",
    )
    validate_parser = commands.add_parser(
        "validate", help="Validate skill and eval files."
    )
    validate_parser.add_argument(
        "--repo", metavar="PATH", help="Repository directory to validate."
    )
    selection = validate_parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--skill", metavar="PATH", help="Skill path relative to skills_path."
    )
    selection.add_argument(
        "--case", metavar="PATH", help="Eval-case path relative to skills_path."
    )
    validate_parser.add_argument(
        "--all", action="store_true", help="Validate every discovered eval case."
    )
    validate_parser.add_argument(
        "--run-commands",
        action="store_true",
        help=(
            "Run checks written in eval files, only after you trust this repository."
        ),
    )
    evaluate_parser = commands.add_parser("eval", help="Run skill evaluations.")
    evaluate_parser.add_argument(
        "--repo", metavar="PATH", help="Repository directory to evaluate."
    )
    evaluate_selection = evaluate_parser.add_mutually_exclusive_group()
    evaluate_selection.add_argument(
        "--skill", metavar="PATH", help="Skill path relative to skills_path."
    )
    evaluate_selection.add_argument(
        "--case", metavar="PATH", help="Eval-case path relative to skills_path."
    )
    evaluate_parser.add_argument(
        "--all", action="store_true", help="Evaluate every discovered eval case."
    )
    evaluate_parser.add_argument(
        "--run-commands",
        action="store_true",
        help=(
            "Run checks written in eval files, only after you trust this repository."
        ),
    )
    evaluate_parser.add_argument(
        "--model-profile",
        metavar="NAME",
        help="Named ranked model profile to use during preflight and evaluation.",
    )
    evaluate_parser.add_argument(
        "--samples",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Run N independent samples (1-10). Each sample has its own evidence; "
            "useful for authoring and model-dependence research."
        ),
    )
    evaluate_parser.add_argument(
        "--with-skill-control",
        action="store_true",
        help=(
            "Also run each sample without the selected skill as a non-gating "
            "authoring control."
        ),
    )
    return parser


def _requested_output(arguments: Sequence[str]) -> str:
    for index, argument in enumerate(arguments):
        if argument == "--output" and index + 1 < len(arguments):
            return "json" if arguments[index + 1] == "json" else "text"
        if argument.startswith("--output="):
            return "json" if argument.partition("=")[2] == "json" else "text"
    return "text"


def _syntax_error(details: str) -> CommandResult:
    return CommandResult(
        Outcome.ERROR,
        "SkillRoll could not understand the command you entered.",
        (
            Diagnostic(
                "SC0003",
                "SkillRoll could not understand the command you entered.",
                details=(details,),
                next_action=(
                    "Run 'skillroll --help', then correct the command and try again."
                ),
            ),
        ),
    )


def _missing_command() -> CommandResult:
    return CommandResult(
        Outcome.ERROR,
        "Choose one SkillRoll command to continue.",
        (
            Diagnostic(
                "SC0002",
                "Choose one SkillRoll command to continue.",
                next_action=(
                    "Run 'skillroll --help' and choose init, doctor, validate, or eval."
                ),
            ),
        ),
    )


def _internal_error(command: str) -> CommandResult:
    return CommandResult(
        Outcome.ERROR,
        "SkillRoll stopped before it could complete your request.",
        (
            Diagnostic(
                "SC0004",
                "SkillRoll stopped before it could complete your request.",
                affected=command,
                next_action=(
                    "Try the command again; if it still fails, report this "
                    "diagnostic code."
                ),
            ),
        ),
    )


COMMANDS: dict[str, Command] = {
    "init": initialize.run,
}


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    commands: dict[str, Command] | None = None,
) -> int:
    """Parse one invocation, render its result, and return its exit status."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    output = _requested_output(arguments)
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    try:
        namespace = _parser().parse_args(arguments)
    except ParseFailure as failure:
        result = _syntax_error(failure.message)
    else:
        output = namespace.output
        if namespace.command is None:
            result = _missing_command()
        else:
            try:
                if namespace.command == "init" and commands is None:
                    result = initialize.run(
                        repo=namespace.repo,
                        skills_path=namespace.skills_path,
                        base_url=namespace.base_url,
                        model=namespace.model,
                        api_key_env=namespace.api_key_env,
                        openrouter_free=namespace.openrouter_free,
                        starter_evals=namespace.starter_evals,
                        yes=namespace.yes,
                        github_workflow=namespace.github_workflow,
                        action_ref=namespace.action_ref,
                        input_stream=(sys.stdin if output == "text" else StringIO()),
                        output_stream=out,
                    )
                elif namespace.command == "doctor" and commands is None:
                    from skillroll.commands import doctor

                    result = doctor.run(
                        repo=namespace.repo, model_profile=namespace.model_profile
                    )
                elif namespace.command == "validate" and commands is None:
                    from skillroll.commands import validate

                    result = validate.run(
                        repo=namespace.repo,
                        skill=namespace.skill,
                        case=namespace.case,
                        run_commands=namespace.run_commands,
                    )
                elif namespace.command == "eval" and commands is None:
                    from skillroll.commands import evaluate

                    result = evaluate.run(
                        repo=namespace.repo,
                        skill=namespace.skill,
                        case=namespace.case,
                        run_commands=namespace.run_commands,
                        model_profile=namespace.model_profile,
                        samples=namespace.samples,
                        with_skill_control=namespace.with_skill_control,
                    )
                else:
                    result = (COMMANDS if commands is None else commands)[
                        namespace.command
                    ]()
            except Exception:
                result = _internal_error(namespace.command)
    rendered = render_json(result) if output == "json" else render_text(result)
    destination = out if output == "json" or result.outcome is Outcome.PASS else err
    destination.write(rendered)
    return result.outcome.exit_code


def entrypoint() -> None:
    """Console-script adapter."""
    raise SystemExit(main())
