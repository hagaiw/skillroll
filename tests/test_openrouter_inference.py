"""Contract tests for the OpenRouter completion-plus-cost specialization."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from skillroll.inference import openrouter as openrouter_module
from skillroll.inference.openrouter import OpenRouterInference, _generation_cost
from skillroll.inference.profile import (
    InferenceFailureKind,
    ResolvedInference,
    SecretValue,
)
from skillroll.inference.transport import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ModelUsage,
    TransportFailure,
)
from skillroll.models import InferenceLimits


def profile(base_url: str = "https://openrouter.ai/api/v1") -> ResolvedInference:
    return ResolvedInference(
        base_url,
        "provider/model",
        SecretValue("secret/key"),
        InferenceLimits(),
    )


class FakeTransport:
    def __init__(self, response: ChatResponse) -> None:
        self.response = response
        self.requests: list[ChatRequest] = []
        self.closed = False

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return self.response

    async def close(self) -> None:
        self.closed = True


class FakeMetadataClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[str, object, object]] = []
        self.closed = False

    async def get(self, path: str, *, cast_to: object, options: object) -> object:
        self.calls.append((path, cast_to, options))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response

    async def close(self) -> None:
        self.closed = True


class ScriptedMetadataClient(FakeMetadataClient):
    def __init__(self, responses: list[object]) -> None:
        super().__init__({})
        self.responses = responses

    async def get(self, path: str, *, cast_to: object, options: object) -> object:
        self.calls.append((path, cast_to, options))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_openrouter_inference_reuses_chat_transport_and_fetches_exact_cost() -> None:
    request = ChatRequest("provider/model", (ChatMessage("user", "hello"),))
    response = ChatResponse("done", (), "served/model", ModelUsage(3, 2, 5), "gen-1")
    transport = FakeTransport(response)
    metadata = FakeMetadataClient({"data": {"id": "gen-1", "total_cost": 0.25}})
    service = OpenRouterInference(
        profile(), transport=transport, metadata_client=metadata, cost_retry_delays=()
    )

    result = asyncio.run(service.complete(request))

    assert result.response is response
    assert result.cost.generation_id == "gen-1"
    assert result.cost.amount == 0.25
    assert result.cost.unit == "credits"
    assert result.cost.source == "openrouter_generation"
    assert transport.requests == [request]
    assert metadata.calls == [
        ("/generation", dict[str, Any], {"params": {"id": "gen-1"}})
    ]
    asyncio.run(service.close())
    assert metadata.closed
    assert not transport.closed


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"data": {"id": "other", "total_cost": 1}},
        {"data": {"id": "gen-1"}},
        {"data": {"id": "gen-1", "total_cost": True}},
        {"data": {"id": "gen-1", "total_cost": -1}},
        {"data": {"id": "gen-1", "total_cost": float("inf")}},
    ],
)
def test_generation_cost_rejects_untrustworthy_metadata(payload: object) -> None:
    with pytest.raises(ValueError, match="OpenRouter generation metadata"):
        _generation_cost(payload, "gen-1")


def test_openrouter_inference_requires_openrouter_and_generation_id() -> None:
    with pytest.raises(ValueError, match="openrouter.ai"):
        OpenRouterInference(profile("https://example.test/v1"))

    service = OpenRouterInference(
        profile(),
        transport=FakeTransport(ChatResponse("done", (), "model", None)),
        metadata_client=FakeMetadataClient({}),
    )
    with pytest.raises(TransportFailure) as raised:
        asyncio.run(
            service.complete(ChatRequest("model", (ChatMessage("user", "hello"),)))
        )
    assert raised.value.failure.kind is InferenceFailureKind.MALFORMED_RESPONSE


def test_openrouter_cost_lookup_redacts_malformed_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module = SimpleNamespace(
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
        RateLimitError=type("RateLimitError", (Exception,), {}),
        APITimeoutError=type("APITimeoutError", (Exception,), {}),
        APIStatusError=type("APIStatusError", (Exception,), {}),
        APIError=type("APIError", (Exception,), {}),
    )
    monkeypatch.setattr(openrouter_module.transport_module, "openai", fake_module)
    service = OpenRouterInference(
        profile(),
        transport=FakeTransport(ChatResponse("done", (), "model", None, "gen-1")),
        metadata_client=FakeMetadataClient(
            {"data": {"id": "gen-1", "total_cost": "secret/key"}}
        ),
    )
    with pytest.raises(TransportFailure) as raised:
        asyncio.run(
            service.complete(ChatRequest("model", (ChatMessage("user", "hello"),)))
        )
    assert raised.value.failure.kind is InferenceFailureKind.MALFORMED_RESPONSE
    assert raised.value.failure.details == (
        "OpenRouter generation metadata did not include a valid cost.",
    )


def test_openrouter_constructs_and_closes_existing_inference_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = ChatResponse("done", (), "model", None, "gen-1")
    transport = FakeTransport(response)
    metadata = FakeMetadataClient({"data": {"id": "gen-1", "total_cost": 0}})
    monkeypatch.setattr(
        openrouter_module.OpenAIChatTransport,
        "from_profile",
        lambda _: transport,
    )
    service = OpenRouterInference(profile(), metadata_client=metadata)
    asyncio.run(service.close())

    monkeypatch.setattr(openrouter_module.transport_module, "AsyncOpenAI", None)
    imported = OpenRouterInference(profile(), transport=transport)
    asyncio.run(imported.close())
    assert transport.closed and metadata.closed

    created: list[object] = []

    def client_factory(**values: object) -> FakeMetadataClient:
        created.append(values)
        return FakeMetadataClient({})

    monkeypatch.setattr(
        openrouter_module.transport_module, "AsyncOpenAI", client_factory
    )
    service = OpenRouterInference(profile(), transport=transport)
    assert created == [
        {
            "api_key": "secret/key",
            "base_url": "https://openrouter.ai/api/v1",
            "timeout": 90,
            "max_retries": 0,
        }
    ]
    asyncio.run(service.close())


@pytest.mark.parametrize(
    ("error_name", "status_code", "expected"),
    [
        ("AuthenticationError", None, InferenceFailureKind.UNAUTHORIZED),
        ("RateLimitError", None, InferenceFailureKind.RATE_LIMITED),
        ("APITimeoutError", None, InferenceFailureKind.TIMEOUT),
        ("APIStatusError", 404, InferenceFailureKind.REQUEST_REJECTED),
        ("APIStatusError", 400, InferenceFailureKind.REQUEST_REJECTED),
        ("APIStatusError", 500, InferenceFailureKind.SERVICE_FAILURE),
        ("APIError", None, InferenceFailureKind.SERVICE_FAILURE),
    ],
)
def test_openrouter_cost_lookup_preserves_failure_category(
    monkeypatch: pytest.MonkeyPatch,
    error_name: str,
    status_code: int | None,
    expected: InferenceFailureKind,
) -> None:
    classes = {
        name: type(name, (Exception,), {})
        for name in (
            "AuthenticationError",
            "RateLimitError",
            "APITimeoutError",
            "APIStatusError",
            "APIError",
        )
    }
    monkeypatch.setattr(
        openrouter_module.transport_module,
        "openai",
        SimpleNamespace(**classes),
    )
    error = classes[error_name]("secret/key")
    if status_code is not None:
        error.status_code = status_code  # type: ignore[attr-defined]
    service = OpenRouterInference(
        profile(),
        transport=FakeTransport(ChatResponse("done", (), "model", None, "gen-1")),
        metadata_client=FakeMetadataClient(error),
        cost_retry_delays=(),
    )
    with pytest.raises(TransportFailure) as raised:
        asyncio.run(
            service.complete(ChatRequest("model", (ChatMessage("user", "hello"),)))
        )
    assert raised.value.failure.kind is expected
    assert raised.value.failure.details == ("[redacted]",)


def test_openrouter_cost_lookup_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module = SimpleNamespace(
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
        RateLimitError=type("RateLimitError", (Exception,), {}),
        APITimeoutError=type("APITimeoutError", (Exception,), {}),
        APIStatusError=type("APIStatusError", (Exception,), {}),
        APIError=type("APIError", (Exception,), {}),
    )
    monkeypatch.setattr(openrouter_module.transport_module, "openai", fake_module)
    service = OpenRouterInference(
        profile(),
        transport=FakeTransport(ChatResponse("done", (), "model", None, "gen-1")),
        metadata_client=FakeMetadataClient(asyncio.CancelledError()),
        cost_retry_delays=(),
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            service.complete(ChatRequest("model", (ChatMessage("user", "hello"),)))
        )


def test_openrouter_cost_lookup_polls_only_eventual_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_error = type("APIStatusError", (Exception,), {})
    missing = status_error("not ready")
    missing.status_code = 404  # type: ignore[attr-defined]
    fake_module = SimpleNamespace(
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
        RateLimitError=type("RateLimitError", (Exception,), {}),
        APITimeoutError=type("APITimeoutError", (Exception,), {}),
        APIStatusError=status_error,
        APIError=type("APIError", (Exception,), {}),
    )
    monkeypatch.setattr(openrouter_module.transport_module, "openai", fake_module)
    metadata = ScriptedMetadataClient(
        [missing, {"data": {"id": "gen-1", "total_cost": 0.125}}]
    )
    service = OpenRouterInference(
        profile(),
        transport=FakeTransport(ChatResponse("done", (), "model", None, "gen-1")),
        metadata_client=metadata,
        cost_retry_delays=(0.0,),
    )
    result = asyncio.run(
        service.complete(ChatRequest("model", (ChatMessage("user", "hello"),)))
    )
    assert result.cost.amount == 0.125
    assert len(metadata.calls) == 2


def test_openrouter_cost_lookup_waits_between_not_found_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_error = type("APIStatusError", (Exception,), {})
    missing = status_error("not ready")
    missing.status_code = 404  # type: ignore[attr-defined]
    fake_module = SimpleNamespace(
        AuthenticationError=type("AuthenticationError", (Exception,), {}),
        RateLimitError=type("RateLimitError", (Exception,), {}),
        APITimeoutError=type("APITimeoutError", (Exception,), {}),
        APIStatusError=status_error,
        APIError=type("APIError", (Exception,), {}),
    )
    monkeypatch.setattr(openrouter_module.transport_module, "openai", fake_module)
    sleeps: list[float] = []

    async def fake_sleep(value: float) -> None:
        sleeps.append(value)

    monkeypatch.setattr(openrouter_module.asyncio, "sleep", fake_sleep)
    metadata = ScriptedMetadataClient(
        [missing, {"data": {"id": "gen-1", "total_cost": 0}}]
    )
    service = OpenRouterInference(
        profile(),
        transport=FakeTransport(ChatResponse("done", (), "model", None, "gen-1")),
        metadata_client=metadata,
        cost_retry_delays=(0.25,),
    )
    asyncio.run(service.complete(ChatRequest("model", (ChatMessage("user", "hello"),))))
    assert sleeps == [0.25]


def test_openrouter_service_async_context_closes_injected_metadata() -> None:
    metadata = FakeMetadataClient({"data": {"id": "gen-1", "total_cost": 0}})
    service = OpenRouterInference(
        profile(),
        transport=FakeTransport(ChatResponse("done", (), "model", None, "gen-1")),
        metadata_client=metadata,
    )

    async def use_service() -> None:
        async with service as entered:
            assert entered is service

    asyncio.run(use_service())
    assert metadata.closed


def test_openrouter_convenience_endpoint_owns_service_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = SimpleNamespace(response="response", cost="cost")
    request = ChatRequest("model", (ChatMessage("user", "hello"),))
    events: list[object] = []

    class FakeService:
        async def __aenter__(self) -> FakeService:
            events.append("enter")
            return self

        async def complete(self, value: ChatRequest) -> object:
            events.append(value)
            return expected

        async def __aexit__(self, *_: object) -> None:
            events.append("exit")

    monkeypatch.setattr(
        openrouter_module, "OpenRouterInference", lambda _: FakeService()
    )
    result = asyncio.run(openrouter_module.openrouter_inference(profile(), request))
    assert result is expected
    assert events == ["enter", request, "exit"]
