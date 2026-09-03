"""Sequential composition of validation, execution, judging, checks, and evidence."""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import cast

from skillroll.artifacts.records import (
    checks_bytes,
    execution_bytes,
    experiment_bytes,
    experiment_report_bytes,
    final_report_bytes,
    judge_bytes,
    result_bytes,
    verdict_bytes,
)
from skillroll.artifacts.store import ArtifactError, ArtifactStore
from skillroll.assertions import AssertionResult, evaluate_assertions
from skillroll.checks import (
    CheckRequest,
    CheckResult,
    CheckRunner,
    HostCheckRunner,
    check_environment,
    redact_check_result,
    skipped_check,
)
from skillroll.diagnostics import CommandResult, Diagnostic, JSONValue
from skillroll.inference.preflight import run_preflight
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
    SecretRedactor,
    SecretValue,
    bounded_failure_details,
    resolve_inference_candidates,
)
from skillroll.inference.transport import ChatTransport, ModelUsage
from skillroll.judge import JudgeAttempt, JudgeFailure, JudgeResult, judge
from skillroll.models import (
    EvalCase,
    InferenceLimits,
    ModelPricing,
    SkillRollConfig,
    effective_limits,
)
from skillroll.outcomes import Outcome
from skillroll.repository_io import current_directory, find_repository_root
from skillroll.runtime.attempt import execute_preliminary
from skillroll.runtime.execution import (
    AgentSkillExecutor,
    ExecutionResult,
    SkillExecutor,
)
from skillroll.validation import (
    command_result,
    selection_from_strings,
    validate_repository,
)
from skillroll.verdicts import CaseResult, aggregate, case_outcome
from skillroll.world.session import MAX_WORLD_ACTIONS_PER_CASE, WorldEvent

TransportFactory = Callable[[ResolvedInference], ChatTransport]
ExecutorFactory = Callable[[ResolvedInference], SkillExecutor]
StoreFactory = Callable[[Path, SecretRedactor], ArtifactStore]


def _transport(profile: ResolvedInference) -> ChatTransport:
    from skillroll.inference.transport import OpenAIChatTransport

    return OpenAIChatTransport.from_profile(profile)


def _executor(profile: ResolvedInference) -> SkillExecutor:
    from skillroll.runtime.agents_sdk import AgentsSdkRuntime

    return AgentSkillExecutor(profile, AgentsSdkRuntime())


def _store(root: Path, redactor: SecretRedactor) -> ArtifactStore:
    return ArtifactStore(root, redactor)


def _usage(values: tuple[ModelUsage, ...] | ModelUsage | None) -> object:
    if isinstance(values, tuple):
        return [
            {
                "input_tokens": item.input_tokens,
                "output_tokens": item.output_tokens,
                "total_tokens": item.total_tokens,
                "cache_read_tokens": item.cache_read_tokens,
            }
            for item in values
        ]
    if isinstance(values, ModelUsage):
        return {
            "input_tokens": values.input_tokens,
            "output_tokens": values.output_tokens,
            "total_tokens": values.total_tokens,
            "cache_read_tokens": values.cache_read_tokens,
        }
    assert values is None
    return None


def _usage_records(
    values: tuple[ModelUsage | None, ...] | ModelUsage | None,
    *,
    stage: str,
    requested_model: str,
    served_model: str | None = None,
) -> dict[str, object]:
    """Render observed provider usage without turning missing data into zero."""
    items = (
        values if isinstance(values, tuple) else (() if values is None else (values,))
    )
    calls = [
        {
            "stage": stage,
            "requested_model": requested_model,
            "served_model": served_model,
            "input_tokens": None if item is None else item.input_tokens,
            "output_tokens": None if item is None else item.output_tokens,
            "total_tokens": None if item is None else item.total_tokens,
            "cache_read_tokens": None if item is None else item.cache_read_tokens,
        }
        for item in items
    ]
    observed = bool(calls) and any(
        value is not None
        for call in calls
        for value in (
            call["input_tokens"],
            call["output_tokens"],
            call["total_tokens"],
            call["cache_read_tokens"],
        )
    )
    return {"status": "observed" if observed else "unavailable", "calls": calls}


def _world_usage(
    events: tuple[WorldEvent, ...], requested_model: str
) -> dict[str, object]:
    """Collect usage from simulated World calls without counting them as turns."""
    calls = []
    for event in events:
        usage = getattr(event, "usage", None)
        if usage is None:
            continue
        calls.append(
            {
                "stage": "world",
                "requested_model": requested_model,
                "served_model": getattr(event, "model", None),
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "total_tokens": usage.total_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
            }
        )
    return {
        "status": "observed" if calls else "unavailable",
        "calls": calls,
    }


def _judge_attempts(judged: JudgeResult) -> tuple[JudgeAttempt, ...]:
    """Use explicit attempts when available, preserving legacy result objects."""
    if judged.attempts:
        return judged.attempts
    if judged.model is None and judged.usage is None:
        return ()
    return (JudgeAttempt(None, judged.model, judged.usage, "unavailable"),)


def _judge_usage_records(
    attempts: tuple[JudgeAttempt, ...], requested_model: str
) -> dict[str, object]:
    """Render each judge attempt with its own served model and usage."""
    calls: list[dict[str, object]] = []
    for attempt in attempts:
        usage = attempt.usage
        calls.append(
            {
                "stage": "semantic_judgment",
                "requested_model": requested_model,
                "served_model": attempt.model,
                "input_tokens": None if usage is None else usage.input_tokens,
                "output_tokens": None if usage is None else usage.output_tokens,
                "total_tokens": None if usage is None else usage.total_tokens,
                "cache_read_tokens": (
                    None if usage is None else usage.cache_read_tokens
                ),
            }
        )
    observed = bool(calls) and any(
        value is not None
        for call in calls
        for value in (
            call["input_tokens"],
            call["output_tokens"],
            call["total_tokens"],
            call["cache_read_tokens"],
        )
    )
    return {"status": "observed" if observed else "unavailable", "calls": calls}


