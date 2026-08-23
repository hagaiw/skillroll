"""Contracts for GitHub-only adapters; all model and GitHub I/O stays fake."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path, PurePosixPath
from subprocess import CompletedProcess

import pytest
import yaml

from skillroll import github, github_action
from skillroll.commands.initialize import run as initialize
from skillroll.diagnostics import CommandResult, Diagnostic, SourceLocation
from skillroll.github import (
    ChangedPath,
    GitDiffError,
    annotation_lines,
    changes_from_iterable,
    git_changes,
    parse_name_status,
    render_summary,
    select_changed,
    valid_reviewed_ref,
    write_github_report,
)
from skillroll.github_action import main as action_main
from skillroll.github_workflow import (
    DEFAULT_ACTION_REF,
    render_workflow,
    valid_action_ref,
)
from skillroll.outcomes import Outcome
from skillroll.validation import validate_repository


def make_repository(root: Path) -> Path:
    for name in ("review", "overview"):
        skill = root / "skills" / name
        (skill / "evals").mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        (skill / "references").mkdir(exist_ok=True)
        (skill / "references" / "context.md").write_text("facts\n", encoding="utf-8")
        for case in ("ordinary", "edge"):
            (skill / "evals" / f"{case}.eval.md").write_text(
                "```skillroll\nschema_version: 1\n```\n\n"
                "## Input\n\nRequest\n\n## World\n\nWorld\n\n"
                "## Success criteria\n\n- Useful result\n",
                encoding="utf-8",
            )
    (root / "skillroll.toml").write_text(
        'schema_version = 1\nskills_path = "skills"\n\n[inference]\n'
        'base_url = "https://example.test/v1"\nmodel = "cheap"\n'
        'api_key_env = "SKILLROLL_API_KEY"\n',
        encoding="utf-8",
    )
    return root


def test_parse_git_name_status_handles_normal_and_renamed_paths() -> None:
    parsed = parse_name_status(
        b"M\0skills/review/SKILL.md\0A\0README.md\0R100\0old.md\0new.md\0"
    )
    assert parsed == (
        ChangedPath("modified", None, PurePosixPath("skills/review/SKILL.md")),
        ChangedPath("added", None, PurePosixPath("README.md")),
        ChangedPath("renamed", PurePosixPath("old.md"), PurePosixPath("new.md")),
    )


def test_parse_git_name_status_handles_more_statuses_and_bad_encoding() -> None:
    parsed = parse_name_status(b"D\0gone.md\0C100\0old.md\0new.md\0Z\0odd.md\0")
    assert parsed[0] == ChangedPath("deleted", PurePosixPath("gone.md"), None)
    assert parsed[1].kind == "renamed"
    assert parsed[2] == ChangedPath("unknown")
    with pytest.raises(GitDiffError, match="cannot read"):
        parse_name_status(b"M\0\xff\0")
    assert parse_name_status(b"") == ()
    assert parse_name_status(b"Z\0") == (ChangedPath("unknown"),)
    assert parse_name_status(b"M\0bad\\path\0") == (ChangedPath("unknown"),)


@pytest.mark.parametrize(
    ("base", "head", "response", "words"),
    [
        ("not-a-sha", "a" * 40, None, "immutable"),
        ("a" * 40, "b" * 40, OSError(), "read the changed"),
        ("a" * 40, "b" * 40, CompletedProcess([], 2), "compare"),
        ("a" * 40, "b" * 40, CompletedProcess([], 0, b"M\0no-end"), "incomplete"),
    ],
)
def test_git_diff_falls_back_without_shell_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base: str,
    head: str,
    response: object,
    words: str,
) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> CompletedProcess[bytes]:
        if isinstance(response, OSError):
            raise response
        assert isinstance(response, CompletedProcess)
        return response

    monkeypatch.setattr(github.subprocess, "run", fake_run)
    observed = git_changes(tmp_path, base, head)
    assert observed.fallback_reason is not None and words in observed.fallback_reason


def test_git_diff_success_uses_a_list_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_args: list[object] = []

    def fake_run(*args: object, **_kwargs: object) -> CompletedProcess[bytes]:
        observed_args.extend(args)
        return CompletedProcess([], 0, b"A\0skills/review/SKILL.md\0")

    monkeypatch.setattr(github.subprocess, "run", fake_run)
    assert git_changes(tmp_path, "a" * 40, "b" * 40).changes[0].kind == "added"
    assert isinstance(observed_args[0], list)


@pytest.mark.parametrize(
    "payload",
    [b"M\0skills/a", b"M\0../escape\0", b"R100\0old\0"],
)
def test_parse_git_name_status_rejects_incomplete_or_unsafe_records(
    payload: bytes,
) -> None:
    if payload == b"M\0../escape\0":
        assert parse_name_status(payload) == (ChangedPath("unknown"),)
    else:
        with pytest.raises(GitDiffError):
            parse_name_status(payload)


@pytest.mark.parametrize(
    ("change", "scope", "count"),
    [
        (ChangedPath("modified", None, PurePosixPath("README.md")), "none", 0),
        (
            ChangedPath(
                "modified", None, PurePosixPath("skills/review/evals/edge.eval.md")
            ),
            "cases",
            1,
        ),
        (
            ChangedPath("modified", None, PurePosixPath("skills/review/SKILL.md")),
            "cases",
            2,
        ),
        (
            ChangedPath("deleted", PurePosixPath("skills/review/evals/edge.eval.md")),
            "all",
            4,
        ),
        (ChangedPath("unknown"), "all", 4),
        (ChangedPath("modified", None, PurePosixPath("pyproject.toml")), "all", 4),
    ],
)
def test_changed_selection_is_narrow_only_when_safe(
    tmp_path: Path, change: ChangedPath, scope: str, count: int
) -> None:
    report = validate_repository(make_repository(tmp_path / "repository"))
    selection = select_changed(report, (change,))
    assert selection.scope == scope
    assert len(selection.cases) == count


def test_changed_selection_unions_skills_and_treats_workflow_as_core(
    tmp_path: Path,
) -> None:
    report = validate_repository(make_repository(tmp_path / "repository"))
    selected = select_changed(
        report,
        (
            ChangedPath("modified", None, PurePosixPath("skills/review/scripts/a.py")),
            ChangedPath(
                "modified", None, PurePosixPath("skills/overview/assets/a.txt")
            ),
        ),
    )
    assert selected.scope == "cases"
    assert len(selected.cases) == 4
    assert (
        select_changed(
            report,
            (ChangedPath("modified", None, PurePosixPath(".github/workflows/x.yml")),),
        ).scope
        == "all"
    )


def test_changed_selector_handles_empty_missing_config_and_unmapped_path(
    tmp_path: Path,
) -> None:
    report = validate_repository(make_repository(tmp_path / "repository"))
    assert select_changed(report, ()).scope == "none"
    assert select_changed(report, (ChangedPath("added", None, None),)).scope == "all"
    invalid = validate_repository(tmp_path / "no-config")
    assert select_changed(invalid, (ChangedPath("unknown"),)).scope == "all"
    assert changes_from_iterable(iter((ChangedPath("unknown"),))) == (
        ChangedPath("unknown"),
    )
    assert github._relative(report.repository_root, Path("/not/inside")) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a" * 40, True),
        ("refs/pull/123/head", True),
        ("refs/pull/01/head", False),
        ("branch-name", False),
        ("refs/pull/x/head", False),
    ],
)
def test_reviewed_ref_validation_is_deliberately_narrow(
    value: str, expected: bool
) -> None:
    assert valid_reviewed_ref(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (DEFAULT_ACTION_REF, True),
        ("owner/repo@v1.2.3", True),
        ("owner/repo@branch name", False),
        ("owner/repo", False),
        ("owner/repo@v1\nrun", False),
    ],
)
def test_action_ref_validation(value: str, expected: bool) -> None:
    assert valid_action_ref(value) is expected


def test_generated_workflow_has_visible_safe_boundaries() -> None:
    workflow = render_workflow("owner/repo@v1", "MODEL_KEY").decode()
    parsed = yaml.safe_load(workflow)
    assert isinstance(parsed, dict)
    assert "pull_request_target" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "fetch-depth: 0" in workflow
    assert "author_association == 'OWNER'" in workflow
    assert "head.repo.full_name == github.repository" in workflow
    assert "MODEL_KEY: ${{ secrets.MODEL_KEY }}" in workflow
    assert "release-verify" in workflow and "schedule:" not in workflow
    assert "workflow_dispatch" in workflow and "reviewed_ref" in workflow
    assert "run_repository_checks" in workflow
    assert "trusted-checks" in workflow
    assert "run-commands: false" in workflow
    validate_steps = parsed["jobs"]["validate"]["steps"]
    validate_action = next(
        step for step in validate_steps if step.get("uses") == "owner/repo@v1"
    )
    assert validate_action["with"]["run-commands"] is False
    assert validate_action["with"]["command-notice"] is True
    live_action = next(
        step
        for step in parsed["jobs"]["live-eval"]["steps"]
        if step.get("uses") == "owner/repo@v1"
    )
    assert live_action["with"]["run-commands"] is False
    assert live_action["with"]["command-notice"] is True
    trusted_live_action = next(
        step
        for step in parsed["jobs"]["trusted-live-eval"]["steps"]
        if step.get("uses") == "owner/repo@v1"
        and step.get("with", {}).get("mode") == "eval"
    )
    assert trusted_live_action["with"]["run-commands"] is False
    trusted_checks = parsed["jobs"]["trusted-checks"]
    assert "inputs.run_repository_checks" in trusted_checks["if"]
    trusted_check_action = next(
        step
        for step in trusted_checks["steps"]
        if step.get("uses") == "owner/repo@v1"
        and step.get("with", {}).get("mode") == "validate"
    )
    assert trusted_check_action["with"]["run-commands"] is True
    assert "SKILLROLL_API_KEY" not in trusted_checks.get("env", {})
    release_steps = parsed["jobs"]["release-verify"]["steps"]
    release_action = next(step for step in release_steps if step.get("id") == "release")
    assert release_action["with"]["run-commands"] is False


def test_init_adds_workflow_only_when_requested_and_never_replaces_it(
    tmp_path: Path,
) -> None:
    repository = make_repository(tmp_path / "repository")
    result = initialize(repo=str(repository), github_workflow=True)
    target = repository / ".github/workflows/skillroll.yml"
    assert result.outcome is Outcome.PASS and target.is_file()
    assert (
        initialize(repo=str(repository), github_workflow=True).outcome is Outcome.ERROR
    )
    assert "MODEL_KEY" not in target.read_text(encoding="utf-8")
    assert "SKILLROLL_API_KEY" in target.read_text(encoding="utf-8")


def test_init_workflow_rejects_bad_refs_and_can_join_first_setup(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    skill = repository / "skills" / "review"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Review\n", encoding="utf-8")
    bad = initialize(
        repo=str(repository),
        skills_path="skills",
        action_ref="not a reference",
    )
    assert bad.outcome is Outcome.ERROR
    combined = initialize(
        repo=str(repository),
        skills_path="skills",
        github_workflow=True,
        action_ref="owner/repo@v1",
    )
    assert combined.outcome is Outcome.PASS
    assert (repository / ".github/workflows/skillroll.yml").is_file()
    existing = initialize(
        repo=str(repository), github_workflow=True, action_ref="not a reference"
    )
    assert existing.outcome is Outcome.ERROR


def test_init_rejects_bad_workflow_ref_before_first_setup_write(tmp_path: Path) -> None:
    repository = tmp_path / "unconfigured"
    skill = repository / "skills" / "review"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Review\n", encoding="utf-8")
    result = initialize(
        repo=str(repository),
        skills_path="skills",
        github_workflow=True,
        action_ref="not a reference",
    )
    assert result.outcome is Outcome.ERROR
    assert not (repository / "skillroll.toml").exists()


def test_github_summary_annotations_and_step_files_are_safe(tmp_path: Path) -> None:
    result = CommandResult(
        Outcome.INCOMPLETE,
        "Need a check",
        (
            Diagnostic(
                "SCV1001",
                "line one\nline two",
                location=SourceLocation("skills/review/evals/a.eval.md", 3),
            ),
            Diagnostic("SCV1002", "ignored"),
        ),
    )
    summary = render_summary(
        result, fork_notice=True, command_notice=True, artifact_uploaded=True
    )
    assert "Model evaluation was intentionally skipped" in summary
    assert "Repository commands are off" in summary
    assert "separate and does not receive the inference key" in summary
    assert "custom command" not in summary.lower()
    annotations = annotation_lines(result, maximum=1)
    assert len(annotations) == 1 and "%0A" in annotations[0]
    summary_path, output_path = tmp_path / "summary", tmp_path / "output"
    assert write_github_report(
        result,
        environment={
            "GITHUB_STEP_SUMMARY": str(summary_path),
            "GITHUB_OUTPUT": str(output_path),
        },
    )
    assert "INCOMPLETE" in summary_path.read_text(encoding="utf-8")
    assert "outcome=INCOMPLETE" in output_path.read_text(encoding="utf-8")


def test_github_reporting_covers_optional_fields_and_invalid_paths() -> None:
    result = CommandResult(
        Outcome.FAIL,
        "broken",
        (
            Diagnostic(
                "SCX",
                "problem",
                affected="review",
                next_action="Fix it.",
                location=SourceLocation("../outside", None),
            ),
        ),
    )
    summary = render_summary(result, github.ChangedSelection("all", (), "complete"))
    assert "Affected" in summary and "Next" in summary and "Selection" in summary
    assert "file=" not in annotation_lines(result)[0]
    assert write_github_report(result, environment={})


def test_github_report_emits_artifact_path_and_annotation_without_line(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    result = CommandResult(
        Outcome.FAIL,
        "broken",
        (
            Diagnostic(
                "SCX",
                "problem",
                location=SourceLocation("skills/review/SKILL.md"),
            ),
        ),
        {"cases": ({"artifact_directory": ".skillroll/runs/one"},)},
    )
    annotation = annotation_lines(result)[0]
    assert "file=skills/review/SKILL.md" in annotation and ",line=" not in annotation
    write_github_report(result, environment={"GITHUB_OUTPUT": str(output)})
    assert "artifact-path=.skillroll/runs/one" in output.read_text(encoding="utf-8")
    missing = CommandResult(
        Outcome.PASS,
        "ok",
        data={"cases": ("not-a-case", {"artifact_directory": None})},
    )
    write_github_report(missing, environment={"GITHUB_OUTPUT": str(output)})
    assert "artifact-path=\n" in output.read_text(encoding="utf-8")


def test_private_action_rejects_invalid_scope_before_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert action_main(["--mode", "eval", "--scope", "changed"]) == 3
    assert (
        action_main(
            ["--mode", "eval", "--scope", "all", "--artifact-retention-days", "0"]
        )
        == 3
    )


def test_private_action_validates_ref_before_checkout_or_running_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert (
        action_main(
            [
                "--mode",
                "validate-ref",
                "--scope",
                "all",
                "--reviewed-ref",
                "a" * 40,
            ]
        )
        == 0
    )


def test_private_action_covers_input_and_selection_error_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        github_action._parser().parse_args(["--mode", "not-a-mode", "--scope", "all"])
    assert github_action._error("").outcome is Outcome.ERROR
    assert action_main(["--mode", "not-a-mode", "--scope", "all"]) == 3
    assert (
        action_main(
            [
                "--mode",
                "validate-ref",
                "--scope",
                "skill",
                "--reviewed-ref",
                "a" * 40,
            ]
        )
        == 3
    )
    assert action_main(["--mode", "eval", "--scope", "skill"]) == 3
    assert (
        action_main(
            ["--mode", "eval", "--scope", "skill", "--selection-path", "review"]
        )
        == 3
    )
    assert (
        action_main(
            [
                "--mode",
                "eval",
                "--scope",
                "changed",
                "--base-sha",
                "a" * 40,
                "--head-sha",
                "b" * 40,
            ]
        )
        == 3
    )
    assert (
        action_main(["--mode", "validate", "--scope", "all", "--head-sha", "a" * 40])
        == 3
    )
    assert (
        action_main(
            [
                "--mode",
                "validate-ref",
                "--scope",
                "all",
                "--reviewed-ref",
                "main",
            ]
        )
        == 3
    )


def test_private_action_selects_docs_and_dispatches_validate_or_eval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = make_repository(tmp_path / "repository")
    monkeypatch.chdir(repository)
    monkeypatch.setattr(
        github_action,
        "git_changes",
        lambda *_args: github.GitDiffResult(
            (ChangedPath("modified", None, PurePosixPath("README.md")),)
        ),
    )
    assert (
        action_main(
            [
                "--mode",
                "eval",
                "--scope",
                "changed",
                "--base-sha",
                "a" * 40,
                "--head-sha",
                "b" * 40,
            ]
        )
        == 0
    )
    called: list[str] = []

    def fake_validate(**_kwargs: object) -> CommandResult:
        called.append("validate")
        return CommandResult(Outcome.PASS, "valid")

    def fake_evaluate(**_kwargs: object) -> CommandResult:
        called.append("eval")
        return CommandResult(Outcome.PASS, "evaluated")

    monkeypatch.setattr(github_action.validate, "run", fake_validate)
    monkeypatch.setattr(github_action.evaluate, "run", fake_evaluate)
    assert (
        action_main(
            [
                "--mode",
                "validate",
                "--scope",
                "all",
                "--command-notice",
                "true",
            ]
        )
        == 0
    )
    assert (
        action_main(
            ["--mode", "eval", "--scope", "skill", "--selection-path", "review"]
        )
        == 0
    )
    assert called == ["validate", "eval"]


def test_private_action_handles_invalid_repo_and_diff_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert action_main(["--mode", "eval", "--scope", "all"]) == 3
    repository = make_repository(tmp_path / "repository")
    monkeypatch.chdir(repository)
    monkeypatch.setattr(
        github_action,
        "git_changes",
        lambda *_args: github.GitDiffResult((), "Could not read the safe diff."),
    )
    calls: list[object] = []

    def fake_evaluate(**kwargs: object) -> CommandResult:
        calls.append(kwargs["selected_cases"])
        return CommandResult(Outcome.PASS, "all")

    monkeypatch.setattr(github_action.evaluate, "run", fake_evaluate)
    assert (
        action_main(
            [
                "--mode",
                "eval",
                "--scope",
                "changed",
                "--base-sha",
                "a" * 40,
                "--head-sha",
                "b" * 40,
            ]
        )
        == 0
    )
    assert isinstance(calls[0], tuple) and len(calls[0]) == 4
    assert (
        action_main(
            ["--mode", "eval", "--scope", "skill", "--selection-path", "missing"]
        )
        == 3
    )


def test_private_module_adapter_exits_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "skillroll.github_action")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "github_action",
            "--mode",
            "validate-ref",
            "--scope",
            "all",
            "--reviewed-ref",
            "a" * 40,
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("skillroll.github_action", run_name="__main__")
    assert exit_info.value.code == 0


def test_composite_action_declares_no_secret_input_or_unsafe_trigger() -> None:
    action = (Path(__file__).parents[1] / "action.yml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(action)
    assert isinstance(parsed, dict)
    assert "secrets." not in action
    assert "pull_request_target" not in action
    assert "javascript" not in action.lower()
    assert "uv run --project" in action
    assert "actions/upload-artifact@v4" in action
    assert "command-notice" in parsed["inputs"]
    assert "--command-notice" in action
