"""Deterministic contract tests for the compatible inference boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any, cast

import pytest

from skillroll import config as config_module
from skillroll.commands import doctor
from skillroll.config import load_config
from skillroll.diagnostics import JSONValue
from skillroll.inference import transport as transport_module
from skillroll.inference.preflight import run_preflight
from skillroll.inference.profile import (
    MAX_FAILURE_DETAIL_BYTES,
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
    SecretRedactor,
    SecretValue,
    bounded_failure_details,
    resolve_inference,
    resolve_inference_candidates,
)
from skillroll.inference.transport import (
    ChatRequest,
    ChatResponse,
    ModelUsage,
    ToolCall,
    TransportFailure,
)
from skillroll.models import InferenceLimits, InferenceSettings, ModelProfile, Skill
from skillroll.outcomes import Outcome
from skillroll.runtime import agents_sdk
from skillroll.runtime.execution import (
    AgentSkillExecutor,
    ExecutionRequest,
    SdkExecution,
    load_skill_text,
    wrapped_instructions,
)


class FakeTransport:
    """A scripted transport proving the preflight never needs HTTP."""

    def __init__(self, responses: list[ChatResponse | BaseException]) -> None:
        self.responses = responses
        self.requests: list[ChatRequest] = []
        self.closed = False

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    async def close(self) -> None:
        self.closed = True


def profile() -> ResolvedInference:
    return ResolvedInference(
        "https://example.test/v1",
        "example/model",
        SecretValue("private/key value"),
        InferenceLimits(),
    )


def valid_responses() -> list[ChatResponse | BaseException]:
    return [
        ChatResponse(
            None,
            (ToolCall("call-1", "skillroll_preflight", {"value": "ready"}),),
            "example/model",
            ModelUsage(1, 2, 3),
        ),
        ChatResponse('{"status":"ready"}', (), "example/model", None),
    ]


def test_default_output_limit_covers_standard_semantic_judgment() -> None:
    assert InferenceLimits().max_output_tokens == 8192
    assert ChatRequest("example/model", ()).max_output_tokens == 8192


def test_secret_and_profile_resolution_never_render_a_key() -> None:
    settings = InferenceSettings("https://example.test/v1", "example/model", "KEY")
    resolved, failure = resolve_inference(settings, {"KEY": "private/key value"})
    assert failure is None
    assert resolved is not None
    assert "private/key" not in repr(resolved.api_key)
    assert str(resolved.api_key) == "[redacted]"
    redactor = SecretRedactor(resolved.api_key)
    assert redactor.redact("private/key value private%2Fkey%20value") == (
        "[redacted] [redacted]"
    )


def test_failure_details_are_bounded_redacted_and_omit_unsafe_request_data() -> None:
    secret = SecretValue("private/key value")
    failure = InferenceFailure(
        InferenceFailureKind.EXECUTION_ERROR,
        "Execution failed.",
        (
            "Exact private/key value; encoded private%2Fkey%20value.",
            "Authorization: Bearer another-provider-token",
            "x" * (MAX_FAILURE_DETAIL_BYTES + 100),
            "This fourth detail stays out of the bounded output.",
        ),
    )

    details = bounded_failure_details(failure, SecretRedactor(secret))

    joined = "\n".join(details)
    assert "private/key value" not in joined
    assert "private%2Fkey%20value" not in joined
    assert "Authorization" not in joined
    assert "[redacted]" in joined
    assert "omitted provider headers" in joined
    assert len(details) == 3
    assert len(details[1].encode("utf-8")) == MAX_FAILURE_DETAIL_BYTES
    assert details[1].endswith(" [truncated]")


def test_failure_details_can_be_empty_without_a_safety_notice() -> None:
    failure = InferenceFailure(InferenceFailureKind.TIMEOUT, "Timed out.", ("",))

    assert bounded_failure_details(failure, SecretRedactor(SecretValue(""))) == ()


def test_profile_reports_missing_configuration_and_blank_key() -> None:
    _, missing_config = resolve_inference(None, {})
    _, missing_key = resolve_inference(
        InferenceSettings("https://example.test/v1", "model", "KEY"), {"KEY": " "}
    )
    assert missing_config is not None
    assert missing_config.kind is InferenceFailureKind.MISSING_CONFIGURATION
    assert missing_key is not None
    assert missing_key.kind is InferenceFailureKind.MISSING_API_KEY
    assert "KEY" in missing_key.summary


def test_preflight_makes_exactly_two_ordered_requests() -> None:
    transport = FakeTransport(valid_responses())
    result = asyncio.run(run_preflight(profile(), transport))
    assert result.passed
    assert len(transport.requests) == 2
    first, second = transport.requests
    assert first.force_tool is None
    assert first.temperature is None and second.temperature is None
    assert first.max_output_tokens == 1024
    assert second.max_output_tokens == 1024
    assert first.messages[0].role == "user"
    assert second.messages[-2].role == "tool"
    assert second.messages[-2].content == "ready"
    assert second.messages[-1].role == "user"
    assert second.response_format is not None
    assert second.response_format["type"] == "json_schema"
    assert result.evidence is not None
    assert result.evidence.usage == (ModelUsage(1, 2, 3),)


def test_preflight_rejects_invalid_calls_and_final_answers() -> None:
    invalid_call = FakeTransport(
        [ChatResponse(None, (ToolCall("x", "wrong", {"value": "ready"}),), None, None)]
    )
    first = valid_responses()[0]
    assert isinstance(first, ChatResponse)
    invalid_final = FakeTransport([first, ChatResponse(" ", (), None, None)])
    invalid_schema = FakeTransport(
        [first, ChatResponse('{"status":"no"}', (), None, None)]
    )
    assert not asyncio.run(run_preflight(profile(), invalid_call)).passed
    assert not asyncio.run(run_preflight(profile(), invalid_final)).passed
    assert not asyncio.run(run_preflight(profile(), invalid_schema)).passed
    assert len(invalid_call.requests) == 1


def test_preflight_preserves_redacted_transport_failure() -> None:
    transport = FakeTransport(
        [
            TransportFailure(
                InferenceFailure(
                    InferenceFailureKind.UNAUTHORIZED,
                    "The endpoint rejected the API key.",
                    ("[redacted]",),
                )
            )
        ]
    )
    result = asyncio.run(run_preflight(profile(), transport))
    assert result.failure is not None
    assert result.failure.kind is InferenceFailureKind.UNAUTHORIZED


def write_repository(root: Path) -> Path:
    (root / "skills").mkdir(parents=True)
    (root / "skillroll.toml").write_text(
        "schema_version = 1\nskills_path = 'skills'\n\n[inference]\n"
        "base_url = 'https://example.test/v1'\nmodel = 'example/model'\n"
        "api_key_env = 'KEY'\n",
        encoding="utf-8",
    )
    return root


def test_doctor_is_two_request_preflight_without_skill_or_writes(
    tmp_path: Path,
) -> None:
    repository = write_repository(tmp_path / "repository")
    transport = FakeTransport(valid_responses())
    before = sorted(path.name for path in repository.iterdir())

    def factory(_: ResolvedInference) -> FakeTransport:
        return transport

    result = doctor.run(
        repo=str(repository),
        environment={"KEY": "private/key value"},
        transport_factory=factory,
    )
    assert result.outcome is Outcome.PASS
    assert len(transport.requests) == 2
    assert transport.closed
    assert sorted(path.name for path in repository.iterdir()) == before
    assert "private/key" not in str(result)


def test_doctor_finds_the_nearest_repository_from_a_nested_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = write_repository(tmp_path / "repository")
    nested = repository / "skills" / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    transport = FakeTransport(valid_responses())

    result = doctor.run(
        environment={"KEY": "private/key value"},
        transport_factory=lambda _: transport,
    )

    assert result.outcome is Outcome.PASS
    assert transport.closed


def test_doctor_explains_missing_key_without_reading_a_secret(tmp_path: Path) -> None:
    result = doctor.run(
        repo=str(write_repository(tmp_path / "repository")), environment={}
    )
    assert result.outcome is Outcome.ERROR
    assert result.diagnostics[0].summary.endswith("empty or unavailable.")
    assert "KEY" in result.diagnostics[0].summary


def test_doctor_uses_ranked_fallback_only_during_preflight(tmp_path: Path) -> None:
    repository = write_repository(tmp_path / "profiles")
    (repository / "skillroll.toml").write_text(
        """schema_version = 1