def _judge_attempts_for(
    judged: JudgeResult | None, failure: InferenceFailure | None
) -> tuple[JudgeAttempt, ...]:
    if judged is not None:
        return _judge_attempts(judged)
    if isinstance(failure, JudgeFailure):
        return failure.attempts
    return ()


def _judge_attempt_data(
    attempt: JudgeAttempt, ordinal: int, requested_model: str
) -> dict[str, object]:
    raw = attempt.raw_response
    response: dict[str, object] = {
        "status": attempt.status,
        "bytes": None,
        "sha256": None,
    }
    if raw is not None:
        encoded = raw.encode("utf-8")
        response.update(
            {
                "bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )
    return {
        "ordinal": ordinal,
        "requested_model": requested_model,
        "served_model": attempt.model,
        "status": attempt.status,
        "response_metadata": response,
        "usage": _usage(attempt.usage),
    }


def _judge_attempts_data(
    attempts: tuple[JudgeAttempt, ...],
    requested_model: str,
) -> list[dict[str, object]]:
    return [
        _judge_attempt_data(attempt, ordinal, requested_model)
        for ordinal, attempt in enumerate(attempts, start=1)
    ]


def _judge_data(
    judged: JudgeResult | None, requested_model: str
) -> dict[str, object] | None:
    if judged is None:
        return None
    attempts = _judge_attempts(judged)
    return {
        "verdict": judged.verdict,
        "rationale": judged.rationale,
        "unmet_criteria": list(judged.unmet_criteria),
        "criteria": [
            {
                "criterion": item.criterion,
                "status": item.status,
                "evidence": item.evidence,
            }
            for item in judged.criteria
        ],
        "model": judged.model,
        "usage": _judge_usage_records(attempts, requested_model),
        "attempts": _judge_attempts_data(attempts, requested_model),
    }


def _judge_artifact_data(
    judged: JudgeResult | None,
    failure: InferenceFailure | None,
    requested_model: str,
) -> dict[str, object] | None:
    """Keep safe judge-attempt evidence even when no decision was accepted."""
    data = _judge_data(judged, requested_model)
    if data is not None:
        return data
    attempts = _judge_attempts_for(judged, failure)
    if not attempts:
        return None
    return {
        "status": "not_run",
        "usage": _judge_usage_records(attempts, requested_model),
        "attempts": _judge_attempts_data(attempts, requested_model),
    }


def _fact_status(assertions: tuple[AssertionResult, ...]) -> str:
    if not assertions:
        return "not_declared"
    return "passed" if all(item.passed for item in assertions) else "failed"


def _trusted_status(checks: tuple[CheckResult, ...]) -> str:
    if not checks:
        return "not_declared"
    if any(item.outcome == "ERROR" for item in checks):
        return "failed"
    if any(item.outcome == "FAIL" for item in checks):
        return "failed"
    if any(item.outcome == "SKIPPED" for item in checks):
        return "not_run"
    return "passed"


def _overall_text(
    outcome: str,
    judged: JudgeResult | None,
    assertions: tuple[AssertionResult, ...],
    checks: tuple[CheckResult, ...],
    failure: InferenceFailure | None,
) -> tuple[str, str]:
    if failure is not None:
        raw_stage = failure.stage or failure.kind.value
        stage = {
            "preflight": "checking the model connection",
            "execution": "running the skill",
            "world": "simulating the World",
            "semantic_judgment": "checking the success criteria",
            "evidence_writing": "saving the report",
        }.get(raw_stage, raw_stage.replace("_", " "))
        return (
            f"The eval stopped while {stage}: {failure.summary}",
            "Fix the reported problem, then run the eval again.",
        )
    if judged is None:
        return (
            "The skill finished, but SkillRoll could not check the success criteria.",
            "Inspect the report and rerun the case.",
        )
    if judged.verdict == "FAIL":
        return (
            "The skill did not meet the success criteria.",
            "Review the unmet criteria and the transcript before changing the "
            "skill or eval.",
        )
    if any(not item.passed for item in assertions):
        return (
            "The skill met the success criteria, but an exact output check failed.",
            "Review the exact-check evidence and decide whether the check or "
            "the skill's final response needs correction.",
        )
    if any(item.outcome == "SKIPPED" for item in checks):
        return (
            "The skill met the success criteria, but a repository check did not run.",
            "Run the listed command explicitly if its result is required.",
        )
    if any(item.outcome in {"FAIL", "ERROR"} for item in checks):
        return (
            "The skill met the success criteria, but a repository check failed.",
            "Inspect the check log and fix the artifact or command.",
        )
    return (
        "The skill met every success criterion.",
        "Keep this eval as regression coverage.",
    )


def _estimate_cost(
    usage_sections: tuple[dict[str, object], ...],
    pricing: ModelPricing | None,
    currency: str = "USD",
) -> dict[str, object]:
    """Estimate cost only when the user supplied rates and complete usage."""
    calls: list[dict[str, object]] = []
    for section in usage_sections:
        values = section.get("calls", ())
        if isinstance(values, (list, tuple)):
            calls.extend(call for call in values if isinstance(call, dict))
    if pricing is None:
        return {"status": "unavailable", "reason": "no user-supplied pricing"}
    if not calls:
        return {"status": "unavailable", "reason": "no provider usage recorded"}
    for call in calls:
        input_tokens = call.get("input_tokens")
        output_tokens = call.get("output_tokens")
        cache_read_tokens = call.get("cache_read_tokens")
        if (
            not isinstance(input_tokens, int)
            or not isinstance(output_tokens, int)
            or (
                cache_read_tokens is not None
                and (
                    not isinstance(cache_read_tokens, int)
                    or cache_read_tokens < 0
                    or cache_read_tokens > input_tokens
                )
            )
            or (
                isinstance(cache_read_tokens, int)
                and cache_read_tokens > 0
                and pricing.cache_read_per_million is None
            )
        ):
            return {"status": "unavailable", "reason": "provider usage is incomplete"}
    amount = 0.0
    for call in calls:
        input_tokens = cast(int, call["input_tokens"])
        output_tokens = cast(int, call["output_tokens"])
        cache_read_tokens = cast(int | None, call.get("cache_read_tokens")) or 0
        amount += (
            (input_tokens - cache_read_tokens) * pricing.input_per_million
            + output_tokens * pricing.output_per_million
            + cache_read_tokens * (pricing.cache_read_per_million or 0.0)
        )
    result: dict[str, object] = {
        "status": "estimated",
        "currency": currency,
        "amount": round(amount / 1_000_000, 8),
        "input_per_million": pricing.input_per_million,
        "output_per_million": pricing.output_per_million,
    }
    if pricing.cache_read_per_million is not None:
        result["cache_read_per_million"] = pricing.cache_read_per_million
    return result


def _result_summary(
    case: EvalCase,
    outcome: str,
    execution: ExecutionResult | None,
    events: tuple[WorldEvent, ...],
    limits: InferenceLimits,
    judged: JudgeResult | None,
    assertions: tuple[AssertionResult, ...],
    checks: tuple[CheckResult, ...],
    failure: InferenceFailure | None,
    requested_model: str,
    failure_stage: str | None = None,
    pricing: ModelPricing | None = None,
    pricing_currency: str = "USD",
    profile_name: str | None = None,
    profile_purpose: str | None = None,
    skill_available: bool = True,
) -> dict[str, object]:
    overall_explanation, next_action = _overall_text(
        outcome, judged, assertions, checks, failure
    )
    judge_data = _judge_data(judged, requested_model)
    execution_present = execution is not None
    check_failure = next((item for item in checks if item.outcome == "ERROR"), None)
    technical_status = (
        "error" if failure is not None or check_failure is not None else "completed"
    )
    technical_stage = (
        failure_stage or _failure_stage(failure)
        if failure is not None
        else "trusted_repository_checks"
        if check_failure is not None
        else None
    )
    technical_message = (
        failure.summary
        if failure is not None
        else None
        if check_failure is None
        else check_failure.detail or "A repository check could not finish."
    )
    technical_details = (
        failure.details
        if failure is not None
        else ()
        if check_failure is None
        else (check_failure.detail,)
    )
    execution_usage = _usage_records(
        None if execution is None else execution.usage,
        stage="execution",
        requested_model=requested_model,
    )
    world_usage = _world_usage(events, requested_model)
    judge_attempts = _judge_attempts_for(judged, failure)
    judge_usage = _judge_usage_records(judge_attempts, requested_model)
    semantic_judgment: dict[str, object] = {
        "status": "accepted"
        if judged is not None and judged.verdict == "PASS"
        else "rejected"
        if judged is not None and judged.verdict == "FAIL"
        else "not_run",
    }
    if judge_data is not None:
        semantic_judgment.update(judge_data)
    elif judge_attempts:
        semantic_judgment.update(
            {
                "usage": judge_usage,
                "attempts": _judge_attempts_data(judge_attempts, requested_model),
            }
        )
    execution_status = "completed" if execution_present else "not_completed"
    return {
        "skill": case.skill.identity.as_posix(),
        "case": case.identity.as_posix(),
        "overall": {
            "outcome": outcome,
            "explanation": overall_explanation,
            "next_action": next_action,
        },
        "execution": {
            "status": execution_status,
            "final_response_produced": execution_present,
            "requested_model": requested_model,
            "model_profile": profile_name,
            "model_profile_purpose": profile_purpose,
            "skill_instructions_available": skill_available,
            "model_turns_used": None if execution is None else execution.turns,
            "model_turns_source": (
                "unavailable" if execution is None else execution.turns_source
            ),
            "model_turn_limit": limits.max_turns,
            "world_actions_used": len(events),
            "world_action_safety_limit": MAX_WORLD_ACTIONS_PER_CASE,
            "usage": execution_usage,
            "world_usage": world_usage,
        },
        "semantic_judgment": semantic_judgment,
        "exact_fact_checks": {
            "status": _fact_status(assertions),
            "items": _assertions(assertions),
        },
        "trusted_repository_checks": {
            "status": _trusted_status(checks),
            "items": _checks(checks),
        },
        "technical_status": {
            "status": technical_status,
            "stage": technical_stage,
            "message": technical_message,
            "details": technical_details,
        },
        "cost": _estimate_cost(
            (execution_usage, world_usage, judge_usage),
            pricing,
            pricing_currency,
        ),
    }


def _assertions(values: tuple[AssertionResult, ...]) -> list[dict[str, object]]:
    return [
        {
            "ordinal": item.ordinal,
            "kind": item.assertion.kind,
            "expected": item.assertion.expected_text,
            "passed": item.passed,
            "observed": item.observed,
        }
        for item in values
    ]


def _checks(values: tuple[CheckResult, ...]) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "name": item.check.name,
            "command": item.check.command,
            "source": item.check.location.path,
            "covers": [path.as_posix() for path in item.check.covers],
            "outcome": item.outcome,
            "exit_code": item.exit_code,
            "duration_seconds": item.duration_seconds,
            "detail": item.detail,
            "stdout_log": None if not item.started else f"checks/{ordinal}-stdout.log",
            "stderr_log": None if not item.started else f"checks/{ordinal}-stderr.log",
        }
        for ordinal, item in enumerate(values, start=1)
    )


