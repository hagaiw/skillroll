"""Tests for [inference.wire] and the Responses transport.

Covers the full wiring from TOML parse -> InferenceSettings -> ResolvedInference
-> OpenAIResponsesTransport.complete(), the Chat Completions default staying
byte-identical, and the invariant that both provider call sites select the same
wire.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from skillroll.config import _inference_wire, load_config
from skillroll.inference import transport as transport_module
from skillroll.inference.profile import (
    ResolvedInference,
    SecretRedactor,
    SecretValue,
    resolve_inference,
)
from skillroll.inference.transport import ChatRequest
from skillroll.models import InferenceLimits, InferenceSettings, InferenceWire
from skillroll.runtime import agents_sdk

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_repo(root: Path, extra: str = "") -> Path:
    """Write a minimal valid repository with an optional extra TOML block."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "skills").mkdir(exist_ok=True)
    (root / "skillroll.toml").write_text(
        "schema_version = 1\n"
        'skills_path = "skills"\n\n'
        "[inference]\n"
        'base_url = "https://example.test/v1"\n'
        'model = "example/model"\n'
        'api_key_env = "KEY"\n' + extra,
        encoding="utf-8",
    )
    return root


def fake_profile(
    wire: InferenceWire = InferenceWire.CHAT_COMPLETIONS,
    extra_body: dict[str, object] | None = None,
    supports_temperature: bool = True,
) -> ResolvedInference:
    return ResolvedInference(
        base_url="https://example.test/v1",
        model="example/model",
        api_key=SecretValue("key"),
        limits=InferenceLimits(),
        extra_body=extra_body or {},
        wire=wire,
        supports_temperature=supports_temperature,
    )


# ---------------------------------------------------------------------------
# _inference_wire validator
# ---------------------------------------------------------------------------


def test_wire_validator_defaults_to_chat_completions() -> None:
    assert _inference_wire(None) is InferenceWire.CHAT_COMPLETIONS


@pytest.mark.parametrize("wire", list(InferenceWire))
def test_wire_validator_accepts_every_supported_wire(wire: InferenceWire) -> None:
    assert _inference_wire(wire.value) is wire


def test_wire_validator_rejects_unknown_value() -> None:
    assert _inference_wire("grpc") is None


def test_wire_validator_rejects_non_string() -> None:
    assert _inference_wire(1) is None
    assert _inference_wire(["responses"]) is None


# ---------------------------------------------------------------------------
# Config parsing and profile resolution
# ---------------------------------------------------------------------------


def test_config_parses_responses_wire(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", 'wire = "responses"\n')
    result = load_config(root)
    assert result.is_valid
    assert result.value is not None
    assert result.value.inference is not None
    assert result.value.inference.wire is InferenceWire.RESPONSES


def test_config_absent_wire_defaults_to_chat_completions(tmp_path: Path) -> None:
    """Regression guard: an existing config must keep its current behavior."""
    root = write_repo(tmp_path / "repo")
    result = load_config(root)
    assert result.value is not None
    assert result.value.inference is not None
    assert result.value.inference.wire is InferenceWire.CHAT_COMPLETIONS


def test_config_rejects_unknown_wire(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", 'wire = "soap"\n')
    assert load_config(root).value is None


def test_resolve_inference_propagates_wire() -> None:
    settings = InferenceSettings(
        "https://example.test/v1",
        "example/model",
        "KEY",
        wire=InferenceWire.RESPONSES,
    )
    resolved, failure = resolve_inference(settings, {"KEY": "secret"})
    assert failure is None
    assert resolved is not None
    assert resolved.wire is InferenceWire.RESPONSES


def test_resolve_inference_defaults_to_chat_completions_wire() -> None:
    settings = InferenceSettings("https://example.test/v1", "example/model", "KEY")
    resolved, _ = resolve_inference(settings, {"KEY": "secret"})
    assert resolved is not None
    assert resolved.wire is InferenceWire.CHAT_COMPLETIONS


# ---------------------------------------------------------------------------
# The two provider call sites must never disagree about the wire
# ---------------------------------------------------------------------------

# One row per wire, naming the pair that must be selected together. Adding a
# wire without teaching both call sites about it fails these tests.
_EXPECTED_PAIRS = {
    InferenceWire.CHAT_COMPLETIONS: (
        transport_module.OpenAIChatTransport,
        agents_sdk.OpenAIChatCompletionsModel,
    ),
    InferenceWire.RESPONSES: (
        transport_module.OpenAIResponsesTransport,
        agents_sdk.OpenAIResponsesModel,
    ),
}


@pytest.mark.parametrize("wire", list(InferenceWire))
def test_every_wire_selects_a_matching_transport_and_model(wire: InferenceWire) -> None:
    expected_transport, expected_model = _EXPECTED_PAIRS[wire]
    assert transport_module.transport_class(wire) is expected_transport
    assert agents_sdk.model_class(wire) is expected_model


def test_expected_pairs_cover_every_wire() -> None:
    assert set(_EXPECTED_PAIRS) == set(InferenceWire)


# ---------------------------------------------------------------------------
# Responses transport: request shape
# ---------------------------------------------------------------------------


def _make_transport(
    extra_body: dict[str, object] | None = None,
    response: object | None = None,
    supports_temperature: bool = True,
) -> tuple[transport_module.OpenAIResponsesTransport, list[dict[str, Any]]]:
    """Return a Responses transport whose fake client records create() kwargs."""
    recorded: list[dict[str, Any]] = []

    default = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="function_call", call_id="c1", name="fn", arguments='{"x":1}'
            )
        ],
        model="m",
        usage=None,
        id="r1",
        status="completed",
    )

    class FakeResponses:
        async def create(self, **kwargs: object) -> object:
            recorded.append(dict(kwargs))
            payload = default if response is None else response
            if isinstance(payload, BaseException):
                raise payload
            return payload

    async def close() -> None:
        return None

    fake = object.__new__(transport_module.OpenAIResponsesTransport)
    p = fake_profile(InferenceWire.RESPONSES, extra_body, supports_temperature)
    object.__setattr__(
        fake, "_client", SimpleNamespace(responses=FakeResponses(), close=close)
    )
    object.__setattr__(fake, "_redactor", SecretRedactor(p.api_key))
    object.__setattr__(fake, "_profile", p)
    return fake, recorded


