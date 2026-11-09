"""Offline command selection and preparation/error diagnostics."""

from dataclasses import replace

import pytest
from test_comparison_integration import repository

from skillroll.artifacts.store import ArtifactError
from skillroll.commands import compare
from skillroll.outcomes import Outcome


@pytest.mark.parametrize(
    "error",
    [
        KeyboardInterrupt(),
        ArtifactError("disk"),
        OSError("read"),
        ValueError("changed"),
    ],
)
def test_preparation_failures_are_diagnostics(tmp_path, monkeypatch, error):
    repository(tmp_path, rules=True)

    def fail(*args):
        raise error

    monkeypatch.setattr(compare, "_current_input_hashes", fail)
    result = compare.run(repo=str(tmp_path), executor_models=("a", "b"))
    assert result.outcome is Outcome.ERROR
    assert result.diagnostics
    assert not (tmp_path / ".skillroll").exists()


@pytest.mark.parametrize("all_cases", [False, True])
def test_current_directory_selection_and_empty_scope(tmp_path, monkeypatch, all_cases):
    repository(tmp_path, rules=True)
    report = compare.validate_repository(tmp_path)
    monkeypatch.setattr(compare, "current_directory", lambda: tmp_path)
    monkeypatch.setattr(
        compare, "validate_repository", lambda *a, **kw: replace(report, cases=())
    )
    result = compare.run(executor_models=("a", "b"), all_cases=all_cases)
    assert result.outcome is Outcome.ERROR
    assert "No valid eval" in result.diagnostics[0].summary


@pytest.mark.parametrize(
    "detail",
    [
        None,
        {"summary": "provider failed", "stage": "execution", "details": ["safe"]},
        {"summary": "failed", "details": ()},
    ],
)
def test_attempt_errors_have_actionable_command_diagnostics(
    tmp_path, monkeypatch, detail
):
    repository(tmp_path, rules=True)

    async def execute(*args, **kw):
        return (
            Outcome.ERROR,
            {"attempts": [{"status": "PASS"}, {"status": "ERROR", "failure": detail}]},
            "complete",
            None,
        )

    monkeypatch.setattr(compare, "_execute_comparison", execute)
    result = compare.run(repo=str(tmp_path), executor_models=("a", "b"))
    assert result.outcome is Outcome.ERROR
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "SCC1001"


def test_missing_candidates_and_inference_settings_fail_without_model_calls(tmp_path):
    assert compare.run(executor_models=()).outcome is Outcome.ERROR
    repository(tmp_path, rules=True)
    (tmp_path / "skillroll.toml").write_text(
        'schema_version = 1\nskills_path = "skills"\n'
    )
    result = compare.run(repo=str(tmp_path), executor_models=("a", "b"), environment={})
    assert result.outcome is Outcome.ERROR
    assert result.diagnostics


def test_invalid_repository_is_rejected_before_creating_evidence(tmp_path):
    result = compare.run(repo=str(tmp_path), executor_models=("a", "b"))
    assert result.outcome is Outcome.ERROR
    assert not (tmp_path / ".skillroll").exists()
