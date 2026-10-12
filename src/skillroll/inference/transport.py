"""Small, fakeable OpenAI-compatible transports (Chat Completions and Responses)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, Self, cast

from skillroll.diagnostics import JSONValue
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
    SecretRedactor,
)
from skillroll.models import InferenceWire

# Kept as patchable lazy sentinels so --help/invalid configuration work from a
# dependency-free wheel, while the HTTP adapter imports OpenAI only when used.
openai: Any | None = None
AsyncOpenAI: type[Any] | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A normalized function call returned by a compatible model."""

    id: str
    name: str
    arguments: Mapping[str, JSONValue]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One non-streaming chat message, including an optional tool exchange."""

    role: str
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChatTool:
    """The one function shape required by a chat request."""

    name: str
    description: str
    parameters: Mapping[str, JSONValue]


@dataclass(frozen=True, slots=True)
class ChatRequest:
    """A provider-neutral non-streaming Chat Completions request."""

    model: str
    messages: tuple[ChatMessage, ...]
    tools: tuple[ChatTool, ...] = ()
    force_tool: str | None = None
    max_output_tokens: int = 8192
    temperature: float | None = None
    response_format: Mapping[str, JSONValue] | None = None


@dataclass(frozen=True, slots=True)
class ModelUsage:
    """Usage reported by a provider, where missing values remain missing."""

    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cache_read_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ChatResponse:
    """The minimal response surface needed by preflight and execution."""

    content: str | None
    tool_calls: tuple[ToolCall, ...]
    model: str | None
    usage: ModelUsage | None
    response_id: str | None = None
    finish_reason: str | None = None


class TransportFailure(Exception):
    """An expected, already-redacted transport failure."""

    def __init__(self, failure: InferenceFailure) -> None:
        self.failure = failure
        super().__init__(failure.summary)


class ChatTransport(Protocol):
    """The injected seam used by deterministic tests and preflight."""

    async def complete(self, request: ChatRequest) -> ChatResponse: ...

    async def close(self) -> None: ...


def _request_messages(messages: Sequence[ChatMessage]) -> list[dict[str, object]]:
    rendered: list[dict[str, object]] = []
    for message in messages:
        value: dict[str, object] = {"role": message.role, "content": message.content}
        if message.tool_calls:
            value["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]
        if message.tool_call_id is not None:
            value["tool_call_id"] = message.tool_call_id
        rendered.append(value)
    return rendered


def _request_tools(tools: Sequence[ChatTool]) -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
            },
        }
        for tool in tools
    ]


def _usage(response: object) -> ModelUsage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "prompt_tokens_details", None)
    cache_read_tokens = getattr(details, "cached_tokens", None)
    if cache_read_tokens is None:
        cache_read_tokens = getattr(usage, "cached_tokens", None)
    return ModelUsage(
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        getattr(usage, "total_tokens", None),
        cache_read_tokens,
    )


def _response_tool_calls(message: object) -> tuple[ToolCall, ...]:
    values = getattr(message, "tool_calls", None) or ()
    parsed: list[ToolCall] = []
    for value in values:
        function: object = getattr(value, "function", None)
        name: object = getattr(function, "name", None)
        arguments: object = getattr(function, "arguments", None)
        identifier: object = getattr(value, "id", None)
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(arguments, str)
            or not arguments
            or not isinstance(identifier, str)
            or not identifier
        ):
            raise ValueError("A tool call was missing its id, name, or arguments.")
        decoded = json.loads(arguments)
        if not isinstance(decoded, dict) or any(
            not isinstance(key, str) for key in decoded
        ):
            raise ValueError("A tool call's arguments were not a JSON object.")
        parsed.append(ToolCall(identifier, name, decoded))
    return tuple(parsed)


def _responses_input(messages: Sequence[ChatMessage]) -> list[dict[str, object]]:
    """Render chat messages as Responses input items.

    Responses has no `messages` array and no `tool` role: an assistant tool call
    becomes a standalone `function_call` item, and its result becomes a matching
    `function_call_output` item keyed by the same `call_id`.
    """
    items: list[dict[str, object]] = []
    for message in messages:
        if message.tool_call_id is not None:
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.content or "",
                }
            )
            continue
        if message.content is not None:
            items.append({"role": message.role, "content": message.content})
        items.extend(
            {
                "type": "function_call",
                "call_id": call.id,
                "name": call.name,
                "arguments": json.dumps(call.arguments),
            }
            for call in message.tool_calls
        )
    return items


def _responses_tools(tools: Sequence[ChatTool]) -> list[dict[str, object]]:
    """Render tools flat, as Responses expects, not nested under `function`."""
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
            # Matches the Chat Completions path, which never sets strict.
            "strict": False,
        }
        for tool in tools
    ]


def _responses_text(response_format: Mapping[str, JSONValue]) -> dict[str, object]:
    """Translate a Chat Completions response_format into a Responses text config.

    Responses flattens the structured-output wrapper: Chat Completions nests
    name/schema/strict under a `json_schema` key, while Responses places them
    beside `type` inside `text.format`.
    """
    rendered: dict[str, object] = dict(response_format)
    nested = rendered.pop("json_schema", None)
    if isinstance(nested, Mapping):
        rendered.update(nested)
    return {"format": rendered}


def _responses_tool_call(item: object) -> ToolCall:
    name: object = getattr(item, "name", None)
    arguments: object = getattr(item, "arguments", None)
    identifier: object = getattr(item, "call_id", None)
    if (
        not isinstance(name, str)
        or not name
        or not isinstance(arguments, str)
        or not arguments
        or not isinstance(identifier, str)
        or not identifier
    ):
        raise ValueError("A tool call was missing its id, name, or arguments.")
    decoded = json.loads(arguments)
    if not isinstance(decoded, dict) or any(
        not isinstance(key, str) for key in decoded
    ):
        raise ValueError("A tool call's arguments were not a JSON object.")
    return ToolCall(identifier, name, decoded)


def _responses_output(response: object) -> tuple[str | None, tuple[ToolCall, ...]]:
    """Read text and tool calls out of the Responses `output` array.

    Items of any other type — reasoning above all, which reasoning models emit
    alongside their answer — carry nothing SkillRoll consumes, so they are
    skipped rather than treated as a malformed response.
    """
    texts: list[str] = []
    calls: list[ToolCall] = []
    for item in getattr(response, "output", None) or ():
        kind = getattr(item, "type", None)
        if kind == "function_call":
            calls.append(_responses_tool_call(item))
        elif kind == "message":
            for part in getattr(item, "content", None) or ():
                text = getattr(part, "text", None)
                if getattr(part, "type", None) == "output_text" and isinstance(
                    text, str
                ):
                    texts.append(text)
    joined = "".join(texts)
    return joined or None, tuple(calls)


def _responses_usage(response: object) -> ModelUsage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "input_tokens_details", None)
    return ModelUsage(
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
        getattr(usage, "total_tokens", None),
        getattr(details, "cached_tokens", None),
    )


def _responses_finish_reason(response: object) -> str | None:
    """Map a Responses status onto the finish_reason judging already reads.

    The judge treats "length" as a reply truncated by the output-token ceiling.
    Responses reports that as status "incomplete" with an incomplete_details
    reason of "max_output_tokens" instead of a per-choice finish_reason.
    """
    if getattr(response, "status", None) != "incomplete":
        return None
    details = getattr(response, "incomplete_details", None)
    reason = getattr(details, "reason", None)
    return "length" if reason == "max_output_tokens" else "incomplete"


def _classified_failure(
    module: Any, error: Exception
) -> tuple[InferenceFailureKind, str] | None:
    """Classify one provider error, or return None to let it propagate.

    Shared by both wires so a Responses failure reports the same kinds, and
    therefore the same user-facing diagnostics, as a Chat Completions one.
    """
    if isinstance(error, module.AuthenticationError):
        return (
            InferenceFailureKind.UNAUTHORIZED,
            "The endpoint rejected the API key.",
        )
    if isinstance(error, module.RateLimitError):
        return (
            InferenceFailureKind.RATE_LIMITED,
            "The endpoint rate-limited this request.",
        )
    if isinstance(error, module.APITimeoutError):
        return (
            InferenceFailureKind.TIMEOUT,
            "The endpoint did not respond before the configured timeout.",
        )
    if isinstance(error, module.APIStatusError):
        kind = (
            InferenceFailureKind.SERVICE_FAILURE
            if error.status_code >= 500
            else InferenceFailureKind.REQUEST_REJECTED
        )
        return kind, "The endpoint rejected SkillRoll's compatibility request."
    if isinstance(error, json.JSONDecodeError | ValueError | IndexError | TypeError):
        return (
            InferenceFailureKind.MALFORMED_RESPONSE,
            "The endpoint returned a response SkillRoll could not read.",
        )
    if isinstance(error, module.APIError):
        return (
            InferenceFailureKind.SERVICE_FAILURE,
            "SkillRoll could not contact the configured endpoint.",
        )
    return None


class OpenAIChatTransport:
    """Explicit client adapter; the only normal HTTP implementation."""

    def __init__(self, profile: ResolvedInference) -> None:
        self._profile = profile
        self._redactor = SecretRedactor(profile.api_key)
        client_type = AsyncOpenAI
        if client_type is None:
            from openai import AsyncOpenAI as imported_client

            client_type = imported_client
        self._client = client_type(
            api_key=profile.api_key.reveal(),
            base_url=profile.base_url,
            timeout=profile.limits.timeout_seconds,
            max_retries=0,
        )

    async def complete(self, request: ChatRequest) -> ChatResponse:
        """Perform exactly one non-streaming Chat Completions request."""
        module = openai
        if module is None:
            import openai as imported_openai

            module = imported_openai

        try:
            request_values: dict[str, object] = {
                "model": cast(Any, request.model),
                "messages": cast(Any, _request_messages(request.messages)),
                "tools": cast(Any, _request_tools(request.tools) or None),
                "tool_choice": cast(
                    Any,
                    {
                        "type": "function",
                        "function": {"name": request.force_tool},
                    }
                    if request.force_tool is not None
                    else None,
                ),
                "max_tokens": request.max_output_tokens,
                "stream": False,
            }
            if request.temperature is not None and self._profile.supports_temperature:
                request_values["temperature"] = request.temperature
            if request.response_format is not None:
                request_values["response_format"] = dict(request.response_format)
            # Provider-specific parameters travel through the SDK's own
            # extra_body escape hatch. Config validation rejects any key
            # SkillRoll sets above, so this cannot override the request shape.
            if self._profile.extra_body:
                request_values["extra_body"] = dict(self._profile.extra_body)
            response = await self._client.chat.completions.create(
                **cast(Any, request_values)
            )
            if len(response.choices) != 1:
                raise ValueError("The endpoint did not return exactly one choice.")
            message = response.choices[0].message
            finish_reason = getattr(response.choices[0], "finish_reason", None)
            return ChatResponse(
                message.content,
                _response_tool_calls(message),
                getattr(response, "model", None),
                _usage(response),
                getattr(response, "id", None),
                finish_reason if isinstance(finish_reason, str) else None,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            classified = _classified_failure(module, error)
            if classified is None:
                raise
            kind, summary = classified
            raise self._failure(kind, summary, error) from error

    def _failure(
        self, kind: InferenceFailureKind, summary: str, error: Exception
    ) -> TransportFailure:
        return TransportFailure(
            InferenceFailure(kind, summary, (self._redactor.redact(str(error)),))
        )

    async def close(self) -> None:
        """Close the request-scoped HTTP client even after cancellation."""
        await self._client.close()

    @classmethod
    def from_profile(cls, profile: ResolvedInference) -> Self:
        """A named factory keeps CLI construction easy to replace in tests."""
        return cls(profile)


class OpenAIResponsesTransport:
    """The same request surface, spoken over /v1/responses.

    Some reasoning models refuse function tools on Chat Completions and accept
    them only here, so this adapter exists to keep reasoning available rather
    than to expose anything new: it satisfies the identical ChatTransport
    protocol and returns the identical ChatResponse.
    """

    def __init__(self, profile: ResolvedInference) -> None:
        self._profile = profile
        self._redactor = SecretRedactor(profile.api_key)
        client_type = AsyncOpenAI
        if client_type is None:
            from openai import AsyncOpenAI as imported_client

            client_type = imported_client
        self._client = client_type(
            api_key=profile.api_key.reveal(),
            base_url=profile.base_url,
            timeout=profile.limits.timeout_seconds,
            max_retries=0,
        )

    async def complete(self, request: ChatRequest) -> ChatResponse:
        """Perform exactly one non-streaming Responses request."""
        module = openai
        if module is None:
            import openai as imported_openai

            module = imported_openai

        try:
            request_values: dict[str, object] = {
                "model": cast(Any, request.model),
                "input": cast(Any, _responses_input(request.messages)),
                "tools": cast(Any, _responses_tools(request.tools) or None),
                "tool_choice": cast(
                    Any,
                    {"type": "function", "name": request.force_tool}
                    if request.force_tool is not None
                    else None,
                ),
                "max_output_tokens": request.max_output_tokens,
                "stream": False,
            }
            if request.temperature is not None and self._profile.supports_temperature:
                request_values["temperature"] = request.temperature
            if request.response_format is not None:
                request_values["text"] = _responses_text(request.response_format)
            # Provider-specific parameters travel through the SDK's own
            # extra_body escape hatch. Config validation rejects any key
            # SkillRoll sets above, so this cannot override the request shape.
            if self._profile.extra_body:
                request_values["extra_body"] = dict(self._profile.extra_body)
            response = await self._client.responses.create(**cast(Any, request_values))
            content, tool_calls = _responses_output(response)
            return ChatResponse(
                content,
                tool_calls,
                getattr(response, "model", None),
                _responses_usage(response),
                getattr(response, "id", None),
                _responses_finish_reason(response),
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            classified = _classified_failure(module, error)
            if classified is None:
                raise
            kind, summary = classified
            raise self._failure(kind, summary, error) from error

    def _failure(
        self, kind: InferenceFailureKind, summary: str, error: Exception
    ) -> TransportFailure:
        return TransportFailure(
            InferenceFailure(kind, summary, (self._redactor.redact(str(error)),))
        )

    async def close(self) -> None:
        """Close the request-scoped HTTP client even after cancellation."""
        await self._client.close()

    @classmethod
    def from_profile(cls, profile: ResolvedInference) -> Self:
        """A named factory keeps CLI construction easy to replace in tests."""
        return cls(profile)


def transport_class(
    wire: InferenceWire,
) -> type[OpenAIChatTransport | OpenAIResponsesTransport]:
    """Choose the transport class for one wire.

    Both provider call sites -- this transport (preflight, world simulation,
    judging) and the Agents SDK runtime that executes the skill -- select from
    profile.wire, so a provider cannot accept preflight on one endpoint and then
    be asked to execute on the other. Keep this in step with
    runtime.agents_sdk.model_class.
    """
    if wire is InferenceWire.RESPONSES:
        return OpenAIResponsesTransport
    return OpenAIChatTransport


def transport_for_profile(profile: ResolvedInference) -> ChatTransport:
    """Build the transport the resolved profile's wire selects."""
    return transport_class(profile.wire).from_profile(profile)
