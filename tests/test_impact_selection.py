"""Explainable changed-case selection without inference or repository code."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path, PurePosixPath
from subprocess import CompletedProcess

import pytest
import yaml
from conftest import ROOT
from test_phase6_github import make_repository

from skillroll import github_action
from skillroll.github import ChangedPath, select_changed
from skillroll.impact import ImpactPolicy, load_impact_policy
from skillroll.validation import validate_repository


def change(path: str, kind: str = "modified") -> ChangedPath:
    assert kind in {"added", "modified"}
    return ChangedPath(kind, None, PurePosixPath(path))  # type: ignore[arg-type]


def test_mixed_diff_keeps_the_selected_case(tmp_path: Path) -> None:
    report = validate_repository(make_repository(tmp_path))
    policy = ImpactPolicy(offline=("tests/**", ".github/workflows/release.yml"))
    selection = select_changed(
        report,
        (
            change("skills/review/evals/ordinary.eval.md"),
            change("tests/test_cli.py"),
            change(".github/workflows/release.yml"),
            change("README.md"),
        ),
        policy,
    )
    assert len(selection.cases) == 1 and selection.scope == "cases"
    assert "Offline-only: tests/test_cli.py" in selection.reason
    assert "Documentation-only: README.md" in selection.reason
    assert "ordinary.eval.md" in selection.cases[0].identity.as_posix()


def test_renames_union_both_skills_and_deletions_select_remaining_cases(
    tmp_path: Path,
) -> None:
    report = validate_repository(make_repository(tmp_path))
    renamed = ChangedPath(
        "renamed",
        PurePosixPath("skills/review/references/a.md"),
        PurePosixPath("skills/overview/references/b.md"),
    )
    assert len(select_changed(report, (renamed,)).cases) == 4
    case = tmp_path / "skills/review/evals/edge.eval.md"
    case.unlink()
    report = validate_repository(tmp_path)
    result = select_changed(
        report,
        (ChangedPath("deleted", PurePosixPath("skills/review/evals/edge.eval.md")),),
    )
    assert result.scope == "cases" and len(result.cases) == 1
    assert result.cases[0].skill.identity.as_posix() == "review"


def test_unknown_paths_and_shared_inputs_stay_conservative(tmp_path: Path) -> None:
    report = validate_repository(make_repository(tmp_path))
    policy = ImpactPolicy(offline=("**",), full=("shared/**",))
    for path in ("skillroll.toml", "action.yml", "shared/prompt.md"):
        assert select_changed(report, (change(path),), policy).scope == "all"
    assert select_changed(report, (change("unknown.py"),)).scope == "all"
    assert select_changed(report, (change("docs/a.md"),)).scope == "none"
    assert select_changed(report, (ChangedPath("unknown"),)).scope == "all"
    assert select_changed(report, (ChangedPath("added"),)).scope == "all"
    assert (
        select_changed(replace(report, config=None), (change("README.md"),)).scope
        == "all"
    )
    assert select_changed(report, ()).scope == "none"


def test_declared_dependencies_expand_transitively_and_handle_cycles(
    tmp_path: Path,
) -> None:
    report = validate_repository(make_repository(tmp_path))
    policy = ImpactPolicy(
        dependencies=(
            ("skills/review/**", ("skills/overview/**",)),
            ("skills/overview/**", ("skills/review/**",)),
        )
    )
    result = select_changed(report, (change("skills/review/SKILL.md"),), policy)
    assert len(result.cases) == 4
    assert "Dependency:" in result.reason
    result = select_changed(report, (change("skills/review/plugin.json"),), policy)
    assert len(result.cases) == 4
    broken = ImpactPolicy(dependencies=(("skills/review/**", ("missing/**",)),))
    assert (
        select_changed(report, (change("skills/review/SKILL.md"),), broken).scope
        == "all"
    )


def test_removed_dependency_source_still_selects_dependents(tmp_path: Path) -> None:
    report = validate_repository(make_repository(tmp_path))
    policy = ImpactPolicy(dependencies=(("removed/**", ("skills/overview/**",)),))
    result = select_changed(
        report, (ChangedPath("deleted", PurePosixPath("removed/script.py")),), policy
    )
    assert result.scope == "cases" and len(result.cases) == 2


def test_repository_policy_matches_dependency_manifests_and_source_boundaries() -> None:
    policy = load_impact_policy(ROOT, ".github/skillroll-impact.toml")
    report = validate_repository(ROOT)
    assert (
        select_changed(report, (change("src/skillroll/release.py"),), policy).scope
        == "none"
    )
    assert (
        select_changed(
            report, (change("src/skillroll/commands/initialize.py"),), policy
        ).scope
        == "none"
    )
    for path in (
        "src/skillroll/runtime/agents_sdk.py",
        "src/skillroll/markdown.py",
        "plugins/harness-prompts/skills/executor-prompt/references/system.md",
    ):
        assert select_changed(report, (change(path),), policy).scope == "all"
    selected = select_changed(
        report, (change("plugins/flow-runner/skills/flow-runner/SKILL.md"),), policy
    )
    assert selected.scope == "cases"
    assert any("change-review-flow" in c.identity.as_posix() for c in selected.cases)
    assert any(
        "blind-skillroll-evaluation" in c.identity.as_posix() for c in selected.cases
    )
    sources = dict(policy.dependencies)
    for plugin in ROOT.glob("plugins/*/.claude-plugin/plugin.json"):
        value = json.loads(plugin.read_text())
        if any(
            dep.get("name") == "flow-runner" for dep in value.get("dependencies", [])
        ):
            assert f"plugins/{value['name']}/**" in sources["plugins/flow-runner/**"]


@pytest.mark.parametrize(
    "relative", ["", "../outside.toml", "/absolute", r"bad\path", "C:outside"]
)
def test_impact_policy_rejects_non_relative_paths(
    tmp_path: Path, relative: str
) -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        load_impact_policy(tmp_path, relative)


@pytest.mark.parametrize(
    "text",
    [
        "invalid = [",
        "schema_version = 2\noffline=[]\nfull=[]\ndependencies=[]",
        "schema_version = true\noffline=[]\nfull=[]\ndependencies=[]",
        "schema_version = 1\noffline=[]\nfull=[]\ndependencies=[]\nextra=1",
        'schema_version = 1\noffline=[]\nfull=[]\ndependencies="bad"',
        "schema_version = 1\noffline=[]\nfull=[]\ndependencies=[1]",
        'schema_version = 1\noffline="bad"\nfull=[]\ndependencies=[]',
    ],
)
def test_impact_policy_rejects_malformed_documents(tmp_path: Path, text: str) -> None:
    (tmp_path / "policy.toml").write_text(text)
    with pytest.raises(ValueError):
        load_impact_policy(tmp_path, "policy.toml")


@pytest.mark.parametrize(
    "pattern", [1, "", "/outside", r"bad\path", "../outside", "a\n", "C:drive"]
)
def test_impact_policy_rejects_unsafe_globs(tmp_path: Path, pattern: object) -> None:
    text = (
        "schema_version=1\noffline=[]\nfull=[]\n[[dependencies]]\n"
        f"changed={json.dumps(pattern)}\naffected=[]\n"
    )
    (tmp_path / "policy.toml").write_text(text)
    with pytest.raises(ValueError):
        load_impact_policy(tmp_path, "policy.toml")


def test_policy_read_failures_and_safe_regular_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="read as TOML"):
        load_impact_policy(tmp_path, "missing.toml")
    target = tmp_path / "policy.toml"
    target.write_text(
        'schema_version=1\noffline=["tests/**"]\nfull=[]\ndependencies=[]'
    )
    assert load_impact_policy(tmp_path, "policy.toml").offline == ("tests/**",)
    link = tmp_path / "linked.toml"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ValueError, match="symlinks"):
        load_impact_policy(tmp_path, "linked.toml")


def test_action_plan_uses_policy_without_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_repository(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "policy.toml").write_text(
        'schema_version=1\noffline=["tests/**"]\nfull=[]\ndependencies=[]'
    )
    monkeypatch.setattr(
        "skillroll.github.subprocess.run",
        lambda *a, **k: CompletedProcess([], 0, b"M\0tests/test.py\0"),
    )
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert (
        github_action.main(
            [
                "--mode",
                "plan",
                "--scope",
                "changed",
                "--base-sha",
                "a" * 40,
                "--head-sha",
                "b" * 40,
                "--impact-policy",
                "policy.toml",
            ]
        )
        == 0
    )
    assert "selected-case-count=0" in output.read_text()
    assert (
        github_action.main(
            [
                "--mode",
                "plan",
                "--scope",
                "changed",
                "--base-sha",
                "a" * 40,
                "--head-sha",
                "b" * 40,
                "--impact-policy",
                "missing.toml",
            ]
        )
        == 3
    )
    assert (
        github_action.main(
            ["--mode", "plan", "--scope", "all", "--impact-policy", "policy.toml"]
        )
        == 3
    )


def test_workflow_plans_and_runs_the_same_candidate_harness() -> None:
    data = yaml.safe_load((ROOT / ".github/workflows/skillroll.yml").read_text())
    jobs = data["jobs"]
    plan = next(s for s in jobs["validate"]["steps"] if s.get("id") == "plan")
    live = next(s for s in jobs["live-eval"]["steps"] if s.get("id") == "live")
    assert plan["uses"] == live["uses"] == "./"
    assert plan["with"]["impact-policy"] == live["with"]["impact-policy"]
    assert plan["with"]["scope"] == live["with"]["scope"] == "changed"
    assert (
        live["with"]["concurrency"] == "${{ vars.SKILLROLL_EVAL_CONCURRENCY || '1' }}"
    )
    assert live["with"]["run-commands"] is False
    assert "selected-case-count != '0'" in jobs["live-eval"]["if"]
    assert "author_association == 'OWNER'" in jobs["live-eval"]["if"]
    assert jobs["live-eval"]["environment"] == "skillroll-eval"


def test_plugin_manifest_expands_own_cases_and_reverse_dependencies() -> None:
    policy = load_impact_policy(ROOT, ".github/skillroll-impact.toml")
    result = select_changed(
        validate_repository(ROOT),
        (change("plugins/flow-runner/.claude-plugin/plugin.json"),),
        policy,
    )
    assert result.scope == "cases"
    assert any(c.identity.as_posix().startswith("flow-runner/") for c in result.cases)
    assert any("change-review-flow" in c.identity.as_posix() for c in result.cases)


def test_policy_dependency_sources_cannot_be_ambiguous(tmp_path: Path) -> None:
    (tmp_path / "policy.toml").write_text(
        "schema_version=1\noffline=[]\nfull=[]\n"
        '[[dependencies]]\nchanged="a/**"\naffected=["skills/review/**"]\n'
        '[[dependencies]]\nchanged="a/**"\naffected=["skills/review/**"]\n'
    )
    with pytest.raises(ValueError, match="unique"):
        load_impact_policy(tmp_path, "policy.toml")


@pytest.mark.parametrize("concurrency", ["0", "17"])
def test_action_rejects_invalid_concurrency_before_selection(concurrency: str) -> None:
    assert (
        github_action.main(
            ["--mode", "plan", "--scope", "all", "--concurrency", concurrency]
        )
        == 3
    )


def test_policy_edit_selects_every_case_even_with_exemption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_repository(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "policy.md").write_text(
        'schema_version=1\noffline=["**"]\nfull=[]\ndependencies=[]'
    )
    monkeypatch.setattr(
        "skillroll.github.subprocess.run",
        lambda *a, **k: CompletedProcess([], 0, b"M\0policy.md\0"),
    )
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert (
        github_action.main(
            [
                "--mode",
                "plan",
                "--scope",
                "changed",
                "--base-sha",
                "a" * 40,
                "--head-sha",
                "b" * 40,
                "--impact-policy",
                "policy.md",
            ]
        )
        == 0
    )
    assert "selected-case-count=4" in output.read_text()


@pytest.mark.parametrize(
    "source",
    ["skills/review/SKILL.md", "skills/review/scripts/**", "skills/r*/references/*.md"],
)
def test_transitive_dependencies_cover_the_skill_surface_not_only_eval_paths(
    tmp_path: Path,
    source: str,
) -> None:
    report = validate_repository(make_repository(tmp_path))
    policy = ImpactPolicy(
        dependencies=(
            ("shared/**", ("skills/review/**",)),
            (source, ("skills/overview/**",)),
        )
    )
    result = select_changed(report, (change("shared/api.py"),), policy)
    assert result.scope == "cases" and len(result.cases) == 4
    assert f"Dependency: {source}" in result.reason


def test_empty_dependency_targets_cannot_hide_unknown_changes(tmp_path: Path) -> None:
    (tmp_path / "policy.toml").write_text(
        "schema_version=1\noffline=[]\nfull=[]\n"
        '[[dependencies]]\nchanged="shared/**"\naffected=[]\n'
    )
    with pytest.raises(ValueError, match="at least one"):
        load_impact_policy(tmp_path, "policy.toml")


def test_single_eval_does_not_expand_broad_skill_dependencies(tmp_path: Path) -> None:
    report = validate_repository(make_repository(tmp_path))
    path = "skills/review/evals/ordinary.eval.md"
    broad = ImpactPolicy(dependencies=(("skills/review/**", ("skills/overview/**",)),))
    assert len(select_changed(report, (change(path),), broad).cases) == 1
    explicit = ImpactPolicy(dependencies=((path, ("skills/overview/**",)),))
    assert len(select_changed(report, (change(path),), explicit).cases) == 3


def test_repository_release_helpers_stay_offline_in_mixed_diffs() -> None:
    policy = load_impact_policy(ROOT, ".github/skillroll-impact.toml")
    report = validate_repository(ROOT)
    paths = (
        ".github/workflows/new-release.yml",
        "tools/prepare_release.py",
        "tools/finalize_release.py",
        "tools/verify_prepared_release.py",
        "tests/test_release.py",
        "docs/releasing.md",
    )
    changes = tuple(change(path) for path in paths)
    assert select_changed(report, changes, policy).scope == "none"
    selected_case = report.cases[0]
    case_path = selected_case.path.relative_to(ROOT).as_posix()
    mixed = select_changed(report, (*changes, change(case_path)), policy)
    assert mixed.scope == "cases" and mixed.cases == (selected_case,)
    for unknown in ("tools/other_release.py", ".github/workflows/other-release.yml"):
        assert (
            select_changed(report, (*changes, change(unknown)), policy).scope == "all"
        )


def test_repository_concurrency_defaults_are_conservative() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/skillroll.yml").read_text())
    dispatch = workflow[True]["workflow_dispatch"]["inputs"]
    assert dispatch["concurrency"]["default"] == 1
    steps = workflow["jobs"]["live-eval"]["steps"]
    live = next(step for step in steps if step.get("id") == "live")
    assert (
        live["with"]["concurrency"] == "${{ vars.SKILLROLL_EVAL_CONCURRENCY || '1' }}"
    )
