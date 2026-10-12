"""The sole concrete OpenAI Agents SDK side-effect adapter."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

from agents import (
    Agent,
    FunctionTool,
    ModelSettings,
    OpenAIChatCompletionsModel,
    OpenAIResponsesModel,
    Runner,
    set_tracing_disabled,
)
from agents.tool_context import ToolContext
from openai import AsyncOpenAI

from skillroll.diagnostics import JSONValue
from skillroll.inference.profile import ResolvedInference
from skillroll.inference.transport import ModelUsage, ToolCall
from skillroll.models import InferenceLimits, InferenceWire
from skillroll.runtime.execution import (
    SdkExecution,
    ToolInputRecorder,
    WorldActionHandler,
)

WORLD_ACTION_DESCRIPTION = (
    "Request one intended action and receive its observed result. "
    'For a bundled file read, use tool_name="Read" with arguments '
    '{"path":"references/file.md"}. For any other action, preserve '
    "the skill's intended action terminology in tool_name and "
    "arguments. The action name records intent; it does not need a "
    "SkillRoll-specific spelling. Do not invent another tool."
)
WORLD_ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "world_action_args",
    "properties": {
        "tool_name": {"title": "Tool Name", "type": "string"},
        "arguments": {
            "title": "Arguments",
            "type": "object",
            "additionalProperties": True,
        },
    },
    "required": ["tool_name", "arguments"],
}
# Some models leak their native tool-call markup into a JSON string value, e.g.
# '{"command": "ls"}\n<parameter name="tool_name">Bash'.
_PARAMETER_TAG = re.compile(r'\s*</?parameter(?: name="(\w+)")?>\s*')


def model_class(
    wire: InferenceWire,
) -> type[OpenAIChatCompletionsModel | OpenAIResponsesModel]:
    """Choose the SDK model class for one wire.

    Execution reads the same profile.wire the compatibility transport reads, so a
    provider that accepted preflight on one endpoint is never asked to execute on
    the other. Keep this in step with transport.transport_for_profile. The names
    resolve at call time so tests can substitute the SDK classes.
    """
    if wire is InferenceWire.RESPONSES:
        return OpenAIResponsesModel
    return OpenAIChatCompletionsModel


def _json_object(value: Mapping[str, object]) -> Mapping[str, JSONValue]:
    """Accept only a small JSON object from the world_action decoder."""
    encoded = json.dumps(value)
    if len(encoded.encode("utf-8")) > 16 * 1024:
        raise ValueError("world_action arguments are larger than 16 KiB.")
    return cast(Mapping[str, JSONValue], json.loads(encoded))


def _object_value(value: object) -> dict[str, object] | None:
    """Return a JSON object, decoding a string-encoded one when necessary."""
    if isinstance(value, str):
        for candidate in (value, value.strip().strip('"')):
            try:
                value = json.loads(candidate)
                break
            except ValueError:
                continue
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return None
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def decode_world_action(raw: str) -> tuple[str, dict[str, object], str | None] | None:
    """Decode world_action input leniently.

    Returns the tool name, arguments and a recovery note (None when the input
    was already well formed), or None when no unambiguous call can be found.
    """
    try:
        parsed: object = json.loads(raw)
    except ValueError:
        parsed = None
    fields = dict(cast(dict[str, object], parsed)) if isinstance(parsed, dict) else {}
    recovery: str | None = None
    text = fields.get("arguments") if isinstance(parsed, dict) else raw
    if isinstance(text, str):
        if isinstance(parsed, dict):
            recovery = "decoded string-encoded arguments"
        pieces = _PARAMETER_TAG.split(text)
        if len(pieces) > 1:
            recovery = "recovered from leaked <parameter> markup"
            fields.pop("arguments", None)
            if pieces[0].strip():
                fields["arguments"] = pieces[0]
            for name, value in zip(pieces[1::2], pieces[2::2], strict=True):
                if name is not None and name not in fields:
                    fields[name] = value.strip()
    tool_name = fields.get("tool_name")
    arguments = _object_value(fields.get("arguments"))
    if not isinstance(tool_name, str) or not tool_name.strip() or arguments is None:
        return None
    return tool_name, arguments, recovery


def world_action_tool(
    world_action: WorldActionHandler, calls: list[ToolCall]
) -> FunctionTool:
    """Build the single world_action tool with a lenient input decoder."""
    recorder = world_action if isinstance(world_action, ToolInputRecorder) else None

    async def invoke(_: ToolContext[Any], raw: str) -> str:
        decoded = decode_world_action(raw)
        if decoded is None:
            message = (
                'world_action input must be a JSON object with "tool_name" '
                '(string) and "arguments" (object). Received: ' + raw[:200]
            )
            if recorder is not None:
                recorder.record_tool_input("rejected", raw, message)
            return message
        tool_name, arguments, recovery = decoded
        if recovery is not None and recorder is not None:
            recorder.record_tool_input("recovered", raw, recovery)
        try:
            if len(tool_name) > 200:
                raise ValueError(
                    "world_action tool_name must contain 1 to 200 characters."
                )
            normalized = _json_object(arguments)
            calls.append(ToolCall(str(len(calls) + 1), tool_name, normalized))
            return await world_action(tool_name, normalized)
        except Exception as error:
            # Same model-visible text the SDK's default tool-error handler used.
            return (
                "An error occurred while running the tool. Please try again. "
                f"Error: {error}"
            )

    return FunctionTool(
        name="world_action",
        description=WORLD_ACTION_DESCRIPTION,
        params_json_schema=WORLD_ACTION_SCHEMA,
        on_invoke_tool=invoke,
        strict_json_schema=False,
    )


class AgentsSdkRuntime:
    """Execute with explicit client/model objects and tracing disabled."""

    async def run(
        self,
        instructions: str,
        user_input: str,
        profile: ResolvedInference,
        limits: InferenceLimits,
        world_action: WorldActionHandler,
    ) -> SdkExecution:
        """Run one agent with only the generic world_action function tool."""
        calls: list[ToolCall] = []

        set_tracing_disabled(True)
        client = AsyncOpenAI(
            api_key=profile.api_key.reveal(),
            base_url=profile.base_url,
            timeout=limits.timeout_seconds,
            max_retries=0,
        )
        try:
            model = model_class(profile.wire)(profile.model, openai_client=client)
            agent = Agent(
                name="SkillRoll evaluated skill",
                instructions=instructions,
                model=model,
                tools=[world_action_tool(world_action, calls)],
                model_settings=ModelSettings(
                    # The SDK renames this to max_output_tokens on the Responses
                    # wire, so one setting covers both models.
                    max_tokens=limits.max_output_tokens,
                    parallel_tool_calls=False,
                    # Same provider-specific parameters the compatibility
                    # transport sends, so execution cannot be rejected by a
                    # provider that already accepted preflight.
                    extra_body=dict(profile.extra_body) or None,
                ),
            )
            result = await Runner.run(agent, user_input, max_turns=limits.max_turns)
            output = result.final_output
            if not isinstance(output, str) or not output.strip():
                raise ValueError("The model returned no final text output.")
            raw_responses = getattr(result, "raw_responses", None)
            if isinstance(raw_responses, Sequence) and not isinstance(
                raw_responses, (str, bytes, bytearray)
            ):
                turns = len(raw_responses)
                turns_source = "provider"
                usage = tuple(
                    usage
                    for response in raw_responses
                    if (usage := _response_usage(response)) is not None
                )
            else:
                turns = None
                turns_source = "unavailable"
                usage = ()
            return SdkExecution(
                output,
                turns,
                usage,
                tuple(calls),
                turns_source,
            )
        finally:
            await client.close()


def _response_usage(response: object) -> ModelUsage | None:
    """Read an Agents SDK response usage value without depending on its class."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "input_tokens_details", None)
    if details is None:
        details = getattr(usage, "prompt_tokens_details", None)
    cache_read_tokens = getattr(details, "cached_tokens", None)
    if cache_read_tokens is None:
        cache_read_tokens = getattr(usage, "cached_tokens", None)
    return ModelUsage(
        getattr(usage, "input_tokens", getattr(usage, "prompt_tokens", None)),
        getattr(usage, "output_tokens", getattr(usage, "completion_tokens", None)),
        getattr(usage, "total_tokens", None),
        cache_read_tokens,
    )