def test_responses_request_uses_input_and_max_output_tokens() -> None:
    transport, calls = _make_transport()
    request = ChatRequest(
        "example/model", (transport_module.ChatMessage("user", "hi"),), (), None, 512
    )
    asyncio.run(transport.complete(request))
    assert calls[0]["input"] == [{"role": "user", "content": "hi"}]
    assert calls[0]["max_output_tokens"] == 512
    assert "messages" not in calls[0]
    assert "max_tokens" not in calls[0]


def test_responses_request_renders_tools_flat() -> None:
    tool = transport_module.ChatTool("fn", "does a thing", {"type": "object"})
    transport, calls = _make_transport()
    asyncio.run(
        transport.complete(
            ChatRequest(
                "example/model",
                (transport_module.ChatMessage("user", "hi"),),
                (tool,),
                "fn",
            )
        )
    )
    assert calls[0]["tools"] == [
        {
            "type": "function",
            "name": "fn",
            "description": "does a thing",
            "parameters": {"type": "object"},
            "strict": False,
        }
    ]
    assert calls[0]["tool_choice"] == {"type": "function", "name": "fn"}


def test_responses_request_maps_tool_exchange_to_call_and_output_items() -> None:
    call = transport_module.ToolCall("call-1", "fn", {"value": "ready"})
    transport, calls = _make_transport()
    asyncio.run(
        transport.complete(
            ChatRequest(
                "example/model",
                (
                    transport_module.ChatMessage("user", "hi"),
                    transport_module.ChatMessage("assistant", tool_calls=(call,)),
                    transport_module.ChatMessage(
                        "tool", "ready", tool_call_id="call-1"
                    ),
                ),
            )
        )
    )
    assert calls[0]["input"] == [
        {"role": "user", "content": "hi"},
        {
            "type": "function_call",
            "call_id": "call-1",
            "name": "fn",
            "arguments": '{"value": "ready"}',
        },
        {"type": "function_call_output", "call_id": "call-1", "output": "ready"},
    ]


def test_responses_request_flattens_json_schema_response_format() -> None:
    transport, calls = _make_transport()
    asyncio.run(
        transport.complete(
            ChatRequest(
                "example/model",
                (transport_module.ChatMessage("user", "hi"),),
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "result",
                        "strict": True,
                        "schema": {"type": "object"},
                    },
                },
            )
        )
    )
    assert calls[0]["text"] == {
        "format": {
            "type": "json_schema",
            "name": "result",
            "strict": True,
            "schema": {"type": "object"},
        }
    }
    assert "response_format" not in calls[0]


def test_responses_request_forwards_extra_body_when_populated() -> None:
    transport, calls = _make_transport({"reasoning": {"effort": "high"}})
    asyncio.run(
        transport.complete(
            ChatRequest("example/model", (transport_module.ChatMessage("user", "hi"),))
        )
    )
    assert calls[0]["extra_body"] == {"reasoning": {"effort": "high"}}


def test_responses_request_omits_extra_body_when_empty() -> None:
    transport, calls = _make_transport({})
    asyncio.run(
        transport.complete(
            ChatRequest("example/model", (transport_module.ChatMessage("user", "hi"),))
        )
    )
    assert "extra_body" not in calls[0]


