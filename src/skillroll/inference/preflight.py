"""Executable compatibility check for a configured model endpoint."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from skillroll.diagnostics import JSONValue
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
)
from skillroll.inference.transport import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatTool,
    ChatTransport,
    ModelUsage,
    ToolCall,
    TransportFailure,
)

_PREFLIGHT_TOOL = ChatTool(
    "skillroll_preflight",
    "Return the supplied value so SkillRoll can verify tool support.",
    {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ("value",),
        "additionalProperties": False,
    },
)

_PREFLIGHT_RESPONSE_FORMAT: dict[str, JSONValue] = {
    "type": "json_schema",
    "json_schema": {
        "name": "skillroll_preflight_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ("ready",)}},
            "required": ("status",),
            "additionalProperties": False,
        },
    },
}

# Compatibility replies contain one tiny tool call and one tiny JSON object.
# Do not inherit a repository's much larger eval-generation allowance: reasoning
# providers may use that entire budget before returning these deterministic replies.
_PREFLIGHT_MAX_OUTPUT_TOKENS = 1024


@dataclass(frozen=True, slots=True)
class PreflightEvidence:
    """Safe provider facts from the two request compatibility exchange."""

    response_model: str | None
    usage: tuple[ModelUsage, ...]


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """Either proof of compatible tool handling or a safe reason it failed."""

    evidence: PreflightEvidence | None
    failure: InferenceFailure | None

    @property
    def passed(self) -> bool:
        return self.evidence is not None and self.failure is None


def _invalid(summary: str) -> PreflightResult:
    return PreflightResult(
        None,
        InferenceFailure(InferenceFailureKind.MALFORMED_RESPONSE, summary),
    )


def _valid_call(response: ChatResponse) -> ToolCall | None:
    if len(response.tool_calls) != 1:
        return None
    call = response.tool_calls[0]
    value: JSONValue | None = call.arguments.get("value")
    if call.name != _PREFLIGHT_TOOL.name or value != "ready":
        return None
    return call


async def run_preflight(
    profile: ResolvedInference, transport: ChatTransport
) -> PreflightResult:
    """Prove tool calling, tool results, and a final reply.

    The request asks for one named call but does not force tool_choice. Some
    OpenAI-compatible models support tools while rejecting forced named calls;
    accepting the model's compliant response keeps this check useful across a
    wider compatible interface.
    """
    output_tokens = min(profile.limits.max_output_tokens, _PREFLIGHT_MAX_OUTPUT_TOKENS)
    first = ChatRequest(
        profile.model,
        (
            ChatMessage(
                "user",
                "Call the skillroll_preflight tool exactly once with value ready. "
                "Do not write text.",
            ),
        ),
        (_PREFLIGHT_TOOL,),
        None,
        output_tokens,
    )
    try:
        first_response = await transport.complete(first)
        call = _valid_call(first_response)
        if call is None:
            return _invalid(
                "The endpoint did not make exactly one valid skillroll_preflight call."
            )
        second = ChatRequest(
            profile.model,
            (
                first.messages[0],
                ChatMessage("assistant", tool_calls=(call,)),
                ChatMessage("tool", "ready", tool_call_id=call.id),
                ChatMessage(
                    "user",
                    "The tool returned ready. Return the required JSON status.",
                ),
            ),
            (),
            None,
            output_tokens,
            response_format=_PREFLIGHT_RESPONSE_FORMAT,
        )
        second_response = await transport.complete(second)
    except asyncio.CancelledError:
        return PreflightResult(
            None,
            InferenceFailure(
                InferenceFailureKind.CANCELLED,
                "The compatibility check was cancelled before it finished.",
            ),
        )
    except TransportFailure as error:
        return PreflightResult(None, error.failure)
    try:
        final_value = json.loads(second_response.content or "")
    except json.JSONDecodeError:
        final_value = None
    if second_response.tool_calls or final_value != {"status": "ready"}:
        return _invalid(
            "The endpoint did not return the required structured final answer after "
            "the tool result."
        )
    usage = tuple(
        item
        for item in (first_response.usage, second_response.usage)
        if item is not None
    )
    return PreflightResult(
        PreflightEvidence(second_response.model or first_response.model, usage), None
    )
