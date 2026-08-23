"""Safe inference compatibility diagnostics for one repository."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from skillroll.config import load_config
from skillroll.diagnostics import CommandResult, Diagnostic, JSONValue
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
    resolve_inference_candidates,
)
from skillroll.outcomes import Outcome
from skillroll.repository_io import current_directory

if TYPE_CHECKING:
    from skillroll.inference.preflight import PreflightResult
    from skillroll.inference.transport import ChatTransport

TransportFactory = Callable[[ResolvedInference], "ChatTransport"]


def _default_transport(profile: ResolvedInference) -> ChatTransport:
    """Delay the optional HTTP/SDK import until configuration needs it."""
    from skillroll.inference.transport import OpenAIChatTransport

    return OpenAIChatTransport.from_profile(profile)


def _failure_result(failure: InferenceFailure) -> CommandResult:
    if failure.kind is InferenceFailureKind.MISSING_CONFIGURATION:
        return CommandResult(
            Outcome.ERROR,
            "Local SkillRoll setup is complete, but this repository does not have "
            "a model endpoint configured yet.",
            (
                Diagnostic(
                    "SCDMISSING_CONFIGURATION",
                    failure.summary,
                    details=(
                        "Add base_url, api_key_env, and either model or profiles "
                        "under [inference] in skillroll.toml. Then set that named "
                        "environment variable.",
                    ),
                    next_action=(
                        "Add those three settings and the key, then run skillroll "
                        "doctor again."
                    ),
                ),
            ),
        )
    return CommandResult(
        Outcome.ERROR,
        "SkillRoll could not verify the configured model endpoint.",
        (
            Diagnostic(
                f"SCD{failure.kind.value.upper()}",
                failure.summary,
                details=failure.details,
                next_action=(
                    "Correct the setting above, then run skillroll doctor again."
                ),
            ),
        ),
    )


def _preflight_result(result: PreflightResult) -> CommandResult:
    if not result.passed:
        assert result.failure is not None
        return _failure_result(result.failure)
    assert result.evidence is not None
    data: Mapping[str, JSONValue] = {
        "response_model": result.evidence.response_model,
        "usage": tuple(
            {
                "input_tokens": item.input_tokens,
                "output_tokens": item.output_tokens,
                "total_tokens": item.total_tokens,
                "cache_read_tokens": item.cache_read_tokens,
            }
            for item in result.evidence.usage
        ),
    }
    return CommandResult(
        Outcome.PASS,
        "The configured model completed SkillRoll's small tool conversation.",
        data=data,
    )


async def _run_preflight(
    profile: ResolvedInference, factory: TransportFactory
) -> PreflightResult:
    from skillroll.inference.preflight import run_preflight

    transport = factory(profile)
    try:
        return await run_preflight(profile, transport)
    finally:
        await transport.close()


def run(
    *,
    repo: str | None = None,
    environment: Mapping[str, str] | None = None,
    transport_factory: TransportFactory = _default_transport,
    model_profile: str | None = None,
) -> CommandResult:
    """Run no more than the two endpoint requests required by preflight."""
    root = current_directory() if repo is None else Path(repo)
    parsed = load_config(root)
    if parsed.value is None:
        return CommandResult(
            Outcome.ERROR,
            "SkillRoll could not read this repository's configuration.",
            parsed.diagnostics,
        )
    candidates, failure = resolve_inference_candidates(
        parsed.value.inference, environment, model_profile
    )
    if failure is not None:
        return _failure_result(failure)
    assert candidates
    failures: list[str] = []
    last_failure: InferenceFailure | None = None
    try:
        for profile in candidates:
            result = asyncio.run(_run_preflight(profile, transport_factory))
            if result.passed:
                return _preflight_result(result)
            assert result.failure is not None
            last_failure = result.failure
            failures.append(f"{profile.model}: {result.failure.summary}")
    except KeyboardInterrupt:
        return _failure_result(
            InferenceFailure(
                kind=InferenceFailureKind.CANCELLED,
                summary="The compatibility check was interrupted before it finished.",
            )
        )
    assert last_failure is not None
    return _failure_result(
        replace(
            last_failure,
            summary=(
                "No ranked model candidate completed SkillRoll's compatibility check."
            ),
            details=tuple(failures),
            stage="preflight",
        )
    )
