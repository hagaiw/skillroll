"""Explicitly opted-in real-endpoint evidence for the installed CLI only."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import pytest
from conftest import ROOT

from skillroll.inference.profile import ResolvedInference, SecretValue
from skillroll.inference.transport import OpenAIChatTransport
from skillroll.judge import judge
from skillroll.models import CaseLimits, EvalCase, InferenceLimits, Skill
from skillroll.runtime.execution import ExecutionResult

LIVE_OPT_IN = "SKILLROLL_LIVE_E2E"
LIVE_KEY = "SKILLROLL_LIVE_API_KEY"
LIVE_BASE_URL = "SKILLROLL_LIVE_BASE_URL"
LIVE_MODEL = "SKILLROLL_LIVE_MODEL"
DIRECT_JUDGE_RESULT = "SKILLROLL_DIRECT_JUDGE_RESULT"
FINAL_OUTPUT_JUDGE_RESULT = "SKILLROLL_FINAL_OUTPUT_JUDGE_RESULT"
DOGFOOD_LIVE_BASE_URL = "https://openrouter.ai/api/v1"
DOGFOOD_LIVE_MODEL = "openai/gpt-4.1-nano"
MAX_CASES = 2
MAX_TURNS = 2
MAX_WORLD_ACTIONS_PER_CASE = 1
MAX_OUTPUT_TOKENS = 1024
PREFLIGHT_REQUESTS = 2
MAX_PROVIDER_REQUESTS = 12
MAX_FAILURE_DIAGNOSTICS = 3
MAX_FAILURE_TEXT_BYTES = 1024
_UNSAFE_DIAGNOSTIC_MARKERS = (
    "authorization",
    "api-key",
    "cookie",
    "headers",
    "messages=",
    "prompt=",
)


def _bounded_live_text(value: object, key: str) -> str:
    """Keep a failed paid-test report useful without echoing credentials."""
    text = str(value)
    if key:
        text = text.replace(key, "[redacted]").replace(
            quote(key, safe=""), "[redacted]"
        )
    if any(marker in text.casefold() for marker in _UNSAFE_DIAGNOSTIC_MARKERS):
        return "[omitted for safety]"
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_FAILURE_TEXT_BYTES:
        return text
    suffix = " [truncated]"
    ceiling = MAX_FAILURE_TEXT_BYTES - len(suffix.encode("utf-8"))
    return encoded[:ceiling].decode("utf-8", errors="ignore") + suffix


def _normalized_live_failure(
    completed: subprocess.CompletedProcess[str], key: str
) -> str:
    """Render only bounded CLI diagnostic fields for a failed live assertion."""
    normalized: dict[str, object] = {"returncode": completed.returncode}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        normalized["diagnostic"] = "SkillRoll did not return JSON output."
        normalized["stdout_bytes"] = len(completed.stdout.encode("utf-8"))
        normalized["stderr_bytes"] = len(completed.stderr.encode("utf-8"))
        return json.dumps(normalized, sort_keys=True)
    if not isinstance(payload, dict):
        normalized["diagnostic"] = "SkillRoll JSON output was not an object."
        return json.dumps(normalized, sort_keys=True)
    for name in ("outcome", "summary"):
        outcome_value = payload.get(name)
        if isinstance(outcome_value, str):
            normalized[name] = _bounded_live_text(outcome_value, key)
    values: list[dict[str, object]] = []
    diagnostics = payload.get("diagnostics")
    if isinstance(diagnostics, list):
        for diagnostic in diagnostics[:MAX_FAILURE_DIAGNOSTICS]:
            if not isinstance(diagnostic, dict):
                continue
            value: dict[str, object] = {}
            for name in ("code", "summary", "affected", "next_action"):
                item = diagnostic.get(name)
                if isinstance(item, str):
                    value[name] = _bounded_live_text(item, key)
            details = diagnostic.get("details")
            if isinstance(details, list):
                value["details"] = [
                    _bounded_live_text(item, key)
                    for item in details[:MAX_FAILURE_DIAGNOSTICS]
                    if isinstance(item, str)
                ]
            if value:
                values.append(value)
    if values:
        normalized["diagnostics"] = values
    return json.dumps(normalized, sort_keys=True)


def _write_atomic_json(path: Path, value: object) -> None:
    """Persist a live result before assertions or terminal rendering."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _executable(environment: Path, name: str) -> Path:
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    return scripts / f"{name}{suffix}"