skills_path = "skills"

[inference]
base_url = "https://example.test/v1"
api_key_env = "KEY"
default_profile = "baseline"

[inference.profiles.baseline]
purpose = "Low-cost compatibility signal."
models = ["unavailable", "available"]
""",
        encoding="utf-8",
    )
    failed = FakeTransport([ChatResponse("not a tool call", (), None, None)])
    selected = FakeTransport(valid_responses())
    transports = {"unavailable": failed, "available": selected}
    seen: list[str] = []

    def factory(resolved: ResolvedInference) -> FakeTransport:
        seen.append(resolved.model)
        return transports[resolved.model]

    result = doctor.run(
        repo=str(repository),
        environment={"KEY": "secret"},
        transport_factory=factory,
    )

    assert result.outcome is Outcome.PASS
    assert seen == ["unavailable", "available"]
    assert failed.closed and selected.closed


def test_doctor_reports_all_ranked_preflight_failures(tmp_path: Path) -> None:
    repository = write_repository(tmp_path / "all-failed")
    (repository / "skillroll.toml").write_text(
        """schema_version = 1
skills_path = "skills"

[inference]
base_url = "https://example.test/v1"
api_key_env = "KEY"
default_profile = "baseline"

[inference.profiles.baseline]
purpose = "Low-cost compatibility signal."
models = ["first", "second"]
""",
        encoding="utf-8",
    )
    transports = {
        "first": FakeTransport([ChatResponse("not a tool call", (), None, None)]),
        "second": FakeTransport(
            [ChatResponse("still not a tool call", (), None, None)]
        ),
    }

    result = doctor.run(
        repo=str(repository),
        environment={"KEY": "secret"},
        transport_factory=lambda resolved: transports[resolved.model],
    )

    assert result.outcome is Outcome.ERROR
    assert "No ranked model candidate" in result.diagnostics[0].summary
    assert "first" in str(result.diagnostics[0].details)
    assert all(transport.closed for transport in transports.values())


class FakeRuntime:
    def __init__(self, result: SdkExecution | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, str, InferenceLimits]] = []

    async def run(
        self,
        instructions: str,
        user_input: str,
        _: ResolvedInference,
        limits: InferenceLimits,
        __: object,
    ) -> SdkExecution:
        self.calls.append((instructions, user_input, limits))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def skill_at(root: Path, content: bytes = b"# A skill\n") -> Skill:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "SKILL.md"
    path.write_bytes(content)
    return Skill("example", PurePosixPath("example"), root, path, root / "evals")


async def world_action(tool_name: str, arguments: Mapping[str, JSONValue]) -> str:
    del tool_name, arguments
    return "simulated"


def test_execution_keeps_skill_text_verbatim_and_normalizes_result(
    tmp_path: Path,
) -> None:
    skill = skill_at(tmp_path / "skill", b"# Exact skill\n\nDo one thing.\n")
    runtime = FakeRuntime(SdkExecution(" final answer ", 2, (), ()))
    executor = AgentSkillExecutor(profile(), runtime)
    attempt = asyncio.run(
        executor.execute(
            ExecutionRequest(skill, "user input", InferenceLimits()), world_action
        )
    )
    assert attempt.failure is None
    assert attempt.result is not None
    assert attempt.result.final_output == "final answer"
    assert runtime.calls[0][1] == "user input"
    assert runtime.calls[0][0].endswith("# Exact skill\n\nDo one thing.\n")
    assert "exactly one tool: world_action" in runtime.calls[0][0]
    assert 'tool_name "Read"' in runtime.calls[0][0]
    assert '"path":"references/context.md"' in runtime.calls[0][0]
    assert "preserve the skill's intended action terminology" in runtime.calls[0][0]
    assert "preserve the skill's intended action terminology" in runtime.calls[0][0]
    assert wrapped_instructions("raw").endswith("raw")


def test_execution_can_run_an_omission_control_without_skill_text() -> None:
    runtime = FakeRuntime(SdkExecution(" control answer ", 1, (), ()))
    attempt = asyncio.run(
        AgentSkillExecutor(profile(), runtime).execute(
            ExecutionRequest(None, "user input", InferenceLimits()), world_action
        )
    )
    assert attempt.failure is None
    assert (
        attempt.result is not None and attempt.result.final_output == "control answer"
    )
    assert "intentionally omitted" in runtime.calls[0][0]


def test_execution_stops_unsafe_skill_and_large_input_before_runtime(
    tmp_path: Path,
) -> None:
    unsafe = skill_at(tmp_path / "unsafe", b"not utf-8: \xff")
    runtime = FakeRuntime(SdkExecution("unused", 1, (), ()))
    executor = AgentSkillExecutor(profile(), runtime)
    unsafe_attempt = asyncio.run(
        executor.execute(
            ExecutionRequest(unsafe, "input", InferenceLimits()), world_action
        )
    )
    too_large = skill_at(tmp_path / "valid")
    large_attempt = asyncio.run(
        executor.execute(
            ExecutionRequest(too_large, "x" * (64 * 1024 + 1), InferenceLimits()),
            world_action,
        )
    )
    assert unsafe_attempt.failure is not None
    assert large_attempt.failure is not None
    assert runtime.calls == []


def test_skill_loader_rejects_symlink_and_large_files(tmp_path: Path) -> None:
    external = tmp_path / "outside.md"
    external.write_text("outside", encoding="utf-8")
    linked = skill_at(tmp_path / "linked")
    linked.skill_file.unlink()
    linked.skill_file.symlink_to(external)
    large = skill_at(tmp_path / "large", b"x" * (128 * 1024 + 1))
    assert load_skill_text(linked)[0] is None
    assert load_skill_text(large)[0] is None


def test_execution_normalizes_and_redacts_runtime_errors(tmp_path: Path) -> None:
    runtime = FakeRuntime(RuntimeError("private/key value private%2Fkey%20value"))
    attempt = asyncio.run(
        AgentSkillExecutor(profile(), runtime).execute(
            ExecutionRequest(skill_at(tmp_path / "skill"), "input", InferenceLimits()),
            world_action,
        )
    )
    assert attempt.result is None
    assert attempt.failure is not None
    assert attempt.failure.kind is InferenceFailureKind.EXECUTION_ERROR
    assert attempt.failure.details == ("[redacted] [redacted]",)


def test_config_accepts_limits_and_rejects_bad_limit_shapes(tmp_path: Path) -> None:
    good = write_repository(tmp_path / "good")
    (good / "skillroll.toml").write_text(
        (good / "skillroll.toml").read_text(encoding="utf-8")
        + "\n[inference.limits]\nmax_turns = 2\ntimeout_seconds = 10\n"
        "max_output_tokens = 256\n",
        encoding="utf-8",
    )
    parsed = load_config(good)
    assert parsed.value is not None
    assert parsed.value.inference is not None
    assert parsed.value.inference.limits == InferenceLimits(2, 10, 256)
    bad = write_repository(tmp_path / "bad")
    (bad / "skillroll.toml").write_text(
        (bad / "skillroll.toml").read_text(encoding="utf-8")
        + "\n[inference.limits]\nunknown = 1\n",
        encoding="utf-8",
    )
    assert load_config(bad).value is None
    range_bad = write_repository(tmp_path / "range-bad")
    (range_bad / "skillroll.toml").write_text(
        (range_bad / "skillroll.toml").read_text(encoding="utf-8")
        + "\n[inference.limits]\nmax_turns = 0\n",
        encoding="utf-8",
    )
    assert load_config(range_bad).value is None


def test_config_uses_the_standard_output_limit_when_omitted(tmp_path: Path) -> None:
    parsed = load_config(write_repository(tmp_path / "default-limits"))

    assert parsed.value is not None
    assert parsed.value.inference is not None
    assert parsed.value.inference.limits.max_output_tokens == 8192


def test_config_accepts_ranked_profiles_and_explicit_pricing(tmp_path: Path) -> None:
    root = write_repository(tmp_path / "profiles")
    (root / "skillroll.toml").write_text(
        """schema_version = 1
