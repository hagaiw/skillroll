"""Safe skill loading and bounded execution orchestration."""

from __future__ import annotations

import asyncio
import json
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
from skillroll.models import ExecutionTopology, InferenceLimits, Skill
from skillroll.prompt_resources import load_harness_prompt

_MAX_INPUT_BYTES = 64 * 1024
_MAX_SKILL_BYTES = 128 * 1024


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
    execution_topology: ExecutionTopology = "action_enabled"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Normalized output returned by one completed reference-agent run."""

    final_output: str
    turns: int | None
    usage: tuple[ModelUsage, ...]
    tool_calls: tuple[ToolCall, ...]
    turns_source: str = "unavailable"
    execution_topology: ExecutionTopology = "action_enabled"


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    """A no-exception result at the execution/domain boundary."""

    result: ExecutionResult | None
    failure: InferenceFailure | None


class SkillExecutor(Protocol):
    """The phase-four evaluator depends only on this execution seam."""

    async def execute(
        self, request: ExecutionRequest, world_action: WorldActionHandler | None = None
    ) -> ExecutionAttempt: ...


@dataclass(frozen=True, slots=True)
class SdkExecution:
    """The narrow result expected from the concrete Agents SDK adapter."""

    final_output: str
    turns: int | None
    usage: tuple[ModelUsage, ...]
    tool_calls: tuple[ToolCall, ...]
    turns_source: str = "unavailable"
    execution_topology: ExecutionTopology = "action_enabled"


class SdkRuntime(Protocol):
    """Injected adapter so orchestration tests never need a model SDK."""

    async def run(
        self,
        instructions: str,
        user_input: str,
        profile: ResolvedInference,
        limits: InferenceLimits,
        world_action: WorldActionHandler | None,
        execution_topology: ExecutionTopology = "action_enabled",
    ) -> SdkExecution: ...


def load_skill_text(skill: Skill) -> tuple[str | None, InferenceFailure | None]:
    """Read only a regular, in-root UTF-8 SKILL.md below the size ceiling."""
    try:
        root = skill.root.resolve(strict=True)
        path = skill.skill_file
        if path.is_symlink() or not path.is_file():
            raise ValueError("SKILL.md is not a regular file.")
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        raw = resolved.read_bytes()
        if len(raw) > _MAX_SKILL_BYTES:
            raise ValueError("SKILL.md is larger than 128 KiB.")
        return raw.decode("utf-8"), None
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


def text_only_wrapped_instructions(skill_text: str) -> str:
    """Add the fixed no-action contract before preserving SKILL.md verbatim."""
    return load_harness_prompt("executor_text_only") + "\n" + skill_text


def text_only_omitted_skill_instructions() -> str:
    """Instructions for a text-only diagnostic run without SKILL.md."""
    return load_harness_prompt("executor_text_only_omission")


def _unexpected_tool_details(tool_calls: tuple[ToolCall, ...]) -> tuple[str, ...]:
    """Preserve normalized rogue calls as bounded, redactor-safe failure facts."""
    return tuple(
        "Unexpected tool call in text-only mode: "
        + call.name
        + " "
        + json.dumps(
            call.arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for call in tool_calls
    )


class AgentSkillExecutor:
    """Timeout/cancellation-safe bridge from a validated skill to the SDK."""

    def __init__(self, profile: ResolvedInference, runtime: SdkRuntime) -> None:
        self._profile = profile
        self._runtime = runtime

    async def execute(
        self, request: ExecutionRequest, world_action: WorldActionHandler | None = None
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
        if request.execution_topology == "text_only":
            action_handler = None
        elif request.execution_topology == "action_enabled":
            action_handler = world_action
        else:
            return ExecutionAttempt(
                None,
                InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "SkillRoll received an unsupported execution topology.",
                ),
            )
        if request.skill is None:
            instructions = (
                text_only_omitted_skill_instructions()
                if request.execution_topology == "text_only"
                else omitted_skill_instructions()
            )
        else:
            text, failure = load_skill_text(request.skill)
            if failure is not None:
                return ExecutionAttempt(None, failure)
            assert text is not None
            instructions = (
                text_only_wrapped_instructions(text)
                if request.execution_topology == "text_only"
                else wrapped_instructions(text)
            )
        try:
            async with asyncio.timeout(request.limits.timeout_seconds):
                executed = await self._runtime.run(
                    instructions,
                    request.user_input,
                    self._profile,
                    request.limits,
                    action_handler,
                    request.execution_topology,
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
        if request.execution_topology == "text_only" and executed.tool_calls:
            redactor = SecretRedactor(self._profile.api_key)
            return ExecutionAttempt(
                None,
                InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "The skill made an unexpected tool call in text-only mode.",
                    tuple(
                        redactor.redact(detail)
                        for detail in _unexpected_tool_details(executed.tool_calls)
                    ),
                ),
            )
        return ExecutionAttempt(
            ExecutionResult(
                executed.final_output.strip(),
                executed.turns,
                executed.usage,
                executed.tool_calls,
                executed.turns_source,
                request.execution_topology,
            ),
            None,
        )