def _dependency_site_packages() -> Path:
    candidates = tuple((ROOT / ".venv").glob("**/site-packages"))
    assert candidates
    return candidates[0]


def _sanitized_build_environment(environment: dict[str, str]) -> dict[str, str]:
    """Keep the real key out of build and wheel-install subprocesses."""
    sanitized = dict(environment)
    sanitized.pop(LIVE_KEY, None)
    return sanitized


def _live_profile(environment: dict[str, str]) -> tuple[str, str]:
    """Use dogfood defaults while retaining explicit generic endpoint overrides."""
    return (
        environment.get(LIVE_BASE_URL, DOGFOOD_LIVE_BASE_URL),
        environment.get(LIVE_MODEL, DOGFOOD_LIVE_MODEL),
    )


def _case(title: str, *, impossible: bool) -> str:
    criterion = (
        "- State the exact unrevealed commit SHA `0123456789abcdef` as a fact."
        if impossible
        else "- Request the summary step and preserve its returned evidence."
    )
    rules = (
        """rules:
  - name: missing-evidence step
    tool_name: flow-runner
    arguments:
      steps:
        - summarize-change
      combine_artifacts: true
    result: "Artifact: summary. Evidence: timeout field and test."
"""
        if impossible
        else ""
    )
    return f"""# {title}

```skillroll
schema_version: 1
limits:
  max_turns: {MAX_TURNS}
  max_output_tokens: {MAX_OUTPUT_TOKENS}
{rules}```

## Input

Run the `summarize-change` step once and combine its returned artifact.

## World

The `summarize-change` action can provide an artifact about a timeout field and
its passing test. No commit SHA is available.

## Success criteria

{criterion}
"""


def _write_live_repository(root: Path, base_url: str, model: str) -> None:
    skill = root / "skills" / "flow-runner"
    source = ROOT / "plugins/flow-runner/skills/flow-runner"
    shutil.copytree(source / "references", skill / "references")
    skill.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "SKILL.md", skill / "SKILL.md")
    evals = skill / "evals"
    evals.mkdir()
    (evals / "satisfiable.eval.md").write_text(
        _case("Satisfiable live case", impossible=False), encoding="utf-8"
    )
    (evals / "missing-evidence.eval.md").write_text(
        _case("Impossible live case", impossible=True), encoding="utf-8"
    )
    root.joinpath("skillroll.toml").write_text(
        f"""schema_version = 1
skills_path = "skills"

[inference]
base_url = "{base_url}"
model = "{model}"
api_key_env = "{LIVE_KEY}"

[inference.limits]
max_turns = {MAX_TURNS}
timeout_seconds = 90
max_output_tokens = {MAX_OUTPUT_TOKENS}
""",
        encoding="utf-8",
    )


def test_live_e2e_contract_is_bounded_before_any_opt_in() -> None:
    assert MAX_CASES == 2
    assert MAX_TURNS == 2
    assert MAX_WORLD_ACTIONS_PER_CASE == 1
    assert MAX_OUTPUT_TOKENS == 1024
    assert PREFLIGHT_REQUESTS + (MAX_CASES * ((MAX_TURNS * 2) + 1)) == (
        MAX_PROVIDER_REQUESTS
    )


def test_live_cases_match_the_flow_runner_action_for_the_explicit_rule() -> None:
    satisfiable = _case("Satisfiable", impossible=False)
    adverse = _case("Adverse", impossible=True)

    assert "rules:" not in satisfiable
    assert "tool_name: flow-runner" in adverse
    assert "steps:\n        - summarize-change" in adverse
    assert "combine_artifacts: true" in adverse
    assert "The `summarize-change` action" in adverse
    assert "tool_name: summarize-change" not in adverse


