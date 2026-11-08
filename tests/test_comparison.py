"""Runner durability, preflight, and drift behavior without live inference."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_comparison_integration import repository
from test_phase4_verdicts import ScriptedTransport, preflight_responses

from skillroll.artifacts.store import ArtifactError, ArtifactStore
from skillroll.commands import compare
from skillroll.diagnostics import CommandResult
from skillroll.inference.profile import InferenceFailure, InferenceFailureKind
from skillroll.inference.transport import ChatResponse, ModelUsage
from skillroll.judge import JudgeResult
from skillroll.outcomes import Outcome
from skillroll.runtime.execution import ExecutionAttempt, ExecutionResult
from skillroll.verdicts import CaseResult


def _artifact_directory(root: Path, result: CommandResult) -> Path:
    return root / result.data["artifact_directory"]


def _preflight_values(model: str) -> list[ChatResponse]:
    return [
        replace(item, model=model, usage=ModelUsage(12, 4, 16))
        for item in preflight_responses()[:2]
    ]


def _summary(root: Path, result: CommandResult) -> dict[str, object]:
    return json.loads(
        (_artifact_directory(root, result) / "comparison.json").read_text()
    )


async def _successful_evaluation(config, cases, **kwargs):
    evaluator, _ = kwargs["_resolved"]
    result = CaseResult(
        case=cases[0],
        outcome="PASS",
        execution=ExecutionResult("done", 1, (ModelUsage(10, 2, 12),), ()),
        judge=JudgeResult(
            "PASS", "criteria met", (), evaluator.model, ModelUsage(2, 1, 3)
        ),
        assertions=(),
        checks=(),
        failure=None,
        artifact_directory=None,
        timings={
            "execution_seconds": 0.2,
            "world_seconds": 0.0,
            "judge_seconds": 0.1,
            "executor_seconds": 0.2,
        },
    )
    return (result,)


def _run_with_fake_evaluation(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    evaluation,
    *,
    transport_factory=None,
    store_factory=None,
) -> CommandResult:
    monkeypatch.setattr(compare, "evaluate_repository", evaluation)
    return compare.run(
        repo=str(root),
        executor_models=("evaluator", "candidate"),
        samples=1,
        seed=7,
        environment={"KEY": "private-key"},
        transport_factory=(
            _preflight_factory() if transport_factory is None else transport_factory
        ),
        store_factory=compare._store if store_factory is None else store_factory,
    )


def _preflight_factory():
    return lambda profile: ScriptedTransport(_preflight_values(profile.model))


def test_input_drift_during_preflight_stops_before_any_case_attempt(
    tmp_path: Path,
) -> None:
    repository(tmp_path, rules=True)
    case_path = tmp_path / "skills/review/evals/basic.eval.md"
    transports: list[ScriptedTransport] = []
    executed: list[str] = []

    class ChangingTransport(ScriptedTransport):
        async def complete(self, request):
            response = await super().complete(request)
            if len(self.requests) == 2 and request.model == "evaluator":
                case_path.write_text(
                    case_path.read_text() + "\nChanged during preflight."
                )
            return response

    def transport_factory(profile):
        transport = ChangingTransport(_preflight_values(profile.model))
        transports.append(transport)
        return transport

    def executor_factory(profile):
        class Executor:
            async def execute(self, request, world_action):
                executed.append(profile.model)
                return ExecutionAttempt(ExecutionResult("done", 1, (), ()), None)

        return Executor()

    result = compare.run(
        repo=str(tmp_path),
        executor_models=("evaluator", "candidate"),
        samples=1,
        environment={"KEY": "private-key"},
        transport_factory=transport_factory,
        executor_factory=executor_factory,
    )

    comparison = _summary(tmp_path, result)
    assert result.outcome is Outcome.ERROR
    assert executed == []
    assert len(transports) == 2
    assert all(item.closed for item in transports)
    assert comparison["failure"]["stage"] == "input_verification"
    assert [item["status"] for item in comparison["attempts"]] == [
        "NOT_RUN",
        "NOT_RUN",
    ]
    assert set(comparison["preflight"]["models"]) == {"evaluator", "candidate"}


def test_preflight_failure_records_reason_and_does_not_fallback_to_another_executor(
    tmp_path: Path,
) -> None:
    repository(tmp_path, rules=True)
    transports: dict[str, ScriptedTransport] = {}
    calls: list[str] = []

    def transport_factory(profile):
        calls.append(profile.model)
        values = (
            _preflight_values(profile.model)
            if profile.model != "candidate"
            else [ChatResponse("not a tool call", (), profile.model, None)]
        )
        transport = ScriptedTransport(values)
        transports[profile.model] = transport
        return transport

    result = compare.run(
        repo=str(tmp_path),
        executor_models=("candidate", "candidate-two"),
        samples=1,
        environment={"KEY": "private-key"},
        transport_factory=transport_factory,
    )

    comparison = _summary(tmp_path, result)
    assert result.outcome is Outcome.ERROR
    assert calls == ["evaluator", "candidate"]
    assert all(item.closed for item in transports.values())
    assert comparison["preflight"]["models"]["candidate"]["status"] == "failed"
    assert "candidate-two" not in comparison["preflight"]["models"]
    assert all(item["status"] == "NOT_RUN" for item in comparison["attempts"])


def test_preflight_cancellation_is_checkpointed_and_transport_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository(tmp_path, rules=True)
    transports: list[ScriptedTransport] = []

    def transport_factory(profile):
        transport = ScriptedTransport(_preflight_values(profile.model))
        transports.append(transport)
        return transport

    async def cancelled_preflight(profile, transport):
        raise asyncio.CancelledError

    monkeypatch.setattr(compare, "run_preflight", cancelled_preflight)
    result = compare.run(
        repo=str(tmp_path),
        executor_models=("evaluator", "candidate"),
        samples=1,
        environment={"KEY": "private-key"},
        transport_factory=transport_factory,
    )

    comparison = _summary(tmp_path, result)
    assert result.outcome is Outcome.ERROR
    assert len(transports) == 1 and transports[0].closed
    assert (
        comparison["preflight"]["models"]["evaluator"]["failure"]["kind"] == "cancelled"
    )
    assert all(item["status"] == "NOT_RUN" for item in comparison["attempts"])


def test_attempt_is_checkpointed_before_executor_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository(tmp_path, rules=True)
    (tmp_path / "skills/review/SKILL.md").write_text("Write an overview.")
    evaluator_values = _preflight_values("evaluator") + [
        replace(preflight_responses()[3], model="evaluator") for _ in range(2)
    ]
    evaluation_errors: list[str] = []
    original_evaluate = compare.evaluate_repository

    async def traced_evaluate(*args, **kwargs):
        try:
            return await original_evaluate(*args, **kwargs)
        except Exception as error:
            evaluation_errors.append(repr(error))
            raise

    monkeypatch.setattr(compare, "evaluate_repository", traced_evaluate)

    def transport_factory(profile):
        values = (
            evaluator_values
            if profile.model == "evaluator"
            else _preflight_values(profile.model)
        )
        return ScriptedTransport(values)

    def executor_factory(profile):
        artifact = next((tmp_path / ".skillroll/comparisons").glob("*/comparison.json"))
        rows = json.loads(artifact.read_text())["attempts"]
        started = [row for row in rows if row.get("status") == "INCOMPLETE"]
        assert len(started) == 1
        assert started[0]["started"] is True
        assert started[0]["executor_model"] == profile.model

        class Executor:
            async def execute(self, request, world_action):
                await world_action("Write", {"path": "overview.md"})
                return ExecutionAttempt(
                    ExecutionResult(
                        "overview written", 1, (ModelUsage(100, 50, 150),), ()
                    ),
                    None,
                )

        return Executor()

    result = compare.run(
        repo=str(tmp_path),
        executor_models=("evaluator", "candidate"),
        samples=1,
        seed=7,
        environment={"KEY": "private-key"},
        transport_factory=transport_factory,
        executor_factory=executor_factory,
    )

    assert result.outcome is Outcome.PASS, evaluation_errors
    comparison = _summary(tmp_path, result)
    assert all(row["started"] is True for row in comparison["attempts"])


def test_input_drift_after_attempt_preserves_run_and_marks_rest_not_run(
    tmp_path: Path,
) -> None:
    repository(tmp_path, rules=True)
    skill_file = tmp_path / "skills/review/SKILL.md"
    evaluator_values = _preflight_values("evaluator") + [
        replace(preflight_responses()[3], model="evaluator")
    ]
    transports: dict[str, ScriptedTransport] = {}

    def transport_factory(profile):
        values = (
            evaluator_values
            if profile.model == "evaluator"
            else _preflight_values(profile.model)
        )
        transport = ScriptedTransport(values)
        transports[profile.model] = transport
        return transport

    def executor_factory(profile):
        class Executor:
            async def execute(self, request, world_action):
                await world_action("Write", {"path": "overview.md"})
                skill_file.write_text("changed after the run started")
                return ExecutionAttempt(
                    ExecutionResult(
                        "overview written", 1, (ModelUsage(10, 2, 12),), ()
                    ),
                    None,
                )

        return Executor()

    result = compare.run(
        repo=str(tmp_path),
        executor_models=("evaluator", "candidate"),
        samples=1,
        seed=7,
        environment={"KEY": "private-key"},
        transport_factory=transport_factory,
        executor_factory=executor_factory,
    )

    comparison = _summary(tmp_path, result)
    assert result.outcome is Outcome.ERROR
    assert len(comparison["attempts"]) == 2
    observed = [item for item in comparison["attempts"] if item.get("started")]
    pending = [item for item in comparison["attempts"] if item["status"] == "NOT_RUN"]
    assert len(observed) == len(pending) == 1
    assert observed[0]["status"] == "ERROR"
    assert observed[0]["case_outcome"] == "PASS"
    assert observed[0]["input_drift"] is True
    assert observed[0]["run_artifact_directory"]


def test_preflight_checkpoint_write_failure_closes_all_transports(
    tmp_path: Path,
) -> None:
    repository(tmp_path, rules=True)
    transports: list[ScriptedTransport] = []

    class FailingStore(ArtifactStore):
        writes = 0

        def write_comparison(self, directory, values):
            self.writes += 1
            if self.writes == 3:
                raise ArtifactError("injected checkpoint failure")
            super().write_comparison(directory, values)

    def store_factory(root, redactor):
        return FailingStore(root, redactor)

    def transport_factory(profile):
        transport = ScriptedTransport(_preflight_values(profile.model))
        transports.append(transport)
        return transport

    result = compare.run(
        repo=str(tmp_path),
        executor_models=("evaluator", "candidate"),
        samples=1,
        environment={"KEY": "private-key"},
        transport_factory=transport_factory,
        store_factory=store_factory,
    )

    assert result.outcome is Outcome.ERROR
    assert len(transports) == 2
    assert all(item.closed for item in transports)
    comparison = _summary(tmp_path, result)
    assert comparison["failure"]["stage"] == "evidence_writing"
    assert set(comparison["preflight"]["models"]) == {"evaluator", "candidate"}


@pytest.mark.parametrize("error", [ValueError("changed"), OSError("read")])
def test_local_input_hash_errors_before_preflight_are_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    repository(tmp_path, rules=True)
    original = compare._current_input_hashes
    calls = 0

    def fail_after_manifest(config, cases):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error
        return original(config, cases)

    monkeypatch.setattr(compare, "_current_input_hashes", fail_after_manifest)
    result = compare.run(
        repo=str(tmp_path),
        executor_models=("evaluator", "candidate"),
        samples=1,
        environment={"KEY": "private-key"},
        transport_factory=_preflight_factory(),
    )

    comparison = _summary(tmp_path, result)
    assert result.outcome is Outcome.ERROR
    assert calls == 2
    assert comparison["failure"]["stage"] == "input_verification"
    assert all(row["status"] == "NOT_RUN" for row in comparison["attempts"])


def test_input_hash_error_after_preflight_retains_preflight_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository(tmp_path, rules=True)
    original = compare._current_input_hashes
    calls = 0
    transports: list[ScriptedTransport] = []

    def fail_after_preflight(config, cases):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ValueError("injected after preflight")
        return original(config, cases)

    def transport_factory(profile):
        transport = ScriptedTransport(_preflight_values(profile.model))
        transports.append(transport)
        return transport

    monkeypatch.setattr(compare, "_current_input_hashes", fail_after_preflight)
    result = compare.run(
        repo=str(tmp_path),
        executor_models=("evaluator", "candidate"),
        samples=1,
        environment={"KEY": "private-key"},
        transport_factory=transport_factory,
    )

    comparison = _summary(tmp_path, result)
    assert result.outcome is Outcome.ERROR
    assert calls == 3
    assert all(transport.closed for transport in transports)
    assert set(comparison["preflight"]["models"]) == {"evaluator", "candidate"}
    assert all(row["status"] == "NOT_RUN" for row in comparison["attempts"])


def test_input_hash_error_before_attempt_keeps_current_slot_unstarted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository(tmp_path, rules=True)
    original = compare._current_input_hashes
    calls = 0

    def fail_before_sample(config, cases):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("injected before sample")
        return original(config, cases)

    monkeypatch.setattr(compare, "_current_input_hashes", fail_before_sample)
    result = compare.run(
        repo=str(tmp_path),
        executor_models=("evaluator", "candidate"),
        samples=1,
        environment={"KEY": "private-key"},
        transport_factory=_preflight_factory(),
    )

    comparison = _summary(tmp_path, result)
    assert result.outcome is Outcome.ERROR
    assert calls == 4
    assert comparison["failure"]["stage"] == "input_verification"
    assert sum(row["status"] == "ERROR" for row in comparison["attempts"]) == 1
    assert sum(row["status"] == "NOT_RUN" for row in comparison["attempts"]) == 1
    assert not any(row.get("started") for row in comparison["attempts"])


def test_input_hash_drift_before_attempt_stops_without_executor_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from skillroll.artifacts.hashes import InputHash

    repository(tmp_path, rules=True)
    original = compare._current_input_hashes
    calls = 0

    def changed_before_sample(config, cases):
        nonlocal calls
        calls += 1
        values = original(config, cases)
        if calls == 4:
            first = values[0]
            return (replace(first, sha256="0" * 64), *values[1:])
        assert all(isinstance(item, InputHash) for item in values)
        return values

    monkeypatch.setattr(compare, "_current_input_hashes", changed_before_sample)
    executions: list[str] = []

    def executor_factory(profile):
        class Executor:
            async def execute(self, request, world_action):
                executions.append(profile.model)
                return ExecutionAttempt(ExecutionResult("done", 1, (), ()), None)

        return Executor()

    result = compare.run(
        repo=str(tmp_path),
        executor_models=("evaluator", "candidate"),
        samples=1,
        environment={"KEY": "private-key"},
        transport_factory=_preflight_factory(),
        executor_factory=executor_factory,
    )

    comparison = _summary(tmp_path, result)
    assert result.outcome is Outcome.ERROR
    assert executions == []
    assert sum(row["status"] == "ERROR" for row in comparison["attempts"]) == 1
    assert sum(row["status"] == "NOT_RUN" for row in comparison["attempts"]) == 1
    assert not any(row.get("started") for row in comparison["attempts"])


def test_input_hash_error_after_attempt_keeps_observed_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository(tmp_path, rules=True)
    original = compare._current_input_hashes
    calls = 0

    def fail_after_sample(config, cases):
        nonlocal calls
        calls += 1
        if calls == 5:
            raise ValueError("injected after sample")
        return original(config, cases)

    monkeypatch.setattr(compare, "_current_input_hashes", fail_after_sample)
    evaluation_errors: list[str] = []

    async def traced_evaluation(*args, **kwargs):
        try:
            return await _successful_evaluation(*args, **kwargs)
        except Exception as error:
            evaluation_errors.append(repr(error))
            raise

    result = _run_with_fake_evaluation(tmp_path, monkeypatch, traced_evaluation)

    comparison = _summary(tmp_path, result)
    observed = [row for row in comparison["attempts"] if row.get("started")]
    assert result.outcome is Outcome.ERROR
    assert len(observed) == 1
    assert observed[0].get("case_outcome") == "PASS", (
        calls,
        comparison,
        evaluation_errors,
    )
    assert observed[0]["status"] == "ERROR"
    assert observed[0]["input_drift"] is True


@pytest.mark.parametrize("mode", ["cancel", "raise", "failure", "empty"])
def test_started_attempt_failures_are_saved_without_retrying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    repository(tmp_path, rules=True)
    calls: list[str] = []

    async def evaluate(config, cases, **kwargs):
        calls.append(kwargs["executor_model"])
        if mode == "cancel":
            raise asyncio.CancelledError
        if mode == "raise":
            raise RuntimeError("injected executor adapter error")
        if mode == "failure":
            return InferenceFailure(
                InferenceFailureKind.UNAUTHORIZED,
                "provider rejected the request",
                stage="execution",
            )
        return ()

    result = _run_with_fake_evaluation(tmp_path, monkeypatch, evaluate)

    comparison = _summary(tmp_path, result)
    assert result.outcome is Outcome.ERROR
    assert len(calls) == 1
    assert sum(row["status"] == "ERROR" for row in comparison["attempts"]) == 1
    assert sum(row["status"] == "NOT_RUN" for row in comparison["attempts"]) == 1
    assert comparison["attempts"][0].get("started") or comparison["attempts"][1].get(
        "started"
    )


def test_outer_cancel_during_preflight_checkpoint_is_saved_and_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository(tmp_path, rules=True)
    original = compare._write_artifacts
    writes = 0
    transports: list[ScriptedTransport] = []

    def cancel_during_preflight(store, directory, manifest, comparison):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise asyncio.CancelledError
        original(store, directory, manifest, comparison)

    def transport_factory(profile):
        transport = ScriptedTransport(_preflight_values(profile.model))
        transports.append(transport)
        return transport

    monkeypatch.setattr(compare, "_write_artifacts", cancel_during_preflight)
    result = compare.run(
        repo=str(tmp_path),
        executor_models=("evaluator", "candidate"),
        samples=1,
        environment={"KEY": "private-key"},
        transport_factory=transport_factory,
    )

    comparison = _summary(tmp_path, result)
    assert result.outcome is Outcome.ERROR
    assert writes == 3
    assert all(transport.closed for transport in transports)
    assert comparison["failure"]["kind"] == "cancelled"
    assert all(row["status"] == "NOT_RUN" for row in comparison["attempts"])


def test_final_comparison_write_error_returns_error_without_retrying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository(tmp_path, rules=True)

    class FailingFinalStore(ArtifactStore):
        writes = 0

        def write_comparison(self, directory, values):
            self.writes += 1
            if self.writes == 9:
                raise ArtifactError("injected final write error")
            super().write_comparison(directory, values)

    result = _run_with_fake_evaluation(
        tmp_path,
        monkeypatch,
        _successful_evaluation,
        store_factory=lambda root, redactor: FailingFinalStore(root, redactor),
    )

    assert result.outcome is Outcome.ERROR
    assert (
        "could not save comparison evidence" in result.data["comparison"]["status"]
        or result.diagnostics
    )


def test_evaluator_transport_close_error_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository(tmp_path, rules=True)
    evaluator_transport = None

    class CloseFailingTransport(ScriptedTransport):
        def __init__(self, values):
            super().__init__(values)
            self.close_calls = 0

        async def close(self):
            self.close_calls += 1
            self.closed = True
            raise RuntimeError("injected transport close error")

    def transport_factory(profile):
        nonlocal evaluator_transport
        if profile.model == "evaluator":
            evaluator_transport = CloseFailingTransport(
                _preflight_values(profile.model)
            )
            return evaluator_transport
        return ScriptedTransport(_preflight_values(profile.model))

    result = _run_with_fake_evaluation(
        tmp_path,
        monkeypatch,
        _successful_evaluation,
        transport_factory=transport_factory,
    )

    comparison = _summary(tmp_path, result)
    assert result.outcome is Outcome.ERROR
    assert evaluator_transport is not None
    assert evaluator_transport.close_calls == 1
    assert comparison["status"] == "error"
    assert comparison["failure"]["stage"] == "evidence_writing"