def _failure_result(
    failure: InferenceFailure, redactor: SecretRedactor | None = None
) -> CommandResult:
    summary = "SkillRoll could not prepare the configured evaluation."
    action: str | None = None
    if failure.kind is InferenceFailureKind.MISSING_CONFIGURATION:
        summary = (
            "SkillRoll cannot evaluate this repository until a model endpoint "
            "is configured."
        )
        action = (
            "Add base_url, api_key_env, and either model or profiles under "
            "[inference] in skillroll.toml, set that environment variable, then run "
            "skillroll doctor."
        )
    elif failure.kind is InferenceFailureKind.MISSING_API_KEY:
        action = (
            "Set the named key in your shell or CI secret, then run skillroll doctor."
        )
    return CommandResult(
        Outcome.ERROR,
        summary,
        (
            Diagnostic(
                "SCE" + failure.kind.value.upper(),
                failure.summary,
                details=(
                    failure.details
                    if redactor is None
                    else bounded_failure_details(failure, redactor)
                ),
                next_action=action,
            ),
        ),
    )


def _failure_stage(failure: InferenceFailure) -> str:
    """Return a stable stage label even for failures from older seams."""
    if failure.stage is not None:
        return failure.stage
    if failure.kind is InferenceFailureKind.JUDGE_INTEGRITY:
        return "semantic_judgment"
    return "execution"


