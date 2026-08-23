"""Contract tests for creating one named eval case."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from conftest import run_module

from skillroll.cli import main
from skillroll.commands import create_case
from skillroll.outcomes import Outcome


def configured_repo(root: Path) -> Path:
    skill = root / "refund"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Refund\n", encoding="utf-8")
    (root / "skillroll.toml").write_text(
        'schema_version = 1\nskills_path = "."\n', encoding="utf-8"
    )
    return skill


def test_new_creates_one_named_case_and_never_replaces_it(tmp_path: Path) -> None:
    skill = configured_repo(tmp_path)
    created = create_case.run(repo=str(tmp_path), target="refund/eligible-order")
    assert created.outcome is Outcome.PASS
    assert created.data["case"] == "refund/evals/eligible-order.eval.md"
    case = skill / "evals" / "eligible-order.eval.md"
    assert "## Success criteria" in case.read_text(encoding="utf-8")
    repeated = create_case.run(
        repo=str(tmp_path), target="refund/eligible-order.eval.md"
    )
    assert repeated.outcome is Outcome.ERROR
    assert "will not replace existing work" in repeated.summary


@pytest.mark.parametrize(
    "target",
    ("refund", "../refund/case", "refund/Not Valid", "refund/bad_name"),
)
def test_new_rejects_ambiguous_or_unsafe_targets(tmp_path: Path, target: str) -> None:
    configured_repo(tmp_path)
    result = create_case.run(repo=str(tmp_path), target=target)
    assert result.outcome is Outcome.ERROR
    assert "SKILL/CASE-NAME" in result.summary


def test_new_requires_setup_and_an_existing_skill(tmp_path: Path) -> None:
    missing_setup = create_case.run(repo=str(tmp_path), target="refund/eligible-order")
    assert missing_setup.outcome is Outcome.ERROR
    configured_repo(tmp_path)
    missing_skill = create_case.run(repo=str(tmp_path), target="missing/eligible-order")
    assert missing_skill.outcome is Outcome.ERROR
    assert "readable SKILL.md" in missing_skill.summary


def test_new_rejects_linked_eval_folder(tmp_path: Path) -> None:
    skill = configured_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (skill / "evals").symlink_to(outside, target_is_directory=True)
    result = create_case.run(repo=str(tmp_path), target="refund/eligible-order")
    assert result.outcome is Outcome.ERROR
    assert "symbolic-link evals" in result.summary


def test_new_cli_uses_the_current_repository(tmp_path: Path) -> None:
    configured_repo(tmp_path)
    process = run_module("new", "refund/eligible-order", cwd=tmp_path)
    assert process.returncode == 0
    assert process.stderr == ""
    assert "refund/evals/eligible-order.eval.md" in process.stdout


def test_main_dispatches_new_case_command(tmp_path: Path) -> None:
    configured_repo(tmp_path)
    stdout = io.StringIO()
    assert (
        main(
            ["new", "refund/eligible-order", "--repo", str(tmp_path)],
            stdout=stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert "refund/evals/eligible-order.eval.md" in stdout.getvalue()
