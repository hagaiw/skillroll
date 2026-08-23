"""Prompt construction and one model call for an unmatched intended action."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
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
from skillroll.prompt_resources import load_harness_prompt

MAX_WORLD_BYTES = 64 * 1024
MAX_RESULT_BYTES = 64 * 1024
MAX_HISTORY_BYTES = 48 * 1024

_SYSTEM = load_harness_prompt("world")


class WorldModelError(Exception):
    """A model world response could not safely become an action result."""

    def __init__(self, failure: InferenceFailure) -> None:
        self.failure = failure
        super().__init__(failure.summary)


@dataclass(frozen=True, slots=True)
class HistoryItem:
    """One complete, already observed action/result pair."""

    tool_name: str
    arguments: Mapping[str, JSONValue]
    result: str


@dataclass(frozen=True, slots=True)
class WorldReply:
    """A validated generated result plus optional provider observations."""

    result: str
    model: str | None
    usage: ModelUsage | None
    omitted_history: int


def _action_text(tool_name: str, arguments: Mapping[str, JSONValue]) -> str:
    arguments_text = json.dumps(
        arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"tool_name: {tool_name}\narguments: {arguments_text}"


def history_view(history: tuple[HistoryItem, ...]) -> tuple[str, int]:
    """Keep newest complete pairs within the deterministic history byte ceiling."""
    included: list[str] = []
    used = 0
    for index, item in reversed(tuple(enumerate(history))):
        rendered = (
            f"Action {index}:\n{_action_text(item.tool_name, item.arguments)}\n"
            f"result: {item.result}\n"
        )
        size = len(rendered.encode("utf-8"))
        if used + size > MAX_HISTORY_BYTES:
            break
        included.append(rendered)
        used += size
    omitted = len(history) - len(included)
    prefix = (
        ""
        if not omitted
        else (
            f"Earlier simulated actions omitted from this request: {omitted}. "
            "Do not contradict facts visible below.\n"
        )
    )
    return prefix + "".join(reversed(included)), omitted


def world_request(
    profile: ResolvedInference,
    limits_tokens: int,
    world: str,
    history: tuple[HistoryItem, ...],
    tool_name: str,
    arguments: Mapping[str, JSONValue],
) -> tuple[ChatRequest, int]:
    """Build a tool-free Chat Completions request for one intended action."""
    if len(world.encode("utf-8")) > MAX_WORLD_BYTES:
        raise WorldModelError(
            InferenceFailure(
                InferenceFailureKind.EXECUTION_ERROR,
                "The eval case's World section is larger than SkillRoll's 64 KiB "
                "limit.",
            )
        )
    past, omitted = history_view(history)
    prompt = (
        f"World:\n{world}\n\nPrior action results:\n{past or '(none)'}\n"
        f"Current intended action:\n{_action_text(tool_name, arguments)}"
    )
    return ChatRequest(
        profile.model,
        (ChatMessage("system", _SYSTEM), ChatMessage("user", prompt)),
        (),
        None,
        limits_tokens,
        0.0,
    ), omitted


async def model_action(
    transport: ChatTransport,
    profile: ResolvedInference,
    limits_tokens: int,
    world: str,
    history: tuple[HistoryItem, ...],
    tool_name: str,
    arguments: Mapping[str, JSONValue],
) -> WorldReply:
    """Make exactly one matching-profile request and validate its text result."""
    request, omitted = world_request(
        profile, limits_tokens, world, history, tool_name, arguments
    )
    try:
        response = await transport.complete(request)
    except asyncio.CancelledError:
        raise
    except TransportFailure as error:
        raise WorldModelError(error.failure) from error
    except Exception as error:
        redactor = SecretRedactor(profile.api_key)
        raise WorldModelError(
            InferenceFailure(
                InferenceFailureKind.SERVICE_FAILURE,
                "SkillRoll could not simulate this action.",
                (redactor.redact(str(error)),),
            )
        ) from error
    if response.tool_calls:
        raise WorldModelError(
            InferenceFailure(
                InferenceFailureKind.MALFORMED_RESPONSE,
                "The simulated world returned a tool call instead of an action result.",
            )
        )
    if not isinstance(response.content, str) or not response.content.strip():
        raise WorldModelError(
            InferenceFailure(
                InferenceFailureKind.MALFORMED_RESPONSE,
                "The simulated world returned no action result text.",
            )
        )
    if len(response.content.encode("utf-8")) > MAX_RESULT_BYTES:
        raise WorldModelError(
            InferenceFailure(
                InferenceFailureKind.MALFORMED_RESPONSE,
                "The simulated world returned more than SkillRoll's 64 KiB "
                "action-result limit.",
            )
        )
    return WorldReply(response.content, response.model, response.usage, omitted)
