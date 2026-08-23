"""The inference-free repository validation command."""

import asyncio
import os
from collections.abc import Mapping
from pathlib import Path

from skillroll.checks import (
    CheckRequest,
    CheckResult,
    CheckRunner,
    HostCheckRunner,
    check_environment,
    redact_check_result,
    skipped_check,
)
from skillroll.diagnostics import CommandResult, Diagnostic
from skillroll.inference.profile import SecretRedactor, SecretValue
from skillroll.models import EvalCase
from skillroll.outcomes import Outcome
from skillroll.repository_io import current_directory
from skillroll.validation import (
    command_result,
    selection_from_strings,
    validate_repository,
)


def run(
    *,
    repo: str | None = None,
    skill: str | None = None,
    case: str | None = None,
    run_commands: bool = False,
    environment: Mapping[str, str] | None = None,
    runner: CheckRunner | None = None,
    selected_cases: tuple[EvalCase, ...] | None = None,
) -> CommandResult:
    """Validate one explicitly selected repository without running its code."""
    root = current_directory() if repo is None else Path(repo)
    report = validate_repository(root, selection_from_strings(skill, case))
    base = command_result(report)
    if base.outcome is not Outcome.PASS or report.config is None:
        return base
    cases = report.cases if selected_cases is None else selected_cases
    config = report.config
    requests = tuple(
        CheckRequest(item, check, "validate", report.repository_root, None)
        for item in cases
        for check in item.checks
    )
    if not requests:
        return base
    active_runner = HostCheckRunner() if runner is None else runner
    values = os.environ if environment is None else environment

    redactor = SecretRedactor(
        SecretValue(
            ""
            if config.inference is None
            else values.get(config.inference.api_key_env, "")
        )
    )

    async def collect() -> tuple[CheckResult, ...]:
        results: list[CheckResult] = []
        for request in requests:
            if run_commands:
                results.append(
                    redact_check_result(
                        await active_runner.run(
                            request, check_environment(config, request, values)
                        ),
                        redactor,
                    )
                )
            else:
                results.append(redact_check_result(skipped_check(request), redactor))
        return tuple(results)

    try:
        checks = asyncio.run(collect())
    except KeyboardInterrupt:
        return CommandResult(
            Outcome.ERROR,
            "SkillRoll stopped while running a repository check.",
            data=base.data,
        )
    pairs = tuple(zip(requests, checks, strict=True))
    skipped = [pair for pair in pairs if pair[1].outcome == "SKIPPED"]
    failed = [pair for pair in pairs if pair[1].outcome == "FAIL"]
    errors = [pair for pair in pairs if pair[1].outcome == "ERROR"]
    skipped_diagnostics = tuple(
        Diagnostic(
            "SCV1001",
            item.detail or "A declared repository check was not run.",
            affected=(f"{request.case.identity.as_posix()}: check “{item.check.name}”"),
            location=item.check.location,
            next_action=(
                "Run the exact command above only after you trust this repository."
            ),
        )
        for request, item in skipped
    )
    if errors:
        return CommandResult(
            Outcome.ERROR,
            "A repository check could not finish.",
            tuple(
                Diagnostic(
                    "SCV1002",
                    item.detail or "A repository check could not finish.",
                    affected=(
                        f"{request.case.identity.as_posix()}: check “{item.check.name}”"
                    ),
                    location=item.check.location,
                    details=(f"Command: {item.check.command}",),
                )
                for request, item in errors
            ),
            base.data,
        )
    if skipped:
        return CommandResult(
            Outcome.INCOMPLETE,
            "Required repository checks were not run.",
            skipped_diagnostics,
            base.data,
        )
    if failed:
        return CommandResult(
            Outcome.FAIL,
            "A repository check reported a failure.",
            tuple(
                Diagnostic(
                    "SCV1003",
                    "This repository check exited with a nonzero status.",
                    affected=(
                        f"{request.case.identity.as_posix()}: check “{item.check.name}”"
                    ),
                    location=item.check.location,
                    details=(f"Command: {item.check.command}",),
                )
                for request, item in failed
            ),
            base.data,
        )
    skill_noun = "skill" if len(report.skills) == 1 else "skills"
    check_noun = "repository check" if len(checks) == 1 else "repository checks"
    return CommandResult(
        Outcome.PASS,
        f"Validated {len(report.skills)} {skill_noun} and ran "
        f"{len(checks)} {check_noun}.",
        data=base.data,
    )
