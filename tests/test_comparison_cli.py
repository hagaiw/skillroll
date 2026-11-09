"""CLI wiring and private comparison-evidence setup, without inference."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import run_module

from skillroll import commands
from skillroll.cli import main
from skillroll.commands import evaluate
from skillroll.diagnostics import CommandResult
from skillroll.initialization.templates import render_ignore
from skillroll.outcomes import Outcome


def test_comparison_cli_forwards_explicit_candidates_and_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def run(**values: object) -> CommandResult:
        observed.update(values)
        return CommandResult(Outcome.PASS, "Comparison complete.")

    monkeypatch.setattr(commands, "compare", SimpleNamespace(run=run), raising=False)
    output = io.StringIO()
    assert (
        main(
            [
                "--output",
                "json",
                "compare",
                "--repo",
                "/example",
                "--case",
                "review/evals/change.eval.md",
                "--executor-model",
                "test/baseline",
                "--executor-model",
                "test/candidate",
                "--model-profile",
                "judge",
                "--samples",
                "3",
                "--seed",
                "42",
                "--run-commands",
            ],
            stdout=output,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert json.loads(output.getvalue())["outcome"] == "PASS"
    assert observed == {
        "repo": "/example",
        "case": "review/evals/change.eval.md",
        "skill": None,
        "all_cases": False,
        "executor_models": ("test/baseline", "test/candidate"),
        "model_profile": "judge",
        "samples": 3,
        "seed": 42,
        "run_commands": True,
    }


def test_comparison_defaults_reach_inference_free_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def run(**values: object) -> CommandResult:
        observed.update(values)
        return CommandResult(Outcome.ERROR, "Candidates are required.")

    monkeypatch.setattr(commands, "compare", SimpleNamespace(run=run), raising=False)
    assert main(["compare"], stdout=io.StringIO(), stderr=io.StringIO()) == 3
    assert observed["executor_models"] == ()
    assert observed["samples"] == 5
    assert observed["seed"] == 0
    assert observed["run_commands"] is False


def test_eval_cli_forwards_executor_override(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def run(**values: object) -> CommandResult:
        observed.update(values)
        return CommandResult(Outcome.PASS, "Evaluation complete.")

    monkeypatch.setattr(evaluate, "run", run)
    assert (
        main(
            ["eval", "--executor-model", "test/cheap"],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        == 0
    )
    assert observed["executor_model"] == "test/cheap"


@pytest.mark.parametrize(
    "arguments",
    [
        ["compare", "--case", "a", "--all"],
        ["compare", "--samples", "many"],
        ["compare", "--seed", "random"],
        ["compare", "--concurrency", "2"],
        ["compare", "--with-skill-control"],
    ],
)
def test_invalid_comparison_syntax_is_normalized(arguments: list[str]) -> None:
    output = io.StringIO()
    assert main(["--output=json", *arguments], stdout=output, stderr=io.StringIO()) == 3
    assert json.loads(output.getvalue())["diagnostics"][0]["code"] == "SC0003"


def test_init_adds_comparison_privacy_rule_to_existing_setup() -> None:
    previous = ".skillroll/runs/\n.skillroll/experiments/\n"
    expected = previous + ".skillroll/comparisons/\n"
    assert render_ignore(previous).decode() == expected
    assert render_ignore(expected).decode() == expected


def test_real_comparison_cli_validates_before_inference(tmp_path: Path) -> None:
    invalid = run_module(
        "--output", "json", "compare", "--executor-model", "one", cwd=tmp_path
    )
    assert invalid.returncode == 3
    assert invalid.stderr == ""
    assert json.loads(invalid.stdout)["diagnostics"][0]["code"] == "SCC2001"
    missing_config = run_module(
        "--output",
        "json",
        "compare",
        "--executor-model",
        "one",
        "--executor-model",
        "two",
        cwd=tmp_path,
    )
    assert missing_config.returncode == 3
    assert json.loads(missing_config.stdout)["diagnostics"][0]["code"] == "SCG1001"
    assert not (tmp_path / ".skillroll").exists()