async def _resolve_profile(
    config: SkillRollConfig,
    environment: Mapping[str, str],
    transport_factory: TransportFactory,
    model_profile: str | None,
) -> tuple[ResolvedInference, ChatTransport] | InferenceFailure:
    """Run compatibility preflight once and retain the selected transport."""
    candidates, failure = resolve_inference_candidates(
        config.inference, environment, model_profile
    )
    if failure is not None:
        return failure
    assert candidates
    profile: ResolvedInference | None = None
    transport: ChatTransport | None = None
    preflight_failures: list[str] = []
    last_preflight_failure: InferenceFailure | None = None
    for candidate in candidates:
        candidate_transport = transport_factory(candidate)
        preflight = await run_preflight(candidate, candidate_transport)
        if preflight.passed:
            profile = candidate
            transport = candidate_transport
            break
        assert preflight.failure is not None
        last_preflight_failure = preflight.failure
        preflight_failures.append(f"{candidate.model}: {preflight.failure.summary}")
        await candidate_transport.close()
    if profile is None or transport is None:
        assert last_preflight_failure is not None
        return replace(
            last_preflight_failure,
            summary=(
                "No ranked model candidate completed SkillRoll's compatibility check."
            ),
            details=tuple(preflight_failures),
            stage="preflight",
        )
    return profile, transport


