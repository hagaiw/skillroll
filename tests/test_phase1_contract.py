"""High-value contract tests for inference-free repository validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import run_module

from skillroll.commands import validate
from skillroll.outcomes import Outcome


def write_repository(root: Path, *, config: str | None = None) -> Path:
    (root / "skills" / "review" / "evals").mkdir(parents=True)
    (root / "skillroll.toml").write_text(
        config or 'schema_version = 1\nskills_path = "skills"\n',
        encoding="utf-8",
    )
    (root / "skills" / "review" / "SKILL.md").write_text(
        "# Review\n\nRead [context](references/context.md).\n", encoding="utf-8"
    )
    (root / "skills" / "review" / "references").mkdir()
    (root / "skills" / "review" / "references" / "context.md").write_text(
        "Useful context.\n", encoding="utf-8"
    )
    for name in ("ordinary", "edge"):
        (root / "skills" / "review" / "evals" / f"{name}.eval.md").write_text(
            "# Check\n\n```skillroll\nschema_version: 1\n```\n\n"
            "## Input\n\nReview the change.\n\n"
            "## World\n\nThe change is small.\n\n"
            "## Success criteria\n\n- Explain the change.\n",
            encoding="utf-8",
        )
    return root


def test_validate_complete_repository_and_json_data(tmp_path: Path) -> None:
    repository = write_repository(tmp_path / "repository")
    completed = run_module("--output", "json", "validate", "--repo", str(repository))
    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert result["outcome"] == "PASS"
    assert result["data"]["skills"] == ["review"]
    assert result["data"]["cases"] == [
        "review/evals/edge.eval.md",
        "review/evals/ordinary.eval.md",
    ]


def test_validate_defaults_to_evals_under_the_current_working_directory(
    tmp_path: Path,
) -> None:
    repository = write_repository(tmp_path / "repository")
    other_evals = repository / "skills" / "other" / "evals"
    other_evals.mkdir(parents=True)
    (other_evals.parent / "SKILL.md").write_text("# Other\n", encoding="utf-8")
    (other_evals / "one.eval.md").write_text(
        (repository / "skills" / "review" / "evals" / "ordinary.eval.md").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    working_directory = repository / "skills" / "review" / "evals"

    scoped = run_module("--output", "json", "validate", cwd=working_directory)

    assert scoped.returncode == 0
    scoped_result = json.loads(scoped.stdout)
    assert scoped_result["data"]["skills"] == ["review"]
    assert scoped_result["data"]["cases"] == [
        "review/evals/edge.eval.md",
        "review/evals/ordinary.eval.md",
    ]

    all_cases = run_module(
        "--output", "json", "validate", "--all", cwd=working_directory
    )

    assert all_cases.returncode == 0
    all_result = json.loads(all_cases.stdout)
    assert all_result["data"]["skills"] == ["other", "review"]
    assert all_result["data"]["cases"] == [
        "other/evals/one.eval.md",
        "review/evals/edge.eval.md",
        "review/evals/ordinary.eval.md",
    ]


def test_validate_function_defaults_to_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = write_repository(tmp_path / "repository")
    monkeypatch.chdir(repository / "skills" / "review" / "evals")

    result = validate.run()

    assert result.outcome is Outcome.PASS
    assert result.data["cases"] == (
        "review/evals/edge.eval.md",
        "review/evals/ordinary.eval.md",
    )


def test_validate_reports_missing_section_and_policy_failure(tmp_path: Path) -> None:
    repository = write_repository(tmp_path / "repository")
    (repository / "skills" / "review" / "evals" / "edge.eval.md").unlink()
    case = repository / "skills" / "review" / "evals" / "ordinary.eval.md"
    case.write_text("## Input\n\nOnly this section.\n", encoding="utf-8")
    completed = run_module("validate", "--repo", str(repository))
    assert completed.returncode == 1
    assert "Success criteria" in completed.stderr


def test_validate_rejects_unsafe_config_and_is_side_effect_free(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "skillroll.toml").write_text(
        'schema_version = 1\nskills_path = "../elsewhere"\n', encoding="utf-8"
    )
    completed = run_module("--output=json", "validate", "--repo", str(repository))
    assert completed.returncode == 3
    assert json.loads(completed.stdout)["diagnostics"][0]["code"] == "SCG1002"
    assert sorted(item.name for item in repository.iterdir()) == ["skillroll.toml"]


def test_validate_selection_and_disabled_policy_are_visible(tmp_path: Path) -> None:
    repository = write_repository(
        tmp_path / "repository",
        config=(
            'schema_version = 1\nskills_path = "skills"\n\n'
            '[guards]\ndisabled = ["SCG2001"]\n'
        ),
    )
    (repository / "skills" / "review" / "evals" / "edge.eval.md").unlink()
    completed = run_module("validate", "--repo", str(repository), "--skill", "review")
    assert completed.returncode == 0
    assert "Disabled guards: SCG2001" in completed.stdout
    incompatible = run_module(
        "validate", "--repo", str(repository), "--skill", "review", "--case", "x"
    )
    assert incompatible.returncode == 3
