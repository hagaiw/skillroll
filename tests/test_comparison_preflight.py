"""Pure compatibility-preflight outcomes, fallback, and transport cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import pytest

from skillroll.commands import compare
from skillroll.inference.preflight import PreflightResult
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
    SecretRedactor,
    SecretValue,
)
from skillroll.inference.transport import (
    ChatRequest,
    ChatResponse,
    ChatTransport,
    ModelUsage,
    ToolCall,
)
from skillroll.models import (
    GuardSettings,
    InferenceLimits,
    InferenceSettings,
    ModelProfile,
    SkillRollConfig,
)


class ScriptedTransport:
    def __init__(self, responses: list[ChatResponse | BaseException]) -> None:
        self.responses = list(responses)
        self.requests: list[ChatRequest] = []
        self.closed = False
        self.close_count = 0

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    async def close(self) -> None:
        self.closed = True
        self.close_count += 1


def _config(candidates: tuple[str, ...] = ("evaluator",)) -> SkillRollConfig:
    root = Path("/comparison/repository")
    settings = InferenceSettings(
        "https://example.test/v1",
        "unused",
        "KEY",
        InferenceLimits(),
        {"selection": ModelProfile("Evaluator", candidates)},
        "selection",
    )
    return SkillRollConfig(
        root,
        PurePosixPath("skills"),
        root / "skills",
        GuardSettings(),
        settings,
        root / "skillroll.toml",
    )


def _responses(model: str, *, valid: bool = True) -> list[ChatResponse]:
    if not valid:
        return [ChatResponse("no function call", (), model, None)]
    return [
        ChatResponse(
            None,
            (ToolCall("preflight-id", "skillroll_preflight", {"value": "ready"}),),
            model,
            ModelUsage(10, 2, 12),
        ),
        ChatResponse(
            '{"status":"ready"}',
            (),
            model,
            ModelUsage(12, 3, 15),
        ),
    ]


def _redactor() -> SecretRedactor:
    return SecretRedactor(SecretValue("private-secret"))


def _run(
    config: SkillRollConfig,
    executor_models: tuple[str, ...],
    transport_factory: Callable[[ResolvedInference], ChatTransport],
    *,
    environment: dict[str, str] | None = None,
    records: dict[str, dict[str, object]] | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[
    tuple[ResolvedInference, ChatTransport] | InferenceFailure,
    dict[str, dict[str, object]],
    list[int],
]:
    updates: dict[str, dict[str, object]] = {} if records is None else records
    checkpoint_calls: list[int] = []

    def save() -> None:
        checkpoint_calls.append(len(checkpoint_calls) + 1)
        if checkpoint is not None:
            checkpoint()

    result = asyncio.run(
        compare._preflight_profiles(
            config,
            {"KEY": "private-secret"} if environment is None else environment,
            "selection",
            executor_models,
            transport_factory,
            _redactor(),
            updates,
            save,
        )
    )
    return result, updates, checkpoint_calls


def test_preflight_resolves_secret_configuration_before_transport_creation() -> None:
    factory_calls = 0

    def factory(_: ResolvedInference) -> ScriptedTransport:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("no transport should be created")

    result, records, checkpoints = _run(
        _config(), (), factory, environment={"KEY": " "}
    )

    assert isinstance(result, InferenceFailure)
    assert result.kind is InferenceFailureKind.MISSING_API_KEY
    assert result.stage == "preflight"
    assert factory_calls == 0
    assert records == {}
    assert checkpoints == []


def test_ranked_fallback_keeps_evaluator_and_probes_distinct_executor_once() -> None:
    first = ScriptedTransport(_responses("unavailable", valid=False))
    evaluator = ScriptedTransport(_responses("fallback"))
    executor = ScriptedTransport(_responses("candidate"))
    transports = {"unavailable": first, "fallback": evaluator, "candidate": executor}
    seen: list[object] = []

    def factory(profile: object) -> ScriptedTransport:
        seen.append(profile)
        return transports[profile.model]

    result, records, checkpoints = _run(
        _config(("unavailable", "fallback")), ("fallback", "candidate"), factory
    )

    assert not isinstance(result, InferenceFailure)
    profile, selected_transport = result
    assert profile.model == "fallback"
    assert selected_transport is evaluator
    assert [item.model for item in seen] == [
        "unavailable",
        "fallback",
        "candidate",
    ]
    assert records["unavailable"]["status"] == "failed"
    assert records["fallback"]["status"] == "passed"
    assert records["candidate"]["status"] == "passed"
    assert checkpoints == [1, 2, 3]
    assert first.closed and executor.closed
    assert evaluator.closed is False
    asyncio.run(selected_transport.close())
    assert evaluator.closed


def test_all_ranked_candidates_fail_with_bounded_failure_summary() -> None:
    first = ScriptedTransport(_responses("first", valid=False))
    second = ScriptedTransport(_responses("second", valid=False))
    transports = {"first": first, "second": second}

    result, records, checkpoints = _run(
        _config(("first", "second")), (), lambda profile: transports[profile.model]
    )

    assert isinstance(result, InferenceFailure)
    assert result.kind is InferenceFailureKind.MALFORMED_RESPONSE
    assert result.stage == "preflight"
    assert result.summary.startswith("No ranked model candidate")
    assert result.details == (
        "first: The endpoint did not make exactly one valid skillroll_preflight call.",
        "second: The endpoint did not make exactly one valid skillroll_preflight call.",
    )
    assert records["first"]["status"] == records["second"]["status"] == "failed"
    assert checkpoints == [1, 2]
    assert first.closed and second.closed


@pytest.mark.parametrize(
    ("failure", "kind", "status"),
    [
        (
            RuntimeError("private-secret failure"),
            InferenceFailureKind.EXECUTION_ERROR,
            "error",
        ),
        (asyncio.CancelledError(), InferenceFailureKind.CANCELLED, "failed"),
    ],
)
def test_preflight_exceptions_are_recorded_and_transport_is_closed(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
    kind: InferenceFailureKind,
    status: str,
) -> None:
    transport = ScriptedTransport([])

    async def broken_preflight(*_: object, **__: object) -> PreflightResult:
        raise failure

    monkeypatch.setattr(compare, "run_preflight", broken_preflight)
    result, records, checkpoints = _run(_config(), (), lambda _: transport)

    assert isinstance(result, InferenceFailure)
    assert result.kind is kind
    assert result.stage == "preflight"
    assert records["evaluator"]["status"] == status
    assert checkpoints == [1]
    assert transport.closed
    assert "private-secret" not in str(records)


def test_transport_creation_error_records_safe_failure_and_stops() -> None:
    calls = 0

    def broken_factory(_: object) -> ScriptedTransport:
        nonlocal calls
        calls += 1
        raise RuntimeError("private-secret in adapter details")

    result, records, checkpoints = _run(_config(), (), broken_factory)

    assert isinstance(result, InferenceFailure)
    assert result.kind is InferenceFailureKind.EXECUTION_ERROR
    assert result.stage == "preflight"
    assert (
        result.summary
        == "SkillRoll could not create the model compatibility transport."
    )
    assert records["evaluator"]["status"] == "error"
    assert "private-secret" not in str(records)
    assert calls == 1
    assert checkpoints == [1]


def test_previous_failed_executor_candidate_aborts_and_closes_selected_evaluator() -> (
    None
):
    failed = ScriptedTransport(_responses("unavailable", valid=False))
    evaluator = ScriptedTransport(_responses("fallback"))
    transports = {"unavailable": failed, "fallback": evaluator}

    result, records, checkpoints = _run(
        _config(("unavailable", "fallback")),
        ("unavailable",),
        lambda profile: transports[profile.model],
    )

    assert isinstance(result, InferenceFailure)
    assert result.kind is InferenceFailureKind.MALFORMED_RESPONSE
    assert "Executor model 'unavailable' failed" in result.summary
    assert result.stage == "preflight"
    assert records["unavailable"]["status"] == "failed"
    assert checkpoints == [1, 2]
    assert failed.closed and evaluator.closed


def test_checkpoint_without_prior_failure_uses_malformed_executor_record_fallback() -> (
    None
):
    evaluator = ScriptedTransport(_responses("evaluator"))
    prior_record = {"executor": {"status": "failed"}}

    result, records, checkpoints = _run(
        _config(),
        ("executor",),
        lambda _: evaluator,
        records=prior_record,
    )

    assert isinstance(result, InferenceFailure)
    assert result.kind is InferenceFailureKind.MALFORMED_RESPONSE
    assert "Executor model 'executor' failed" in result.summary
    assert result.stage == "preflight"
    assert records["evaluator"]["status"] == "passed"
    assert checkpoints == [1]
    assert evaluator.closed


def test_executor_preflight_failure_closes_both_candidate_and_evaluator() -> None:
    evaluator = ScriptedTransport(_responses("evaluator"))
    candidate = ScriptedTransport(_responses("candidate", valid=False))
    transports = {"evaluator": evaluator, "candidate": candidate}

    result, records, checkpoints = _run(
        _config(), ("candidate",), lambda profile: transports[profile.model]
    )

    assert isinstance(result, InferenceFailure)
    assert result.kind is InferenceFailureKind.MALFORMED_RESPONSE
    assert "Executor model 'candidate' failed" in result.summary
    assert records["candidate"]["status"] == "failed"
    assert checkpoints == [1, 2]
    assert candidate.closed and evaluator.closed


@pytest.mark.parametrize("checkpoint_number", [1, 2])
def test_checkpoint_exception_closes_every_transport(
    checkpoint_number: int,
) -> None:
    evaluator = ScriptedTransport(_responses("evaluator"))
    candidate = ScriptedTransport(_responses("candidate"))
    transports = {"evaluator": evaluator, "candidate": candidate}
    calls = 0

    def fail_checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == checkpoint_number:
            raise RuntimeError("checkpoint write failed")

    with pytest.raises(RuntimeError, match="checkpoint write failed"):
        _run(
            _config(),
            ("candidate",),
            lambda profile: transports[profile.model],
            checkpoint=fail_checkpoint,
        )

    assert evaluator.closed
    if checkpoint_number == 2:
        assert candidate.closed
    else:
        assert candidate.closed is False
