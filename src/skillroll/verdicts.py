"""Pure outcome precedence for complete and deliberately incomplete evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from skillroll.assertions import AssertionResult
from skillroll.checks import CheckResult
from skillroll.inference.profile import InferenceFailure
from skillroll.judge import JudgeResult
from skillroll.models import EvalCase
from skillroll.outcomes import Outcome
from skillroll.runtime.execution import ExecutionResult
from skillroll.world.session import WorldEvent

type CaseOutcome = Literal["PASS", "FAIL", "INCOMPLETE", "ERROR"]


@dataclass(frozen=True, slots=True)
class CaseResult:
    """All truthfully observed facts for one case, not merely its final color."""

    case: EvalCase
    outcome: CaseOutcome
    execution: ExecutionResult | None
    judge: JudgeResult | None
    assertions: tuple[AssertionResult, ...]
    checks: tuple[CheckResult, ...]
    failure: InferenceFailure | None
    artifact_directory: PurePosixPath | None
    events: tuple[WorldEvent, ...] = ()
    skill_available: bool = True


def case_outcome(
    failure: InferenceFailure | None,
    judge: JudgeResult | None,
    assertions: tuple[AssertionResult, ...],
    checks: tuple[CheckResult, ...],
) -> CaseOutcome:
    """Apply the approved ERROR > INCOMPLETE > FAIL > PASS priority exactly."""
    if failure is not None or any(item.outcome == "ERROR" for item in checks):
        return "ERROR"
    if any(item.outcome == "SKIPPED" for item in checks):
        return "INCOMPLETE"
    if (
        judge is None
        or judge.verdict == "FAIL"
        or any(not item.passed for item in assertions)
        or any(item.outcome == "FAIL" for item in checks)
    ):
        return "FAIL"
    return "PASS"


def aggregate(results: tuple[CaseResult, ...]) -> Outcome:
    """Map the same priority across all selected cases to stable process status."""
    values = {item.outcome for item in results}
    if "ERROR" in values:
        return Outcome.ERROR
    if "INCOMPLETE" in values:
        return Outcome.INCOMPLETE
    if "FAIL" in values:
        return Outcome.FAIL
    return Outcome.PASS
