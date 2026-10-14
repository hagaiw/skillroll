"""Bounded case scheduling, isolation, and shutdown without model calls."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest
from conftest import run_module
from test_phase4_verdicts import (
    Executor,
    ScriptedTransport,
    case_at,
    preflight_responses,
)

from skillroll.commands import evaluate
from skillroll.inference.profile import InferenceFailure, InferenceFailureKind
from skillroll.models import GuardSettings, InferenceSettings, SkillRollConfig
from skillroll.outcomes import Outcome
from skillroll.runtime.attempt import PreliminaryAttempt


def configuration(root: Path) -> SkillRollConfig:
    return SkillRollConfig(
        root,
        PurePosixPath("skills"),
        root / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        root / "skillroll.toml",
    )


def failed_attempt() -> PreliminaryAttempt:
    return PreliminaryAttempt(
        None,
        InferenceFailure(InferenceFailureKind.EXECUTION_ERROR, "offline stub"),
        None,
    )


def test_cases_overlap_with_bounded_concurrency_fresh_executors_and_stable_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = case_at(tmp_path)
    cases = tuple(
        replace(case, identity=PurePosixPath(f"skill/evals/{index}.md"))
        for index in range(5)
    )
    transport = ScriptedTransport(preflight_responses())
    executors: list[Executor] = []
    completion_order: list[str] = []
    active = peak = 0

    def factory(_: object) -> Executor:
        executor = Executor()
        executors.append(executor)
        return executor

    async def preliminary(*args: object, **kwargs: object) -> PreliminaryAttempt:
        nonlocal active, peak
        selected = args[1]
        active += 1
        peak = max(peak, active)
        # Reverse completion within the initial pair without timing assumptions.
        if selected.identity == cases[0].identity:
            await second_finished.wait()
        else:
            await asyncio.sleep(0)
        completion_order.append(selected.identity.as_posix())
        second_finished.set()
        active -= 1
        return failed_attempt()

    async def run() -> None:
        nonlocal second_finished
        second_finished = asyncio.Event()
        result = await evaluate.evaluate_repository(
            configuration(tmp_path),
            tuple(reversed(cases)),
            environment={"KEY": "secret"},
            run_commands=False,
            concurrency=2,
            transport_factory=lambda _: transport,
            executor_factory=factory,
        )
        assert not isinstance(result, InferenceFailure)
        assert [item.case.identity for item in result] == [c.identity for c in cases]

    second_finished: asyncio.Event
    monkeypatch.setattr(evaluate, "execute_preliminary", preliminary)
    asyncio.run(run())
    assert peak == 2
    assert active == 0
    assert completion_order[0] == cases[1].identity.as_posix()
    assert len(executors) == len(cases)
    assert len({id(executor) for executor in executors}) == len(cases)
    assert len(transport.requests) == 2  # One profile compatibility preflight.
    assert transport.closed


@pytest.mark.parametrize("failure_mode", ["cancel", "worker_error"])
def test_shutdown_drains_active_workers_before_transport_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_mode: str
) -> None:
    case = case_at(tmp_path)
    cases = tuple(
        replace(case, identity=PurePosixPath(f"skill/{i}.md")) for i in range(4)
    )
    active = 0
    stopped = 0
    transport = ScriptedTransport(preflight_responses())

    async def close() -> None:
        assert active == 0
        transport.closed = True

    async def preliminary(*args: object, **kwargs: object) -> PreliminaryAttempt:
        nonlocal active, stopped
        active += 1
        if active == 2:
            started.set()
        try:
            await started.wait()
            if failure_mode == "worker_error" and args[1].identity == cases[0].identity:
                raise RuntimeError("worker failed")
            await never.wait()
            return failed_attempt()
        finally:
            # Simulate asynchronous worker resource cleanup.
            await asyncio.sleep(0)
            active -= 1
            stopped += 1

    async def run() -> None:
        nonlocal started, never
        started, never = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(
            evaluate.evaluate_repository(
                configuration(tmp_path),
                cases,
                environment={"KEY": "secret"},
                run_commands=False,
                concurrency=2,
                transport_factory=lambda _: transport,
            )
        )
        await started.wait()
        if failure_mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(RuntimeError, match="worker failed"):
                await task

    started: asyncio.Event
    never: asyncio.Event
    monkeypatch.setattr(transport, "close", close)
    monkeypatch.setattr(evaluate, "execute_preliminary", preliminary)
    asyncio.run(run())
    assert stopped >= 2
    assert active == 0
    assert transport.closed


@pytest.mark.parametrize(
    "concurrency,run_commands", [(0, False), (17, False), (2, True)]
)
def test_invalid_concurrency_fails_before_preflight_or_repository_access(
    tmp_path: Path, concurrency: int, run_commands: bool
) -> None:
    result = evaluate.run(
        repo=str(tmp_path / "missing"),
        concurrency=concurrency,
        run_commands=run_commands,
    )
    assert result.outcome is Outcome.ERROR
    assert "--concurrency" in result.diagnostics[0].summary

    async def run() -> None:
        for method in (evaluate.evaluate_repository, evaluate.evaluate_experiment):
            kwargs = (
                {"samples": 1, "with_skill_control": False}
                if method == evaluate.evaluate_experiment
                else {}
            )
            result = await method(
                configuration(tmp_path),
                (),
                environment={},
                run_commands=run_commands,
                concurrency=concurrency,
                **kwargs,
            )
            assert isinstance(result, InferenceFailure)
            assert "--concurrency" in result.summary

    asyncio.run(run())


def test_cli_passes_concurrency_into_evaluation() -> None:
    result = run_module("eval", "--concurrency", "0")
    assert result.returncode != 0
    assert "--concurrency must" in result.stderr


def test_experiment_parallelizes_cases_but_keeps_samples_and_controls_sequential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = case_at(tmp_path)
    cases = tuple(
        replace(case, identity=PurePosixPath(f"skill/{i}.md")) for i in range(2)
    )
    transport = ScriptedTransport(preflight_responses())
    active = peak = 0
    modes: list[bool] = []

    async def preliminary(*args: object, **kwargs: object) -> PreliminaryAttempt:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        modes.append(kwargs["skill_available"])
        await asyncio.sleep(0)
        active -= 1
        return failed_attempt()

    monkeypatch.setattr(evaluate, "execute_preliminary", preliminary)
    result = asyncio.run(
        evaluate.evaluate_experiment(
            configuration(tmp_path),
            cases,
            environment={"KEY": "secret"},
            run_commands=False,
            samples=2,
            with_skill_control=True,
            concurrency=2,
            transport_factory=lambda _: transport,
            executor_factory=lambda _: Executor(),
        )
    )
    assert isinstance(result, evaluate.ExperimentResult)
    assert peak == 2
    assert modes == [True, True, False, False] * 2
    assert [pair.sample for pair in result.pairs] == [1, 1, 2, 2]
    assert len(transport.requests) == 2
    assert transport.closed
