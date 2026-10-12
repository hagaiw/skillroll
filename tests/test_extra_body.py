"""Tests for [inference.extra_body] config support.

Covers the full wiring from TOML parse → InferenceSettings → ResolvedInference
→ OpenAIChatTransport.complete(), plus all validation rejection branches.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from skillroll.config import _EXTRA_BODY_RESERVED_KEYS, _extra_body, load_config
from skillroll.inference import transport as transport_module
from skillroll.inference.profile import (
    ResolvedInference,
    SecretRedactor,
    SecretValue,
    resolve_inference,
)
from skillroll.inference.transport import ChatRequest
from skillroll.models import InferenceLimits, InferenceSettings
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


def fake_profile(extra_body: dict[str, object] | None = None) -> ResolvedInference:
    return ResolvedInference(
        base_url="https://example.test/v1",
        model="example/model",
        api_key=SecretValue("key"),
        limits=InferenceLimits(),
        extra_body=extra_body or {},
    )


# ---------------------------------------------------------------------------
# _extra_body validator unit tests
# ---------------------------------------------------------------------------


def test_extra_body_validator_accepts_none_as_empty_dict() -> None:
    assert _extra_body(None) == {}


def test_extra_body_validator_accepts_empty_dict() -> None:
    assert _extra_body({}) == {}


def test_extra_body_validator_accepts_simple_key_value_pairs() -> None:
    result = _extra_body({"reasoning_effort": "none", "x_custom": True})
    assert result == {"reasoning_effort": "none", "x_custom": True}


def test_extra_body_validator_accepts_nested_dict_within_depth_limit() -> None:
    nested = {"a": {"b": {"c": {"d": "leaf"}}}}
    assert _extra_body(nested) is not None


def test_extra_body_validator_rejects_over_nested_value() -> None:
    too_deep = {"a": {"b": {"c": {"d": {"e": "too deep"}}}}}
    assert _extra_body(too_deep) is None


def test_extra_body_validator_rejects_non_dict_top_level() -> None:
    assert _extra_body("string") is None
    assert _extra_body(42) is None
    assert _extra_body([1, 2]) is None


def test_extra_body_validator_rejects_non_finite_float() -> None:
    assert _extra_body({"x": float("inf")}) is None
    assert _extra_body({"x": float("nan")}) is None


def test_extra_body_validator_rejects_empty_string_key() -> None:
    assert _extra_body({"": "value"}) is None


def test_extra_body_validator_rejects_non_string_key() -> None:
    # TOML always produces str keys, but the validator guards against
    # programmatic misuse.
    assert _extra_body({1: "value"}) is None  # type: ignore[arg-type]


def test_extra_body_validator_rejects_oversized_payload() -> None:
    # Build a payload that serializes to more than 8 KB.  Use distinct keys so
    # the dict comprehension doesn't collapse to a single entry.
    import json

    big = {f"key_{i:04d}": "v" * 100 for i in range(100)}
    assert len(json.dumps(big).encode("utf-8")) > 8192, (
        "precondition: payload must exceed limit"
    )
    assert _extra_body(big) is None


@pytest.mark.parametrize("reserved", sorted(_EXTRA_BODY_RESERVED_KEYS))
def test_extra_body_validator_rejects_every_reserved_key(reserved: str) -> None:
    assert _extra_body({reserved: "any"}) is None


def test_extra_body_validator_accepts_list_values() -> None:
    assert _extra_body({"flags": [1, "two", None, True]}) is not None


def test_extra_body_validator_rejects_unsupported_value_type() -> None:
    assert _extra_body({"fn": object()}) is None  # type: ignore[dict-item]


# ---------------------------------------------------------------------------
# Config parsing: valid [inference.extra_body] round-trips
# ---------------------------------------------------------------------------


def test_config_parses_extra_body_and_stores_it_on_settings(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path / "repo",
        '\n[inference.extra_body]\nreasoning_effort = "none"\n',
    )
    result = load_config(root)
    assert result.is_valid
    assert result.value is not None
    assert result.value.inference is not None
    assert dict(result.value.inference.extra_body) == {"reasoning_effort": "none"}


def test_config_absent_extra_body_yields_empty_dict(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo")
    result = load_config(root)
    assert result.is_valid
    assert result.value is not None
    assert result.value.inference is not None
    assert result.value.inference.extra_body == {}


def test_config_rejects_reserved_key_in_extra_body(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path / "repo",
        '\n[inference.extra_body]\nmodel = "override"\n',
    )
    assert load_config(root).value is None


def test_config_rejects_non_dict_extra_body(tmp_path: Path) -> None:
    root = write_repo(tmp_path / "repo")
    (root / "skillroll.toml").write_text(
        "schema_version = 1\n"
        'skills_path = "skills"\n\n'
        "[inference]\n"
        'base_url = "https://example.test/v1"\n'
        'model = "example/model"\n'
        'api_key_env = "KEY"\n'
        "extra_body = 42\n",
        encoding="utf-8",
    )
    assert load_config(root).value is None


# ---------------------------------------------------------------------------
# Profile resolution: extra_body flows through to ResolvedInference
# ---------------------------------------------------------------------------


def test_resolve_inference_propagates_extra_body() -> None:
    settings = InferenceSettings(
        "https://example.test/v1",
        "example/model",
        "KEY",
        extra_body={"reasoning_effort": "none"},
    )
    resolved, failure = resolve_inference(settings, {"KEY": "secret"})
    assert failure is None
    assert resolved is not None
    assert dict(resolved.extra_body) == {"reasoning_effort": "none"}


def test_resolve_inference_empty_extra_body_by_default() -> None:
    settings = InferenceSettings("https://example.test/v1", "example/model", "KEY")
    resolved, failure = resolve_inference(settings, {"KEY": "secret"})
    assert failure is None
    assert resolved is not None
    assert resolved.extra_body == {}


# ---------------------------------------------------------------------------
# Transport: extra_body forwarded to SDK when populated; omitted when empty
# ---------------------------------------------------------------------------


def _make_transport(
    extra_body: dict[str, object] | None = None,
) -> tuple[transport_module.OpenAIChatTransport, list[dict[str, Any]]]:
    """Return a transport backed by a fake client that records create() kwargs."""
    recorded: list[dict[str, Any]] = []

    class FakeCompletions:
        async def create(self, **kwargs: object) -> object:
            recorded.append(dict(kwargs))
            # Return a minimal valid response.
            tool_call = SimpleNamespace(
                id="c1",
                function=SimpleNamespace(name="fn", arguments='{"x":1}'),
            )
            message = SimpleNamespace(content=None, tool_calls=[tool_call])
            choice = SimpleNamespace(message=message, finish_reason="tool_calls")
            return SimpleNamespace(choices=[choice], model="m", usage=None, id="r1")

    async def close() -> None:
        return None

    fake = object.__new__(transport_module.OpenAIChatTransport)
    p = fake_profile(extra_body)
    object.__setattr__(
        fake,
        "_client",
        SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions()), close=close
        ),
    )
    object.__setattr__(fake, "_redactor", SecretRedactor(p.api_key))
    object.__setattr__(fake, "_profile", p)
    return fake, recorded


def test_transport_forwards_extra_body_to_sdk_when_populated() -> None:
    transport, calls = _make_transport({"reasoning_effort": "none"})
    msg = transport_module.ChatMessage("user", "hi")
    request = ChatRequest("example/model", (msg,))
    asyncio.run(transport.complete(request))
    assert len(calls) == 1
    assert calls[0].get("extra_body") == {"reasoning_effort": "none"}


def test_transport_omits_extra_body_from_sdk_when_empty() -> None:
    """Regression guard: absent extra_body must not alter existing request shape."""
    transport, calls = _make_transport({})
    msg = transport_module.ChatMessage("user", "hi")
    request = ChatRequest("example/model", (msg,))
    asyncio.run(transport.complete(request))
    assert len(calls) == 1
    assert "extra_body" not in calls[0]


def test_transport_omits_extra_body_when_profile_has_no_extra_body() -> None:
    """ResolvedInference constructed without extra_body defaults to empty dict."""
    transport, calls = _make_transport(None)
    msg = transport_module.ChatMessage("user", "hi")
    request = ChatRequest("example/model", (msg,))
    asyncio.run(transport.complete(request))
    assert len(calls) == 1
    assert "extra_body" not in calls[0]


# ---------------------------------------------------------------------------
# AgentsSdkRuntime: extra_body forwarded to ModelSettings
# ---------------------------------------------------------------------------


def _run_sdk(
    monkeypatch: pytest.MonkeyPatch,
    extra_body: dict[str, object],
) -> dict[str, object]:
    """Run AgentsSdkRuntime with a fake Agent/Runner; return ModelSettings kwargs."""
    seen: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        async def close(self) -> None:
            pass

    class FakeAgent:
        def __init__(self, **kwargs: object) -> None:
            seen["model_settings"] = kwargs.get("model_settings")

        tools: list[Any] = []

    class FakeRunner:
        @staticmethod
        async def run(agent: Any, _: str, **__: object) -> object:
            return SimpleNamespace(
                final_output="result",
                raw_responses=[
                    SimpleNamespace(
                        usage=SimpleNamespace(
                            input_tokens=1, output_tokens=1, total_tokens=2
                        )
                    )
                ],
            )

    monkeypatch.setattr(agents_sdk, "AsyncOpenAI", FakeClient)
    monkeypatch.setattr(agents_sdk, "Agent", FakeAgent)
    monkeypatch.setattr(agents_sdk, "Runner", FakeRunner)
    monkeypatch.setattr(agents_sdk, "set_tracing_disabled", lambda *_: None)
    monkeypatch.setattr(
        agents_sdk, "OpenAIChatCompletionsModel", lambda *a, **k: object()
    )
    # Keep ModelSettings as a plain dict-of-kwargs so assertions are easy.
    monkeypatch.setattr(agents_sdk, "ModelSettings", lambda **kwargs: kwargs)

    profile = fake_profile(extra_body)

    asyncio.run(
        agents_sdk.AgentsSdkRuntime().run(
            "instructions",
            "input",
            profile,
            InferenceLimits(2, 10, 256),
            lambda *_: None,
        )
    )
    return seen["model_settings"]  # type: ignore[return-value]


def test_agents_sdk_forwards_extra_body_to_model_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """extra_body on the profile must appear in the ModelSettings passed to Agent."""
    ms = _run_sdk(monkeypatch, {"reasoning_effort": "none"})
    assert ms["extra_body"] == {"reasoning_effort": "none"}


def test_agents_sdk_model_settings_extra_body_is_none_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: empty extra_body must yield None (not {}) in ModelSettings."""
    ms = _run_sdk(monkeypatch, {})
    assert ms["extra_body"] is None
