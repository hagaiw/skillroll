"""A small, fakeable OpenAI-compatible Chat Completions transport."""

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
            if request.temperature is not None:
                request_values["temperature"] = request.temperature
            if request.response_format is not None:
                request_values["response_format"] = dict(request.response_format)
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
        except module.AuthenticationError as error:
            raise self._failure(
                InferenceFailureKind.UNAUTHORIZED,
                "The endpoint rejected the API key.",
                error,
            ) from error
        except module.RateLimitError as error:
            raise self._failure(
                InferenceFailureKind.RATE_LIMITED,
                "The endpoint rate-limited this request.",
                error,
            ) from error
        except module.APITimeoutError as error:
            raise self._failure(
                InferenceFailureKind.TIMEOUT,
                "The endpoint did not respond before the configured timeout.",
                error,
            ) from error
        except module.APIStatusError as error:
            kind = (
                InferenceFailureKind.SERVICE_FAILURE
                if error.status_code >= 500
                else InferenceFailureKind.REQUEST_REJECTED
            )
            raise self._failure(
                kind,
                "The endpoint rejected SkillRoll's compatibility request.",
                error,
            ) from error
        except (json.JSONDecodeError, ValueError, IndexError, TypeError) as error:
            raise self._failure(
                InferenceFailureKind.MALFORMED_RESPONSE,
                "The endpoint returned a response SkillRoll could not read.",
                error,
            ) from error
        except module.APIError as error:
            raise self._failure(
                InferenceFailureKind.SERVICE_FAILURE,
                "SkillRoll could not contact the configured endpoint.",
                error,
            ) from error

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
