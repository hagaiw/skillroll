"""Phase-3 composition for one preliminary, not-yet-judged execution."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath

from skillroll.artifacts.hashes import InputHash, classify_bundle_path, hash_file
from skillroll.artifacts.records import RunFacts, manifest_bytes
from skillroll.artifacts.store import ArtifactError, ArtifactStore
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
    SecretRedactor,
    bounded_failure_details,
)
from skillroll.inference.transport import ChatTransport
from skillroll.models import (
    EvalCase,
    InferenceLimits,
    SkillRollConfig,
    effective_limits,
)
from skillroll.runtime.execution import (
    ExecutionAttempt,
    ExecutionRequest,
    SkillExecutor,
)
from skillroll.world.bundle import BundleError, BundleIndex, BundleWarning, build_bundle
from skillroll.world.session import WorldEvent, WorldSession


@dataclass(frozen=True, slots=True)
class PreliminaryAttempt:
    """A complete execution record with no behavioral verdict yet."""

    execution: ExecutionAttempt | None
    failure: InferenceFailure | None
    artifact_directory: PurePosixPath | None
    events: tuple[WorldEvent, ...] = ()
    warnings: tuple[BundleWarning, ...] = ()


def input_hashes(
    config: SkillRollConfig, case: EvalCase, bundle: BundleIndex
) -> tuple[InputHash, ...]:
    """Return every required config/case/bundle identity exactly once."""
    values = [
        hash_file(PurePosixPath("skillroll.toml"), "config", config.config_path),
        hash_file(case.identity, "eval_case", case.path),
    ]
    for item in bundle.files:
        values.append(
            InputHash(
                case.skill.identity / item.path,
                classify_bundle_path(item.path),
                item.sha256,
                item.size,
            )
        )
    return tuple(sorted(values, key=lambda item: item.identity.as_posix()))


def _limit_values(limits: InferenceLimits) -> dict[str, int]:
    return {
        "max_turns": limits.max_turns,
        "timeout_seconds": limits.timeout_seconds,
        "max_output_tokens": limits.max_output_tokens,
    }


async def execute_preliminary(
    config: SkillRollConfig,
    case: EvalCase,
    profile: ResolvedInference,
    executor: SkillExecutor,
    transport: ChatTransport,
    store: ArtifactStore,
    *,
    skill_available: bool = True,
) -> PreliminaryAttempt:
    """Execute a validated case and persist evidence without assigning a verdict."""
    limits = effective_limits(profile.limits, case.limits)
    if limits is None:
        return PreliminaryAttempt(
            None,
            InferenceFailure(
                InferenceFailureKind.EXECUTION_ERROR,
                "This eval case raises a limit above the repository's inference limit.",
            ),
            None,
            (),
        )
    try:
        bundle = (
            build_bundle(case.skill.root)
            if skill_available
            else BundleIndex(case.skill.root, ())
        )
        warnings = bundle.warnings
        inputs = input_hashes(config, case, bundle)
        manifest = manifest_bytes(inputs)
        run_id, directory, started = store.create()
    except (ArtifactError, BundleError, ValueError) as error:
        return PreliminaryAttempt(
            None,
            InferenceFailure(InferenceFailureKind.EXECUTION_ERROR, str(error)),
            None,
            (),
        )
    session = WorldSession(
        profile, limits, case.world_markdown, bundle, case.rules, transport
    )
    execution: ExecutionAttempt | None
    failure: InferenceFailure | None = None
    status = "executed"
    try:
        execution = await executor.execute(
            ExecutionRequest(
                case.skill if skill_available else None,
                case.input_markdown,
                limits,
            ),
            session,
        )
        failure = execution.failure
        if failure is not None:
            status = (
                "cancelled"
                if failure.kind == InferenceFailureKind.CANCELLED
                else "error"
            )
    except asyncio.CancelledError:
        execution = None
        failure = InferenceFailure(
            InferenceFailureKind.CANCELLED,
            "The skill execution was cancelled before it finished.",
        )
        status = "cancelled"
    facts = RunFacts(
        run_id,
        started,
        case.skill.identity.as_posix(),
        case.identity.as_posix(),
        case.title,
        profile.base_url,
        profile.model,
        _limit_values(profile.limits),
        _limit_values(limits),
        hashlib.sha256(manifest).hexdigest(),
        status,
        session.events,
        None if failure is None else failure.summary,
        ()
        if failure is None
        else bounded_failure_details(failure, SecretRedactor(profile.api_key)),
        profile.profile_name,
        profile.profile_purpose,
        skill_available,
        warnings,
    )
    try:
        store.write(directory, facts, manifest, session.events)
    except ArtifactError as error:
        return PreliminaryAttempt(
            execution,
            InferenceFailure(InferenceFailureKind.EXECUTION_ERROR, str(error)),
            PurePosixPath(".skillroll") / "runs" / run_id,
            session.events,
            warnings,
        )
    return PreliminaryAttempt(
        execution,
        failure,
        PurePosixPath(".skillroll") / "runs" / run_id,
        session.events,
        warnings,
    )
