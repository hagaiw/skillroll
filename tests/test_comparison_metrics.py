"""Pure comparison cost, usage, timing, outcome, and report contracts."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from skillroll.commands import compare
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
)
from skillroll.inference.transport import ModelUsage
from skillroll.judge import JudgeResult
from skillroll.models import (
    EvalCase,
    GuardSettings,
    InferenceSettings,
    ModelPricing,
    PricingSettings,
    Skill,
    SkillRollConfig,
)
from skillroll.outcomes import Outcome
from skillroll.runtime.execution import ExecutionResult
from skillroll.verdicts import CaseResult
from skillroll.world.session import WorldEvent


def _case(tmp_path: Path) -> EvalCase:
    skill_root = tmp_path / "skills" / "review"
    evals = skill_root / "evals"
    evals.mkdir(parents=True)
    skill_file = skill_root / "SKILL.md"
    skill_file.write_text("Review the task.\n", encoding="utf-8")
    case_path = evals / "case.eval.md"
    case_path.write_text("case data\n", encoding="utf-8")
    skill = Skill(
        "review",
        PurePosixPath("skills/review"),
        skill_root,
        skill_file,
        evals,
    )
    return EvalCase(
        case_path,
        PurePosixPath("skills/review/evals/case.eval.md"),
        skill,
        "Review",
        "Write a concise review.",
        "The source is accurate.",
        "- The review is accurate.",
        (),
    )


def _config(root: Path, *, pricing: bool = True) -> SkillRollConfig:
    prices = None
    if pricing:
        prices = PricingSettings(
            "USD",
            {
                "baseline": ModelPricing(1.0, 3.0),
                "candidate": ModelPricing(0.5, 2.0),
                "evaluator": ModelPricing(2.0, 4.0),
            },
        )
    return SkillRollConfig(
        root,
        PurePosixPath("skills"),
        root / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "evaluator", "KEY"),
        root / "skillroll.toml",
        prices,
    )


def _usage_call(
    stage: str, model: str, input_tokens: int, output_tokens: int
) -> dict[str, object]:
    return {
        "stage": stage,
        "requested_model": model,
        "served_model": f"served/{model}",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cache_read_tokens": None,
    }


def _attempt(
    case: EvalCase,
    executor_model: str,
    *,
    outcome: str = "PASS",
    execution_usage: tuple[ModelUsage, ...] | None = None,
    execution_turns: int | None = 1,
    world_usage: ModelUsage | None = None,
    world_missing_usage: int = 0,
    judge_usage: ModelUsage | None = None,
    judge_attempted: bool = True,
    timings: dict[str, float | None] | None = None,
    failure: InferenceFailure | None = None,
) -> CaseResult:
    world_event = (
        ()
        if world_usage is None
        else (
            WorldEvent(
                0,
                "Read",
                {"path": "source.md"},
                "source facts",
                "world_model",
                model="served/evaluator",
                usage=world_usage,
            ),
        )
    )
    execution = (
        None
        if execution_usage is None
        else ExecutionResult("review ready", execution_turns, execution_usage, ())
    )
    judge = (
        None
        if judge_usage is None
        else JudgeResult(
            "PASS", "The criterion is met.", (), "served/evaluator", judge_usage
        )
    )
    values = (
        {
            "execution_seconds": 0.06,
            "world_seconds": 0.02,
            "judge_seconds": 0.03,
            "executor_seconds": 0.04,
        }
        if timings is None
        else timings
    )
    if not judge_attempted:
        values = {**values, "judge_seconds": None}
    return CaseResult(
        case,
        outcome,  # type: ignore[arg-type]
        execution,
        judge,
        (),
        (),
        failure,
        PurePosixPath(f".skillroll/runs/{executor_model}-run"),
        world_event,
        True,
        values,
        bool(world_event) or world_missing_usage > 0,
        world_missing_usage,
    )


def _preflight(model: str, *, status: str = "passed") -> dict[str, object]:
    return {
        "status": status,
        "requested_model": model,
        "served_model": f"served/{model}",
        "usage": {
            "status": "observed",
            "calls": [
                _usage_call("preflight", model, 10, 2),
                _usage_call("preflight", model, 12, 3),
            ],
        },
    }


def test_attempt_role_sections_mark_partial_and_uninvoked_roles(tmp_path: Path) -> None:
    case = _case(tmp_path)
    event_usage = ModelUsage(20, 5, 25)
    incomplete = _attempt(
        case,
        "candidate",
        outcome="ERROR",
        execution_usage=(ModelUsage(100, 20, 120),),
        execution_turns=2,
        world_usage=event_usage,
        world_missing_usage=1,
        judge_attempted=False,
        failure=InferenceFailure(
            InferenceFailureKind.SERVICE_FAILURE,
            "World response was unavailable.",
            stage="world",
        ),
    )

    roles = compare._attempt_role_sections(incomplete, "candidate", "evaluator")

    assert roles["execution"]["status"] == "partial"
    assert roles["execution"]["usage_complete"] is False
    assert len(roles["execution"]["calls"]) == 1
    assert roles["world"]["status"] == "unavailable"
    assert roles["world"]["missing_usage_calls"] == 1
    assert roles["world"]["calls"][0]["requested_model"] == "evaluator"
    assert roles["semantic_judgment"]["status"] == "not_invoked"

    attempt = compare._attempt_data(
        incomplete,
        sequence=7,
        sample=2,
        executor_model="candidate",
        evaluator_model="evaluator",
        redactor=compare.SecretRedactor(compare.SecretValue("sensitive")),
    )
    assert attempt["started"] is True
    assert attempt["status"] == "ERROR"
    assert attempt["timings"]["judge_seconds"] is None
    assert attempt["role_usage"] == roles

    not_started = _attempt(
        case,
        "baseline",
        timings={
            "execution_seconds": None,
            "world_seconds": None,
            "judge_seconds": None,
            "executor_seconds": None,
        },
        judge_attempted=False,
    )
    not_started_roles = compare._attempt_role_sections(
        not_started, "baseline", "evaluator"
    )
    assert not_started_roles["execution"]["status"] == "not_invoked"
    assert not_started_roles["semantic_judgment"]["status"] == "not_invoked"


def test_usage_summary_prices_only_complete_observed_samples() -> None:
    observed = {
        "status": "observed",
        "calls": [_usage_call("execution", "candidate", 100, 20)],
    }
    partial = {
        "status": "partial",
        "usage_complete": False,
        "calls": [_usage_call("execution", "candidate", 50, 8)],
    }
    summary = compare._usage_summary(
        (
            {"status": "PASS", "role_usage": {"execution": observed}},
            {"status": "ERROR", "role_usage": {"execution": partial}},
        ),
        role="execution",
        expected=2,
        pricing=ModelPricing(0.5, 2.0),
        currency="USD",
    )
    assert summary["status"] == "partial"
    assert summary["samples_with_usage"] == 1
    assert summary["samples_with_known_status"] == 1
    assert len(summary["calls"]) == 2
    assert summary["cost"] == {
        "status": "unavailable",
        "reason": "provider usage is incomplete",
    }

    not_invoked = compare._usage_summary(
        ({"status": "PASS", "role_usage": {"world": {"status": "not_invoked"}}},),
        role="world",
        expected=1,
        pricing=None,
        currency="USD",
    )
    assert not_invoked["status"] == "not_invoked"
    assert not_invoked["cost"] == {
        "status": "estimated",
        "currency": "USD",
        "amount": 0.0,
        "reason": "the model role was not invoked",
    }

    malformed_calls = compare._usage_summary(
        (
            {
                "status": "ERROR",
                "role_usage": {"world": {"status": "partial", "calls": "invalid"}},
            },
        ),
        role="world",
        expected=1,
        pricing=None,
        currency="USD",
    )
    assert malformed_calls["status"] == "unavailable"
    assert malformed_calls["calls"] == []

    malformed_roles = compare._usage_summary(
        ({"status": "PASS", "role_usage": "invalid"},),
        role="world",
        expected=1,
        pricing=None,
        currency="USD",
    )
    assert malformed_roles["status"] == "unavailable"


def test_usage_summary_distinguishes_missing_started_data_and_not_run() -> None:
    started_without_role = compare._usage_summary(
        ({"status": "PASS"},),
        role="semantic_judgment",
        expected=1,
        pricing=ModelPricing(1.0, 2.0),
        currency="USD",
    )
    assert started_without_role["status"] == "unavailable"
    assert started_without_role["cost"]["reason"] == (
        "role evidence is missing for a started sample"
    )

    unrun = compare._usage_summary(
        ({"status": "NOT_RUN"},),
        role="execution",
        expected=1,
        pricing=ModelPricing(1.0, 2.0),
        currency="USD",
    )
    assert unrun["status"] == "unavailable"
    assert unrun["cost"]["reason"] == "some planned samples did not run"


def test_numeric_timing_filters_and_median_statuses() -> None:
    attempts = (
        {"timings": {"executor_seconds": 0.2}},
        {"timings": {"executor_seconds": 0.6}},
        {"timings": {"executor_seconds": True}},
        {"timings": "not a mapping"},
    )
    values = compare._numeric_values(attempts, "executor_seconds")
    assert values == [0.2, 0.6]
    assert compare._median_data(values, expected=2) == {
        "status": "observed",
        "median_seconds": 0.4,
        "samples_with_timing": 2,
        "samples_expected": 2,
    }
    assert compare._median_data([0.3], expected=2)["status"] == "partial"
    assert compare._median_data([], expected=2) == {
        "status": "unavailable",
        "median_seconds": None,
        "samples_with_timing": 0,
        "samples_expected": 2,
    }


def test_outcome_counts_pairing_and_precedence_include_planned_runs(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path)
    attempts = (
        {
            "sample": 1,
            "case": case.identity.as_posix(),
            "executor_model": "baseline",
            "status": "PASS",
        },
        {
            "sample": 1,
            "case": case.identity.as_posix(),
            "executor_model": "candidate",
            "status": "FAIL",
        },
        {
            "sample": 2,
            "case": case.identity.as_posix(),
            "executor_model": "baseline",
            "status": "NOT_RUN",
        },
    )
    counts = compare._outcome_counts(attempts, ("baseline", "candidate"), (case,))
    baseline_counts = counts[0]["counts"]
    assert baseline_counts == {
        "PASS": 1,
        "FAIL": 0,
        "ERROR": 0,
        "INCOMPLETE": 0,
        "NOT_RUN": 1,
    }
    paired = compare._paired_outcomes(attempts, ("baseline", "candidate"), (case,), 2)
    assert paired[0]["baseline_outcome"] == "PASS"
    assert paired[0]["candidate_outcome"] == "FAIL"
    assert paired[1]["baseline_outcome"] == "NOT_RUN"
    assert paired[1]["candidate_outcome"] == "NOT_RUN"

    assert compare._overall_outcome(attempts[:2], "complete") is Outcome.FAIL
    assert (
        compare._overall_outcome(({"status": "INCOMPLETE"},), "complete")
        is Outcome.INCOMPLETE
    )
    assert compare._overall_outcome(({"status": "PASS"},), "partial") is Outcome.ERROR
    assert (
        compare._overall_outcome(({"status": "NOT_RUN"},), "complete") is Outcome.ERROR
    )
    assert compare._overall_outcome(({"status": "PASS"},), "complete") is Outcome.PASS


def test_preflight_cost_requires_two_complete_usage_records() -> None:
    config = _config(Path("/repo"))
    assert compare._preflight_cost("candidate", {"status": "failed"}, config, "USD")[
        "reason"
    ] == ("preflight failed")
    assert (
        compare._preflight_cost(
            "candidate",
            {"status": "passed", "usage": {"status": "unavailable", "calls": []}},
            config,
            "USD",
        )["reason"]
        == "preflight provider usage is unavailable"
    )
    assert (
        compare._preflight_cost(
            "candidate",
            {
                "status": "passed",
                "usage": {
                    "status": "observed",
                    "calls": [_usage_call("preflight", "candidate", 1, 1)],
                },
            },
            config,
            "USD",
        )["reason"]
        == "both preflight calls must report provider usage"
    )

    full = compare._preflight_cost(
        "candidate",
        {
            "status": "passed",
            "usage": {
                "status": "observed",
                "calls": [
                    _usage_call("preflight", "candidate", 10, 2),
                    _usage_call("preflight", "candidate", 12, 3),
                ],
            },
        },
        config,
        "USD",
    )
    assert full["status"] == "estimated"
    assert full["amount"] == 0.000021
    unpriced = compare._preflight_cost(
        "unpriced",
        {
            "status": "passed",
            "usage": {
                "status": "observed",
                "calls": [
                    _usage_call("preflight", "unpriced", 10, 2),
                    _usage_call("preflight", "unpriced", 12, 3),
                ],
            },
        },
        config,
        "USD",
    )
    assert unpriced["status"] == "unavailable"
    assert unpriced["reason"] == "no user-supplied pricing"


def test_metrics_summary_and_report_keep_roles_timings_and_cost_reasons(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path)
    config = _config(tmp_path)
    evaluator_usage = ModelUsage(20, 5, 25)
    baseline = _attempt(
        case,
        "baseline",
        execution_usage=(ModelUsage(100, 20, 120),),
        world_usage=evaluator_usage,
        judge_usage=ModelUsage(10, 3, 13),
    )
    candidate = _attempt(
        case,
        "candidate",
        outcome="ERROR",
        execution_usage=(ModelUsage(50, 8, 58),),
        execution_turns=2,
        world_usage=evaluator_usage,
        world_missing_usage=1,
        judge_attempted=False,
        failure=InferenceFailure(
            InferenceFailureKind.SERVICE_FAILURE,
            "The run stopped while contacting the World.",
            stage="world",
        ),
        timings={
            "execution_seconds": 0.08,
            "world_seconds": 0.03,
            "judge_seconds": None,
            "executor_seconds": 0.05,
        },
    )
    attempts = (
        compare._attempt_data(
            baseline,
            sequence=1,
            sample=1,
            executor_model="baseline",
            evaluator_model="evaluator",
            redactor=compare.SecretRedactor(compare.SecretValue("secret")),
        ),
        compare._attempt_data(
            candidate,
            sequence=2,
            sample=1,
            executor_model="candidate",
            evaluator_model="evaluator",
            redactor=compare.SecretRedactor(compare.SecretValue("secret")),
        ),
    )
    summary = compare._summary_data(
        comparison_id="comparison-id",
        status="complete",
        attempts=attempts,
        executor_models=("baseline", "candidate"),
        cases=(case,),
        samples=1,
        config=config,
        evaluator_model="evaluator",
        failure=None,
        preflight={
            "status": "passed",
            "models": {
                "baseline": _preflight("baseline"),
                "candidate": _preflight("candidate"),
            },
        },
    )

    metrics = summary["metrics"]
    assert isinstance(metrics, list)
    baseline_metrics = metrics[0]
    assert baseline_metrics["roles"]["execution"]["cost"]["status"] == "estimated"
    assert baseline_metrics["timings"]["executor_seconds"]["median_seconds"] == 0.04
    candidate_metrics = metrics[1]
    assert candidate_metrics["roles"]["execution"]["status"] == "unavailable"
    assert candidate_metrics["roles"]["execution"]["cost"]["status"] == "unavailable"
    assert candidate_metrics["roles"]["world"]["cost"]["status"] == "unavailable"
    assert candidate_metrics["roles"]["semantic_judgment"]["status"] == "not_invoked"
    assert candidate_metrics["roles"]["semantic_judgment"]["cost"]["amount"] == 0.0

    report = compare._report_bytes(summary).decode("utf-8")
    assert "| PASS | FAIL | ERROR | INCOMPLETE | NOT_RUN |" in report
    assert (
        "executor_seconds` is execution wall time minus World callback time" in report
    )
    assert "Median executor_seconds: 0.040s" in report
    assert "`baseline`: passed preflight; estimated cost" in report
    assert "`candidate`: passed preflight; estimated cost" in report
    assert "provider usage is incomplete" in report
    assert "[run report]" in report

    no_pairs = dict(summary)
    no_pairs["paired_outcomes"] = []
    assert "No paired sample finished." in compare._report_bytes(no_pairs).decode(
        "utf-8"
    )

    empty_summary = compare._summary_data(
        comparison_id="empty-comparison",
        status="partial",
        attempts=(),
        executor_models=("baseline", "candidate"),
        cases=(case,),
        samples=1,
        config=config,
        evaluator_model=None,
        failure=None,
        preflight={"status": "unavailable", "models": {}},
    )
    empty_report = compare._report_bytes(empty_summary).decode("utf-8")
    assert "Fixed World and judge model: `unavailable`" in empty_report
    assert "No individual run evidence was created." in empty_report