async def evaluate_repository(
    config: SkillRollConfig,
    cases: tuple[EvalCase, ...],
    *,
    environment: Mapping[str, str],
    run_commands: bool,
    transport_factory: TransportFactory = _transport,
    executor_factory: ExecutorFactory = _executor,
    check_runner: CheckRunner | None = None,
    store_factory: StoreFactory = _store,
    model_profile: str | None = None,
    skill_available: bool = True,
    _resolved: tuple[ResolvedInference, ChatTransport] | None = None,
    _close_transport: bool = True,
) -> tuple[CaseResult, ...] | InferenceFailure:
    """Evaluate every selected case once, in stable order, after one preflight."""
    resolved = _resolved or await _resolve_profile(
        config, environment, transport_factory, model_profile
    )
    if isinstance(resolved, InferenceFailure):
        return resolved
    profile, transport = resolved
    try:
        redactor = SecretRedactor(profile.api_key)
        store = store_factory(config.repository_root, redactor)
        executor = executor_factory(profile)
        runner = HostCheckRunner() if check_runner is None else check_runner
        results: list[CaseResult] = []
        for case in sorted(cases, key=lambda item: item.identity.as_posix()):
            preliminary = await execute_preliminary(
                config,
                case,
                profile,
                executor,
                transport,
                store,
                skill_available=skill_available,
            )
            events = preliminary.events
            checks: tuple[CheckResult, ...] = ()
            assertions: tuple[AssertionResult, ...] = ()
            judged: JudgeResult | None = None
            failure = preliminary.failure
            failure_stage = "execution" if failure is not None else None
            execution = (
                None if preliminary.execution is None else preliminary.execution.result
            )
            limits = effective_limits(profile.limits, case.limits)
            if limits is None:
                limits = profile.limits
            directory = (
                None
                if preliminary.artifact_directory is None
                else config.repository_root / preliminary.artifact_directory
            )
            if failure is None and execution is not None and directory is not None:
                assertions = evaluate_assertions(
                    case.assertions, execution.final_output
                )
                judged, failure = await judge(
                    replace(profile, limits=limits),
                    transport,
                    case,
                    execution,
                    events,
                    skill_available=skill_available,
                )
                if failure is not None:
                    failure_stage = "semantic_judgment"
                try:
                    store.append(
                        directory,
                        (
                            (
                                "execution.json",
                                execution_bytes(
                                    execution.final_output,
                                    execution.turns,
                                    {
                                        "execution": _usage_records(
                                            execution.usage,
                                            stage="execution",
                                            requested_model=profile.model,
                                        ),
                                        "world": _world_usage(events, profile.model),
                                    },
                                    turns_source=execution.turns_source,
                                ),
                            ),
                            (
                                "judge.json",
                                judge_bytes(
                                    _judge_artifact_data(
                                        judged, failure, profile.model
                                    ),
                                    _assertions(assertions),
                                ),
                            ),
                        ),
                    )
                except ArtifactError as error:
                    failure = InferenceFailure(
                        InferenceFailureKind.EXECUTION_ERROR, str(error)
                    )
                    failure_stage = "evidence_writing"
                if failure is None:
                    collected = []
                    for check in case.checks if skill_available else ():
                        request = CheckRequest(
                            case, check, "eval", config.repository_root, directory
                        )
                        observed = (
                            await runner.run(
                                request, check_environment(config, request, environment)
                            )
                            if run_commands
                            else skipped_check(request)
                        )
                        collected.append(
                            redact_check_result(
                                observed, SecretRedactor(profile.api_key)
                            )
                        )
                    checks = tuple(collected)
            if failure is not None:
                failure = replace(failure, stage=failure_stage or failure.stage)
            outcome = case_outcome(failure, judged, assertions, checks)
            result = CaseResult(
                case,
                outcome,
                execution,
                judged,
                assertions,
                checks,
                failure,
                preliminary.artifact_directory,
                events,
                skill_available,
            )
            if directory is not None:
                try:
                    check_data = _checks(checks)
                    log_values = tuple(
                        value
                        for ordinal, item in enumerate(checks, start=1)
                        if item.started
                        for value in (
                            (
                                f"checks/{ordinal}-stdout.log",
                                item.stdout.encode("utf-8"),
                            ),
                            (
                                f"checks/{ordinal}-stderr.log",
                                item.stderr.encode("utf-8"),
                            ),
                        )
                    )
                    judge_data = _judge_data(judged, profile.model)
                    summary = _result_summary(
                        case,
                        outcome,
                        execution,
                        events,
                        limits,
                        judged,
                        assertions,
                        checks,
                        failure,
                        profile.model,
                        failure_stage=failure_stage,
                        pricing=(
                            None
                            if config.pricing is None
                            else config.pricing.models.get(profile.model)
                        ),
                        pricing_currency=(
                            "USD" if config.pricing is None else config.pricing.currency
                        ),
                        profile_name=profile.profile_name,
                        profile_purpose=profile.profile_purpose,
                        skill_available=skill_available,
                    )
                    store.append(
                        directory,
                        (
                            (
                                "verdict.json",
                                verdict_bytes(
                                    outcome,
                                    None if failure is None else failure.summary,
                                    ()
                                    if failure is None
                                    else bounded_failure_details(failure, redactor),
                                ),
                            ),
                            ("checks.json", checks_bytes(check_data)),
                            ("result.json", result_bytes(summary)),
                            (
                                "report.md",
                                final_report_bytes(
                                    case.skill.identity.as_posix(),
                                    case.identity.as_posix(),
                                    outcome,
                                    judge_data,
                                    tuple(_assertions(assertions)),
                                    check_data,
                                    None if failure is None else failure.summary,
                                    ()
                                    if failure is None
                                    else bounded_failure_details(failure, redactor),
                                    finished=execution is not None,
                                    events=preliminary.events,
                                    execution_turns=(
                                        None if execution is None else execution.turns
                                    ),
                                    execution_turn_limit=limits.max_turns,
                                    execution_turns_source=(
                                        "unavailable"
                                        if execution is None
                                        else execution.turns_source
                                    ),
                                    failure_stage=failure_stage,
                                    model=profile.model,
                                    model_profile=profile.profile_name,
                                    model_profile_purpose=profile.profile_purpose,
                                    skill_available=skill_available,
                                ),
                            ),
                        )
                        + log_values,
                    )
                except ArtifactError as error:
                    result = CaseResult(
                        case,
                        "ERROR",
                        execution,
                        judged,
                        assertions,
                        checks,
                        InferenceFailure(
                            InferenceFailureKind.EXECUTION_ERROR,
                            str(error),
                            stage="evidence_writing",
                        ),
                        preliminary.artifact_directory,
                        events,
                        skill_available,
                    )
            results.append(result)
        return tuple(results)
    finally:
        if _close_transport:
            await transport.close()


@dataclass(frozen=True, slots=True)
class ExperimentPair:
    """One sample's selected-skill run and optional omission control."""

    sample: int
    skill: CaseResult
    control: CaseResult | None


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    """A research experiment plus its parent evidence directory."""

    pairs: tuple[ExperimentPair, ...]
    artifact_directory: PurePosixPath
    summary: Mapping[str, object]


def _outcome_counts(values: tuple[CaseResult, ...]) -> dict[str, int]:
    return {
        name: sum(item.outcome == name for item in values)
        for name in ("PASS", "FAIL", "INCOMPLETE", "ERROR")
    }


