"""One bounded, evidence-only semantic decision for a completed eval case."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass

from skillroll.diagnostics import JSONValue
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
    SecretRedactor,
)
from skillroll.inference.transport import (
    ChatMessage,
    ChatRequest,
    ChatTransport,
    ModelUsage,
    TransportFailure,
)
from skillroll.models import EvalCase
from skillroll.prompt_resources import load_harness_prompt
from skillroll.runtime.execution import ExecutionResult
from skillroll.world.session import WorldEvent

MAX_JUDGE_BYTES = 256 * 1024
MAX_EXPLANATION_BYTES = 4 * 1024
JUDGE_OUTPUT_TOKEN_TIERS = (4096, 8192, 16384)
_SYSTEM = load_harness_prompt("judge")


@dataclass(frozen=True, slots=True)
class JudgeResult:
    """The judge's coherent semantic decision and safe provider evidence."""

    verdict: str
    rationale: str
    unmet_criteria: tuple[str, ...]
    model: str | None
    usage: ModelUsage | None
    criteria: tuple[CriterionAssessment, ...] = ()


@dataclass(frozen=True, slots=True)
class CriterionAssessment:
    """One inspectable, model-reported assessment for an authored criterion."""

    criterion: str
    status: str
    evidence: str


def criteria_items(markdown: str) -> tuple[str, ...]:
    """Extract short authored criteria without turning them into assertions."""
    values = tuple(
        line.strip()[2:].strip()
        for line in markdown.splitlines()
        if line.strip().startswith(("- ", "* ")) and line.strip()[2:].strip()
    )
    if values:
        return values
    stripped = markdown.strip()
    return (stripped,) if stripped else ("The observed behavior is acceptable.",)


def estimate_judge_output_tokens(criteria_count: int, evidence_bytes: int) -> int:
    """Return a conservative documented starting tier for semantic judgment."""
    if evidence_bytes > 64 * 1024 or criteria_count >= 7:
        tier = 2
    elif criteria_count <= 3:
        tier = 0
    else:
        tier = 1
    return JUDGE_OUTPUT_TOKEN_TIERS[tier]


def _diagnostic_output_tokens(
    criteria_count: int, evidence_bytes: int, configured: int
) -> int | None:
    estimate = estimate_judge_output_tokens(criteria_count, evidence_bytes)
    higher = next(
        (tier for tier in JUDGE_OUTPUT_TOKEN_TIERS if tier > configured), None
    )
    if higher is None:
        return None
    return max(estimate, higher)


