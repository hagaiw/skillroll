"""Lenient decoding of the single world_action tool input."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agents.tool_context import ToolContext

from skillroll.artifacts.records import transcript_bytes
from skillroll.inference.profile import ResolvedInference, SecretValue
from skillroll.inference.transport import ChatRequest, ChatResponse, ChatTransport
from skillroll.models import InferenceLimits
from skillroll.runtime import agents_sdk
from skillroll.world.bundle import BundleIndex
from skillroll.world.session import WorldSession

# A real rejected call shape: the model's native tool-call markup leaked into
# the arguments, so the nested object arrived as a string with the next
# parameter's markup swallowed into it.
MARKUP_LEAK = (
    r'{"arguments":"{\"command\": \"git clone '
    r"https://github.com/example-org/example-app.git "
    r"\\\"$WORKSPACE_DIR/example-app\\\"\"}\n"
    r'<parameter name=\"tool_name\">Bash"}'
)
CLONE = (
    "git clone https://github.com/example-org/example-app.git "
    '"$WORKSPACE_DIR/example-app"'
)
REJECTION = (
    'world_action input must be a JSON object with "tool_name" (string) and '
    '"arguments" (object). Received: '
)


class FakeTransport(ChatTransport):
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse("simulated", (), "world", None)

    async def close(self) -> None:
        pass


def profile() -> ResolvedInference:
    return ResolvedInference(
        "https://example.test/v1",
        "cheap-model",
        SecretValue("test-secret"),
        InferenceLimits(4, 30, 128),
    )


def session(tmp_path: Path) -> tuple[WorldSession, FakeTransport]:
    transport = FakeTransport()
    world = WorldSession(
        profile(),
        InferenceLimits(4, 30, 128),
        "world",
        BundleIndex(tmp_path, ()),
        (),
        transport,
    )
    return world, transport


def invoke(
    monkeypatch: pytest.MonkeyPatch, handler: Any, inputs: list[str]
) -> tuple[list[str], tuple[Any, ...]]:
    """Run the adapter with a fake Runner that sends raw tool inputs."""
    outputs: list[str] = []

    class Client:
        def __init__(self, **_: object) -> None:
            pass

        async def close(self) -> None:
            pass

    class Agent:
        def __init__(self, **kwargs: Any) -> None:
            self.tools = kwargs["tools"]

    class Runner:
        @staticmethod
        async def run(agent: Any, _: str, **__: object) -> object:
            (tool,) = agent.tools
            for raw in inputs:
                context = ToolContext(
                    None,
                    tool_name="world_action",
                    tool_call_id="call-1",
                    tool_arguments=raw,
                )
                outputs.append(str(await tool.on_invoke_tool(context, raw)))
            return SimpleNamespace(final_output="finished")

    monkeypatch.setattr(agents_sdk, "AsyncOpenAI", Client)
    monkeypatch.setattr(agents_sdk, "Agent", Agent)
    monkeypatch.setattr(agents_sdk, "Runner", Runner)
    monkeypatch.setattr(agents_sdk, "set_tracing_disabled", lambda _: None)
    monkeypatch.setattr(
        agents_sdk, "OpenAIChatCompletionsModel", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(agents_sdk, "ModelSettings", lambda **kwargs: kwargs)
    result = asyncio.run(
        agents_sdk.AgentsSdkRuntime().run(
            "instructions", "input", profile(), InferenceLimits(), handler
        )
    )
    return outputs, result.tool_calls


def test_well_formed_call_passes_through_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world, _ = session(tmp_path)
    raw = json.dumps(
        {"tool_name": "Bash", "arguments": {"command": "ls", "n": [1, {"a": None}]}}
    )
    outputs, calls = invoke(monkeypatch, world, [raw])
    assert outputs == ["simulated"]
    assert [(call.name, call.arguments) for call in calls] == [
        ("Bash", {"command": "ls", "n": [1, {"a": None}]})
    ]
    assert [event.source for event in world.events] == ["world_model"]


def test_extra_top_level_keys_are_ignored() -> None:
    decoded = agents_sdk.decode_world_action(
        '{"tool_name": "Read", "arguments": {"path": "a"}, "reason": "x"}'
    )
    assert decoded == ("Read", {"path": "a"}, None)


def test_string_encoded_arguments_are_decoded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world, _ = session(tmp_path)
    raw = json.dumps({"tool_name": "Bash", "arguments": '{"command": "ls"}'})
    outputs, calls = invoke(monkeypatch, world, [raw])
    assert outputs == ["simulated"]
    assert [(call.name, call.arguments) for call in calls] == [
        ("Bash", {"command": "ls"})
    ]


def test_captured_markup_leak_recovers_the_intended_call() -> None:
    assert agents_sdk.decode_world_action(MARKUP_LEAK) == (
        "Bash",
        {"command": CLONE},
        "recovered from leaked <parameter> markup",
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            '<parameter name="tool_name">Bash</parameter>'
            '<parameter name="arguments">{"command": "ls"}</parameter>',
            ("Bash", {"command": "ls"}),
        ),
        (
            json.dumps({"tool_name": "Bash", "arguments": '"{"command": "ls"}"'}),
            ("Bash", {"command": "ls"}),
        ),
        (
            json.dumps({"tool_name": "Bash", "arguments": json.dumps('{"a": 1}')}),
            ("Bash", {"a": 1}),
        ),
    ],
)
def test_other_recoverable_shapes(raw: str, expected: tuple[str, object]) -> None:
    decoded = agents_sdk.decode_world_action(raw)
    assert decoded is not None
    assert decoded[:2] == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        '{"tool_name": "Bash"}',
        '{"command": "ls"}',
        '{"tool_name": "Bash", "arguments": "ls -la"}',
        '{"tool_name": "Bash", "arguments": "\\"plain\\""}',
        '{"tool_name": "  ", "arguments": {}}',
        '{"tool_name": "a", "arguments": {}}{"tool_name": "b", "arguments": {}}',
        "[1, 2]",
    ],
)
def test_unrecoverable_input_returns_specific_error_without_calling_handler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw: str
) -> None:
    world, transport = session(tmp_path)
    outputs, calls = invoke(monkeypatch, world, [raw])
    assert outputs == [REJECTION + raw[:200]]
    assert calls == ()
    assert transport.requests == []


def test_rejected_call_is_recorded_in_the_transcript(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world, _ = session(tmp_path)
    raw = '{"command": "ls"}' + "x" * 5000
    invoke(monkeypatch, world, [raw])
    (event,) = world.events
    assert event.source == "rejected"
    assert event.tool_name == "world_action"
    assert event.arguments == {"raw": raw[:2048]}
    assert event.result.startswith(REJECTION)
    line = json.loads(transcript_bytes(world.events))
    assert line["source"] == "rejected"
    assert line["arguments"]["raw"] == raw[:2048]


def test_recovered_call_is_recorded_and_still_runs_the_handler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world, transport = session(tmp_path)
    follow_up = json.dumps({"tool_name": "Bash", "arguments": {"command": "pwd"}})
    outputs, calls = invoke(monkeypatch, world, [MARKUP_LEAK, follow_up])
    assert outputs == ["simulated", "simulated"]
    assert [(call.name, call.arguments) for call in calls] == [
        ("Bash", {"command": CLONE}),
        ("Bash", {"command": "pwd"}),
    ]
    assert [(event.source, event.tool_name) for event in world.events] == [
        ("recovered", "world_action"),
        ("world_model", "Bash"),
        ("world_model", "Bash"),
    ]
    assert world.events[0].arguments == {"raw": MARKUP_LEAK}
    assert world.events[0].result == "recovered from leaked <parameter> markup"
    # The diagnostic event is kept out of the World simulator's history.
    assert "world_action" not in str(transport.requests[1])
    assert "recovered" not in str(transport.requests[1])


def test_handler_without_recorder_and_handler_errors_reach_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing(tool_name: str, arguments: object) -> str:
        raise RuntimeError("world unavailable")

    outputs, calls = invoke(
        monkeypatch,
        failing,
        ["", json.dumps({"tool_name": "Bash", "arguments": '{"command": "ls"}'})],
    )
    assert outputs[0] == REJECTION
    assert outputs[1] == (
        "An error occurred while running the tool. Please try again. "
        "Error: world unavailable"
    )
    assert len(calls) == 1
