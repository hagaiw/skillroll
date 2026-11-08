"""Reproducible, local evidence for explicit executor-model comparisons."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import os
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import urlsplit, urlunsplit

from skillroll.artifacts.hashes import InputHash
from skillroll.artifacts.records import canonical_json
from skillroll.artifacts.store import ArtifactError, ArtifactStore
from skillroll.checks import CheckRunner
from skillroll.commands.evaluate import (
    ExecutorFactory,
    StoreFactory,
    TransportFactory,
    _estimate_cost,
    _execution_usage_complete,
    _executor,
    _failure_result,
    _store,
    _transport,
    _usage_records,
    _world_usage,
    evaluate_repository,
)
from skillroll.diagnostics import CommandResult, Diagnostic, JSONValue
from skillroll.inference.preflight import PreflightEvidence, run_preflight
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
    SecretRedactor,
    SecretValue,
    bounded_failure_details,
    resolve_inference_candidates,
)
from skillroll.inference.transport import ChatTransport
from skillroll.models import EvalCase, ModelPricing, SkillRollConfig, effective_limits
from skillroll.outcomes import Outcome
from skillroll.prompt_resources import PromptName, load_harness_prompt
from skillroll.repository_io import current_directory, find_repository_root
from skillroll.runtime.attempt import input_hashes
from skillroll.validation import (
    command_result,
    selection_from_strings,
    validate_repository,
)
from skillroll.verdicts import CaseResult
from skillroll.world.bundle import BundleError, BundleIndex, build_bundle

_OUTCOMES = ("PASS", "FAIL", "ERROR", "INCOMPLETE", "NOT_RUN")
_PROMPTS = ("executor", "executor_omission", "world", "judge")
_DEPENDENCIES = (
    "openai-agents",
    "openai",
    "pydantic",
    "httpx",
    "markdown-it-py",
    "PyYAML",
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_data(values: Sequence[InputHash]) -> list[dict[str, object]]:
    return [
        {
            "identity": item.identity.as_posix(),
            "kind": item.kind,
            "sha256": item.sha256,
            "bytes": item.bytes,
        }
        for item in sorted(values, key=lambda item: item.identity.as_posix())
    ]


def _current_input_hashes(
    config: SkillRollConfig, cases: tuple[EvalCase, ...]
) -> tuple[InputHash, ...]:
    """Hash the configuration, selected cases, and every selected skill bundle."""
    values: dict[str, InputHash] = {}
    bundles: dict[Path, BundleIndex] = {}
    for case in cases:
        bundle = bundles.get(case.skill.root)
        if bundle is None:
            bundle = build_bundle(case.skill.root)
            bundles[case.skill.root] = bundle
        case_values = input_hashes(config, case, bundle)
        for item in case_values:
            identity = item.identity.as_posix()
            previous = values.get(identity)
            if previous is not None and previous != item:
                raise ValueError(
                    f"SkillRoll observed inconsistent bytes for input {identity}."
                )
            values[identity] = item
    return tuple(sorted(values.values(), key=lambda item: item.identity.as_posix()))


def _harness_fingerprint() -> dict[str, object]:
    """Fingerprint installed package source, effective prompts, and key versions."""
    package_root = Path(__file__).resolve().parents[1]
    source_files: list[dict[str, object]] = []
    for directory, child_directories, filenames in os.walk(
        package_root, followlinks=False
    ):
        current = Path(directory)
        child_directories[:] = [
            name for name in child_directories if not (current / name).is_symlink()
        ]
        for filename in filenames:
            source = current / filename
            if not filename.endswith(".py") or source.is_symlink():
                continue
            try:
                raw = source.read_bytes()
            except OSError as error:
                raise ValueError(
                    "SkillRoll could not fingerprint its installed Python source."
                ) from error
            source_files.append(
                {
                    "identity": PurePosixPath(
                        "skillroll", source.relative_to(package_root).as_posix()
                    ).as_posix(),
                    "sha256": _sha256(raw),
                    "bytes": len(raw),
                }
            )
    source_files.sort(key=lambda item: cast(str, item["identity"]))

    prompt_hashes = {
        name: _sha256(load_harness_prompt(cast(PromptName, name)).encode("utf-8"))
        for name in _PROMPTS
    }
    try:
        version = importlib.metadata.version("skillroll")
    except importlib.metadata.PackageNotFoundError:
        from skillroll._version import __version__

        version = __version__
    dependencies: dict[str, str | None] = {}
    for dependency in _DEPENDENCIES:
        try:
            dependencies[dependency] = importlib.metadata.version(dependency)
        except importlib.metadata.PackageNotFoundError:
            dependencies[dependency] = None
    payload = {
        "package_version": version,
        "source_files": source_files,
        "effective_prompt_sha256": prompt_hashes,
    }
    return {
        **payload,
        "source_fingerprint_sha256": _sha256(canonical_json(payload)),
        "dependency_versions": dependencies,
    }


def _profile_candidates(
    config: SkillRollConfig, model_profile: str | None
) -> tuple[str, ...]:
    settings = config.inference
    if settings is None:
        return ()
    if not settings.profiles:
        return (settings.model,) if model_profile is None else ()
    selected = model_profile or settings.default_profile
    if selected is None and len(settings.profiles) == 1:
        selected = next(iter(settings.profiles))
    profile = None if selected is None else settings.profiles.get(selected)
    return () if profile is None else profile.models


def _pricing_snapshot(
    config: SkillRollConfig, model_names: Sequence[str]
) -> dict[str, object]:
    if config.pricing is None:
        return {"currency": None, "models": {}}
    models: dict[str, object] = {}
    for model in dict.fromkeys(model_names):
        price = config.pricing.models.get(model)
        models[model] = (
            None
            if price is None
            else {
                "input_per_million": price.input_per_million,
                "output_per_million": price.output_per_million,
                "cache_read_per_million": price.cache_read_per_million,
            }
        )
    return {"currency": config.pricing.currency, "models": models}


def _inference_settings_data(config: SkillRollConfig) -> dict[str, object]:
    settings = config.inference
    if settings is None:
        return {"status": "unavailable"}
    limits = settings.limits
    endpoint = urlsplit(settings.base_url)
    host = endpoint.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if endpoint.port is not None:
        host += f":{endpoint.port}"
    safe_endpoint = urlunsplit((endpoint.scheme, host, endpoint.path, "", ""))
    return {
        "status": "configured",
        "base_url": safe_endpoint,
        "base_url_sha256": _sha256(settings.base_url.encode("utf-8")),
        "wire": settings.wire.value,
        "supports_temperature": settings.supports_temperature,
        "limits": {
            "max_turns": limits.max_turns,
            "timeout_seconds": limits.timeout_seconds,
            "max_output_tokens": limits.max_output_tokens,
        },
        # Gateway options can carry secrets. The config itself is already hashed.
        "extra_body_sha256": _sha256(canonical_json(settings.extra_body)),
    }


def _schedule(
    cases: tuple[EvalCase, ...],
    executor_models: tuple[str, ...],
    samples: int,
    seed: int,
) -> list[dict[str, object]]:
    entries = [
        {
            "sequence": 0,
            "sample": sample,
            "case": case.identity.as_posix(),
            "executor_model": model,
        }
        for sample in range(1, samples + 1)
        for case in sorted(cases, key=lambda item: item.identity.as_posix())
        for model in executor_models
    ]
    random.Random(seed).shuffle(entries)
    for sequence, entry in enumerate(entries, start=1):
        entry["sequence"] = sequence
        entry["status"] = "NOT_RUN"
    return entries


def _configured_limits(config: SkillRollConfig, case: EvalCase) -> dict[str, int]:
    assert config.inference is not None
    limits = effective_limits(config.inference.limits, case.limits)
    if limits is None:
        limits = config.inference.limits
    return {
        "max_turns": limits.max_turns,
        "timeout_seconds": limits.timeout_seconds,
        "max_output_tokens": limits.max_output_tokens,
    }


def _manifest(
    *,
    comparison_id: str,
    executor_models: tuple[str, ...],
    evaluator_models: tuple[str, ...],
    model_profile: str | None,
    cases: tuple[EvalCase, ...],
    schedule: list[dict[str, object]],
    samples: int,
    seed: int,
    run_commands: bool,
    config: SkillRollConfig,
    input_values: tuple[InputHash, ...] | None,
    harness: dict[str, object],
    status: str,
) -> dict[str, object]:
    values: dict[str, object] = {
        "format_version": 1,
        "comparison_id": comparison_id,
        "status": status,
        "requested_executor_models": list(executor_models),
        "evaluator": {
            "requested_model_profile": model_profile,
            "configured_candidates": list(evaluator_models),
            "selected_model": None,
            "selected_profile": None,
            "selected_purpose": None,
        },
        "samples_requested": samples,
        "seed": seed,
        "run_commands": run_commands,
        "cases": [
            {
                "case": case.identity.as_posix(),
                "skill": case.skill.identity.as_posix(),
                "effective_limits": (
                    _configured_limits(config, case)
                    if config.inference is not None
                    else None
                ),
            }
            for case in sorted(cases, key=lambda item: item.identity.as_posix())
        ],
        "schedule": schedule,
        "inference": _inference_settings_data(config),
        "pricing_snapshot": _pricing_snapshot(
            config, (*executor_models, *evaluator_models)
        ),
        "harness": harness,
        "input_hashes": (None if input_values is None else _hash_data(input_values)),
    }
    return values


def _failure_data(
    failure: InferenceFailure, redactor: SecretRedactor
) -> dict[str, object]:
    return {
        "kind": failure.kind.value,
        "stage": failure.stage or "preflight",
        "summary": redactor.redact(failure.summary),
        "details": list(bounded_failure_details(failure, redactor)),
    }


def _usage_calls(section: Mapping[str, object]) -> list[dict[str, object]]:
    calls = section.get("calls", ())
    if not isinstance(calls, (list, tuple)):
        return []
    return [dict(call) for call in calls if isinstance(call, Mapping)]


def _preflight_cost(
    model: str,
    record: Mapping[str, object],
    config: SkillRollConfig,
    currency: str,
) -> dict[str, object]:
    if record.get("status") != "passed":
        return {"status": "unavailable", "reason": "preflight failed"}
    usage = record.get("usage")
    if not isinstance(usage, Mapping) or usage.get("status") != "observed":
        return {
            "status": "unavailable",
            "reason": "preflight provider usage is unavailable",
        }
    if len(_usage_calls(usage)) != 2:
        return {
            "status": "unavailable",
            "reason": "both preflight calls must report provider usage",
        }
    pricing = None if config.pricing is None else config.pricing.models.get(model)
    return _estimate_cost((dict(usage),), pricing, currency)


def _attempt_role_sections(
    result: CaseResult, executor_model: str, evaluator_model: str
) -> dict[str, dict[str, object]]:
    execution_usage = _usage_records(
        None if result.execution is None else result.execution.usage,
        stage="execution",
        requested_model=executor_model,
    )
    execution_attempted = result.timings.get("execution_seconds") is not None
    execution_usage["usage_complete"] = (
        not execution_attempted or _execution_usage_complete(result.execution)
    )
    if execution_attempted and not execution_usage["usage_complete"]:
        execution_usage["status"] = (
            "partial" if _usage_calls(execution_usage) else "unavailable"
        )
    world_usage = _world_usage(
        result.events,
        evaluator_model,
        result.world_inference_made,
        result.world_missing_usage,
    )
    if not result.world_inference_made and not result.world_missing_usage:
        world_usage["status"] = "not_invoked"
    elif result.world_missing_usage:
        world_usage["status"] = "unavailable"
    judge_usage = _usage_records(
        None if result.judge is None else result.judge.usage,
        stage="semantic_judgment",
        requested_model=evaluator_model,
        served_model=None if result.judge is None else result.judge.model,
    )
    timings = result.timings
    judge_attempted = timings.get("judge_seconds") is not None
    if not execution_attempted:
        execution_usage["status"] = "not_invoked"
    if not judge_attempted:
        judge_usage["status"] = "not_invoked"
    return {
        "execution": execution_usage,
        "world": world_usage,
        "semantic_judgment": judge_usage,
    }


def _attempt_data(
    case_result: CaseResult,
    *,
    sequence: int,
    sample: int,
    executor_model: str,
    evaluator_model: str,
    redactor: SecretRedactor,
) -> dict[str, object]:
    failure = case_result.failure
    timing_value = getattr(case_result, "timings", {})
    timings = dict(timing_value) if isinstance(timing_value, Mapping) else {}
    return {
        "sequence": sequence,
        "sample": sample,
        "started": True,
        "case": case_result.case.identity.as_posix(),
        "executor_model": executor_model,
        "evaluator_model": evaluator_model,
        "status": case_result.outcome,
        "case_outcome": case_result.outcome,
        "run_artifact_directory": (
            None
            if case_result.artifact_directory is None
            else case_result.artifact_directory.as_posix()
        ),
        "failure": None if failure is None else _failure_data(failure, redactor),
        "role_usage": _attempt_role_sections(
            case_result, executor_model, evaluator_model
        ),
        "timings": timings,
    }


def _outcome_counts(
    attempts: Sequence[Mapping[str, object]],
    executor_models: tuple[str, ...],
    cases: tuple[EvalCase, ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for model in executor_models:
        for case in sorted(cases, key=lambda item: item.identity.as_posix()):
            selected = [
                item
                for item in attempts
                if item.get("executor_model") == model
                and item.get("case") == case.identity.as_posix()
            ]
            rows.append(
                {
                    "executor_model": model,
                    "case": case.identity.as_posix(),
                    "counts": {
                        outcome: sum(item.get("status") == outcome for item in selected)
                        for outcome in _OUTCOMES
                    },
                }
            )
    return rows


def _paired_outcomes(
    attempts: Sequence[Mapping[str, object]],
    executor_models: tuple[str, ...],
    cases: tuple[EvalCase, ...],
    samples: int,
) -> list[dict[str, object]]:
    baseline = executor_models[0]
    by_key = {
        (
            item.get("sample"),
            item.get("case"),
            item.get("executor_model"),
        ): item.get("status", "NOT_RUN")
        for item in attempts
    }
    values: list[dict[str, object]] = []
    for sample in range(1, samples + 1):
        for case in sorted(cases, key=lambda item: item.identity.as_posix()):
            baseline_outcome = by_key.get(
                (sample, case.identity.as_posix(), baseline), "NOT_RUN"
            )
            for model in executor_models[1:]:
                values.append(
                    {
                        "sample": sample,
                        "case": case.identity.as_posix(),
                        "baseline_model": baseline,
                        "baseline_outcome": baseline_outcome,
                        "candidate_model": model,
                        "candidate_outcome": by_key.get(
                            (sample, case.identity.as_posix(), model), "NOT_RUN"
                        ),
                    }
                )
    return values


def _numeric_values(attempts: Sequence[Mapping[str, object]], key: str) -> list[float]:
    values: list[float] = []
    for item in attempts:
        raw_timings = item.get("timings", {})
        if not isinstance(raw_timings, Mapping):
            continue
        value = raw_timings.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            values.append(float(value))
    return values


def _median_data(values: list[float], expected: int) -> dict[str, object]:
    if not values:
        return {
            "status": "unavailable",
            "median_seconds": None,
            "samples_with_timing": 0,
            "samples_expected": expected,
        }
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2
    )
    return {
        "status": "observed" if len(values) == expected else "partial",
        "median_seconds": median,
        "samples_with_timing": len(values),
        "samples_expected": expected,
    }


def _usage_summary(
    attempts: Sequence[Mapping[str, object]],
    *,
    role: str,
    expected: int,
    pricing: ModelPricing | None,
    currency: str,
) -> dict[str, object]:
    sections = []
    known = 0
    invoked = 0
    unavailable = 0
    considered = 0
    for attempt in attempts:
        roles = attempt.get("role_usage", {})
        if not isinstance(roles, Mapping):
            continue
        section = roles.get(role)
        if not isinstance(section, Mapping):
            continue
        considered += 1
        state = section.get("status")
        if state in {"observed", "not_invoked"}:
            known += 1
        if state == "observed":
            invoked += 1
        elif state in {"unavailable", "partial"}:
            unavailable += 1
        sections.append(dict(section))
    calls = [call for section in sections for call in _usage_calls(section)]
    not_run = sum(item.get("status") == "NOT_RUN" for item in attempts)
    started_without_role_data = max(0, expected - not_run - considered)
    if known < expected:
        usage_status = "partial" if known else "unavailable"
    elif invoked == 0:
        usage_status = "not_invoked"
    else:
        usage_status = "observed"
    if unavailable or not_run or started_without_role_data or known < expected:
        reason = (
            "some planned samples did not run"
            if not_run
            else "role evidence is missing for a started sample"
            if started_without_role_data
            else "provider usage is incomplete"
            if unavailable
            else "usage is unavailable for one or more samples"
        )
        cost: dict[str, object] = {"status": "unavailable", "reason": reason}
    elif invoked == 0:
        cost = {
            "status": "estimated",
            "currency": currency,
            "amount": 0.0,
            "reason": "the model role was not invoked",
        }
    else:
        cost = _estimate_cost(tuple(sections), pricing, currency)
    return {
        "status": usage_status,
        "samples_with_usage": invoked,
        "samples_with_known_status": known,
        "samples_expected": expected,
        "calls": calls,
        "cost": cost,
    }


def _group_metrics(
    attempts: Sequence[Mapping[str, object]],
    executor_models: tuple[str, ...],
    cases: tuple[EvalCase, ...],
    samples: int,
    config: SkillRollConfig,
    evaluator_model: str | None,
) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    currency = "USD" if config.pricing is None else config.pricing.currency
    for executor_model in executor_models:
        for case in sorted(cases, key=lambda item: item.identity.as_posix()):
            selected = [
                item
                for item in attempts
                if item.get("executor_model") == executor_model
                and item.get("case") == case.identity.as_posix()
            ]
            execution_pricing = (
                None
                if config.pricing is None
                else config.pricing.models.get(executor_model)
            )
            evaluator_pricing = (
                None
                if config.pricing is None or evaluator_model is None
                else config.pricing.models.get(evaluator_model)
            )
            timings = {
                key: _median_data(_numeric_values(selected, key), samples)
                for key in (
                    "execution_seconds",
                    "world_seconds",
                    "judge_seconds",
                    "executor_seconds",
                )
            }
            groups.append(
                {
                    "executor_model": executor_model,
                    "case": case.identity.as_posix(),
                    "roles": {
                        "execution": _usage_summary(
                            selected,
                            role="execution",
                            expected=samples,
                            pricing=execution_pricing,
                            currency=currency,
                        ),
                        "world": _usage_summary(
                            selected,
                            role="world",
                            expected=samples,
                            pricing=evaluator_pricing,
                            currency=currency,
                        ),
                        "semantic_judgment": _usage_summary(
                            selected,
                            role="semantic_judgment",
                            expected=samples,
                            pricing=evaluator_pricing,
                            currency=currency,
                        ),
                    },
                    "timings": timings,
                }
            )
    return groups


def _summary_data(
    *,
    comparison_id: str,
    status: str,
    attempts: Sequence[Mapping[str, object]],
    executor_models: tuple[str, ...],
    cases: tuple[EvalCase, ...],
    samples: int,
    config: SkillRollConfig,
    evaluator_model: str | None,
    failure: Mapping[str, object] | None,
    preflight: Mapping[str, object],
) -> dict[str, object]:
    preflight_data = dict(preflight)
    raw_models = preflight_data.get("models", {})
    models = raw_models if isinstance(raw_models, Mapping) else {}
    currency = "USD" if config.pricing is None else config.pricing.currency
    preflight_data["evaluator_model"] = evaluator_model
    preflight_data["costs"] = {
        model: _preflight_cost(model, record, config, currency)
        for model, record in models.items()
        if isinstance(model, str) and isinstance(record, Mapping)
    }
    return {
        "format_version": 1,
        "comparison_id": comparison_id,
        "status": status,
        "preflight": preflight_data,
        "attempts": [dict(item) for item in attempts],
        "outcome_counts": _outcome_counts(attempts, executor_models, cases),
        "paired_outcomes": _paired_outcomes(attempts, executor_models, cases, samples),
        "metrics": _group_metrics(
            attempts,
            executor_models,
            cases,
            samples,
            config,
            evaluator_model,
        ),
        "failure": None if failure is None else dict(failure),
    }


def _report_bytes(summary: Mapping[str, object]) -> bytes:
    lines = [
        "# SkillRoll model comparison",
        "",
        f"- Comparison: `{summary.get('comparison_id', 'unknown')}`",
        f"- Status: **{summary.get('status', 'unknown')}**",
        "- Outcomes are descriptive observations from the recorded samples.",
        "",
        "## Outcome counts by executor model and case",
        "",
        "| Executor model | Case | PASS | FAIL | ERROR | INCOMPLETE | NOT_RUN |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    counts = cast(list[dict[str, object]], summary["outcome_counts"])
    for raw in counts:
        grouped = cast(dict[str, int], raw["counts"])
        lines.append(
            "| {model} | `{case}` | {pass_count} | {fail_count} | {error_count} | "
            "{incomplete_count} | {not_run_count} |".format(
                model=raw["executor_model"],
                case=raw["case"],
                pass_count=grouped["PASS"],
                fail_count=grouped["FAIL"],
                error_count=grouped["ERROR"],
                incomplete_count=grouped["INCOMPLETE"],
                not_run_count=grouped["NOT_RUN"],
            )
        )
    lines.extend(("", "## Paired outcomes", ""))
    paired = cast(list[dict[str, object]], summary["paired_outcomes"])
    if paired:
        lines.extend(
            (
                "Each row pairs the first requested executor model with one other "
                "model for the same case and sample.",
                "",
                "| Sample | Case | Baseline model | Outcome | Other model | Outcome |",
                "| ---: | --- | --- | --- | --- | --- |",
            )
        )
        for raw in paired:
            lines.append(
                "| {sample} | `{case}` | {baseline} | {baseline_outcome} | "
                "{candidate} | {candidate_outcome} |".format(
                    sample=raw["sample"],
                    case=raw["case"],
                    baseline=raw["baseline_model"],
                    baseline_outcome=raw["baseline_outcome"],
                    candidate=raw["candidate_model"],
                    candidate_outcome=raw["candidate_outcome"],
                )
            )
    else:
        lines.append("No paired sample finished.")
    preflight = cast(dict[str, object], summary["preflight"])
    lines.extend(("", "## Preflight", ""))
    evaluator = preflight["evaluator_model"]
    lines.append(f"- Fixed World and judge model: `{evaluator or 'unavailable'}`")
    models = cast(dict[str, dict[str, object]], preflight["models"])
    costs = cast(dict[str, dict[str, object]], preflight["costs"])
    for model, record in models.items():
        cost = costs[model]
        rendered_cost = (
            "unavailable"
            if cost.get("status") != "estimated"
            else f"{cost.get('amount')} {cost.get('currency')}"
        )
        lines.append(
            f"- `{model}`: {record['status']} preflight; estimated cost {rendered_cost}"
        )
    lines.extend(("", "## Timing and usage", ""))
    lines.append(
        "`executor_seconds` is execution wall time minus World callback time, "
        "a harness proxy rather than isolated model latency."
    )
    metrics = cast(list[dict[str, object]], summary["metrics"])
    for raw in metrics:
        lines.extend(
            (
                f"### {raw['executor_model']} — `{raw['case']}`",
                "",
            )
        )
        timings = cast(dict[str, dict[str, object]], raw["timings"])
        for name, detail in timings.items():
            median = detail["median_seconds"]
            rendered = "unavailable" if median is None else f"{median:.3f}s"
            coverage = (
                f" ({detail['samples_with_timing']}/"
                f"{detail['samples_expected']} samples)"
            )
            lines.append(f"- Median {name}: {rendered}{coverage}")
        roles = cast(dict[str, dict[str, object]], raw["roles"])
        for role, detail in roles.items():
            cost = cast(dict[str, object], detail["cost"])
            estimate = (
                "unavailable"
                if cost.get("status") != "estimated"
                else f"{cost.get('amount')} {cost.get('currency')}"
            )
            reason = (
                ""
                if cost.get("status") == "estimated"
                else f" ({cost.get('reason', 'usage unavailable')})"
            )
            lines.append(
                f"- {role}: {detail['status']} usage; total estimated cost "
                f"{estimate}{reason}"
            )
        lines.append("")
    attempts = cast(list[dict[str, object]], summary["attempts"])
    evidence = [item for item in attempts if item.get("run_artifact_directory")]
    lines.extend(("## Run evidence", ""))
    if evidence:
        for item in evidence:
            run_directory = cast(str, item["run_artifact_directory"])
            run_id = PurePosixPath(run_directory).name
            lines.append(
                f"- Sample {item.get('sample')} `{item.get('case')}` with "
                f"`{item.get('executor_model')}` ({item.get('status')}): "
                f"[run report](../../runs/{run_id}/report.md)"
            )
    else:
        lines.append("No individual run evidence was created.")
    lines.append("")
    lines.extend(
        (
            "The machine-readable `comparison.json` contains every attempt, "
            "including errors and planned runs that did not start.",
            "",
        )
    )
    return "\n".join(lines).encode("utf-8")


def _command_result(
    outcome: Outcome,
    summary: str,
    directory: PurePosixPath,
    comparison: Mapping[str, object] | None = None,
    diagnostics: tuple[Diagnostic, ...] = (),
) -> CommandResult:
    return CommandResult(
        outcome,
        summary,
        diagnostics,
        {
            "artifact_directory": directory.as_posix(),
            "comparison": (
                {}
                if comparison is None
                else cast(Mapping[str, JSONValue], dict(comparison))
            ),
        },
    )


def _write_artifacts(
    store: ArtifactStore,
    directory: Path,
    manifest: Mapping[str, object],
    comparison: Mapping[str, object],
) -> None:
    store.write_comparison(
        directory,
        (
            ("manifest.json", canonical_json(manifest)),
            ("comparison.json", canonical_json(comparison)),
            ("report.md", _report_bytes(comparison)),
        ),
    )


async def _preflight_profiles(
    config: SkillRollConfig,
    environment: Mapping[str, str],
    model_profile: str | None,
    executor_models: tuple[str, ...],
    transport_factory: TransportFactory,
    redactor: SecretRedactor,
    records: dict[str, dict[str, object]],
    checkpoint: Callable[[], None],
) -> tuple[ResolvedInference, ChatTransport] | InferenceFailure:
    candidates, failure = resolve_inference_candidates(
        config.inference, environment, model_profile
    )
    if failure is not None:
        return replace(failure, stage="preflight")
    assert candidates
    selected: ResolvedInference | None = None
    selected_transport: ChatTransport | None = None
    failures: list[str] = []
    failures_by_model: dict[str, InferenceFailure] = {}
    last_failure: InferenceFailure | None = None

    async def probe(
        profile: ResolvedInference, *, keep_transport: bool
    ) -> tuple[ChatTransport | None, InferenceFailure | None]:
        try:
            transport = transport_factory(profile)
        except Exception:
            result_failure = InferenceFailure(
                InferenceFailureKind.EXECUTION_ERROR,
                "SkillRoll could not create the model compatibility transport.",
                stage="preflight",
            )
            records[profile.model] = {
                "status": "error",
                "requested_model": profile.model,
                "failure": _failure_data(result_failure, redactor),
                "usage": {"status": "unavailable", "calls": []},
            }
            checkpoint()
            return None, result_failure
        keep = False
        try:
            try:
                result = await run_preflight(profile, transport)
            except asyncio.CancelledError:
                result_failure = InferenceFailure(
                    InferenceFailureKind.CANCELLED,
                    "The model compatibility check was cancelled.",
                    stage="preflight",
                )
                result = None
            except Exception:
                result_failure = InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "The model compatibility check could not finish.",
                    stage="preflight",
                )
                result = None
            if result is not None and result.passed:
                assert result.evidence is not None
                records[profile.model] = _preflight_record(
                    profile.model, result.evidence
                )
                checkpoint()
                if keep_transport:
                    keep = True
                    return transport, None
                return None, None
            if result is not None:
                assert result.failure is not None
                result_failure = replace(result.failure, stage="preflight")
            records[profile.model] = {
                "status": (
                    "failed"
                    if result_failure.kind is not InferenceFailureKind.EXECUTION_ERROR
                    else "error"
                ),
                "requested_model": profile.model,
                "failure": _failure_data(result_failure, redactor),
                "usage": {"status": "unavailable", "calls": []},
            }
            failures_by_model[profile.model] = result_failure
            checkpoint()
            return None, result_failure
        finally:
            if not keep:
                await transport.close()

    for candidate in candidates:
        transport, candidate_failure = await probe(candidate, keep_transport=True)
        if candidate_failure is not None:
            last_failure = candidate_failure
            failures_by_model[candidate.model] = candidate_failure
            failures.append(
                f"{candidate.model}: {redactor.redact(candidate_failure.summary)}"
            )
            if candidate_failure.kind in {
                InferenceFailureKind.CANCELLED,
                InferenceFailureKind.EXECUTION_ERROR,
            }:
                return candidate_failure
            continue
        assert transport is not None
        selected = candidate
        selected_transport = transport
        break
    if selected is None or selected_transport is None:
        assert last_failure is not None
        return replace(
            last_failure,
            summary=(
                "No ranked model candidate completed SkillRoll's compatibility check."
            ),
            details=tuple(failures),
            stage="preflight",
        )

    # The selected evaluator transport is also the World and judge transport.
    keep_evaluator = False
    try:
        for model in executor_models:
            prior = records.get(model)
            if prior is not None:
                if prior.get("status") != "passed":
                    prior_failure = failures_by_model.get(model, last_failure)
                    if prior_failure is not None:
                        return replace(
                            prior_failure,
                            summary=(
                                f"Executor model '{model}' failed SkillRoll's "
                                "compatibility check."
                            ),
                            stage="preflight",
                        )
                    return InferenceFailure(
                        InferenceFailureKind.MALFORMED_RESPONSE,
                        f"Executor model '{model}' failed SkillRoll's "
                        "compatibility check.",
                        stage="preflight",
                    )
                continue
            candidate = replace(
                selected,
                model=model,
                profile_name=None,
                profile_purpose=None,
            )
            _, candidate_failure = await probe(candidate, keep_transport=False)
            if candidate_failure is not None:
                return replace(
                    candidate_failure,
                    summary=(
                        f"Executor model '{model}' failed SkillRoll's "
                        "compatibility check."
                    ),
                    stage="preflight",
                )
        keep_evaluator = True
        return selected, selected_transport
    finally:
        if not keep_evaluator:
            await selected_transport.close()


def _preflight_record(
    requested_model: str, evidence: PreflightEvidence
) -> dict[str, object]:
    return {
        "status": "passed",
        "requested_model": requested_model,
        "served_model": evidence.response_model,
        "usage": _usage_records(
            evidence.usage,
            stage="preflight",
            requested_model=requested_model,
            served_model=evidence.response_model,
        ),
    }


def _overall_outcome(attempts: Sequence[Mapping[str, object]], status: str) -> Outcome:
    if status != "complete" or any(
        item.get("status") in {"ERROR", "NOT_RUN"} for item in attempts
    ):
        return Outcome.ERROR
    if any(item.get("status") == "INCOMPLETE" for item in attempts):
        return Outcome.INCOMPLETE
    if any(item.get("status") == "FAIL" for item in attempts):
        return Outcome.FAIL
    return Outcome.PASS


def _argument_failure(summary: str, next_action: str) -> CommandResult:
    return CommandResult(
        Outcome.ERROR,
        "SkillRoll could not start the model comparison.",
        (Diagnostic("SCC2001", summary, next_action=next_action),),
    )


def _valid_arguments(
    executor_models: Sequence[str], samples: int, seed: int
) -> str | None:
    if not 2 <= len(executor_models) <= 8:
        return "--executor-model must name between 2 and 8 models."
    if any(
        not isinstance(model, str)
        or not model.strip()
        or "\n" in model
        or "\r" in model
        or len(model.strip().encode("utf-8")) > 200
        for model in executor_models
    ):
        return "Every --executor-model value must be a nonblank model name."
    normalized = tuple(model.strip() for model in executor_models)
    if len(set(normalized)) != len(normalized):
        return "--executor-model values must be unique."
    if (
        isinstance(samples, bool)
        or not isinstance(samples, int)
        or not 1 <= samples <= 10
    ):
        return "--samples must be an integer from 1 to 10."
    if (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or not 0 <= seed <= 2**32 - 1
    ):
        return "--seed must be an integer from 0 to 4294967295."
    return None


async def _execute_comparison(
    config: SkillRollConfig,
    cases: tuple[EvalCase, ...],
    *,
    executor_models: tuple[str, ...],
    samples: int,
    run_commands: bool,
    environment: Mapping[str, str],
    model_profile: str | None,
    transport_factory: TransportFactory,
    executor_factory: ExecutorFactory,
    check_runner: CheckRunner | None,
    store_factory: StoreFactory,
    artifact_store: ArtifactStore,
    comparison_id: str,
    artifact_directory: Path,
    manifest: dict[str, object],
    schedule: list[dict[str, object]],
    input_hashes_snapshot: tuple[InputHash, ...],
    redactor: SecretRedactor,
) -> tuple[Outcome, dict[str, object], str, InferenceFailure | None]:
    attempts: list[dict[str, object]] = [dict(item) for item in schedule]
    preflight_records: dict[str, dict[str, object]] = {}
    evaluator_profile: ResolvedInference | None = None
    evaluator_transport: ChatTransport | None = None
    failure: InferenceFailure | None = None
    status = "in_progress"
    expected_fingerprint = _sha256(canonical_json(_hash_data(input_hashes_snapshot)))

    def summary() -> dict[str, object]:
        return _summary_data(
            comparison_id=comparison_id,
            status=status,
            attempts=attempts,
            executor_models=executor_models,
            cases=cases,
            samples=samples,
            config=config,
            evaluator_model=(
                None if evaluator_profile is None else evaluator_profile.model
            ),
            failure=None if failure is None else _failure_data(failure, redactor),
            preflight={"models": preflight_records},
        )

    try:
        try:
            before_preflight = _current_input_hashes(config, cases)
            before_preflight_fingerprint = _sha256(
                canonical_json(_hash_data(before_preflight))
            )
        except (BundleError, OSError, ValueError) as error:
            before_preflight_fingerprint = ""
            failure = InferenceFailure(
                InferenceFailureKind.EXECUTION_ERROR,
                "SkillRoll could not verify local inputs before model preflight: "
                f"{error}",
                stage="input_verification",
            )
        if before_preflight_fingerprint != expected_fingerprint:
            failure = failure or InferenceFailure(
                InferenceFailureKind.EXECUTION_ERROR,
                "SkillRoll detected that configuration, eval, or skill files "
                "changed after the comparison manifest was written.",
                stage="input_verification",
            )
            status = "error"
            manifest["status"] = status
            manifest["failure"] = _failure_data(failure, redactor)
            comparison = summary()
            _write_artifacts(artifact_store, artifact_directory, manifest, comparison)
            return Outcome.ERROR, comparison, "inputs changed before preflight", failure

        def checkpoint_preflight() -> None:
            _write_artifacts(artifact_store, artifact_directory, manifest, summary())

        resolved = await _preflight_profiles(
            config,
            environment,
            model_profile,
            executor_models,
            transport_factory,
            redactor,
            preflight_records,
            checkpoint_preflight,
        )
        if isinstance(resolved, InferenceFailure):
            failure = resolved
            status = "error"
            manifest["status"] = status
            comparison = summary()
            _write_artifacts(artifact_store, artifact_directory, manifest, comparison)
            return Outcome.ERROR, comparison, "preflight failed", failure
        evaluator_profile, evaluator_transport = resolved
        manifest["status"] = "in_progress"
        manifest["evaluator"] = {
            **cast(dict[str, object], manifest["evaluator"]),
            "selected_model": evaluator_profile.model,
            "selected_profile": evaluator_profile.profile_name,
            "selected_purpose": evaluator_profile.profile_purpose,
        }
        try:
            after_preflight = _current_input_hashes(config, cases)
            after_preflight_fingerprint = _sha256(
                canonical_json(_hash_data(after_preflight))
            )
        except (BundleError, OSError, ValueError) as error:
            after_preflight_fingerprint = ""
            failure = InferenceFailure(
                InferenceFailureKind.EXECUTION_ERROR,
                "SkillRoll could not verify local inputs after model preflight: "
                f"{error}",
                stage="input_verification",
            )
        if after_preflight_fingerprint != expected_fingerprint:
            failure = failure or InferenceFailure(
                InferenceFailureKind.EXECUTION_ERROR,
                "SkillRoll detected that configuration, eval, or skill files "
                "changed during model preflight.",
                stage="input_verification",
            )
            status = "error"
            manifest["status"] = status
            manifest["failure"] = _failure_data(failure, redactor)
            comparison = summary()
            _write_artifacts(artifact_store, artifact_directory, manifest, comparison)
            return Outcome.ERROR, comparison, "inputs changed during preflight", failure

        _write_artifacts(artifact_store, artifact_directory, manifest, summary())
        case_by_identity = {case.identity.as_posix(): case for case in cases}
        for index, scheduled in enumerate(schedule):
            current_entry = attempts[index]
            model = cast(str, scheduled["executor_model"])
            case_identity = cast(str, scheduled["case"])
            case = case_by_identity[case_identity]
            try:
                before = _current_input_hashes(config, cases)
                before_fingerprint = _sha256(canonical_json(_hash_data(before)))
            except (BundleError, OSError, ValueError) as error:
                failure = InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "SkillRoll could not verify local inputs before sample "
                    f"{scheduled['sample']}: {error}",
                    stage="input_verification",
                )
                current_entry.update(
                    {
                        "status": "ERROR",
                        "failure": _failure_data(failure, redactor),
                    }
                )
                status = "error"
                break
            if before_fingerprint != expected_fingerprint:
                failure = InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "SkillRoll detected that configuration, eval, or skill files "
                    "changed during the comparison.",
                    stage="input_verification",
                )
                current_entry.update(
                    {"status": "ERROR", "failure": _failure_data(failure, redactor)}
                )
                status = "error"
                break

            current_entry.update({"status": "INCOMPLETE", "started": True})
            _write_artifacts(artifact_store, artifact_directory, manifest, summary())

            executor_profile = replace(
                evaluator_profile,
                model=model,
                profile_name=None,
                profile_purpose=None,
            )
            try:
                result = await evaluate_repository(
                    config,
                    (case,),
                    environment=environment,
                    run_commands=run_commands,
                    concurrency=1,
                    transport_factory=transport_factory,
                    executor_factory=executor_factory,
                    check_runner=check_runner,
                    store_factory=store_factory,
                    model_profile=model_profile,
                    executor_model=model,
                    _resolved=(evaluator_profile, evaluator_transport),
                    _executor_profile=executor_profile,
                    _close_transport=False,
                )
            except asyncio.CancelledError:
                failure = InferenceFailure(
                    InferenceFailureKind.CANCELLED,
                    "The comparison was cancelled during a model attempt.",
                    stage="execution",
                )
                current_entry.update(
                    {
                        "status": "ERROR",
                        "failure": _failure_data(failure, redactor),
                    }
                )
                status = "error"
                break
            except Exception:
                failure = InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "SkillRoll could not complete this model attempt.",
                    stage="execution",
                )
                current_entry.update(
                    {
                        "status": "ERROR",
                        "failure": _failure_data(failure, redactor),
                    }
                )
                status = "error"
                break
            if isinstance(result, InferenceFailure):
                failure = replace(result, stage=result.stage or "execution")
                current_entry.update(
                    {
                        "status": "ERROR",
                        "failure": _failure_data(failure, redactor),
                    }
                )
                status = "error"
                break
            if len(result) != 1:
                failure = InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "SkillRoll received an unexpected number of case results.",
                    stage="execution",
                )
                current_entry.update(
                    {
                        "status": "ERROR",
                        "failure": _failure_data(failure, redactor),
                    }
                )
                status = "error"
                break
            observed = _attempt_data(
                result[0],
                sequence=cast(int, scheduled["sequence"]),
                sample=cast(int, scheduled["sample"]),
                executor_model=model,
                evaluator_model=evaluator_profile.model,
                redactor=redactor,
            )
            current_entry.clear()
            current_entry.update(observed)
            try:
                after = _current_input_hashes(config, cases)
                after_fingerprint = _sha256(canonical_json(_hash_data(after)))
            except (BundleError, OSError, ValueError) as error:
                after_fingerprint = ""
                failure = InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "SkillRoll could not verify local inputs after sample "
                    f"{scheduled['sample']}: {error}",
                    stage="input_verification",
                )
            if after_fingerprint != expected_fingerprint:
                failure = failure or InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "SkillRoll detected that configuration, eval, or skill files "
                    "changed during the comparison.",
                    stage="input_verification",
                )
                current_entry["case_outcome"] = current_entry["status"]
                current_entry["status"] = "ERROR"
                current_entry["input_drift"] = True
                current_entry["failure"] = _failure_data(failure, redactor)
                status = "error"
            _write_artifacts(artifact_store, artifact_directory, manifest, summary())
            if failure is not None:
                break
        else:
            status = "complete"
    except asyncio.CancelledError:
        failure = InferenceFailure(
            InferenceFailureKind.CANCELLED,
            "The comparison was cancelled before all scheduled attempts finished.",
            stage="execution",
        )
        status = "error"
    except (ArtifactError, OSError, ValueError) as error:
        failure = InferenceFailure(
            InferenceFailureKind.EXECUTION_ERROR,
            str(error),
            stage="evidence_writing",
        )
        status = "error"
    finally:
        if evaluator_transport is not None:
            try:
                await evaluator_transport.close()
            except Exception:
                failure = failure or InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "SkillRoll could not close the configured model transport.",
                    stage="evidence_writing",
                )
                status = "error"

    manifest["status"] = status
    if failure is not None:
        manifest["failure"] = _failure_data(failure, redactor)
    comparison = summary()
    try:
        _write_artifacts(artifact_store, artifact_directory, manifest, comparison)
    except ArtifactError as error:
        failure = InferenceFailure(
            InferenceFailureKind.EXECUTION_ERROR,
            str(error),
            stage="evidence_writing",
        )
        return (
            Outcome.ERROR,
            comparison,
            "could not save comparison evidence",
            failure,
        )
    outcome = _overall_outcome(attempts, status)
    return outcome, comparison, status, failure


def run(
    *,
    executor_models: tuple[str, ...] = (),
    samples: int = 5,
    seed: int = 0,
    repo: str | None = None,
    skill: str | None = None,
    case: str | None = None,
    all_cases: bool = False,
    model_profile: str | None = None,
    run_commands: bool = False,
    environment: Mapping[str, str] | None = None,
    transport_factory: TransportFactory = _transport,
    executor_factory: ExecutorFactory = _executor,
    check_runner: CheckRunner | None = None,
    store_factory: StoreFactory = _store,
) -> CommandResult:
    """Validate local scope and run one explicit, preflighted model matrix."""
    argument_error = _valid_arguments(executor_models, samples, seed)
    if argument_error is not None:
        return _argument_failure(
            argument_error,
            "Supply 2 to 8 unique --executor-model values, --samples from 1 to 10, "
            "and a seed from 0 to 4294967295.",
        )
    executor_models = tuple(model.strip() for model in executor_models)
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
    config = report.config
    cases = report.cases
    if not cases:
        return _argument_failure(
            "No valid eval cases were selected for comparison.",
            "Select a skill or eval case that contains at least one valid case.",
        )
    values = os.environ if environment is None else environment
    secret = (
        "" if config.inference is None else values.get(config.inference.api_key_env, "")
    )
    redactor = SecretRedactor(SecretValue(secret))
    failure: InferenceFailure | None = None
    try:
        frozen_hashes = _current_input_hashes(config, cases)
        harness = _harness_fingerprint()
        artifact_store = store_factory(config.repository_root, redactor)
        comparison_id, artifact_directory = artifact_store.create_comparison()
        schedule = _schedule(cases, executor_models, samples, seed)
        evaluator_models = _profile_candidates(config, model_profile)
        manifest = _manifest(
            comparison_id=comparison_id,
            executor_models=executor_models,
            evaluator_models=evaluator_models,
            model_profile=model_profile,
            cases=cases,
            schedule=schedule,
            samples=samples,
            seed=seed,
            run_commands=run_commands,
            config=config,
            input_values=frozen_hashes,
            harness=harness,
            status="in_progress",
        )
        _write_artifacts(
            artifact_store,
            artifact_directory,
            manifest,
            _summary_data(
                comparison_id=comparison_id,
                status="in_progress",
                attempts=schedule,
                executor_models=executor_models,
                cases=cases,
                samples=samples,
                config=config,
                evaluator_model=None,
                failure=None,
                preflight={"models": {}},
            ),
        )
        outcome, comparison, status, failure = asyncio.run(
            _execute_comparison(
                config,
                cases,
                executor_models=executor_models,
                samples=samples,
                run_commands=run_commands,
                environment=values,
                model_profile=model_profile,
                transport_factory=transport_factory,
                executor_factory=executor_factory,
                check_runner=check_runner,
                store_factory=store_factory,
                artifact_store=artifact_store,
                comparison_id=comparison_id,
                artifact_directory=artifact_directory,
                manifest=manifest,
                schedule=schedule,
                input_hashes_snapshot=frozen_hashes,
                redactor=redactor,
            )
        )
    except KeyboardInterrupt:
        return _failure_result(
            InferenceFailure(
                InferenceFailureKind.CANCELLED,
                "The comparison was cancelled before it finished.",
            ),
            redactor,
        )
    except ArtifactError as error:
        return _failure_result(
            InferenceFailure(
                InferenceFailureKind.EXECUTION_ERROR,
                str(error),
                stage="evidence_writing",
            ),
            redactor,
        )
    except (BundleError, OSError, ValueError) as error:
        return _failure_result(
            InferenceFailure(
                InferenceFailureKind.EXECUTION_ERROR,
                f"SkillRoll could not prepare the comparison inputs: {error}",
                stage="input_verification",
            ),
            redactor,
        )
    diagnostics: list[Diagnostic] = []
    if failure is not None:
        diagnostics.append(
            Diagnostic(
                "SCC1001",
                redactor.redact(failure.summary),
                details=bounded_failure_details(failure, redactor),
                next_action=(
                    "Inspect comparison.json and its linked run evidence before "
                    "starting a new comparison."
                ),
            )
        )
    elif outcome is Outcome.ERROR:
        attempts = cast(list[dict[str, object]], comparison["attempts"])
        for attempt in attempts:
            if attempt.get("status") != "ERROR":
                continue
            detail = attempt.get("failure")
            if isinstance(detail, Mapping):
                message = cast(str, detail.get("summary", "The attempt failed."))
                stage = cast(str, detail.get("stage", "execution"))
                raw_details = detail.get("details", ())
                details = (
                    tuple(cast(list[str], raw_details))
                    if isinstance(raw_details, list)
                    else ()
                )
            else:
                message = "This attempt did not produce trustworthy evidence."
                stage = "execution"
                details = ()
            diagnostics.append(
                Diagnostic(
                    "SCC1001",
                    message,
                    affected=(
                        f"{attempt.get('case')}: executor model "
                        f"{attempt.get('executor_model')}"
                    ),
                    details=(f"Technical stage: {stage}", *details),
                )
            )
    summary_text = {
        Outcome.PASS: "Every scheduled model comparison attempt passed.",
        Outcome.FAIL: (
            "At least one scheduled model comparison attempt failed its criteria."
        ),
        Outcome.INCOMPLETE: (
            "At least one scheduled model comparison attempt was incomplete."
        ),
        Outcome.ERROR: (
            "The model comparison stopped before producing complete "
            "trustworthy evidence."
        ),
    }[outcome]
    if failure is not None:
        summary_text = redactor.redact(failure.summary)
    report_path = (
        PurePosixPath(".skillroll") / "comparisons" / comparison_id / "report.md"
    )
    return _command_result(
        outcome,
        f"{summary_text} Comparison: {report_path}.",
        PurePosixPath(".skillroll") / "comparisons" / comparison_id,
        comparison,
        tuple(diagnostics),
    )
