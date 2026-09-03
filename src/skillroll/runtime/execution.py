"""Safe skill loading and bounded execution orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from skillroll.diagnostics import JSONValue
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
    SecretRedactor,
)
from skillroll.inference.transport import ModelUsage, ToolCall
from skillroll.models import InferenceLimits, Skill
from skillroll.prompt_resources import load_harness_prompt

_MAX_INPUT_BYTES = 64 * 1024


class WorldActionHandler(Protocol):
    """The future world boundary, represented as one generic agent tool."""

    async def __call__(
        self, tool_name: str, arguments: Mapping[str, JSONValue]
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    """Everything required to execute one already validated skill."""

    skill: Skill | None
    user_input: str
    limits: InferenceLimits


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Normalized output returned by one completed reference-agent run."""

    final_output: str
    turns: int | None
    usage: tuple[ModelUsage, ...]
    tool_calls: tuple[ToolCall, ...]
    turns_source: str = "unavailable"


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    """A no-exception result at the execution/domain boundary."""

    result: ExecutionResult | None
    failure: InferenceFailure | None


class SkillExecutor(Protocol):
    """The phase-four evaluator depends only on this execution seam."""

    async def execute(
        self, request: ExecutionRequest, world_action: WorldActionHandler
    ) -> ExecutionAttempt: ...


@dataclass(frozen=True, slots=True)
class SdkExecution:
    """The narrow result expected from the concrete Agents SDK adapter."""

    final_output: str
    turns: int | None
    usage: tuple[ModelUsage, ...]
    tool_calls: tuple[ToolCall, ...]
    turns_source: str = "unavailable"


class SdkRuntime(Protocol):
    """Injected adapter so orchestration tests never need a model SDK."""

    async def run(
        self,
        instructions: str,
        user_input: str,
        profile: ResolvedInference,
        limits: InferenceLimits,
        world_action: WorldActionHandler,
    ) -> SdkExecution: ...


def load_skill_text(skill: Skill) -> tuple[str | None, InferenceFailure | None]:
    """Read only a regular, in-root UTF-8 SKILL.md file."""
    try:
        root = skill.root.resolve(strict=True)
        path = skill.skill_file
        if path.is_symlink() or not path.is_file():
            raise ValueError("SKILL.md is not a regular file.")
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        with resolved.open("r", encoding="utf-8", newline="") as opened:
            return opened.read(), None
    except (OSError, UnicodeDecodeError, ValueError) as error:
        return None, InferenceFailure(
            InferenceFailureKind.EXECUTION_ERROR,
            "SkillRoll could not safely read this skill's SKILL.md file.",
            (str(error),),
        )


def wrapped_instructions(skill_text: str) -> str:
    """Add only the harness contract before preserving SKILL.md verbatim."""
    return load_harness_prompt("executor") + "\n" + skill_text


def omitted_skill_instructions() -> str:
    """Instructions for the diagnostic run that intentionally omits SKILL.md."""
    return load_harness_prompt("executor_omission")


class AgentSkillExecutor:
    """Timeout/cancellation-safe bridge from a validated skill to the SDK."""

    def __init__(self, profile: ResolvedInference, runtime: SdkRuntime) -> None:
        self._profile = profile
        self._runtime = runtime

    async def execute(
        self, request: ExecutionRequest, world_action: WorldActionHandler
    ) -> ExecutionAttempt:
        """Execute once, with local input checks before any model interaction."""
        if len(request.user_input.encode("utf-8")) > _MAX_INPUT_BYTES:
            return ExecutionAttempt(
                None,
                InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "The evaluation input is larger than SkillRoll's 64 KiB limit.",
                ),
            )
        if request.skill is None:
            instructions = omitted_skill_instructions()
        else:
            text, failure = load_skill_text(request.skill)
            if failure is not None:
                return ExecutionAttempt(None, failure)
            assert text is not None
            instructions = wrapped_instructions(text)
        try:
            async with asyncio.timeout(request.limits.timeout_seconds):
                executed = await self._runtime.run(
                    instructions,
                    request.user_input,
                    self._profile,
                    request.limits,
                    world_action,
                )
        except TimeoutError:
            return ExecutionAttempt(
                None,
                InferenceFailure(
                    InferenceFailureKind.TIMEOUT,
                    "The skill did not finish before the configured timeout.",
                ),
            )
        except asyncio.CancelledError:
            return ExecutionAttempt(
                None,
                InferenceFailure(
                    InferenceFailureKind.CANCELLED,
                    "The skill execution was cancelled before it finished.",
                ),
            )
        except Exception as error:
            redactor = SecretRedactor(self._profile.api_key)
            return ExecutionAttempt(
                None,
                InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "SkillRoll could not complete the configured skill execution.",
                    (redactor.redact(str(error)),),
                ),
            )
        return ExecutionAttempt(
            ExecutionResult(
                executed.final_output.strip(),
                executed.turns,
                executed.usage,
                executed.tool_calls,
                executed.turns_source,
            ),
            None,
        )
