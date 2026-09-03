"""Pure version-two artifact renderers and records."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from skillroll.artifacts.hashes import InputHash
from skillroll.world.bundle import BundleWarning
from skillroll.world.session import WorldEvent

ARTIFACT_FORMAT_VERSION = 2


def canonical_json(value: object) -> bytes:
    """Render a stable machine-readable artifact with a final newline."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def manifest_bytes(inputs: tuple[InputHash, ...]) -> bytes:
    """Render sorted input identities in the documented format-version envelope."""
    files = [
        {
            "identity": item.identity.as_posix(),
            "kind": item.kind,
            "sha256": item.sha256,
            "bytes": item.bytes,
        }
        for item in sorted(inputs, key=lambda item: item.identity.as_posix())
    ]
    return canonical_json({"format_version": ARTIFACT_FORMAT_VERSION, "files": files})


def transcript_bytes(events: tuple[WorldEvent, ...]) -> bytes:
    """Render only action results, never a provider request or prompt."""
    lines: list[bytes] = []
    for event in events:
        value: dict[str, object] = {
            "arguments": dict(event.arguments),
            "index": event.index,
            "result": event.result,
            "source": event.source,
            "tool_name": event.tool_name,
        }
        if event.rule_name is not None:
            value["rule_name"] = event.rule_name
        lines.append(canonical_json(value))
    return b"".join(lines)


@dataclass(frozen=True, slots=True)
class RunFacts:
    """Safe logical facts used to render run.json and the readable report."""

    run_id: str
    started_at: str
    skill: str
    case: str
    title: str | None
    base_url: str
    model: str
    configured_limits: Mapping[str, int]
    effective_limits: Mapping[str, int]
    input_manifest_sha256: str
    status: str
    events: tuple[WorldEvent, ...]
    failure: str | None = None
    failure_details: tuple[str, ...] = ()
    profile_name: str | None = None
    profile_purpose: str | None = None
    skill_available: bool = True
    warnings: tuple[BundleWarning, ...] = ()


def _warning_data(warning: BundleWarning) -> dict[str, object]:
    """Render one non-secret bundle advisory for machine-readable evidence."""
    return {
        "path": warning.path.as_posix(),
        "bytes": warning.size,
        "summary": warning.summary,
    }


def run_bytes(facts: RunFacts) -> bytes:
    """Render the non-secret machine-readable run record."""
    values: dict[str, object] = {
        "format_version": ARTIFACT_FORMAT_VERSION,
        "run_id": facts.run_id,
        "started_at": facts.started_at,
        "repository_root": ".",
        "skill": facts.skill,
        "case": facts.case,
        "skill_instructions_available": facts.skill_available,
        "title": facts.title,
        "profile": {
            "base_url": facts.base_url,
            "model": facts.model,
            "name": facts.profile_name,
            "purpose": facts.profile_purpose,
        },
        "configured_limits": dict(facts.configured_limits),
        "effective_limits": dict(facts.effective_limits),
        "input_manifest": {
            "file": "inputs.json",
            "sha256": facts.input_manifest_sha256,
        },
        "transcript": {
            "actions": len(facts.events),
            "compacted_history_actions": sum(
                item.omitted_history for item in facts.events
            ),
        },
        "status": facts.status,
    }
    if facts.failure is not None:
        values["failure"] = facts.failure
    if facts.failure_details:
        values["failure_details"] = list(facts.failure_details)
    if facts.warnings:
        values["warnings"] = [_warning_data(item) for item in facts.warnings]
    return canonical_json(values)


