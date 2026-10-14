"""Failure details obey the same bounded boundary in every evidence artifact."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path, PurePosixPath

from test_phase4_verdicts import ScriptedTransport, case_at, preflight_responses

from skillroll.commands import evaluate
from skillroll.inference.profile import (
    MAX_FAILURE_DETAIL_BYTES,
    InferenceFailure,
    InferenceFailureKind,
)
from skillroll.models import GuardSettings, InferenceSettings, SkillRollConfig
from skillroll.runtime.execution import ExecutionAttempt


def test_execution_failure_details_are_bounded_and_redacted_in_all_artifacts(
    tmp_path: Path,
) -> None:
    case = case_at(tmp_path)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        tmp_path / "skillroll.toml",
    )
    config.config_path.write_text("schema_version = 1", encoding="utf-8")
    failure = InferenceFailure(
        InferenceFailureKind.EXECUTION_ERROR,
        "The provider rejected the request.",
        (
            "request headers: authorization=opaque-provider-credential",
            "HTTP error: secret-key",
            "x" * (MAX_FAILURE_DETAIL_BYTES + 100),
        ),
    )

    class FailedExecutor:
        async def execute(
            self, request: object, world_action: object
        ) -> ExecutionAttempt:
            return ExecutionAttempt(None, failure)

    transport = ScriptedTransport(preflight_responses()[:2])
    result = asyncio.run(
        evaluate.evaluate_repository(
            config,
            (case,),
            environment={"KEY": "secret-key"},
            run_commands=False,
            transport_factory=lambda _: transport,
            executor_factory=lambda _: FailedExecutor(),
        )
    )
    assert not isinstance(result, InferenceFailure)
    assert result[0].outcome == "ERROR"
    directory = tmp_path / result[0].artifact_directory
    for name in ("run.json", "verdict.json", "result.json", "report.md"):
        text = (directory / name).read_text()
        assert "opaque-provider-credential" not in text, name
        assert "secret-key" not in text, name
        assert "omitted provider headers" in text, name
        assert "[truncated]" in text, name
    details = json.loads((directory / "result.json").read_text())["technical_status"][
        "details"
    ]
    assert "HTTP error: [redacted]" in details
    assert all(
        len(detail.encode("utf-8")) <= MAX_FAILURE_DETAIL_BYTES for detail in details
    )