def _control_interpretation(skill: CaseResult, control: CaseResult | None) -> str:
    if control is None:
        return "Samples were run without the optional no-skill comparison."
    if skill.outcome in {"ERROR", "INCOMPLETE"} or control.outcome in {
        "ERROR",
        "INCOMPLETE",
    }:
        return (
            "The comparison is inconclusive because one or both runs did not "
            "produce a trustworthy result."
        )
    if skill.outcome == "PASS" and control.outcome == "FAIL":
        return "This sample passed with the skill and failed without it."
    if control.outcome == "PASS":
        return (
            "This case passed without the skill; Input, World, criteria, "
            "or general model behavior may be carrying the result."
        )
    if skill.outcome == "FAIL":
        return "The skill did not pass this sample."
    return "The skill passed, but the no-skill run did not produce a clear comparison."


def _experiment_usage(
    results: tuple[CaseResult, ...], requested_model: str
) -> dict[str, object]:
    calls: list[dict[str, object]] = []
    for item in results:
        sections = (
            _usage_records(
                None if item.execution is None else item.execution.usage,
                stage="execution",
                requested_model=requested_model,
            ),
            _world_usage(item.events, requested_model),
            _judge_usage_records(
                _judge_attempts_for(item.judge, item.failure),
                requested_model,
            ),
        )
        for section in sections:
            values = section.get("calls", ())
            if isinstance(values, (list, tuple)):
                calls.extend(call for call in values if isinstance(call, dict))
    return {"status": "observed" if calls else "unavailable", "calls": calls}


def _experiment_interpretation(
    pairs: tuple[ExperimentPair, ...], with_control: bool
) -> dict[str, str]:
    skill = tuple(pair.skill for pair in pairs)
    controls = tuple(pair.control for pair in pairs if pair.control is not None)
    if not with_control:
        return {
            "status": "sampling_only",
            "explanation": (
                "Independent samples were collected without a no-skill comparison."
            ),
            "next_action": (
                "Inspect outcome variance and add --with-skill-control before "
                "treating the case as a strong regression signal."
            ),
        }
    if any(item.outcome in {"ERROR", "INCOMPLETE"} for item in skill + controls):
        return {
            "status": "technically_inconclusive",
            "explanation": (
                "At least one skill or no-skill run did not "
                "produce trustworthy evidence."
            ),
            "next_action": (
                "Fix the technical error or World setup, then run the comparison again."
            ),
        }
    if not any(item.outcome == "PASS" for item in skill):
        return {
            "status": "skill_not_ready",
            "explanation": ("The skill did not pass any sample."),
            "next_action": (
                "Inspect the transcripts and criteria before "
                "changing the control or raising the model."
            ),
        }
    distinguished = bool(pairs) and all(
        pair.skill.outcome == "PASS"
        and pair.control is not None
        and pair.control.outcome == "FAIL"
        for pair in pairs
    )
    if distinguished:
        return {
            "status": "consistent_discrimination",
            "explanation": (
                "Every sample passed with the skill and failed without it."
            ),
            "next_action": (
                "Review the paired evidence and record the model, cost, and "
                "remaining variance before adopting the case."
            ),
        }
    if any(
        pair.skill.outcome == "PASS"
        and pair.control is not None
        and pair.control.outcome == "FAIL"
        for pair in pairs
    ):
        return {
            "status": "mixed_discrimination",
            "explanation": (
                "Some samples distinguish the selected skill, but the comparison "
                "is not consistent across samples."
            ),
            "next_action": (
                "Inspect the divergent transcripts and decide whether the cause "
                "is model variance, scenario design, World state, or skill "
                "behavior."
            ),
        }
    return {
        "status": "no_observed_discrimination",
        "explanation": (
            "The samples did not perform better with the skill than without it."
        ),
        "next_action": (
            "Review Input, World, and success criteria for leaked answers or "
            "an overly general task."
        ),
    }