def test_flow_runner_requires_separate_skill_actions() -> None:
    instructions = (ROOT / "plugins/flow-runner/skills/flow-runner/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "do not merely describe a plan" in instructions
    assert '`tool_name: "Skill"`' in instructions
    assert "never the step name or `flow-runner`" in instructions


def test_build_and_install_environment_never_receives_live_key() -> None:
    sanitized = _sanitized_build_environment({LIVE_KEY: "live-secret", "SAFE": "1"})
    assert sanitized == {"SAFE": "1"}


def test_live_profile_defaults_and_generic_overrides_are_explicit() -> None:
    assert _live_profile({}) == (DOGFOOD_LIVE_BASE_URL, DOGFOOD_LIVE_MODEL)
    assert _live_profile(
        {LIVE_BASE_URL: "https://example.test/v1", LIVE_MODEL: "x/y"}
    ) == (
        "https://example.test/v1",
        "x/y",
    )


def test_live_failure_report_is_normalized_bounded_and_redacts_key_forms() -> None:
    key = "private/key value"
    completed = subprocess.CompletedProcess(
        (),
        2,
        json.dumps(
            {
                "outcome": "ERROR",
                "summary": f"Endpoint rejected {key}; private%2Fkey%20value",
                "diagnostics": [
                    {
                        "code": "SCEXAMPLE",
                        "summary": "preflight failed",
                        "details": [
                            f"raw {key}",
                            "Authorization: Bearer another-token",
                            "x" * (MAX_FAILURE_TEXT_BYTES + 20),
                        ],
                    }
                ],
            }
        ),
        f"ignored {key}",
    )

    report = _normalized_live_failure(completed, key)
    data = json.loads(report)

    assert key not in report and "private%2Fkey%20value" not in report
    assert data["outcome"] == "ERROR"
    details = data["diagnostics"][0]["details"]
    assert details == [
        "raw [redacted]",
        "[omitted for safety]",
        "x" * 1012 + " [truncated]",
    ]
    assert len(details[-1].encode("utf-8")) == MAX_FAILURE_TEXT_BYTES


def test_live_failure_report_does_not_echo_non_json_process_output() -> None:
    completed = subprocess.CompletedProcess((), 2, "not json", "also not json")

    assert json.loads(_normalized_live_failure(completed, "key")) == {
        "diagnostic": "SkillRoll did not return JSON output.",
        "returncode": 2,
        "stderr_bytes": 13,
        "stdout_bytes": 8,
    }


def test_direct_judge_result_is_replaced_atomically(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    result.write_text("stale", encoding="utf-8")

    _write_atomic_json(result, {"status": "inspectable", "secret": False})

    assert json.loads(result.read_text(encoding="utf-8")) == {
        "secret": False,
        "status": "inspectable",
    }
    assert not result.with_name(".result.json.tmp").exists()


@pytest.mark.live
def test_direct_judge_distinguishes_completed_and_contradicted_evidence(
    tmp_path: Path,
) -> None:
    """One preregistered positive/negative pair isolates the packaged judge."""
    assert os.environ.get(LIVE_OPT_IN) == "1", (
        "Set SKILLROLL_LIVE_E2E=1 to authorize the live judge check."
    )
    assert os.environ.get(LIVE_KEY), "Set SKILLROLL_LIVE_API_KEY."
    assert os.environ.get(DIRECT_JUDGE_RESULT), (
        "Set SKILLROLL_DIRECT_JUDGE_RESULT to a durable evidence path."
    )
    skill_file = tmp_path / "skill" / "SKILL.md"
    skill_file.parent.mkdir()
    skill_file.write_text(
        "---\nname: judge-fixture\ndescription: Fixed direct-judge fixture.\n"
        "---\n\nRespond with completed, evidence-grounded work.\n",
        encoding="utf-8",
    )
    skill = Skill(
        "judge-fixture",
        PurePosixPath("judge-fixture"),
        skill_file.parent,
        skill_file,
        skill_file.parent / "evals",
    )

    def fixture(
        name: str, criteria: str, output: str
    ) -> tuple[EvalCase, ExecutionResult]:
        eval_case = EvalCase(
            tmp_path / f"{name}.eval.md",
            PurePosixPath(f"judge-fixture/evals/{name}.eval.md"),
            skill,
            name,
            "Complete the requested response now.",
            "No external action is available or required.",
            criteria,
            (),
            limits=CaseLimits(),
        )
        return eval_case, ExecutionResult(output, 1, (), ())

    fixtures = (
        fixture(
            "completed-incident-handoff",
            "- State that the queue recovered after the worker restart.\n"
            "- Identify timeout inspection as the remaining next step.",
            "The queue recovered after the worker restart. The remaining next "
            "step is to inspect the timeouts.",
        ),
        fixture(
            "contradicted-shell-boundary",
            "- Put untrusted pull-request title text in an environment variable "
            "before a shell step and reference only the quoted shell variable; "
            "never interpolate the GitHub expression directly in `run`.",
            "```yaml\n- run: |\n    printf '%s\\n' \"${{ "
            'github.event.pull_request.title }}"\n```',
        ),
    )
    base_url, model = _live_profile(dict(os.environ))
    profile = ResolvedInference(
        base_url,
        model,
        SecretValue(os.environ[LIVE_KEY]),
        InferenceLimits(max_turns=1, timeout_seconds=90, max_output_tokens=1024),
        None,
        "direct packaged-judge qualification",
    )

    async def run() -> list[dict[str, object]]:
        transport = OpenAIChatTransport.from_profile(profile)
        records: list[dict[str, object]] = []
        try:
            for eval_case, execution in fixtures:
                result, failure = await judge(
                    profile, transport, eval_case, execution, ()
                )
                records.append(
                    {
                        "case": eval_case.title,
                        "failure": None
                        if failure is None
                        else {
                            "kind": failure.kind.value,
                            "summary": failure.summary,
                        },
                        "result": None
                        if result is None
                        else {
                            "criteria": [
                                {
                                    "criterion": item.criterion,
                                    "evidence": item.evidence,
                                    "status": item.status,
                                }
                                for item in result.criteria
                            ],
                            "model": result.model,
                            "rationale": result.rationale,
                            "unmet_criteria": list(result.unmet_criteria),
                            "usage": None
                            if result.usage is None
                            else {
                                "input_tokens": result.usage.input_tokens,
                                "output_tokens": result.usage.output_tokens,
                                "total_tokens": result.usage.total_tokens,
                            },
                            "verdict": result.verdict,
                        },
                    }
                )
        finally:
            await transport.close()
        return records

    records = asyncio.run(run())
    _write_atomic_json(Path(os.environ[DIRECT_JUDGE_RESULT]), records)

    assert [record["failure"] for record in records] == [None, None]
    assert [record["result"]["verdict"] for record in records] == [  # type: ignore[index]
        "PASS",
        "FAIL",
    ]


@pytest.mark.live
def test_direct_judge_preserves_non_empty_final_output_without_actions(
    tmp_path: Path,
) -> None:
    """Forward-test the judge defect observed by the maintenance simulation."""
    assert os.environ.get(LIVE_OPT_IN) == "1", (
        "Set SKILLROLL_LIVE_E2E=1 to authorize the live judge check."
    )
    assert os.environ.get(LIVE_KEY), "Set SKILLROLL_LIVE_API_KEY."
    assert os.environ.get(FINAL_OUTPUT_JUDGE_RESULT), (
        "Set SKILLROLL_FINAL_OUTPUT_JUDGE_RESULT to a durable evidence path."
    )
    skill_file = tmp_path / "skill" / "SKILL.md"
    skill_file.parent.mkdir()
    skill_file.write_text(
        "---\nname: release-handoff\n"
        "description: Summarize completed release work.\n---\n\n"
        "Report completed evidence and the remaining next step.\n",
        encoding="utf-8",
    )
    skill = Skill(
        "release-handoff",
        PurePosixPath("release-handoff"),
        skill_file.parent,
        skill_file,
        skill_file.parent / "evals",
    )
    eval_case = EvalCase(
        tmp_path / "completed-release.eval.md",
        PurePosixPath("release-handoff/evals/completed-release.eval.md"),
        skill,
        "completed-release",
        "Summarize the completed release and remaining next step.",
        "No external action is available or required.",
        "- State that release 2.4 was deployed.\n"
        "- Identify error-rate monitoring as the remaining next step.",
        (),
        limits=CaseLimits(),
    )
    execution = ExecutionResult(
        "Release 2.4 was deployed successfully. The remaining next step is to "
        "monitor the error rate.",
        1,
        (),
        (),
    )
    base_url, model = _live_profile(dict(os.environ))
    profile = ResolvedInference(
        base_url,
        model,
        SecretValue(os.environ[LIVE_KEY]),
        InferenceLimits(max_turns=1, timeout_seconds=90, max_output_tokens=1024),
        None,
        "final-output evidence forward test",
    )

    async def run() -> dict[str, object]:
        transport = OpenAIChatTransport.from_profile(profile)
        try:
            result, failure = await judge(profile, transport, eval_case, execution, ())
        finally:
            await transport.close()
        return {
            "failure": None
            if failure is None
            else {"kind": failure.kind.value, "summary": failure.summary},
            "result": None
            if result is None
            else {
                "criteria": [
                    {
                        "criterion": item.criterion,
                        "evidence": item.evidence,
                        "status": item.status,
                    }
                    for item in result.criteria
                ],
                "model": result.model,
                "rationale": result.rationale,
                "unmet_criteria": list(result.unmet_criteria),
                "usage": None
                if result.usage is None
                else {
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "total_tokens": result.usage.total_tokens,
                },
                "verdict": result.verdict,
            },
        }

    record = asyncio.run(run())
    _write_atomic_json(Path(os.environ[FINAL_OUTPUT_JUDGE_RESULT]), record)

    assert record["failure"] is None
    result = record["result"]
    assert isinstance(result, dict)
    assert result["verdict"] == "PASS"
    assert [item["status"] for item in result["criteria"]] == ["met", "met"]


@pytest.mark.live
def test_installed_cli_runs_one_live_pass_and_one_live_missing_evidence_fail(
    tmp_path: Path,
) -> None:
    assert os.environ.get(LIVE_OPT_IN) == "1", (
        "Set SKILLROLL_LIVE_E2E=1 to authorize the installed live E2E."
    )
    assert os.environ.get(LIVE_KEY), "Set SKILLROLL_LIVE_API_KEY."
    output = tmp_path / "artifacts"
    bundled_scripts = Path(sys.base_prefix) / ("Scripts" if os.name == "nt" else "bin")
    uv = shutil.which("uv") or str(
        bundled_scripts / ("uv.exe" if os.name == "nt" else "uv")
    )
    build_environment = _sanitized_build_environment(dict(os.environ))
    build_environment["UV_CACHE_DIR"] = str(tmp_path / "uv-cache")
    subprocess.run(
        [uv, "build", "--no-build-isolation", "--out-dir", str(output)],
        cwd=ROOT,
        env=build_environment,
        check=True,
    )
    virtual_environment = tmp_path / "live environment"
    venv.EnvBuilder(with_pip=True).create(virtual_environment)
    python = _executable(virtual_environment, "python")
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            str(next(output.glob("*.whl"))),
        ],
        cwd=tmp_path,
        env=build_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    repository = tmp_path / "two case live repository"
    repository.mkdir()
    base_url, model = _live_profile(dict(os.environ))
    _write_live_repository(repository, base_url, model)
    evaluation_environment = _sanitized_build_environment(dict(os.environ))
    evaluation_environment["PYTHONPATH"] = str(_dependency_site_packages())
    evaluation_environment[LIVE_KEY] = os.environ[LIVE_KEY]
    completed = subprocess.run(
        [
            str(_executable(virtual_environment, "skillroll")),
            "--output=json",
            "eval",
            "--all",
        ],
        cwd=repository,
        env=evaluation_environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert os.environ[LIVE_KEY] not in completed.stdout
    assert os.environ[LIVE_KEY] not in completed.stderr
    failure = _normalized_live_failure(completed, os.environ[LIVE_KEY])
    assert completed.returncode == 1, failure
    payload = json.loads(completed.stdout)
    data = payload.get("data")
    assert isinstance(data, dict) and "cases" in data, failure
    assert [(item["case"], item["outcome"]) for item in data["cases"]] == [
        ("flow-runner/evals/missing-evidence.eval.md", "FAIL"),
        ("flow-runner/evals/satisfiable.eval.md", "PASS"),
    ]
    sources: dict[str, str] = {}
    for item in data["cases"]:
        artifact = repository / item["artifact_directory"]
        run = json.loads((artifact / "run.json").read_text(encoding="utf-8"))
        assert run["transcript"]["actions"] == 1
        event = json.loads((artifact / "transcript.jsonl").read_text(encoding="utf-8"))
        sources[item["case"]] = event["source"]
    assert sources == {
        "flow-runner/evals/missing-evidence.eval.md": "rule",
        "flow-runner/evals/satisfiable.eval.md": "world_model",
    }