skills_path = "skills"

[inference]
base_url = "https://example.test/v1"
api_key_env = "KEY"
default_profile = "authoring-baseline"

[inference.profiles.authoring-baseline]
purpose = "Low-cost release signal for ordinary skill behavior."
models = ["provider/mini", "provider/fallback-mini"]

[inference.profiles.investigation]
purpose = "Stronger diagnosis when the baseline result is ambiguous."
models = ["provider/strong"]

[pricing]
currency = "USD"

[pricing.models."provider/mini"]
input_per_million = 0.4
output_per_million = 1.6
cache_read_per_million = 0.1
""",
        encoding="utf-8",
    )
    parsed = load_config(root)
    assert parsed.value is not None
    assert parsed.value.inference is not None
    assert parsed.value.inference.model == "provider/mini"
    assert parsed.value.inference.default_profile == "authoring-baseline"
    assert parsed.value.inference.profiles["authoring-baseline"].models == (
        "provider/mini",
        "provider/fallback-mini",
    )
    assert parsed.value.pricing is not None
    assert parsed.value.pricing.models["provider/mini"].output_per_million == 1.6


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"bad.name": {"purpose": "p", "models": ["m"]}},
        {"valid": {"purpose": "p"}},
        {"valid": {"purpose": 7, "models": ["m"]}},
        {"valid": {"purpose": "p", "models": []}},
        {"valid": {"purpose": "p", "models": [""]}},
        {"valid": {"purpose": "p", "models": ["m", " m"]}},
    ],
)
def test_model_profiles_reject_malformed_shapes(value: object) -> None:
    assert config_module._model_profiles(value) is None


def test_pricing_rejects_an_unknown_shape() -> None:
    assert config_module._pricing([]) is None


def test_profile_selection_failures_are_explicit() -> None:
    profiles = {
        "baseline": ModelProfile("Low-cost signal.", ("provider/mini",)),
        "investigation": ModelProfile("Stronger diagnosis.", ("provider/strong",)),
    }
    settings = InferenceSettings(
        "https://example.test/v1", "unused", "KEY", profiles=profiles
    )
    _, missing_selection = resolve_inference_candidates(settings, {"KEY": "secret"})
    _, unknown_selection = resolve_inference_candidates(
        settings, {"KEY": "secret"}, "missing"
    )
    _, legacy_selection = resolve_inference_candidates(
        InferenceSettings("https://example.test/v1", "model", "KEY"),
        {"KEY": "secret"},
        "baseline",
    )
    assert missing_selection is not None
    assert unknown_selection is not None
    assert legacy_selection is not None
    single = InferenceSettings(
        "https://example.test/v1",
        "unused",
        "KEY",
        profiles={"only": ModelProfile("Only purpose.", ("provider/model",))},
    )
    candidates, failure = resolve_inference_candidates(single, {"KEY": "secret"})
    assert failure is None and candidates is not None
    assert candidates[0].profile_name == "only"


@pytest.mark.parametrize(
    "model_line",
    [
        'model = "first"\n',
        'model = "\\nfirst"\n',
    ],
)
def test_config_rejects_ambiguous_or_unsafe_model_selection(
    tmp_path: Path, model_line: str
) -> None:
    root = write_repository(tmp_path / "ambiguous")
    (root / "skillroll.toml").write_text(
        """schema_version = 1
