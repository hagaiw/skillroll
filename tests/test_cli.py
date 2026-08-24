from __future__ import annotations

import io
import json
import runpy
import sys
from pathlib import Path

import pytest
from conftest import run_module

from skillroll.cli import entrypoint, main
from skillroll.diagnostics import CommandResult
from skillroll.outcomes import Outcome


def test_init_without_skills_is_actionable(tmp_path: Path) -> None:
    process = run_module("init", cwd=tmp_path)
    assert process.returncode == 3
    assert process.stdout == ""
    assert "SC0001" not in process.stderr
    assert "did not find any SKILL.md" in process.stderr
    assert "Next:" in process.stderr


def test_json_result_uses_stdout_only(tmp_path: Path) -> None:
    process = run_module("--output", "json", "eval", cwd=tmp_path)
    assert process.returncode == 3
    assert process.stderr == ""
    assert json.loads(process.stdout)["diagnostics"][0]["code"] == "SCG1001"


def test_json_init_never_prompts_even_when_stdin_is_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = tmp_path / "skills" / "review"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Review\n", encoding="utf-8")

    class TerminalInput(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", TerminalInput())
    stdout = io.StringIO()
    assert (
        main(
            [
                "--output=json",
                "init",
                "--repo",
                str(tmp_path),
                "--skills-path",
                "skills",
                "--starter-evals",
                "review",
            ],
            stdout=stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert json.loads(stdout.getvalue())["data"]["skills_path"] == "skills"


@pytest.mark.parametrize("command", ["init", "doctor", "eval"])
def test_default_dispatch_calls_each_handler(
    command: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main([command], stdout=io.StringIO(), stderr=io.StringIO()) == 3


def test_missing_command_is_normalized() -> None:
    process = run_module()
    assert process.returncode == 3
    assert "Choose one SkillRoll command" in process.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ("unknown",),
        ("eval", "--unknown"),
        ("eval", "--all", "--case", "review/evals/one.eval.md"),
        ("validate", "--all", "--skill", "review"),
        ("--output",),
        ("--output", "xml", "eval"),
    ],
)
def test_invalid_syntax_never_leaks_argparse_usage(arguments: tuple[str, ...]) -> None:
    process = run_module(*arguments)
    assert process.returncode == 3
    assert "usage:" not in process.stderr.lower()
    assert "could not understand" in process.stderr


def test_malformed_json_invocation_stays_machine_readable() -> None:
    process = run_module("--output=json", "unknown")
    assert process.returncode == 3
    assert process.stderr == ""
    assert json.loads(process.stdout)["diagnostics"][0]["code"] == "SC0003"


def test_direct_syntax_and_missing_command_paths() -> None:
    stderr = io.StringIO()
    assert main(["unknown"], stdout=io.StringIO(), stderr=stderr) == 3
    assert "could not understand" in stderr.getvalue()
    assert main([], stdout=io.StringIO(), stderr=io.StringIO()) == 3


@pytest.mark.parametrize(
    "arguments", [["--output", "text", "eval"], ["--output=json", "eval"]]
)
def test_direct_output_spelling_paths(arguments: list[str]) -> None:
    assert main(arguments, stdout=io.StringIO(), stderr=io.StringIO()) == 3


def test_unexpected_handler_exception_is_normalized_without_traceback() -> None:
    def broken() -> CommandResult:
        raise RuntimeError("private implementation detail")

    stdout, stderr = io.StringIO(), io.StringIO()
    exit_code = main(["eval"], stdout=stdout, stderr=stderr, commands={"eval": broken})
    assert exit_code == 3
    assert stdout.getvalue() == ""
    assert "[SC0004]" in stderr.getvalue()
    assert "private implementation detail" not in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


def test_pass_text_goes_to_stdout() -> None:
    result = CommandResult(Outcome.PASS, "Everything passed.")
    stdout, stderr = io.StringIO(), io.StringIO()
    assert (
        main(["eval"], stdout=stdout, stderr=stderr, commands={"eval": lambda: result})
        == 0
    )
    assert stdout.getvalue() == "PASS — Everything passed.\n"
    assert stderr.getvalue() == ""


@pytest.mark.parametrize("argument", ["--help", "--version"])
def test_help_and_version_succeed(argument: str) -> None:
    process = run_module(argument)
    assert process.returncode == 0
    assert process.stdout
    assert process.stderr == ""


def test_default_streams_argv_entrypoint_and_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["skillroll", "eval"])
    assert main() == 3
    with pytest.raises(SystemExit) as exit_info:
        entrypoint()
    assert exit_info.value.code == 3
    with pytest.raises(SystemExit) as module_exit:
        runpy.run_module("skillroll", run_name="__main__")
    assert module_exit.value.code == 3