def _event_text(event: WorldEvent) -> str:
    details = [
        f"{event.index}. tool: {event.tool_name}",
        "arguments: "
        + json.dumps(
            event.arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        f"source: {event.source}",
    ]
    if event.rule_name is not None:
        details.append(f"rule: {event.rule_name}")
    details.append(f"result: {event.result}")
    return "\n".join(details)


def _response_format(criteria_count: int) -> dict[str, JSONValue]:
    """Require the judge's bounded decision without echoed authored prose."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "skillroll_judge_decision",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string", "enum": ("PASS", "FAIL")},
                    "rationale": {"type": "string"},
                    "criteria": {
                        "type": "array",
                        "minItems": criteria_count,
                        "maxItems": criteria_count,
                        "items": {
                            "type": "object",
                            "properties": {
                                "status": {
                                    "type": "string",
                                    "enum": ("met", "not_met", "unclear"),
                                },
                                "evidence": {"type": "string"},
                            },
                            "required": ("status", "evidence"),
                            "additionalProperties": False,
                        },
                    },
                    "unmet_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 16,
                    },
                },
                "required": (
                    "verdict",
                    "rationale",
                    "criteria",
                    "unmet_criteria",
                ),
                "additionalProperties": False,
            },
        },
    }


def judge_request(
    profile: ResolvedInference,
    case: EvalCase,
    execution: ExecutionResult,
    events: tuple[WorldEvent, ...],
    *,
    skill_available: bool = True,
) -> tuple[ChatRequest | None, InferenceFailure | None]:
    """Render only task context and observed evidence for the judge."""
    del skill_available
    criteria = criteria_items(case.success_criteria_markdown)
    criteria_evidence = "\n".join(
        f"{index}. {criterion}" for index, criterion in enumerate(criteria, start=1)
    )
    actions = (
        "\n\n".join(_event_text(event) for event in events) or "No completed actions."
    )
    user = "\n\n".join(
        (
            "Input:\n" + case.input_markdown,
            "Success criteria:\n" + case.success_criteria_markdown,
            "Criteria to assess:\n" + criteria_evidence,
            "Complete ordered actions:\n" + actions,
            "Final output:\n" + execution.final_output,
        )
    )
    if len(user.encode("utf-8")) > MAX_JUDGE_BYTES:
        measured = len(user.encode("utf-8"))
        return None, InferenceFailure(
            InferenceFailureKind.EXECUTION_ERROR,
            f"The judge evidence for {case.identity.as_posix()} is {measured} "
            f"bytes, above SkillRoll's {MAX_JUDGE_BYTES} byte limit.",
            (
                "Make context, output, or action results more concise, or use a "
                "narrow deterministic check for structured evidence.",
            ),
        )
    return (
        ChatRequest(
            profile.model,
            (ChatMessage("system", _SYSTEM), ChatMessage("user", user)),
            (),
            None,
            profile.limits.max_output_tokens,
            0.0,
            response_format=_response_format(len(criteria)),
        ),
        None,
    )


def _parse(
    content: str | None,
    has_tools: bool,
    expected_criteria: Sequence[str] = (),
) -> tuple[JudgeResult | None, InferenceFailure | None]:
    if has_tools or content is None or not content.strip():
        return None, InferenceFailure(
            InferenceFailureKind.MALFORMED_RESPONSE,
            "The judge did not return the required JSON decision object.",
        )
    try:
        value = json.loads(content)
    except json.JSONDecodeError as error:
        return None, InferenceFailure(
            InferenceFailureKind.MALFORMED_RESPONSE,
            "The judge response was not valid JSON.",
            (str(error),),
        )
    required = {"verdict", "rationale", "unmet_criteria"}
    if expected_criteria:
        required.add("criteria")
    if not isinstance(value, dict) or set(value) != required:
        return None, InferenceFailure(
            InferenceFailureKind.JUDGE_INTEGRITY,
            "The judge response must contain exactly verdict, rationale, "
            + ("criteria, " if expected_criteria else "")
            + "and unmet_criteria.",
        )
    verdict = value.get("verdict")
    rationale = value.get("rationale")
    unmet = value.get("unmet_criteria")
    if verdict not in {"PASS", "FAIL"}:
        return None, InferenceFailure(
            InferenceFailureKind.JUDGE_INTEGRITY,
            "The judge verdict must be exactly PASS or FAIL.",
        )
    if not isinstance(rationale, str) or not rationale.strip():
        return None, InferenceFailure(
            InferenceFailureKind.JUDGE_INTEGRITY,
            "The judge rationale must be a non-empty string.",
        )
    if not isinstance(unmet, list) or any(
        not isinstance(item, str) or not item.strip() for item in unmet
    ):
        return None, InferenceFailure(
            InferenceFailureKind.JUDGE_INTEGRITY,
            "The judge unmet_criteria value must be an array of non-empty strings.",
        )
    unmet_criteria = tuple(item.strip() for item in unmet)
    assessments: tuple[CriterionAssessment, ...] = ()
    if expected_criteria:
        raw_criteria = value.get("criteria")
        if not isinstance(raw_criteria, list) or len(raw_criteria) != len(
            expected_criteria
        ):
            return None, InferenceFailure(
                InferenceFailureKind.JUDGE_INTEGRITY,
                "The judge must assess every authored Success criterion exactly once.",
            )
        parsed_criteria: list[CriterionAssessment] = []
        for index, item in enumerate(raw_criteria):
            if not isinstance(item, dict) or set(item) not in (
                {"status", "evidence"},
                {"criterion", "status", "evidence"},
            ):
                return None, InferenceFailure(
                    InferenceFailureKind.JUDGE_INTEGRITY,
                    f"The judge criterion assessment {index + 1} must contain "
                    "status and evidence only.",
                )
            status = item.get("status")
            evidence = item.get("evidence")
            if status not in {"met", "not_met", "unclear"}:
                return None, InferenceFailure(
                    InferenceFailureKind.JUDGE_INTEGRITY,
                    f"The judge criterion assessment {index + 1} status must be "
                    "exactly met, not_met, or unclear.",
                )
            if not isinstance(evidence, str) or not evidence.strip():
                return None, InferenceFailure(
                    InferenceFailureKind.JUDGE_INTEGRITY,
                    f"The judge criterion assessment {index + 1} evidence must "
                    "be a non-empty string.",
                )
            if len(evidence.encode("utf-8")) > MAX_EXPLANATION_BYTES:
                return None, InferenceFailure(
                    InferenceFailureKind.JUDGE_INTEGRITY,
                    f"The judge criterion assessment {index + 1} evidence exceeds "
                    f"SkillRoll's {MAX_EXPLANATION_BYTES} byte limit.",
                )
            parsed_criteria.append(
                CriterionAssessment(expected_criteria[index], status, evidence.strip())
            )
        assessments = tuple(parsed_criteria)
        statuses = {item.status for item in assessments}
        if verdict == "PASS" and statuses != {"met"}:
            return None, InferenceFailure(
                InferenceFailureKind.JUDGE_INTEGRITY,
                "A PASS judge decision requires every criterion assessment to be met.",
            )
        if verdict == "FAIL" and not statuses.intersection({"not_met", "unclear"}):
            return None, InferenceFailure(
                InferenceFailureKind.JUDGE_INTEGRITY,
                "A FAIL judge decision requires a not_met or unclear criterion.",
            )
    if (verdict == "PASS" and unmet_criteria) or (
        verdict == "FAIL" and not unmet_criteria
    ):
        return None, InferenceFailure(
            InferenceFailureKind.JUDGE_INTEGRITY,
            "The judge verdict and unmet_criteria disagree; SkillRoll cannot "
            "trust this decision.",
        )
    rationale = rationale.strip()
    if (
        len(rationale.encode("utf-8")) > MAX_EXPLANATION_BYTES
        or len(unmet_criteria) > 16
        or any(len(item.encode("utf-8")) > 1024 for item in unmet_criteria)
    ):
        return None, InferenceFailure(
            InferenceFailureKind.MALFORMED_RESPONSE,
            "The judge rationale or unmet criteria exceed SkillRoll's evidence limits.",
        )
    return (
        JudgeResult(verdict, rationale, unmet_criteria, None, None, assessments),
        None,
    )


async def judge(
    profile: ResolvedInference,
    transport: ChatTransport,
    case: EvalCase,
    execution: ExecutionResult,
    events: tuple[WorldEvent, ...],
    *,
    skill_available: bool = True,
) -> tuple[JudgeResult | None, InferenceFailure | None]:
    """Make exactly one no-tools request and normalize every technical failure."""
    request, failure = judge_request(
        profile, case, execution, events, skill_available=skill_available
    )
    if failure is not None:
        return None, failure
    assert request is not None
    try:
        response = await transport.complete(request)
    except asyncio.CancelledError:
        return None, InferenceFailure(
            InferenceFailureKind.CANCELLED,
            "The judge was cancelled before it could decide this evaluation.",
        )
    except TransportFailure as error:
        return None, error.failure
    except Exception as error:
        return None, InferenceFailure(
            InferenceFailureKind.SERVICE_FAILURE,
            "SkillRoll could not contact the configured judge.",
            (SecretRedactor(profile.api_key).redact(str(error)),),
        )
    if response.finish_reason == "length":
        criteria_count = len(criteria_items(case.success_criteria_markdown))
        evidence_bytes = len((request.messages[-1].content or "").encode("utf-8"))
        configured = profile.limits.max_output_tokens
        suggested = _diagnostic_output_tokens(
            criteria_count, evidence_bytes, configured
        )
        noun = "criterion" if criteria_count == 1 else "criteria"
        details = [
            "provider finish_reason: length",
            f"case complexity: {criteria_count} {noun}; {len(events)} completed "
            f"actions; {evidence_bytes} judge-evidence bytes",
        ]
        if suggested is None:
            details.append(
                "max_output_tokens is already 16384; shorten the criteria or "
                "evidence, or choose a model that can complete the structured verdict"
            )
        else:
            details.append(f"suggested diagnostic max_output_tokens: {suggested}")
        details.extend(
            (
                "The shared max_output_tokens limit also caps execution and World "
                "model calls; raising it increases worst-case spend.",
                "Preserve this ERROR and rerun with only that limit changed as a "
                "non-scoring diagnostic.",
            )
        )
        return None, InferenceFailure(
            InferenceFailureKind.MALFORMED_RESPONSE,
            f"The semantic judge exhausted max_output_tokens={configured}; no "
            "semantic verdict was produced. This run is a technical ERROR, not a "
            "skill FAIL.",
            tuple(details),
        )
    parsed, failure = _parse(
        response.content,
        bool(response.tool_calls),
        criteria_items(case.success_criteria_markdown),
    )
    if parsed is None:
        return None, failure
    return JudgeResult(
        parsed.verdict,
        parsed.rationale,
        parsed.unmet_criteria,
        response.model,
        response.usage,
        parsed.criteria,
    ), None