skills_path = "skills"

[inference]
base_url = "https://example.test/v1"
api_key_env = "KEY"
"""
        + model_line
        + """

[inference.profiles.baseline]
purpose = "One clear purpose."
models = ["provider/model"]
""",
        encoding="utf-8",
    )
    assert load_config(root).value is None


@pytest.mark.parametrize(
    "pricing",
    [
        """[pricing]\ncurrency = \"USD\"\n[pricing.models]\n"""
        '"provider/mini" = { input_per_million = -1, output_per_million = 1 }\n',
        """[pricing]\ncurrency = \"US\"\n[pricing.models]\n"""
        '"provider/mini" = { input_per_million = 1, output_per_million = 1 }\n',
        """[pricing]\ncurrency = \"USD\"\n[pricing.models]\n"""
        '"provider/mini" = { input_per_million = 1, output_per_million = 1, '
        "extra = 2 }\n",
    ],
)
def test_config_rejects_unusable_pricing(tmp_path: Path, pricing: str) -> None:
    root = write_repository(tmp_path / "bad-pricing")
    (root / "skillroll.toml").write_text(
        (root / "skillroll.toml").read_text(encoding="utf-8") + "\n" + pricing,
        encoding="utf-8",
    )
    assert load_config(root).value is None


def test_ranked_profile_candidates_preserve_one_profile_for_all_stages() -> None:
    settings = InferenceSettings(
        "https://example.test/v1",
        "unused",
        "KEY",
        profiles={
            "baseline": ModelProfile(
                "Low-cost release signal.", ("provider/first", "provider/second")
            )
        },
        default_profile="baseline",
    )
    candidates, failure = resolve_inference_candidates(settings, {"KEY": "secret"})
    assert failure is None
    assert candidates is not None
    assert [candidate.model for candidate in candidates] == [
        "provider/first",
        "provider/second",
    ]
    assert {candidate.profile_name for candidate in candidates} == {"baseline"}
    assert {candidate.profile_purpose for candidate in candidates} == {
        "Low-cost release signal."
    }