# ---------------------------------------------------------------------------
# Responses transport: response reading
# ---------------------------------------------------------------------------


def test_responses_reads_text_and_skips_reasoning_items() -> None:
    payload = SimpleNamespace(
        output=[
            SimpleNamespace(type="reasoning", summary=[], content=[]),
            SimpleNamespace(
                type="message",
                content=[
                    SimpleNamespace(type="output_text", text="the "),
                    SimpleNamespace(type="refusal", refusal="ignored"),
                    SimpleNamespace(type="output_text", text="answer"),
                ],
            ),
        ],
        model="m",
        usage=SimpleNamespace(
            input_tokens=7,
            output_tokens=3,
            total_tokens=10,
            input_tokens_details=SimpleNamespace(cached_tokens=4),
        ),
        id="resp-1",
        status="completed",
    )
    transport, _ = _make_transport(response=payload)
    result = asyncio.run(
        transport.complete(
            ChatRequest("example/model", (transport_module.ChatMessage("user", "hi"),))
        )
    )
    assert result.content == "the answer"
    assert result.tool_calls == ()
    assert result.usage == transport_module.ModelUsage(7, 3, 10, 4)
    assert result.response_id == "resp-1"
    assert result.finish_reason is None


def test_responses_reads_function_calls_from_output() -> None:
    transport, _ = _make_transport()
    result = asyncio.run(
        transport.complete(
            ChatRequest("example/model", (transport_module.ChatMessage("user", "hi"),))
        )
    )
    assert result.tool_calls == (transport_module.ToolCall("c1", "fn", {"x": 1}),)
    assert result.content is None


def test_responses_reports_truncated_output_as_length() -> None:
    payload = SimpleNamespace(
        output=[],
        model="m",
        usage=None,
        id="r1",
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
    )
    transport, _ = _make_transport(response=payload)
    result = asyncio.run(
        transport.complete(
            ChatRequest("example/model", (transport_module.ChatMessage("user", "hi"),))
        )
    )
    assert result.finish_reason == "length"


def test_responses_malformed_tool_call_becomes_a_transport_failure() -> None:
    payload = SimpleNamespace(
        output=[SimpleNamespace(type="function_call", call_id="c1", name="fn")],
        model="m",
        usage=None,
        id="r1",
        status="completed",
    )
    transport, _ = _make_transport(response=payload)
    with pytest.raises(transport_module.TransportFailure):
        asyncio.run(
            transport.complete(
                ChatRequest(
                    "example/model", (transport_module.ChatMessage("user", "hi"),)
                )
            )
        )


def test_responses_propagates_cancellation() -> None:
    transport, _ = _make_transport(response=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            transport.complete(
                ChatRequest(
                    "example/model", (transport_module.ChatMessage("user", "hi"),)
                )
            )
        )


# ---------------------------------------------------------------------------
# inference.supports_temperature
# ---------------------------------------------------------------------------
#
# Judging and world simulation ask for temperature 0 (judge.py, world/model.py
# both pass it literally). Reasoning models on some gateways reject the
# parameter outright, so a repository can declare that its model does not take
# it. The flag is model-scoped rather than wire-scoped because the rejection
# follows the model: the same gateway accepts temperature from a non-reasoning
# model on the very same endpoint.


def test_config_absent_supports_temperature_defaults_to_true(tmp_path: Path) -> None:
    """Regression guard: existing configs keep sending temperature."""
    root = write_repo(tmp_path / "repo")
    result = load_config(root)
    assert result.value is not None
    assert result.value.inference is not None
    assert result.value.inference.supports_temperature is True