def report_bytes(facts: RunFacts) -> bytes:
    """Render a friendly preliminary report that deliberately does not judge."""
    lines = [
        "# SkillRoll run",
        "",
        f"- Skill: `{facts.skill}`",
        f"- Eval case: `{facts.case}`",
        f"- Model: `{facts.model}`",
        "- Skill instructions: "
        + ("available" if facts.skill_available else "intentionally omitted"),
        "- Effective limits: "
        + ", ".join(
            f"{name}={value}" for name, value in facts.effective_limits.items()
        ),
        "",
    ]
    if facts.warnings:
        lines.extend(("## Warnings", ""))
        lines.extend(f"- {item.summary}" for item in facts.warnings)
        lines.append("")
    lines.extend(("## Actions", ""))
    if not facts.events:
        lines.append("No action completed.")
    for event in facts.events:
        source = (
            "read from the skill folder"
            if event.source == "skill_bundle"
            else "Dungeon Master"
            if event.source == "world_model"
            else event.source.replace("_", " ")
        )
        lines.extend(
            (
                f"### {event.index + 1}. `{event.tool_name}` ({source})",
                "",
                f"Result: {event.result}",
                "",
            )
        )
    omitted = sum(item.omitted_history for item in facts.events)
    if omitted:
        lines.extend(
            (
                f"The Dungeon Master omitted {omitted} earlier actions to stay "
                "within its history limit.",
                "",
            )
        )
    if facts.failure is not None:
        lines.extend(
            (
                "## Why the run stopped",
                "",
                facts.failure,
                "",
                "Fix this issue, then run the eval again.",
                "",
            )
        )
    if facts.failure_details:
        lines.extend(("Technical details (redacted):", ""))
        lines.extend(f"- {detail}" for detail in facts.failure_details)
        lines.append("")
    lines.extend(
        (
            "This run has not been checked against the success criteria yet.",
            "Machine-readable details are in this run directory.",
            "",
        )
    )
    return "\n".join(lines).encode("utf-8")