def test_transport_helpers_and_failures_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = ToolCall("call", "function", {"value": "ready"})
    messages = transport_module._request_messages(
        [
            transport_module.ChatMessage("assistant", tool_calls=(call,)),
            transport_module.ChatMessage("tool", "ready", tool_call_id="call"),
        ]
    )
    assert messages[0]["tool_calls"]
    assert messages[1]["tool_call_id"] == "call"
    assert (
        transport_module._request_tools(
            [transport_module.ChatTool("f", "d", {"type": "object"})]
        )[0]["type"]
        == "function"
    )
    usage = transport_module._usage(
        SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=1,
                completion_tokens=2,
                total_tokens=3,
                prompt_tokens_details=SimpleNamespace(cached_tokens=4),
            )
        )
    )
    assert usage == ModelUsage(1, 2, 3, 4)
    assert transport_module._usage(
        SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=1,
                completion_tokens=2,
                total_tokens=3,
                cached_tokens=4,
            )
        )
    ) == ModelUsage(1, 2, 3, 4)
    response_calls = transport_module._response_tool_calls(
        SimpleNamespace(
            tool_calls=[
                SimpleNamespace(
                    id="id",
                    function=SimpleNamespace(name="f", arguments='{"a":"b"}'),
                )
            ]
        )
    )
    assert response_calls[0].arguments == {"a": "b"}
    with pytest.raises(ValueError):
        transport_module._response_tool_calls(SimpleNamespace(tool_calls=[object()]))

    class FakeAuth(Exception):
        pass

    class FakeRate(Exception):
        pass

    class FakeTimeout(Exception):
        pass

    class FakeStatus(Exception):
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    class FakeApi(Exception):
        pass

    monkeypatch.setattr(
        transport_module,
        "openai",
        SimpleNamespace(
            AuthenticationError=FakeAuth,
            RateLimitError=FakeRate,
            APITimeoutError=FakeTimeout,
            APIStatusError=FakeStatus,
            APIError=FakeApi,
        ),
    )

    seen_requests: list[dict[str, object]] = []

    class FakeCompletions:
        def __init__(self, response: object) -> None:
            self.response = response

        async def create(self, **kwargs: object) -> object:
            seen_requests.append(kwargs)
            if isinstance(self.response, BaseException):
                raise self.response
            return self.response

    def adapter(response: object) -> transport_module.OpenAIChatTransport:
        fake = object.__new__(transport_module.OpenAIChatTransport)
        object.__setattr__(fake, "_profile", profile())
        object.__setattr__(fake, "_redactor", SecretRedactor(profile().api_key))
        object.__setattr__(
            fake,
            "_client",
            SimpleNamespace(
                chat=SimpleNamespace(completions=FakeCompletions(response)),
                close=empty_close,
            ),
        )
        return fake

    async def empty_close() -> None:
        return None

    good_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=[]),
                finish_reason="length",
            )
        ],
        model="model",
        usage=None,
    )
    request = ChatRequest(
        "model",
        (transport_module.ChatMessage("user", "hi"),),
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    completed = asyncio.run(adapter(good_response).complete(request))
    assert completed.content == "ok" and completed.finish_reason == "length"
    assert seen_requests[0]["temperature"] == 0.0
    assert seen_requests[0]["response_format"] == {"type": "json_object"}
    default_request = ChatRequest(
        "model", (transport_module.ChatMessage("user", "hi"),)
    )
    assert asyncio.run(adapter(good_response).complete(default_request)).content == "ok"
    assert "temperature" not in seen_requests[1]
    assert "response_format" not in seen_requests[1]
    for error, kind in (
        (FakeAuth("private/key value"), InferenceFailureKind.UNAUTHORIZED),
        (FakeRate("rate"), InferenceFailureKind.RATE_LIMITED),
        (FakeTimeout("slow"), InferenceFailureKind.TIMEOUT),
        (FakeStatus(400), InferenceFailureKind.REQUEST_REJECTED),
        (FakeStatus(500), InferenceFailureKind.SERVICE_FAILURE),
        (FakeApi("down"), InferenceFailureKind.SERVICE_FAILURE),
        (ValueError("shape"), InferenceFailureKind.MALFORMED_RESPONSE),
    ):
        with pytest.raises(TransportFailure) as raised:
            asyncio.run(adapter(error).complete(request))
        assert raised.value.failure.kind is kind


def test_transport_constructor_and_agents_sdk_adapter_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[dict[str, object]] = []

    class Client:
        def __init__(self, **kwargs: object) -> None:
            constructed.append(kwargs)
            self.chat = SimpleNamespace(completions=SimpleNamespace())
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(transport_module, "AsyncOpenAI", Client)
    created = transport_module.OpenAIChatTransport(profile())
    assert constructed[0]["max_retries"] == 0
    assert constructed[0]["api_key"] == "private/key value"
    asyncio.run(created.close())
    assert isinstance(
        transport_module.OpenAIChatTransport.from_profile(profile()),
        transport_module.OpenAIChatTransport,
    )

    seen: dict[str, object] = {}

    def fake_trace(disabled: bool) -> None:
        seen["tracing"] = disabled

    def fake_tool(**kwargs: object) -> Any:
        seen["function_tool"] = kwargs
        return lambda function: function

    class Agent:
        def __init__(self, **kwargs: object) -> None:
            self.tools = kwargs["tools"]
            seen["agent"] = kwargs

    class Runner:
        @staticmethod
        async def run(agent: Any, _: str, **kwargs: object) -> object:
            seen["runner"] = kwargs
            value = await agent.tools[0](
                "read_file", {"path": "x", "options": {"follow": True}}
            )
            assert value == "simulated"
            return SimpleNamespace(
                final_output="finished",
                raw_responses=[
                    SimpleNamespace(
                        usage=SimpleNamespace(
                            input_tokens=11,
                            output_tokens=7,
                            total_tokens=18,
                        )
                    )
                ],
            )

    monkeypatch.setattr(agents_sdk, "AsyncOpenAI", Client)
    monkeypatch.setattr(agents_sdk, "Agent", Agent)
    monkeypatch.setattr(agents_sdk, "Runner", Runner)
    monkeypatch.setattr(agents_sdk, "function_tool", fake_tool)
    monkeypatch.setattr(agents_sdk, "set_tracing_disabled", fake_trace)
    monkeypatch.setattr(
        agents_sdk, "OpenAIChatCompletionsModel", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(agents_sdk, "ModelSettings", lambda **kwargs: kwargs)
    result = asyncio.run(
        agents_sdk.AgentsSdkRuntime().run(
            "instructions",
            "input",
            profile(),
            InferenceLimits(2, 10, 256),
            world_action,
        )
    )
    assert result.final_output == "finished"
    assert result.turns == 1 and result.turns_source == "provider"
    assert result.usage[0].total_tokens == 18
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {
        "path": "x",
        "options": {"follow": True},
    }
    assert agents_sdk._response_usage(SimpleNamespace(usage=None)) is None
    assert agents_sdk._response_usage(
        SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=4,
                total_tokens=14,
                input_token_details=SimpleNamespace(cached_tokens=3),
            )
        )
    ) == ModelUsage(10, 4, 14, 3)
    assert seen["function_tool"] == {
        "name_override": "world_action",
        "description_override": (
            "Request one intended action and receive its observed result. "
            'For a bundled file read, use tool_name="Read" with arguments '
            '{"path":"references/file.md"}. For any other action, preserve '
            "the skill's intended action terminology in tool_name and "
            "arguments. The action name records intent; it does not need a "
            "SkillRoll-specific spelling. Do not invent another tool."
        ),
        "strict_mode": False,
    }
    assert seen["tracing"] is True
    assert seen["runner"] == {"max_turns": 2}
    with pytest.raises(ValueError):
        agents_sdk._json_object({"value": "x" * (16 * 1024)})

    class InvalidRunner:
        @staticmethod
        async def run(agent: Any, _: str, **__: object) -> object:
            await agent.tools[0]("", {})
            return SimpleNamespace(final_output="never")

    monkeypatch.setattr(agents_sdk, "Runner", InvalidRunner)
    with pytest.raises(ValueError):
        asyncio.run(
            agents_sdk.AgentsSdkRuntime().run(
                "instructions",
                "input",
                profile(),
                InferenceLimits(2, 10, 256),
                world_action,
            )
        )

    class BlankRunner:
        @staticmethod
        async def run(_: Any, __: str, **___: object) -> object:
            return SimpleNamespace(final_output=" ")

    monkeypatch.setattr(agents_sdk, "Runner", BlankRunner)
    with pytest.raises(ValueError):
        asyncio.run(
            agents_sdk.AgentsSdkRuntime().run(
                "instructions",
                "input",
                profile(),
                InferenceLimits(2, 10, 256),
                world_action,
            )
        )


