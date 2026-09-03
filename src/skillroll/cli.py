"""SkillRoll command-line parsing and result delivery."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import resources
from io import StringIO
from typing import Never, TextIO

from skillroll import __version__
from skillroll.commands import initialize
from skillroll.diagnostics import CommandResult, Diagnostic, render_json, render_text
from skillroll.outcomes import Outcome

Command = Callable[[], CommandResult]


def _setup_mascot() -> str:
    """Load the fixed ANSI welcome art shipped with the CLI."""
    path = resources.files("skillroll").joinpath("_assets", "setup-mascot.ansi")
    try:
        return path.read_text(encoding="utf-8").rstrip("\n")
    except (FileNotFoundError, OSError, UnicodeError):
        return ""


def _show_setup_mascot(
    *, command: str | None, output: str, out: TextIO, result: CommandResult
) -> bool:
    """Keep ANSI art out of JSON, pipes, no-op setup, and limited terminals."""
    return (
        command == "init"
        and output == "text"
        and result.outcome is Outcome.PASS
        and bool(result.data.get("skills_path"))
        and bool(result.data.get("changed_paths"))
        and bool(getattr(out, "isatty", lambda: False)())
        and os.environ.get("TERM") != "dumb"
        and "NO_COLOR" not in os.environ
    )


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
        description=(
            "Test skills with Markdown evals and a Dungeon Master that simulates "
            "the outside world."
        ),
        epilog=(
            "init creates local setup files. Add --github-workflow only when "
            "you want a visible GitHub Actions workflow."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    commands = parser.add_subparsers(dest="command")
    init_parser = commands.add_parser(
        "init", help="Set up SkillRoll in a skills repository."
    )
    init_parser.add_argument(
        "--repo",
        metavar="PATH",
        help="Repository directory override; otherwise use the current directory.",
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
        help="Create two starter evals for a skill relative to skills_path.",
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
            "Configure OpenRouter's changing free route for setup checks only; "
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
    new_parser = commands.add_parser("new", help="Create an eval for a skill.")
    new_parser.add_argument(
        "skill",
        metavar="SKILL_PATH",
        help="Skill path relative to skills_path.",
    )
    new_parser.add_argument(
        "name",
        metavar="EVAL_NAME",
        help="New eval name, in lowercase kebab-case.",
    )
    new_parser.add_argument(
        "--repo",
        metavar="PATH",
        help=(
            "Repository directory override; otherwise use the nearest skillroll.toml."
        ),
    )
    doctor_parser = commands.add_parser("doctor", help="Check the model connection.")
    doctor_parser.add_argument(
        "--repo",
        metavar="PATH",
        help=(
            "Repository directory override; otherwise use the nearest skillroll.toml."
        ),
    )
    doctor_parser.add_argument(
        "--model-profile",
        metavar="NAME",
        help="Model profile to use.",
    )
    validate_parser = commands.add_parser(
        "validate", help="Check evals under the current directory without a model."
    )
    validate_parser.add_argument(
        "--repo",
        metavar="PATH",
        help=(
            "Repository directory override; otherwise use the nearest skillroll.toml."
        ),
    )
    selection = validate_parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--skill", metavar="PATH", help="Skill path relative to skills_path."
    )
    selection.add_argument(
        "--case", metavar="PATH", help="Eval-case path relative to skills_path."
    )
    selection.add_argument(
        "--all",
        action="store_true",
        help="Validate every discovered eval case in the selected repository.",
    )
    validate_parser.add_argument(
        "--run-commands",
        action="store_true",
        help=(
            "Run repository commands declared by evals. Only use this for code "
            "you trust."
        ),
    )
    evaluate_parser = commands.add_parser("eval", help="Run skill evals.")
    evaluate_parser.add_argument(
        "--repo",
        metavar="PATH",
        help=(
            "Repository directory override; otherwise use the nearest skillroll.toml."
        ),
    )
    evaluate_selection = evaluate_parser.add_mutually_exclusive_group()
    evaluate_selection.add_argument(
        "--skill", metavar="PATH", help="Skill path relative to skills_path."
    )
    evaluate_selection.add_argument(
        "--case", metavar="PATH", help="Eval-case path relative to skills_path."
    )
    evaluate_selection.add_argument(
        "--all",
        action="store_true",
        help="Evaluate every discovered eval case in the selected repository.",
    )
    evaluate_parser.add_argument(
        "--run-commands",
        action="store_true",
        help=(
            "Run repository commands declared by evals. Only use this for code "
            "you trust."
        ),
    )
    model_selection = evaluate_parser.add_mutually_exclusive_group()
    model_selection.add_argument(
        "--model-profile",
        metavar="NAME",
        help="Model profile to use.",
    )
    model_selection.add_argument(
        "--model",
        metavar="MODEL",
        help=(
            "Override the configured model for this eval invocation; cannot be "
            "combined with --model-profile."
        ),
    )
    evaluate_parser.add_argument(
        "--samples",
        type=int,
        default=1,
        metavar="N",
        help="Run each eval N times (1-10).",
    )
    evaluate_parser.add_argument(
        "--with-skill-control",
        action="store_true",
        help="Also run without the skill to check whether the eval depends on it.",
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
                    "Run 'skillroll --help' and choose init, new, doctor, validate, "
                    "or eval."
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
    parsed_command: str | None = None
    try:
        namespace = _parser().parse_args(arguments)
    except ParseFailure as failure:
        result = _syntax_error(failure.message)
    else:
        output = namespace.output
        parsed_command = namespace.command
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
                elif namespace.command == "new" and commands is None:
                    from skillroll.commands import create_case

                    result = create_case.run(
                        skill=namespace.skill,
                        name=namespace.name,
                        repo=namespace.repo,
                    )
                elif namespace.command == "validate" and commands is None:
                    from skillroll.commands import validate

                    result = validate.run(
                        repo=namespace.repo,
                        skill=namespace.skill,
                        case=namespace.case,
                        all_cases=namespace.all,
                        run_commands=namespace.run_commands,
                    )
                elif namespace.command == "eval" and commands is None:
                    from skillroll.commands import evaluate

                    result = evaluate.run(
                        repo=namespace.repo,
                        skill=namespace.skill,
                        case=namespace.case,
                        all_cases=namespace.all,
                        run_commands=namespace.run_commands,
                        model_profile=namespace.model_profile,
                        model_override=namespace.model,
                        samples=namespace.samples,
                        with_skill_control=namespace.with_skill_control,
                    )
                else:
                    result = (COMMANDS if commands is None else commands)[
                        namespace.command
                    ]()
            except Exception:
                result = _internal_error(namespace.command)
    if _show_setup_mascot(
        command=parsed_command,
        output=output,
        out=out,
        result=result,
    ):
        mascot = _setup_mascot()
        if mascot:
            out.write(mascot + "\n\n")
    rendered = render_json(result) if output == "json" else render_text(result)
    destination = out if output == "json" or result.outcome is Outcome.PASS else err
    destination.write(rendered)
    return result.outcome.exit_code


def entrypoint() -> None:
    """Console-script adapter."""
    raise SystemExit(main())
