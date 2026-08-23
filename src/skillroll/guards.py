"""Objective guards expressed as pure findings over parsed repository values."""

from __future__ import annotations

from skillroll.diagnostics import Diagnostic
from skillroll.models import (
    EvalCase,
    FindingDisposition,
    GuardFinding,
    Skill,
    SkillRollConfig,
)


def _policy(
    config: SkillRollConfig,
    guard_id: str,
    diagnostic: Diagnostic,
    disposition: FindingDisposition = "advisory",
) -> GuardFinding:
    return GuardFinding(
        guard_id,
        True,
        guard_id in config.guards.disabled,
        diagnostic,
        disposition,
    )


def minimum_case_findings(
    config: SkillRollConfig, skills: tuple[Skill, ...], cases: tuple[EvalCase, ...]
) -> tuple[GuardFinding, ...]:
    counts = {skill: 0 for skill in skills}
    for case in cases:
        counts[case.skill] += 1

    def diagnostic(skill: Skill, count: int) -> Diagnostic:
        if count == 0:
            return Diagnostic(
                "SCG2001",
                f"The '{skill.name}' skill has no valid eval cases.",
                affected=skill.name,
                next_action=(
                    "Add a focused .eval.md file if behavioral coverage is useful."
                ),
            )
        return Diagnostic(
            "SCG2001",
            f"The '{skill.name}' skill has fewer than two valid eval cases.",
            affected=skill.name,
            next_action=(
                "Add another .eval.md file if broader coverage is useful; one "
                "case is still runnable."
            ),
        )

    return tuple(
        _policy(
            config,
            "SCG2001",
            diagnostic(skill, count),
        )
        for skill, count in counts.items()
        if count < 2
    )