def test_config_parses_supports_temperature_false(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", "supports_temperature = false\n")
    result = load_config(root)
    assert result.value is not None
    assert result.value.inference is not None
    assert result.value.inference.supports_temperature is False


def test_config_rejects_non_boolean_supports_temperature(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo", 'supports_temperature = "no"\n')
    assert load_config(root).value is None


def test_resolve_inference_propagates_supports_temperature() -> None:
    settings = InferenceSettings(
        "https://example.test/v1",
        "example/model",
        "KEY",
        supports_temperature=False,
    )
    resolved, _ = resolve_inference(settings, {"KEY": "secret"})
    assert resolved is not None
    assert resolved.supports_temperature is False


def _make_chat_transport(
    supports_temperature: bool = True,
) -> tuple[transport_module.OpenAIChatTransport, list[dict[str, Any]]]:
    """Return a Chat Completions transport whose fake client records kwargs."""
    recorded: list[dict[str, Any]] = []
    payload = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=None),
                finish_reason="stop",
            )
        ],
        model="m",
        usage=None,
        id="r1",
    )

    class FakeCompletions:
        async def create(self, **kwargs: object) -> object:
            recorded.append(dict(kwargs))
            return payload

    fake = object.__new__(transport_module.OpenAIChatTransport)
    p = fake_profile(supports_temperature=supports_temperature)
    object.__setattr__(
        fake,
        "_client",
        SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
    object.__setattr__(fake, "_redactor", SecretRedactor(p.api_key))
    object.__setattr__(fake, "_profile", p)
    return fake, recorded


def _temperature_request() -> ChatRequest:
    return ChatRequest(
        "example/model",
        (transport_module.ChatMessage("user", "hi"),),
        (),
        None,
        512,
        0.0,
    )


@pytest.mark.parametrize("wire", list(InferenceWire))
def test_temperature_is_sent_by_default_on_every_wire(wire: InferenceWire) -> None:
    transport: Any
    if wire is InferenceWire.RESPONSES:
        transport, calls = _make_transport()
    else:
        transport, calls = _make_chat_transport()
    asyncio.run(transport.complete(_temperature_request()))
    assert calls[0]["temperature"] == 0.0


@pytest.mark.parametrize("wire", list(InferenceWire))
def test_temperature_is_omitted_when_the_model_rejects_it(wire: InferenceWire) -> None:
    transport: Any
    if wire is InferenceWire.RESPONSES:
        transport, calls = _make_transport(supports_temperature=False)
    else:
        transport, calls = _make_chat_transport(supports_temperature=False)
    asyncio.run(transport.complete(_temperature_request()))
    assert "temperature" not in calls[0]


# ---------------------------------------------------------------------------
# Construction, error classification and payload edge cases
# ---------------------------------------------------------------------------


def _request() -> ChatRequest:
    return ChatRequest("example/model", (transport_module.ChatMessage("user", "hi"),))


@pytest.mark.parametrize("client_is_patched", [True, False])
def test_responses_transport_constructs_and_closes_its_client(
    monkeypatch: pytest.MonkeyPatch, client_is_patched: bool
) -> None:
    closed: list[bool] = []
    built: list[dict[str, object]] = []

    class Client:
        def __init__(self, **kwargs: object) -> None:
            built.append(kwargs)

        async def close(self) -> None:
            closed.append(True)

    if client_is_patched:
        monkeypatch.setattr(transport_module, "AsyncOpenAI", Client)
    else:
        # Leave the module-level hook empty so the real client class is imported.
        monkeypatch.setattr(transport_module, "AsyncOpenAI", None)
    created = transport_module.OpenAIResponsesTransport.from_profile(
        fake_profile(InferenceWire.RESPONSES)
    )
    asyncio.run(created.close())
    if client_is_patched:
        assert built[0]["max_retries"] == 0
        assert built[0]["api_key"] == "key"
        assert closed == [True]


def test_responses_transport_imports_openai_when_the_hook_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(transport_module, "openai", None)
    transport, calls = _make_transport()
    asyncio.run(transport.complete(_request()))
    assert len(calls) == 1


@pytest.mark.parametrize("wire", list(InferenceWire))
def test_unclassified_errors_propagate_unchanged_on_every_wire(
    wire: InferenceWire,
) -> None:
    error = RuntimeError("not a provider error")
    if wire is InferenceWire.RESPONSES:
        transport, _ = _make_transport(response=error)
    else:
        transport = object.__new__(transport_module.OpenAIChatTransport)

        async def create(**_: object) -> object:
            raise error

        async def close() -> None:
            return None

        object.__setattr__(transport, "_profile", fake_profile(wire))
        object.__setattr__(
            transport, "_redactor", SecretRedactor(fake_profile(wire).api_key)
        )
        object.__setattr__(
            transport,
            "_client",
            SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                close=close,
            ),
        )
    with pytest.raises(RuntimeError, match="not a provider error"):
        asyncio.run(transport.complete(_request()))


def test_responses_tool_call_arguments_must_be_a_json_object() -> None:
    payload = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="function_call", call_id="c1", name="fn", arguments="[1, 2]"
            )
        ],
        model="m",
        usage=None,
        id="r1",
        status="completed",
    )
    transport, _ = _make_transport(response=payload)
    with pytest.raises(transport_module.TransportFailure):
        asyncio.run(transport.complete(_request()))


def test_responses_response_format_without_nested_schema_is_kept_as_is() -> None:
    transport, calls = _make_transport()
    asyncio.run(
        transport.complete(
            ChatRequest(
                "example/model",
                (transport_module.ChatMessage("user", "hi"),),
                response_format={"type": "json_schema", "json_schema": "oops"},
            )
        )
    )
    assert calls[0]["text"] == {"format": {"type": "json_schema"}}


def test_responses_transport_uses_the_preloaded_openai_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openai as real_openai

    monkeypatch.setattr(transport_module, "openai", real_openai)
    transport, calls = _make_transport()
    asyncio.run(transport.complete(_request()))
    assert len(calls) == 1