def final_report_bytes(
    skill: str,
    case: str,
    outcome: str,
    judge: Mapping[str, object] | None,
    assertions: tuple[Mapping[str, object], ...],
    checks: tuple[Mapping[str, object], ...],
    failure: str | None,
    failure_details: tuple[str, ...] = (),
    *,
    finished: bool | None = None,
    events: tuple[WorldEvent, ...] = (),
    execution_turns: int | None = None,
    execution_turn_limit: int | None = None,
    execution_turns_source: str = "unavailable",
    failure_stage: str | None = None,
    model: str | None = None,
    model_profile: str | None = None,
    model_profile_purpose: str | None = None,
    skill_available: bool = True,
    warnings: tuple[BundleWarning, ...] = (),
) -> bytes:
    """Render a final report in terms a new maintainer can act on."""
    if finished is None:
        finished = failure is None

    assertion_labels = {
        "final_output_contains": "output contains this fact",
        "final_output_not_contains": "output omits this forbidden literal",
        "final_output_equals": "output exactly matches this text",
    }
    lines = [
        "# SkillRoll eval report",
        "",
        f"- Skill: `{skill}`",
        f"- Eval case: `{case}`",
        "- Skill instructions: "
        + ("available" if skill_available else "intentionally omitted"),
        f"- Result: **{outcome}**",
        "- Skill finished: " + ("yes" if finished else "no"),
    ]
    if model is not None:
        lines.insert(4, f"- Model: `{model}`")
        if model_profile is not None:
            lines.insert(5, f"- Model profile: `{model_profile}`")
            if model_profile_purpose is not None:
                lines.insert(6, f"- Profile purpose: {model_profile_purpose}")
    if execution_turns is not None:
        lines.append(f"- Skill turns: {execution_turns}")
    if warnings:
        lines.extend(("", "## Warnings", ""))
        lines.extend(f"- {item.summary}" for item in warnings)
    lines.extend(("", "## Actions", ""))
    if not events:
        lines.append("No action completed.")
    for event in events:
        source = (
            "skill folder"
            if event.source == "skill_bundle"
            else "Dungeon Master"
            if event.source == "world_model"
            else event.source.replace("_", " ")
        )
        lines.extend(
            (
                f"### {event.index + 1}. `{event.tool_name}` ({source})",
                "",
                "Arguments: "
                + json.dumps(
                    event.arguments,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "",
                f"Result: {event.result}",
                "",
            )
        )
    omitted = sum(item.omitted_history for item in events)
    if omitted:
        lines.extend(
            (
                f"The Dungeon Master omitted {omitted} earlier actions to stay "
                "within its history limit.",
                "",
            )
        )
    lines.extend(("## Success criteria", ""))
    if judge is None:
        lines.append("The success criteria could not be reviewed.")
    else:
        lines.append(f"Result: **{judge.get('verdict', 'unknown')}**")
        rationale = judge.get("rationale")
        if isinstance(rationale, str) and rationale:
            lines.extend(("", rationale))
        unmet = judge.get("unmet_criteria")
        if isinstance(unmet, (list, tuple)) and unmet:
            lines.extend(("", "Unmet criteria:"))
            lines.extend(f"- {item}" for item in unmet)
        criteria = judge.get("criteria")
        if isinstance(criteria, (list, tuple)) and criteria:
            lines.extend(("", "Criteria:"))
            for item in criteria:
                if not isinstance(item, Mapping):
                    continue
                criterion = item.get("criterion", "Unnamed criterion")
                status = item.get("status", "unknown")
                evidence = item.get("evidence")
                lines.append(f"- **{status}** — {criterion}")
                if isinstance(evidence, str) and evidence:
                    lines.append(f"  Evidence: {evidence}")
    lines.extend(("", "## Exact checks", ""))
    if not assertions:
        lines.append("No exact fact checks were declared for this case.")
    for assertion in assertions:
        marker = "passed" if assertion.get("passed") else "failed"
        kind = str(assertion.get("kind", "unknown"))
        label = assertion_labels.get(kind, kind)
        lines.append(
            f"- Fact check {assertion.get('ordinal', '?')} ({label}): {marker}."
        )
        expected = assertion.get("expected")
        if isinstance(expected, str):
            lines.append(f"  Expected: {expected}")
        observed = assertion.get("observed")
        if isinstance(observed, str) and observed:
            lines.append(f"  Observed: {observed}")
    lines.extend(("", "## Repository checks", ""))
    if not checks:
        lines.append("No repository checks were declared for this case.")
    for check in checks:
        lines.append(
            f"- {check.get('name', 'Unnamed check')}: "
            f"{check.get('outcome', 'unknown')}."
        )
        detail = check.get("detail")
        if isinstance(detail, str) and detail:
            lines.extend(("", detail))
    if failure is not None:
        heading = (
            "What prevented completion"
            if not finished
            else "What prevented a trustworthy result"
        )
        lines.extend(("", f"## {heading}", "", failure))
        if failure_stage is not None:
            lines.extend(("", f"Technical stage: `{failure_stage}`."))
    if failure_details:
        lines.extend(("", "## Technical details (redacted)", ""))
        lines.extend(f"- {detail}" for detail in failure_details)
    lines.extend(("", "## Usage", ""))
    if execution_turns is None:
        lines.append("Model turns used: unavailable.")
    else:
        limit = "unknown" if execution_turn_limit is None else str(execution_turn_limit)
        lines.append(
            f"Model turns used: {execution_turns} of {limit} "
            f"({execution_turns_source})."
        )
    lines.append(
        "Token usage, cost, and machine-readable details are in `result.json`."
    )
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def execution_bytes(
    final_output: str,
    turns: int | None,
    usage: object,
    *,
    turns_source: str = "unavailable",
) -> bytes:
    """Render completed execution facts before a repository check can begin."""
    return canonical_json(
        {
            "format_version": ARTIFACT_FORMAT_VERSION,
            "final_output": final_output,
            "turns_used": turns,
            "turns_source": turns_source,
            "usage": usage,
        }
    )


def judge_bytes(judge: object, exact_fact_checks: object) -> bytes:
    """Render decision facts only; prompts and raw provider responses never persist."""
    return canonical_json(
        {
            "format_version": ARTIFACT_FORMAT_VERSION,
            "semantic_judgment": judge,
            "exact_fact_checks": exact_fact_checks,
        }
    )


def verdict_bytes(
    outcome: str, failure: str | None, failure_details: tuple[str, ...] = ()
) -> bytes:
    """Render the single final state, retaining a normalized technical failure."""
    value: dict[str, object] = {
        "format_version": ARTIFACT_FORMAT_VERSION,
        "overall_outcome": outcome,
    }
    if failure is not None:
        value["failure"] = failure
    if failure_details:
        value["failure_details"] = list(failure_details)
    return canonical_json(value)


def checks_bytes(checks: object) -> bytes:
    """Render compact declared-check outcomes and artifact log names."""
    return canonical_json(
        {"format_version": ARTIFACT_FORMAT_VERSION, "trusted_repository_checks": checks}
    )


def result_bytes(summary: Mapping[str, object]) -> bytes:
    """Render the v2 result summary with independent user-facing statuses."""
    return canonical_json({"format_version": ARTIFACT_FORMAT_VERSION, **dict(summary)})


def experiment_bytes(summary: Mapping[str, object]) -> bytes:
    """Render the bounded parent record for a sampling/control experiment."""
    return canonical_json({"schema_version": 1, **dict(summary)})


def experiment_report_bytes(summary: Mapping[str, object]) -> bytes:
    """Render a short report that points authors to paired run evidence."""
    interpretation = summary.get("interpretation")
    if not isinstance(interpretation, Mapping):
        interpretation = {}
    lines = [
        "# SkillRoll comparison report",
        "",
        f"- Eval case: `{summary.get('case', 'selected cases')}`",
        f"- Model: `{summary.get('model', 'unknown')}`",
        f"- Samples: {summary.get('samples_requested', 'unknown')}",
        f"- Interpretation: **{interpretation.get('status', 'unknown')}**",
        "",
        str(interpretation.get("explanation", "No interpretation was recorded.")),
        "",
        str(interpretation.get("next_action", "Inspect the paired evidence.")),
        "",
    ]
    warnings = summary.get("warnings", ())
    if isinstance(warnings, (list, tuple)) and warnings:
        lines.extend(("## Warnings", ""))
        for warning in warnings:
            if not isinstance(warning, Mapping):
                continue
            warning_skill = warning.get("skill", "unknown skill")
            warning_case = warning.get("case")
            context = f"Skill `{warning_skill}`"
            if warning_case:
                context += f" (case `{warning_case}`)"
            lines.append(
                f"- {context}: "
                f"{warning.get('summary', 'A large skill file was indexed.')}"
            )
        lines.append("")
    lines.extend(
        (
            "## Paired runs",
            "",
            "| Sample | With skill | Without skill | Interpretation | Evidence |",
            "| ---: | --- | --- | --- | --- |",
        )
    )
    pairs = summary.get("paired_comparisons", ())
    if isinstance(pairs, (list, tuple)):
        for pair in pairs:
            if not isinstance(pair, Mapping):
                continue
            skill = pair.get("skill_run")
            control = pair.get("skill_control_run")
            skill = skill if isinstance(skill, Mapping) else {}
            control = control if isinstance(control, Mapping) else {}
            evidence = " ".join(
                str(path)
                for path in (
                    skill.get("artifact_directory", ""),
                    control.get("artifact_directory", ""),
                )
                if path
            )
            lines.append(
                f"| {pair.get('sample', '?')} | {skill.get('outcome', 'unknown')} | "
                f"{control.get('outcome', 'not run')} | "
                f"{pair.get('control_interpretation', 'not recorded')} | `{evidence}` |"
            )
    lines.extend(("", "## Counts", ""))
    for name in ("skill_runs", "skill_control_runs"):
        values = summary.get(name)
        if isinstance(values, Mapping):
            lines.append(
                f"- {name}: "
                + ", ".join(f"{key}={value}" for key, value in values.items())
                + "."
            )
    lines.extend(
        (
            "",
            "The no-skill comparison helps check whether the eval depends on the "
            "skill. It does not change the skill's PASS/FAIL result.",
            "",
            "Per-run `report.md`, `result.json`, and `transcript.jsonl` contain "
            "the evidence needed for manual review.",
        )
    )
    return "\n".join(lines).encode("utf-8")
