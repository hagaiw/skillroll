"""The sole concrete OpenAI Agents SDK side-effect adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

from agents import (
    Agent,
    ModelSettings,
    OpenAIChatCompletionsModel,
    Runner,
    function_tool,
    set_tracing_disabled,
)
from openai import AsyncOpenAI

from skillroll.diagnostics import JSONValue
from skillroll.inference.profile import ResolvedInference
from skillroll.inference.transport import ModelUsage, ToolCall
from skillroll.models import ExecutionTopology, InferenceLimits
from skillroll.runtime.execution import SdkExecution, WorldActionHandler


def _json_object(value: Mapping[str, object]) -> Mapping[str, JSONValue]:
    """Accept only a small JSON object from the SDK's function-tool decoder."""
    encoded = json.dumps(value)
    if len(encoded.encode("utf-8")) > 16 * 1024:
        raise ValueError("world_action arguments are larger than 16 KiB.")
    return cast(Mapping[str, JSONValue], json.loads(encoded))


class AgentsSdkRuntime:
    """Execute with explicit client/model objects and tracing disabled."""

    async def run(
        self,
        instructions: str,
        user_input: str,
        profile: ResolvedInference,
        limits: InferenceLimits,
        world_action: WorldActionHandler | None = None,
        execution_topology: ExecutionTopology = "action_enabled",
    ) -> SdkExecution:
        """Run one agent with the explicitly selected execution topology."""
        if execution_topology not in {"action_enabled", "text_only"}:
            raise ValueError("SkillRoll received an unsupported execution topology.")
        calls: list[ToolCall] = []
        tools: list[Any] = []
        if execution_topology == "action_enabled":
            if world_action is None:
                raise ValueError(
                    "Action-enabled execution requires a World action handler."
                )

            @function_tool(
                name_override="world_action",
                description_override=(
                    "Request one intended action and receive its observed result. "
                    'For a bundled file read, use tool_name="Read" with arguments '
                    '{"path":"references/file.md"}. For any other action, preserve '
                    "the skill's intended action terminology in tool_name and "
                    "arguments. The action name records intent; it does not need a "
                    "SkillRoll-specific spelling. Do not invent another tool."
                ),
                strict_mode=False,
            )
            async def call_world_action(
                tool_name: str, arguments: dict[str, object]
            ) -> str:
                """Call the supplied world handler after checking bounded JSON input."""
                if not tool_name or len(tool_name) > 200:
                    raise ValueError(
                        "world_action tool_name must contain 1 to 200 characters."
                    )
                normalized = _json_object(arguments)
                calls.append(ToolCall(str(len(calls) + 1), tool_name, normalized))
                return await world_action(tool_name, normalized)

            tools.append(call_world_action)

        set_tracing_disabled(True)
        client = AsyncOpenAI(
            api_key=profile.api_key.reveal(),
            base_url=profile.base_url,
            timeout=limits.timeout_seconds,
            max_retries=0,
        )
        try:
            model = OpenAIChatCompletionsModel(profile.model, openai_client=client)
            agent = Agent(
                name="SkillRoll evaluated skill",
                instructions=instructions,
                model=model,
                tools=tools,
                model_settings=ModelSettings(
                    max_tokens=limits.max_output_tokens,
                    parallel_tool_calls=False,
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
                execution_topology,
            )
        finally:
            await client.close()


def _response_usage(response: object) -> ModelUsage | None:
    """Read an Agents SDK response usage value without depending on its class."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "input_token_details", None)
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