async def evaluate_experiment(
    config: SkillRollConfig,
    cases: tuple[EvalCase, ...],
    *,
    environment: Mapping[str, str],
    run_commands: bool,
    samples: int,
    with_skill_control: bool,
    transport_factory: TransportFactory = _transport,
    executor_factory: ExecutorFactory = _executor,
    check_runner: CheckRunner | None = None,
    store_factory: StoreFactory = _store,
    model_profile: str | None = None,
) -> ExperimentResult | InferenceFailure:
    """Collect independent samples and optional paired skill-omission controls."""
    resolved = await _resolve_profile(
        config, environment, transport_factory, model_profile
    )
    if isinstance(resolved, InferenceFailure):
        return resolved
    profile, transport = resolved
    redactor = SecretRedactor(profile.api_key)
    parent_store = store_factory(config.repository_root, redactor)
    pairs: list[ExperimentPair] = []
    try:
        for sample in range(1, samples + 1):
            selected = await evaluate_repository(
                config,
                cases,
                environment=environment,
                run_commands=run_commands,
                transport_factory=transport_factory,
                executor_factory=executor_factory,
                check_runner=check_runner,
                store_factory=store_factory,
                model_profile=model_profile,
                skill_available=True,
                _resolved=(profile, transport),
                _close_transport=False,
            )
            if isinstance(selected, InferenceFailure):
                return selected
            controls: tuple[CaseResult, ...] = ()
            if with_skill_control:
                control_values = await evaluate_repository(
                    config,
                    cases,
                    environment=environment,
                    run_commands=False,
                    transport_factory=transport_factory,
                    executor_factory=executor_factory,
                    check_runner=check_runner,
                    store_factory=store_factory,
                    model_profile=model_profile,
                    skill_available=False,
                    _resolved=(profile, transport),
                    _close_transport=False,
                )
                if isinstance(control_values, InferenceFailure):
                    return control_values
                controls = control_values
            for index, skill_result in enumerate(selected):
                pairs.append(
                    ExperimentPair(
                        sample,
                        skill_result,
                        None if not with_skill_control else controls[index],
                    )
                )
    finally:
        await transport.close()

    frozen_pairs = tuple(pairs)
    skill_runs = tuple(pair.skill for pair in frozen_pairs)
    control_runs = tuple(
        pair.control for pair in frozen_pairs if pair.control is not None
    )
    interpretation = _experiment_interpretation(frozen_pairs, with_skill_control)
    experiment_id, directory = parent_store.create_experiment()
    summary: dict[str, object] = {
        "experiment_id": experiment_id,
        "case": (cases[0].identity.as_posix() if len(cases) == 1 else "selected cases"),
        "cases": [case.identity.as_posix() for case in cases],
        "model": profile.model,
        "model_profile": profile.profile_name,
        "model_profile_purpose": profile.profile_purpose,
        "samples_requested": samples,
        "with_skill_control": with_skill_control,
        "skill_runs": _outcome_counts(skill_runs),
        "skill_control_runs": _outcome_counts(control_runs),
        "paired_comparisons": [
            {
                "sample": pair.sample,
                "case": pair.skill.case.identity.as_posix(),
                "skill_run": {
                    "outcome": pair.skill.outcome,
                    "artifact_directory": (
                        None
                        if pair.skill.artifact_directory is None
                        else pair.skill.artifact_directory.as_posix()
                    ),
                },
                "skill_control_run": (
                    None
                    if pair.control is None
                    else {
                        "outcome": pair.control.outcome,
                        "artifact_directory": (
                            None
                            if pair.control.artifact_directory is None
                            else pair.control.artifact_directory.as_posix()
                        ),
                    }
                ),
                "control_interpretation": _control_interpretation(
                    pair.skill, pair.control
                ),
            }
            for pair in frozen_pairs
        ],
        "usage": {
            "skill_runs": _experiment_usage(skill_runs, profile.model),
            "skill_control_runs": _experiment_usage(control_runs, profile.model),
        },
        "cost": {
            "skill_runs": _estimate_cost(
                (_experiment_usage(skill_runs, profile.model),),
                None
                if config.pricing is None
                else config.pricing.models.get(profile.model),
                "USD" if config.pricing is None else config.pricing.currency,
            ),
            "skill_control_runs": _estimate_cost(
                (_experiment_usage(control_runs, profile.model),),
                None
                if config.pricing is None
                else config.pricing.models.get(profile.model),
                "USD" if config.pricing is None else config.pricing.currency,
            ),
        },
        "interpretation": interpretation,
        "artifact_directory": (
            PurePosixPath(".skillroll") / "experiments" / experiment_id
        ).as_posix(),
    }
    try:
        parent_store.write_experiment(
            directory,
            experiment_bytes(summary),
            experiment_report_bytes(summary),
        )
    except ArtifactError as error:
        return InferenceFailure(
            InferenceFailureKind.EXECUTION_ERROR,
            str(error),
            stage="evidence_writing",
        )
    return ExperimentResult(
        frozen_pairs,
        PurePosixPath(".skillroll") / "experiments" / experiment_id,
        summary,
    )


