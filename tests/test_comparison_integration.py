"""Compare uses native run evidence and keeps executor/evaluator routing separate."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_phase4_verdicts import ScriptedTransport, preflight_responses

from skillroll.commands import compare
from skillroll.inference.transport import ModelUsage
from skillroll.outcomes import Outcome
from skillroll.runtime.execution import ExecutionAttempt, ExecutionResult


def repository(root: Path, *, rules: bool) -> None:
    (root / "skillroll.toml").write_text("""schema_version = 1
skills_path = "skills"
[inference]
base_url = "https://example.test/v1"
model = "evaluator"
executor_model = "ignored-configured-executor"
api_key_env = "KEY"
[pricing.models.evaluator]
input_per_million = 2
output_per_million = 4
[pricing.models.candidate]
input_per_million = 1
output_per_million = 2
""")
    skill = root / "skills" / "review"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text("Write an overview.")
    metadata = ""
    if rules:
        metadata = """rules:
- name: write
  tool_name: Write
  arguments: {path: overview.md}
  result: simulated write
"""
    (skill / "evals" / "basic.eval.md").write_text(
        "# Write overview\n\n```skillroll\nschema_version: 1\n"
        + metadata
        + "```\n\n## Input\nWrite overview.md.\n\n## World\nWrites succeed."
        + "\n\n## Success criteria\nsuccess\n"
    )


@pytest.mark.parametrize("rules", [False, True])
def test_native_comparison_routes_roles_and_preserves_all_run_evidence(
    tmp_path: Path, rules: bool
) -> None:
    repository(tmp_path, rules=rules)
    transports = {}
    executed = []

    def transport_factory(profile):
        # The manifest must exist before the very first network adapter is made.
        paths = list((tmp_path / ".skillroll/comparisons").glob("*/manifest.json"))
        manifest = json.loads(paths[0].read_text())
        assert len(manifest["schedule"]) == 4
        assert manifest["input_hashes"]
        responses = preflight_responses()[:2]
        if profile.model == "evaluator":
            for _ in range(4):
                responses.extend(
                    preflight_responses()[3:] if rules else preflight_responses()[2:]
                )
        transport = ScriptedTransport(
            [
                replace(item, model=profile.model, usage=ModelUsage(12, 4, 16))
                for item in responses
            ]
        )
        transports[profile.model] = transport
        return transport

    def executor_factory(profile):
        class Executor:
            async def execute(self, request, world_action):
                executed.append(profile.model)
                await world_action("Write", {"path": "overview.md"})
                return ExecutionAttempt(
                    ExecutionResult(
                        "overview written", 1, (ModelUsage(100, 50, 150),), ()
                    ),
                    None,
                )

        return Executor()

    result = compare.run(
        repo=str(tmp_path),
        executor_models=("evaluator", "candidate"),
        samples=2,
        seed=7,
        environment={"KEY": "private-key"},
        transport_factory=transport_factory,
        executor_factory=executor_factory,
    )
    assert result.outcome is Outcome.PASS, result
    directory = tmp_path / result.data["artifact_directory"]
    manifest = json.loads((directory / "manifest.json").read_text())
    summary = json.loads((directory / "comparison.json").read_text())
    assert executed == [row["executor_model"] for row in manifest["schedule"]]
    assert set(transports) == {"evaluator", "candidate"}
    assert all(item.closed for item in transports.values())
    assert len(transports["candidate"].requests) == 2
    assert summary["status"] == "complete"
    assert len(summary["attempts"]) == 4
    for attempt in summary["attempts"]:
        run = tmp_path / attempt["run_artifact_directory"]
        saved = json.loads((run / "result.json").read_text())
        assert saved["models"] == {
            "executor": attempt["executor_model"],
            "world": "evaluator",
            "judge": "evaluator",
        }
        assert saved["cost"]["status"] == "estimated"
        execution_cost = 0.0004 if attempt["executor_model"] == "evaluator" else 0.0002
        evaluator_cost = 0.00004 if rules else 0.00008
        assert saved["cost"]["amount"] == pytest.approx(execution_cost + evaluator_cost)
        assert saved["timings"]["judge_seconds"] is not None
        assert saved["timings"]["executor_seconds"] >= 0
        assert "private-key" not in (run / "result.json").read_text()
        assert (
            saved["execution"]["usage"]["calls"][0]["requested_model"]
            == (attempt["executor_model"])
        )
    assert "private-key" not in (directory / "manifest.json").read_text()
