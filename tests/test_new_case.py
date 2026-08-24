"""Contract tests for creating one named eval case."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from conftest import run_module

from skillroll.cli import main
from skillroll.commands import create_case
from skillroll.outcomes import Outcome
from skillroll.repository_io import find_repository_root


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
    created = create_case.run(repo=str(tmp_path), skill="refund", name="eligible-order")
    assert created.outcome is Outcome.PASS
    assert created.data["case"] == "refund/evals/eligible-order.eval.md"
    case = skill / "evals" / "eligible-order.eval.md"
    assert "## Success criteria" in case.read_text(encoding="utf-8")
    repeated = create_case.run(
        repo=str(tmp_path), skill="refund", name="eligible-order.eval.md"
    )
    assert repeated.outcome is Outcome.ERROR
    assert "will not replace existing work" in repeated.summary


@pytest.mark.parametrize(
    ("skill", "name", "expected_message"),
    (
        ("refund", "bad_name", "eval name"),
        ("../refund", "case", "skill path"),
        ("refund", "Not Valid", "eval name"),
    ),
)
def test_new_rejects_ambiguous_or_unsafe_targets(
    tmp_path: Path, skill: str, name: str, expected_message: str
) -> None:
    configured_repo(tmp_path)
    result = create_case.run(repo=str(tmp_path), skill=skill, name=name)
    assert result.outcome is Outcome.ERROR
    assert expected_message in result.summary


def test_new_requires_setup_and_an_existing_skill(tmp_path: Path) -> None:
    missing_setup = create_case.run(
        repo=str(tmp_path), skill="refund", name="eligible-order"
    )
    assert missing_setup.outcome is Outcome.ERROR
    configured_repo(tmp_path)
    missing_skill = create_case.run(
        repo=str(tmp_path), skill="missing", name="eligible-order"
    )
    assert missing_skill.outcome is Outcome.ERROR
    assert "readable SKILL.md" in missing_skill.summary


def test_new_rejects_linked_eval_folder(tmp_path: Path) -> None:
    skill = configured_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (skill / "evals").symlink_to(outside, target_is_directory=True)
    result = create_case.run(repo=str(tmp_path), skill="refund", name="eligible-order")
    assert result.outcome is Outcome.ERROR
    assert "symbolic-link evals" in result.summary


def test_new_cli_uses_the_current_repository(tmp_path: Path) -> None:
    configured_repo(tmp_path)
    process = run_module("new", "refund", "eligible-order", cwd=tmp_path)
    assert process.returncode == 0
    assert process.stderr == ""
    assert "refund/evals/eligible-order.eval.md" in process.stdout


def test_new_cli_walks_up_to_the_nearest_repository_config(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    skill = configured_repo(repository)
    nested = skill / "references" / "notes"
    nested.mkdir(parents=True)

    process = run_module("new", "refund", "eligible-order", cwd=nested)

    assert process.returncode == 0
    assert process.stderr == ""
    assert (skill / "evals" / "eligible-order.eval.md").is_file()


def test_new_cli_uses_the_nearest_config_when_repositories_are_nested(
    tmp_path: Path,
) -> None:
    outer = tmp_path / "outer"
    configured_repo(outer)
    inner = outer / "inner"
    local_skill = inner / "local"
    local_skill.mkdir(parents=True)
    (local_skill / "SKILL.md").write_text("# Local\n", encoding="utf-8")
    (inner / "skillroll.toml").write_text(
        'schema_version = 1\nskills_path = "."\n', encoding="utf-8"
    )
    nested = local_skill / "references"
    nested.mkdir()

    process = run_module("new", "local", "eligible-order", cwd=nested)

    assert process.returncode == 0
    assert process.stderr == ""
    assert (local_skill / "evals" / "eligible-order.eval.md").is_file()
    assert not (outer / "refund" / "evals").exists()


def test_new_cli_explicit_repo_overrides_ancestor_discovery(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    configured_repo(outer)
    inner = outer / "inner"
    local_skill = inner / "local"
    local_skill.mkdir(parents=True)
    (local_skill / "SKILL.md").write_text("# Local\n", encoding="utf-8")
    (inner / "skillroll.toml").write_text(
        'schema_version = 1\nskills_path = "."\n', encoding="utf-8"
    )
    nested = local_skill / "references"
    nested.mkdir()

    process = run_module(
        "new",
        "refund",
        "eligible-order",
        "--repo",
        str(outer),
        cwd=nested,
    )

    assert process.returncode == 0
    assert process.stderr == ""
    assert (outer / "refund" / "evals" / "eligible-order.eval.md").is_file()
    assert not (local_skill / "evals").exists()


def test_new_cli_without_any_ancestor_config_keeps_setup_diagnostic(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "workspace" / "nested"
    nested.mkdir(parents=True)

    process = run_module("new", "refund", "eligible-order", cwd=nested)

    assert process.returncode == 3
    assert process.stdout == ""
    assert "valid local setup" in process.stderr


def test_repository_root_discovery_uses_nearest_config_and_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    configured_repo(repository)
    nested = repository / "refund" / "references"
    nested.mkdir()

    assert find_repository_root(nested) == repository
    monkeypatch.chdir(nested)
    assert find_repository_root() == repository

    no_config = tmp_path / "no-config" / "nested"
    no_config.mkdir(parents=True)
    assert find_repository_root(no_config) == no_config


def test_main_dispatches_new_case_command(tmp_path: Path) -> None:
    configured_repo(tmp_path)
    stdout = io.StringIO()
    assert (
        main(
            ["new", "refund", "eligible-order", "--repo", str(tmp_path)],
            stdout=stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert "refund/evals/eligible-order.eval.md" in stdout.getvalue()