def run(
    *,
    repo: str | None = None,
    skill: str | None = None,
    case: str | None = None,
    all_cases: bool = False,
    run_commands: bool = False,
    environment: Mapping[str, str] | None = None,
    transport_factory: TransportFactory = _transport,
    executor_factory: ExecutorFactory = _executor,
    check_runner: CheckRunner | None = None,
    store_factory: StoreFactory = _store,
    selected_cases: tuple[EvalCase, ...] | None = None,
    model_profile: str | None = None,
    samples: int = 1,
    with_skill_control: bool = False,
) -> CommandResult:
    """Resolve the local scope, validate, then run the complete pipeline."""
    if samples < 1 or samples > 10:
        return CommandResult(
            Outcome.ERROR,
            "SkillRoll could not start the comparison.",
            (
                Diagnostic(
                    "SCE2001",
                    "--samples must be an integer from 1 to 10.",
                    next_action=(
                        "Choose a sample count from 1 to 10. Use --with-skill-control "
                        "to compare each sample with the selected skill omitted."
                    ),
                ),
            ),
        )
    if repo is None:
        working_directory = current_directory()
        root = find_repository_root(working_directory)
        scope = (
            None
            if all_cases or skill is not None or case is not None
            else working_directory
        )
    else:
        root = Path(repo)
        scope = None
    selection = selection_from_strings(skill, case)
    report = (
        validate_repository(root, selection)
        if scope is None
        else validate_repository(root, selection, scope=scope)
    )
    validation = command_result(report)
    if validation.outcome is not Outcome.PASS or report.config is None:
        return validation
    values = os.environ if environment is None else environment
    research_mode = samples != 1 or with_skill_control
    try:
        result = asyncio.run(
            evaluate_experiment(
                report.config,
                report.cases if selected_cases is None else selected_cases,
                environment=values,
                run_commands=run_commands,
                samples=samples,
                with_skill_control=with_skill_control,
                transport_factory=transport_factory,
                executor_factory=executor_factory,
                check_runner=check_runner,
                store_factory=store_factory,
                model_profile=model_profile,
            )
            if research_mode
            else evaluate_repository(
                report.config,
                report.cases if selected_cases is None else selected_cases,
                environment=values,
                run_commands=run_commands,
                transport_factory=transport_factory,
                executor_factory=executor_factory,
                check_runner=check_runner,
                store_factory=store_factory,
                model_profile=model_profile,
            )
        )
    except KeyboardInterrupt:
        return _failure_result(
            InferenceFailure(
                InferenceFailureKind.CANCELLED,
                "The evaluation was cancelled before it finished.",
            )
        )
    if isinstance(result, InferenceFailure):
        return _failure_result(
            result,
            SecretRedactor(
                SecretValue(
                    ""
                    if report.config.inference is None
                    else values.get(report.config.inference.api_key_env, "")
                )
            ),
        )
    experiment = result if isinstance(result, ExperimentResult) else None
    if experiment is not None:
        case_results = tuple(pair.skill for pair in experiment.pairs)
    else:
        assert isinstance(result, tuple)
        case_results = result
    outcome = aggregate(case_results)
    redactor = SecretRedactor(
        SecretValue(
            ""
            if report.config.inference is None
            else values.get(report.config.inference.api_key_env, "")
        )
    )
    diagnostics = (
        tuple(
            Diagnostic(
                "SCE1001",
                item.failure.summary,
                affected=item.case.identity.as_posix(),
                details=(
                    f"Technical stage: {_failure_stage(item.failure)}",
                    *bounded_failure_details(item.failure, redactor),
                ),
                next_action=(
                    "Inspect the case's result.json and rerun after addressing the "
                    "reported technical stage."
                ),
            )
            for item in case_results
            if item.failure is not None
        )
        + tuple(
            Diagnostic(
                "SCE1002",
                check.detail or "A required repository check was not run.",
                affected=(
                    f"{item.case.identity.as_posix()}: check “{check.check.name}”"
                ),
                location=check.check.location,
                next_action=(
                    "Run the exact command above only after you trust this repository."
                ),
            )
            for item in case_results
            for check in item.checks
            if check.outcome == "SKIPPED"
        )
        + tuple(
            Diagnostic(
                "SCE1003" if check.outcome == "FAIL" else "SCE1004",
                (
                    "This repository check exited with a nonzero status."
                    if check.outcome == "FAIL"
                    else check.detail or "A repository check could not finish."
                ),
                affected=(
                    f"{item.case.identity.as_posix()}: check “{check.check.name}”"
                ),
                location=check.check.location,
                details=(f"Command: {check.check.command}",),
            )
            for item in case_results
            for check in item.checks
            if check.outcome in {"FAIL", "ERROR"}
        )
    )
    outcome_counts = {
        value: sum(item.outcome == value for item in case_results)
        for value in ("PASS", "FAIL", "INCOMPLETE", "ERROR")
    }
    semantic_counts = {
        "accepted": sum(
            item.judge is not None and item.judge.verdict == "PASS"
            for item in case_results
        ),
        "rejected": sum(
            item.judge is not None and item.judge.verdict == "FAIL"
            for item in case_results
        ),
        "not_run": sum(item.judge is None for item in case_results),
    }
    trusted_counts = {
        "passed": sum(
            bool(item.checks) and all(check.outcome == "PASS" for check in item.checks)
            for item in case_results
        ),
        "not_run": sum(
            any(check.outcome == "SKIPPED" for check in item.checks)
            for item in case_results
        ),
        "failed": sum(
            any(check.outcome in {"FAIL", "ERROR"} for check in item.checks)
            for item in case_results
        ),
    }
    if len(case_results) == 1 and experiment is None:
        case_result = case_results[0]
        summary_text = {
            "PASS": " met every success criterion.",
            "FAIL": " missed at least one success criterion.",
            "INCOMPLETE": " needs a repository check that did not run.",
            "ERROR": " could not produce a trustworthy result.",
        }[case_result.outcome]
        summary_text = case_result.case.identity.as_posix() + summary_text
    else:
        counts = (
            ("passed", outcome_counts["PASS"]),
            ("failed", outcome_counts["FAIL"]),
            ("incomplete", outcome_counts["INCOMPLETE"]),
            ("errors", outcome_counts["ERROR"]),
        )
        count_text = ", ".join(f"{count} {label}" for label, count in counts if count)
        subject = "sampled runs" if experiment is not None else "evals"
        summary_text = f"Ran {len(case_results)} {subject}: {count_text}."
    if experiment is not None:
        report_text = (
            " Report: " + experiment.artifact_directory.as_posix() + "/report.md."
        )
    else:
        report_paths = tuple(
            item.artifact_directory / "report.md"
            for item in case_results
            if item.artifact_directory is not None
        )
        report_text = (
            ""
            if not report_paths
            else f" Report: {report_paths[0].as_posix()}."
            if len(report_paths) == 1
            else f" Reports: {len(report_paths)} run folders under .skillroll/runs/."
        )
    return CommandResult(
        outcome,
        summary_text
        + (
            " Parent experiment: " + experiment.artifact_directory.as_posix() + "."
            if experiment is not None
            else ""
        )
        + report_text,
        diagnostics,
        {
            "outcome_counts": outcome_counts,
            "semantic_judgment_counts": semantic_counts,
            "trusted_check_counts": trusted_counts,
            **(
                {}
                if experiment is None
                else {
                    "experiment": cast(Mapping[str, JSONValue], experiment.summary),
                    "experiment_artifact_directory": (
                        experiment.artifact_directory.as_posix()
                    ),
                }
            ),
            "cases": tuple(
                {
                    "case": item.case.identity.as_posix(),
                    "outcome": item.outcome,
                    "artifact_directory": None
                    if item.artifact_directory is None
                    else item.artifact_directory.as_posix(),
                }
                for item in case_results
            ),
        },
    )
