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

    return tuple(
        _policy(
            config,
            "SCG2001",
            Diagnostic(
                "SCG2001",
                f"The '{skill.name}' skill has only one valid eval case.",
                affected=skill.name,
                next_action=(
                    "Add another .eval.md file if broader coverage is useful; one "
                    "case is still runnable."
                ),
            ),
        )
        for skill, count in counts.items()
        if count == 1
    )
