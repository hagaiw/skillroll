"""Immutable values shared by the inference-free validation boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

from skillroll.diagnostics import Diagnostic, JSONValue, SourceLocation

type GuardId = Literal["SCG2001"]
type FindingDisposition = Literal["blocking", "advisory"]
type ExecutionTopology = Literal["action_enabled", "text_only"]


@dataclass(frozen=True, slots=True)
class InferenceLimits:
    """Repository-wide ceilings for one model-backed skill run."""

    max_turns: int = 8
    timeout_seconds: int = 90
    max_output_tokens: int = 8192


@dataclass(frozen=True, slots=True)
class InferenceSettings:
    base_url: str
    model: str
    api_key_env: str
    limits: InferenceLimits = InferenceLimits()
    profiles: Mapping[str, ModelProfile] = field(default_factory=dict)
    default_profile: str | None = None


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """One named purpose with ranked model candidates for preflight."""

    purpose: str
    models: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """User-supplied prices per million tokens for one model."""

    input_per_million: float
    output_per_million: float
    cache_read_per_million: float | None = None


@dataclass(frozen=True, slots=True)
class PricingSettings:
    """Optional explicit price data; SkillRoll never fetches it implicitly."""

    currency: str
    models: Mapping[str, ModelPricing]


@dataclass(frozen=True, slots=True)
class GuardSettings:
    disabled: frozenset[GuardId] = frozenset()


@dataclass(frozen=True, slots=True)
class SkillRollConfig:
    repository_root: Path
    skills_path: PurePosixPath
    skills_root: Path
    guards: GuardSettings
    inference: InferenceSettings | None
    config_path: Path
    pricing: PricingSettings | None = None


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    identity: PurePosixPath
    root: Path
    skill_file: Path
    evals_directory: Path


@dataclass(frozen=True, slots=True)
class DeclaredCheck:
    name: str
    command: str
    covers: tuple[PurePosixPath, ...]
    location: SourceLocation


@dataclass(frozen=True, slots=True)
class DeterministicRule:
    """One exact intended-action result supplied by an eval author."""

    name: str
    tool_name: str
    arguments: JSONValue
    result: str


@dataclass(frozen=True, slots=True)
class CaseLimits:
    """Optional per-case restrictions; they can never enlarge repository limits."""

    max_turns: int | None = None
    timeout_seconds: int | None = None
    max_output_tokens: int | None = None


type AssertionKind = Literal[
    "final_output_contains",
    "final_output_not_contains",
    "final_output_equals",
]


@dataclass(frozen=True, slots=True)
class Assertion:
    """One optional exact final-output fact declared in an eval case."""

    kind: AssertionKind
    expected_text: str | None = None


def effective_limits(
    repository_limits: InferenceLimits, case_limits: CaseLimits
) -> InferenceLimits | None:
    """Apply case restrictions, rejecting any attempt to exceed repository bounds."""
    values = {
        "max_turns": case_limits.max_turns,
        "timeout_seconds": case_limits.timeout_seconds,
        "max_output_tokens": case_limits.max_output_tokens,
    }
    repository_values = {
        "max_turns": repository_limits.max_turns,
        "timeout_seconds": repository_limits.timeout_seconds,
        "max_output_tokens": repository_limits.max_output_tokens,
    }
    if any(
        value is not None and value > repository_values[name]
        for name, value in values.items()
    ):
        return None
    return InferenceLimits(
        values["max_turns"] or repository_limits.max_turns,
        values["timeout_seconds"] or repository_limits.timeout_seconds,
        values["max_output_tokens"] or repository_limits.max_output_tokens,
    )


@dataclass(frozen=True, slots=True)
class EvalCase:
    path: Path
    identity: PurePosixPath
    skill: Skill
    title: str | None
    input_markdown: str
    world_markdown: str
    success_criteria_markdown: str
    checks: tuple[DeclaredCheck, ...]
    rules: tuple[DeterministicRule, ...] = ()
    limits: CaseLimits = CaseLimits()
    assertions: tuple[Assertion, ...] = ()
    execution_topology: ExecutionTopology = "action_enabled"


@dataclass(frozen=True, slots=True)
class GuardFinding:
    guard_id: str
    is_policy: bool
    is_disabled: bool
    diagnostic: Diagnostic
    disposition: FindingDisposition = "blocking"

    @property
    def is_blocking(self) -> bool:
        """Whether this finding prevents a command from proceeding."""
        return self.disposition == "blocking" and not self.is_disabled

    @property
    def is_advisory(self) -> bool:
        """Whether this finding is useful feedback without being a gate."""
        return self.disposition == "advisory" and not self.is_disabled


@dataclass(frozen=True, slots=True)
class ValidationReport:
    repository_root: Path
    config: SkillRollConfig | None
    skills: tuple[Skill, ...]
    cases: tuple[EvalCase, ...]
    findings: tuple[GuardFinding, ...]
    skipped_safe_symlinks: tuple[PurePosixPath, ...]


@dataclass(frozen=True, slots=True)
class Selection:
    skill: PurePosixPath | None = None
    case: PurePosixPath | None = None


@dataclass(frozen=True, slots=True)
class ParsedResult[T]:
    value: T | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def is_valid(self) -> bool:
        return self.value is not None and not self.diagnostics