def test_agents_sdk_world_tool_schema_allows_an_arbitrary_json_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    class Client:
        def __init__(self, **_: object) -> None:
            pass

        async def close(self) -> None:
            pass

    class Agent:
        def __init__(self, **kwargs: object) -> None:
            seen["tool"] = kwargs["tools"]

    class Runner:
        @staticmethod
        async def run(_: object, __: str, **___: object) -> object:
            return SimpleNamespace(final_output="finished")

    monkeypatch.setattr(agents_sdk, "AsyncOpenAI", Client)
    monkeypatch.setattr(agents_sdk, "Agent", Agent)
    monkeypatch.setattr(agents_sdk, "Runner", Runner)
    monkeypatch.setattr(agents_sdk, "set_tracing_disabled", lambda _: None)
    monkeypatch.setattr(
        agents_sdk, "OpenAIChatCompletionsModel", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(agents_sdk, "ModelSettings", lambda **kwargs: kwargs)

    asyncio.run(
        agents_sdk.AgentsSdkRuntime().run(
            "instructions", "input", profile(), InferenceLimits(), world_action
        )
    )

    (tool,) = cast(tuple[Any], seen["tool"])
    schema = tool.params_json_schema
    assert tool.strict_json_schema is False
    assert schema["properties"]["arguments"]["additionalProperties"] is True


def test_remaining_failure_and_cancellation_boundaries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from skillroll.commands import doctor as doctor_module
    from skillroll.inference.preflight import PreflightResult

    failed = doctor_module._preflight_result(
        PreflightResult(
            None,
            InferenceFailure(InferenceFailureKind.REQUEST_REJECTED, "no"),
        )
    )
    assert failed.outcome is Outcome.ERROR
    default = doctor_module._default_transport(profile())
    asyncio.run(default.close())

    def interrupt(coroutine: object) -> object:
        assert hasattr(coroutine, "close")
        coroutine.close()  # type: ignore[union-attr]
        raise KeyboardInterrupt

    monkeypatch.setattr(doctor_module.asyncio, "run", interrupt)
    interrupted = doctor.run(
        repo=str(write_repository(tmp_path / "repo")),
        environment={"KEY": "x"},
        transport_factory=lambda _: FakeTransport(valid_responses()),
    )
    assert interrupted.diagnostics[0].summary.startswith(
        "The compatibility check was interrupted"
    )
    monkeypatch.undo()
    assert SecretRedactor(SecretValue("")).redact("unchanged") == "unchanged"
    cancelled = FakeTransport([asyncio.CancelledError()])
    assert asyncio.run(run_preflight(profile(), cancelled)).failure is not None
    duplicate = FakeTransport(
        [
            ChatResponse(
                None,
                (
                    ToolCall("a", "skillroll_preflight", {"value": "ready"}),
                    ToolCall("b", "skillroll_preflight", {"value": "ready"}),
                ),
                None,
                None,
            )
        ]
    )
    assert not asyncio.run(run_preflight(profile(), duplicate)).passed


def test_remaining_transport_and_execution_error_paths(tmp_path: Path) -> None:
    async def close() -> None:
        return None

    def adapter(response: object) -> transport_module.OpenAIChatTransport:
        fake = object.__new__(transport_module.OpenAIChatTransport)

        class Completions:
            async def create(self, **_: object) -> object:
                if isinstance(response, BaseException):
                    raise response
                return response

        object.__setattr__(
            fake,
            "_client",
            SimpleNamespace(
                chat=SimpleNamespace(completions=Completions()), close=close
            ),
        )
        object.__setattr__(fake, "_redactor", SecretRedactor(profile().api_key))
        return fake

    request = ChatRequest("model", (transport_module.ChatMessage("user", "hi"),))
    bad_choices = SimpleNamespace(choices=[], model="m", usage=None)
    with pytest.raises(TransportFailure):
        asyncio.run(adapter(bad_choices).complete(request))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adapter(asyncio.CancelledError()).complete(request))
    with pytest.raises(ValueError):
        transport_module._response_tool_calls(
            SimpleNamespace(
                tool_calls=[
                    SimpleNamespace(
                        id="x", function=SimpleNamespace(name="x", arguments="[]")
                    )
                ]
            )
        )

    class RaisingRuntime:
        def __init__(self, error: BaseException) -> None:
            self.error = error

        async def run(self, *_: object) -> SdkExecution:
            raise self.error

    case = ExecutionRequest(skill_at(tmp_path / "skill"), "input", InferenceLimits())
    timeout = asyncio.run(
        AgentSkillExecutor(profile(), RaisingRuntime(TimeoutError())).execute(
            case, world_action
        )
    )
    cancelled = asyncio.run(
        AgentSkillExecutor(profile(), RaisingRuntime(asyncio.CancelledError())).execute(
            case, world_action
        )
    )
    assert (
        timeout.failure is not None
        and timeout.failure.kind is InferenceFailureKind.TIMEOUT
    )
    assert (
        cancelled.failure is not None
        and cancelled.failure.kind is InferenceFailureKind.CANCELLED
    )
