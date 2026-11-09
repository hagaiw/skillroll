"""Executor and evaluator model routing, usage, timing, and artifacts."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path, PurePosixPath

import pytest

from skillroll.commands import evaluate
from skillroll.config import load_config
from skillroll.inference.profile import (
    InferenceFailure,
    ResolvedInference,
    SecretValue,
)
from skillroll.inference.transport import (
    ChatRequest,
    ChatResponse,
    ModelUsage,
    ToolCall,
)
from skillroll.judge import JudgeResult
from skillroll.models import (
    EvalCase,
    GuardSettings,
    InferenceLimits,
    InferenceSettings,
    InferenceWire,
    ModelPricing,
    ModelProfile,
    PricingSettings,
    Skill,
    SkillRollConfig,
)
from skillroll.runtime.execution import ExecutionAttempt, ExecutionResult
from skillroll.verdicts import CaseResult
from skillroll.world.bundle import BundleIndex
from skillroll.world.session import WorldSession


class ScriptedTransport:
    def __init__(self, responses: list[ChatResponse], *, delay: float = 0.0) -> None:
        self.responses = list(responses)
        self.delay = delay
        self.requests: list[ChatRequest] = []
        self.closed = False

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.responses.pop(0)

    async def close(self) -> None:
        self.closed = True


class RoleExecutor:
    def __init__(self, profile: ResolvedInference) -> None:
        self.profile = profile

    async def execute(self, request: object, world_action: object) -> ExecutionAttempt:
        assert callable(world_action)
        await asyncio.sleep(0.002)
        await world_action("Lookup", {"item": "status"})
        return ExecutionAttempt(
            ExecutionResult(
                "The status is ready.",
                1,
                (ModelUsage(5, 4, 9),),
                (),
            ),
            None,
        )


def _preflight_responses(model: str) -> list[ChatResponse]:
    return [
        ChatResponse(
            None,
            (ToolCall("preflight-id", "skillroll_preflight", {"value": "ready"}),),
            model,
            None,
        ),
        ChatResponse('{"status":"ready"}', (), model, None),
    ]


def _case_files(root: Path) -> tuple[SkillRollConfig, EvalCase]:
    skill_root = root / "skills" / "status"
    evals = skill_root / "evals"
    evals.mkdir(parents=True)
    skill_file = skill_root / "SKILL.md"
    skill_file.write_text("# Status\n", encoding="utf-8")
    case_path = evals / "status.eval.md"
    case_path.write_text("case evidence\n", encoding="utf-8")
    config_path = root / "skillroll.toml"
    config_path.write_text("schema_version = 1\n", encoding="utf-8")
    skill = Skill(
        "status",
        PurePosixPath("skills/status"),
        skill_root,
        skill_file,
        evals,
    )
    case = EvalCase(
        case_path,
        PurePosixPath("skills/status/evals/status.eval.md"),
        skill,
        "Status",
        "Find the current status.",
        "The status is ready.",
        "- The final response reports the status.",
        (),
    )
    config = SkillRollConfig(
        root,
        PurePosixPath("skills"),
        root / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "evaluator", "KEY"),
        config_path,
    )
    return config, case


def _runtime_transports(
    evaluator_model: str, *, samples: int = 1, delay: float = 0.0
) -> ScriptedTransport:
    responses = _preflight_responses(evaluator_model)
    for _ in range(samples):
        responses.extend(
            (
                ChatResponse(
                    "The status is ready.",
                    (),
                    evaluator_model,
                    ModelUsage(2, 3, 5),
                ),
                ChatResponse(
                    json.dumps(
                        {
                            "verdict": "PASS",
                            "rationale": "The response reports the status.",
                            "criteria": [
                                {
                                    "status": "met",
                                    "evidence": "The status was reported.",
                                }
                            ],
                            "unmet_criteria": [],
                        }
                    ),
                    (),
                    evaluator_model,
                    ModelUsage(10, 4, 14),
                ),
            )
        )
    return ScriptedTransport(responses, delay=delay)


def _executor_preflight(model: str) -> ScriptedTransport:
    return ScriptedTransport(_preflight_responses(model))


@pytest.mark.parametrize("wire", tuple(InferenceWire))
def test_executor_override_routes_models_and_records_roles(
    tmp_path: Path, wire: InferenceWire
) -> None:
    config, case = _case_files(tmp_path)
    config = SkillRollConfig(
        config.repository_root,
        config.skills_path,
        config.skills_root,
        config.guards,
        InferenceSettings(
            "https://example.test/v1",
            "evaluator-model",
            "KEY",
            wire=wire,
            executor_model="configured-executor",
        ),
        config.config_path,
        PricingSettings(
            "USD",
            {
                "evaluator-model": ModelPricing(2.0, 4.0),
                "override-executor": ModelPricing(1.0, 3.0),
            },
        ),
    )
    evaluator = _runtime_transports("evaluator-model")
    candidate = _executor_preflight("override-executor")
    profiles: list[ResolvedInference] = []
    executors: list[RoleExecutor] = []

    def transport_factory(profile: ResolvedInference) -> ScriptedTransport:
        profiles.append(profile)
        return evaluator if profile.model == "evaluator-model" else candidate

    def executor_factory(profile: ResolvedInference) -> RoleExecutor:
        executor = RoleExecutor(profile)
        executors.append(executor)
        return executor

    result = asyncio.run(
        evaluate.evaluate_repository(
            config,
            (case,),
            environment={"KEY": "test-key"},
            run_commands=False,
            transport_factory=transport_factory,
            executor_factory=executor_factory,
            executor_model="override-executor",
        )
    )

    assert not isinstance(result, InferenceFailure)
    assert result[0].outcome == "PASS"
    assert [profile.model for profile in profiles] == [
        "evaluator-model",
        "override-executor",
    ]
    assert all(profile.wire is wire for profile in profiles)
    assert executors[0].profile.model == "override-executor"
    assert [request.model for request in candidate.requests] == [
        "override-executor",
        "override-executor",
    ]
    assert [request.model for request in evaluator.requests] == [
        "evaluator-model",
        "evaluator-model",
        "evaluator-model",
        "evaluator-model",
    ]
    assert result[0].artifact_directory is not None
    artifact = tmp_path / result[0].artifact_directory.as_posix()
    run_record = json.loads((artifact / "run.json").read_text(encoding="utf-8"))
    execution_record = json.loads(
        (artifact / "execution.json").read_text(encoding="utf-8")
    )
    result_record = json.loads((artifact / "result.json").read_text(encoding="utf-8"))
    report = (artifact / "report.md").read_text(encoding="utf-8")
    assert run_record["models"] == {
        "executor": "override-executor",
        "world": "evaluator-model",
        "judge": "evaluator-model",
    }
    assert execution_record["models"] == {
        "executor": "override-executor",
        "world_and_judge": "evaluator-model",
    }
    assert execution_record["usage"]["execution"]["calls"][0]["requested_model"] == (
        "override-executor"
    )
    assert execution_record["usage"]["world"]["calls"][0]["requested_model"] == (
        "evaluator-model"
    )
    assert result_record["models"] == {
        "executor": "override-executor",
        "world": "evaluator-model",
        "judge": "evaluator-model",
    }
    assert result_record["cost"]["status"] == "estimated"
    assert result_record["cost"]["amount"] == 0.000069
    assert result_record["timings"]["execution_seconds"] is not None
    assert result_record["timings"]["world_seconds"] is not None
    assert result_record["timings"]["judge_seconds"] is not None
    assert result_record["timings"]["executor_seconds"] == pytest.approx(
        max(
            0.0,
            result_record["timings"]["execution_seconds"]
            - result_record["timings"]["world_seconds"],
        )
    )
    assert "Executor model: `override-executor`" in report
    assert "World and judge model: `evaluator-model`" in report
    assert evaluator.closed and candidate.closed


def test_default_model_profile_and_equal_executor_reuse_evaluator_preflight(
    tmp_path: Path,
) -> None:
    config, case = _case_files(tmp_path)
    settings = InferenceSettings(
        "https://example.test/v1",
        "unused-model",
        "KEY",
        profiles={"baseline": ModelProfile("Default evaluator", ("fallback-model",))},
        default_profile="baseline",
    )
    config = SkillRollConfig(
        config.repository_root,
        config.skills_path,
        config.skills_root,
        config.guards,
        settings,
        config.config_path,
    )
    evaluator = _runtime_transports("fallback-model")
    created: list[ResolvedInference] = []

    def transport_factory(profile: ResolvedInference) -> ScriptedTransport:
        created.append(profile)
        return evaluator

    result = asyncio.run(
        evaluate.evaluate_repository(
            config,
            (case,),
            environment={"KEY": "test-key"},
            run_commands=False,
            transport_factory=transport_factory,
            executor_factory=RoleExecutor,
        )
    )

    assert not isinstance(result, InferenceFailure)
    assert result[0].outcome == "PASS"
    assert [profile.model for profile in created] == ["fallback-model"]
    assert result[0].timings["judge_seconds"] is not None
    assert evaluator.closed


def test_invalid_override_and_executor_preflight_failure_do_not_leak_transports(
    tmp_path: Path,
) -> None:
    config, case = _case_files(tmp_path)
    calls = 0

    def unused_factory(_: ResolvedInference) -> ScriptedTransport:
        nonlocal calls
        calls += 1
        raise AssertionError("invalid override must fail before any request")

    invalid = asyncio.run(
        evaluate.evaluate_repository(
            config,
            (case,),
            environment={"KEY": "test-key"},
            run_commands=False,
            transport_factory=unused_factory,
            executor_model=" \n ",
        )
    )
    assert isinstance(invalid, InferenceFailure)
    assert calls == 0

    evaluator = ScriptedTransport(_preflight_responses("evaluator"))
    rejected_executor = ScriptedTransport(
        [ChatResponse("not a valid tool call", (), "executor", None)]
    )
    config = SkillRollConfig(
        config.repository_root,
        config.skills_path,
        config.skills_root,
        config.guards,
        InferenceSettings(
            "https://example.test/v1", "evaluator", "KEY", executor_model="executor"
        ),
        config.config_path,
    )
    result = asyncio.run(
        evaluate.evaluate_repository(
            config,
            (case,),
            environment={"KEY": "test-key"},
            run_commands=False,
            transport_factory=lambda profile: (
                evaluator if profile.model == "evaluator" else rejected_executor
            ),
        )
    )
    assert isinstance(result, InferenceFailure)
    assert result.stage == "preflight"
    assert evaluator.closed and rejected_executor.closed
    assert len(evaluator.requests) == 2 and len(rejected_executor.requests) == 1


def test_sampled_experiment_preflights_configured_executor_only_once(
    tmp_path: Path,
) -> None:
    config, case = _case_files(tmp_path)
    config = SkillRollConfig(
        config.repository_root,
        config.skills_path,
        config.skills_root,
        config.guards,
        InferenceSettings(
            "https://example.test/v1",
            "evaluator",
            "KEY",
            executor_model="configured-executor",
        ),
        config.config_path,
    )
    evaluator = _runtime_transports("evaluator", samples=2)
    executor_candidate = _executor_preflight("configured-executor")
    factories: list[ResolvedInference] = []
    executor_profiles: list[str] = []

    def transport_factory(profile: ResolvedInference) -> ScriptedTransport:
        factories.append(profile)
        return evaluator if profile.model == "evaluator" else executor_candidate

    def executor_factory(profile: ResolvedInference) -> RoleExecutor:
        executor_profiles.append(profile.model)
        return RoleExecutor(profile)

    result = asyncio.run(
        evaluate.evaluate_experiment(
            config,
            (case,),
            environment={"KEY": "test-key"},
            run_commands=False,
            samples=2,
            with_skill_control=False,
            transport_factory=transport_factory,
            executor_factory=executor_factory,
        )
    )

    assert not isinstance(result, InferenceFailure)
    assert len(executor_candidate.requests) == 2
    assert [profile.model for profile in factories] == [
        "evaluator",
        "configured-executor",
    ]
    assert executor_profiles == ["configured-executor", "configured-executor"]
    assert result.summary["executor_model"] == "configured-executor"
    assert evaluator.closed and executor_candidate.closed


def test_sampled_executor_validation_and_preflight_failure_close_transports(
    tmp_path: Path,
) -> None:
    config, case = _case_files(tmp_path)
    called = False

    def unused_factory(_: ResolvedInference) -> ScriptedTransport:
        nonlocal called
        called = True
        raise AssertionError("invalid override must fail before preflight")

    invalid = asyncio.run(
        evaluate.evaluate_experiment(
            config,
            (case,),
            environment={"KEY": "test-key"},
            run_commands=False,
            samples=2,
            with_skill_control=False,
            transport_factory=unused_factory,
            executor_model=" ",
        )
    )
    assert isinstance(invalid, InferenceFailure)
    assert not called

    config = SkillRollConfig(
        config.repository_root,
        config.skills_path,
        config.skills_root,
        config.guards,
        InferenceSettings(
            "https://example.test/v1",
            "evaluator",
            "KEY",
            executor_model="executor",
        ),
        config.config_path,
    )
    evaluator = ScriptedTransport(_preflight_responses("evaluator"))
    failed_executor = ScriptedTransport(
        [ChatResponse("not a valid tool call", (), "executor", None)]
    )
    result = asyncio.run(
        evaluate.evaluate_experiment(
            config,
            (case,),
            environment={"KEY": "test-key"},
            run_commands=False,
            samples=2,
            with_skill_control=False,
            transport_factory=lambda profile: (
                evaluator if profile.model == "evaluator" else failed_executor
            ),
        )
    )
    assert isinstance(result, InferenceFailure)
    assert result.stage == "preflight"
    assert evaluator.closed and failed_executor.closed


def test_mixed_stage_costs_and_missing_world_usage_remain_truthful() -> None:
    pricing = {
        "executor": ModelPricing(1.0, 3.0),
        "evaluator": ModelPricing(2.0, 4.0),
    }
    execution = {
        "calls": [
            {
                "requested_model": "executor",
                "input_tokens": 5,
                "output_tokens": 4,
            }
        ]
    }
    judged = {
        "calls": [
            {
                "requested_model": "evaluator",
                "input_tokens": 10,
                "output_tokens": 4,
            }
        ]
    }
    complete_world = {
        "calls": [
            {
                "requested_model": "evaluator",
                "input_tokens": 2,
                "output_tokens": 3,
            }
        ],
        "inference_made": True,
        "missing_usage_calls": 0,
    }
    complete = evaluate._estimate_role_cost(
        execution,
        complete_world,
        judged,
        pricing,
        "USD",
        execution_attempted=True,
        judge_attempted=True,
    )
    assert complete["status"] == "estimated"
    assert complete["amount"] == 0.000069

    partial_world = {
        **complete_world,
        "missing_usage_calls": 1,
    }
    partial = evaluate._estimate_role_cost(
        execution,
        partial_world,
        judged,
        pricing,
        "USD",
        execution_attempted=True,
        judge_attempted=True,
    )
    assert partial["status"] == "unavailable"
    stages = partial["stages"]
    assert isinstance(stages, dict)
    world_cost = stages["world"]
    assert isinstance(world_cost, dict)
    assert world_cost["status"] == "unavailable"
    assert world_cost["observed_usage_cost"]["amount"] == 0.000016

    failed_world = evaluate._estimate_role_cost(
        execution,
        {"calls": [], "inference_made": True, "missing_usage_calls": 1},
        judged,
        pricing,
        "USD",
        execution_attempted=True,
        judge_attempted=True,
    )
    assert failed_world["status"] == "unavailable"
    failed_world_stages = failed_world["stages"]
    assert isinstance(failed_world_stages, dict)
    assert failed_world_stages["world"]["status"] == "unavailable"

    failed_execution = evaluate._estimate_role_cost(
        {"calls": execution["calls"], "usage_complete": False},
        {"calls": [], "inference_made": False, "missing_usage_calls": 0},
        {"calls": []},
        pricing,
        "USD",
        execution_attempted=True,
        judge_attempted=False,
    )
    assert failed_execution["status"] == "unavailable"
    execution_stages = failed_execution["stages"]
    assert isinstance(execution_stages, dict)
    execution_cost = execution_stages["execution"]
    assert isinstance(execution_cost, dict)
    assert execution_cost["status"] == "unavailable"
    assert execution_cost["observed_usage_cost"]["amount"] == 0.000017

    missing_model = evaluate._estimate_role_cost(
        {"calls": [{"input_tokens": 1, "output_tokens": 1}]},
        {"calls": [], "inference_made": False},
        {"calls": []},
        pricing,
        "USD",
        execution_attempted=True,
        judge_attempted=False,
    )
    assert missing_model["status"] == "unavailable"
    missing_model_stages = missing_model["stages"]
    assert isinstance(missing_model_stages, dict)
    assert missing_model_stages["execution"]["reason"] == (
        "provider usage is incomplete"
    )

    deterministic = evaluate._estimate_role_cost(
        execution,
        {"calls": [], "inference_made": False, "missing_usage_calls": 0},
        judged,
        pricing,
        "USD",
        execution_attempted=True,
        judge_attempted=True,
    )
    deterministic_stages = deterministic["stages"]
    assert isinstance(deterministic_stages, dict)
    assert deterministic_stages["world"]["amount"] == 0.0


def test_experiment_cost_does_not_hide_a_run_with_missing_executor_usage(
    tmp_path: Path,
) -> None:
    _, case = _case_files(tmp_path)
    full = ExecutionResult("done", 1, (ModelUsage(5, 4, 9),), ())
    missing = ExecutionResult("done", 1, (), ())
    judge = JudgeResult("PASS", "criteria met", (), "evaluator", ModelUsage(2, 1, 3))
    results = (
        CaseResult(
            case,
            "PASS",
            full,
            judge,
            (),
            (),
            None,
            PurePosixPath(".skillroll/runs/one"),
            timings={"execution_seconds": 0.1},
        ),
        CaseResult(
            case,
            "PASS",
            missing,
            judge,
            (),
            (),
            None,
            PurePosixPath(".skillroll/runs/two"),
            timings={"execution_seconds": 0.1},
        ),
    )
    cost = evaluate._experiment_cost(
        results,
        "evaluator",
        "executor",
        {
            "executor": ModelPricing(1.0, 3.0),
            "evaluator": ModelPricing(2.0, 4.0),
        },
        "USD",
    )
    assert cost["status"] == "unavailable"
    stages = cost["stages"]
    assert isinstance(stages, dict)
    execution_cost = stages["execution"]
    assert isinstance(execution_cost, dict)
    assert execution_cost["status"] == "unavailable"
    assert execution_cost["observed_usage_cost"]["amount"] == 0.000017


def test_result_summary_uses_legacy_single_model_pricing_fallback(
    tmp_path: Path,
) -> None:
    _, case = _case_files(tmp_path)
    execution = ExecutionResult("done", 1, (ModelUsage(2, 3, 5),), ())
    judge = JudgeResult("PASS", "criteria met", (), "model", ModelUsage(1, 1, 2))
    summary = evaluate._result_summary(
        case,
        "PASS",
        execution,
        (),
        InferenceLimits(),
        judge,
        (),
        (),
        None,
        "model",
        pricing=ModelPricing(1.0, 2.0),
    )
    cost = summary["cost"]
    assert isinstance(cost, dict)
    assert cost["status"] == "estimated"
    assert cost["amount"] == 0.000011


def test_world_session_callback_timing_does_not_double_count_queued_wait(
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "skill"
    skill_root.mkdir()
    transport = ScriptedTransport(
        [
            ChatResponse("one", (), "model", None),
            ChatResponse("two", (), "model", None),
        ],
        delay=0.02,
    )
    profile = ResolvedInference(
        "https://example.test/v1", "model", SecretValue("key"), InferenceLimits()
    )
    session = WorldSession(
        profile,
        InferenceLimits(),
        "World",
        BundleIndex(skill_root, ()),
        (),
        transport,
    )

    async def exercise() -> float:
        started = time.perf_counter()
        await asyncio.gather(session("One", {}), session("Two", {}))
        return time.perf_counter() - started

    wall = asyncio.run(exercise())
    assert session.world_seconds >= 0.03
    assert session.world_seconds <= wall + 0.01
    assert session.world_inference_attempts == 2
    assert session.world_missing_usage == 2


def test_config_parses_executor_model_and_rejects_invalid_values(
    tmp_path: Path,
) -> None:
    (tmp_path / "skills").mkdir()
    path = tmp_path / "skillroll.toml"
    path.write_text(
        'schema_version = 1\nskills_path = "skills"\n'
        '[inference]\nbase_url = "https://example.test/v1"\n'
        'model = "evaluator"\nexecutor_model = "executor"\n'
        'api_key_env = "KEY"\n',
        encoding="utf-8",
    )
    parsed = load_config(tmp_path)
    assert parsed.is_valid and parsed.value is not None
    assert parsed.value.inference is not None
    assert parsed.value.inference.executor_model == "executor"

    path.write_text(
        'schema_version = 1\nskills_path = "skills"\n'
        '[inference]\nbase_url = "https://example.test/v1"\n'
        'model = "evaluator"\nexecutor_model = "\\ninvalid"\n'
        'api_key_env = "KEY"\n',
        encoding="utf-8",
    )
    invalid = load_config(tmp_path)
    assert not invalid.is_valid
