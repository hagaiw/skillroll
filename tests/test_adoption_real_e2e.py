"""Real-inference adoption journey for an existing marketplace repository."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest
from conftest import ROOT

ADOPTION_OPT_IN = "SKILLROLL_ADOPTION_E2E"
ADOPTION_KEY = "SKILLROLL_ADOPTION_API_KEY"
ADOPTION_BASE_URL = "SKILLROLL_ADOPTION_BASE_URL"
ADOPTION_MODEL = "SKILLROLL_ADOPTION_MODEL"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-4.1-nano"
MAX_CASES_PER_RUN = 1
MAX_TURNS = 2
MAX_OUTPUT_TOKENS = 1024
MAX_TIMEOUT_SECONDS = 90


def _python(environment: Path) -> Path:
    return environment / ("Scripts" if os.name == "nt" else "bin") / "python"


def _dependency_site_packages() -> Path:
    candidates = tuple((ROOT / ".venv").glob("**/site-packages"))
    assert candidates
    return candidates[0]


def _subprocess_environment(
    environment: Path, *, key: str | None = None
) -> dict[str, str]:
    values = dict(os.environ)
    values["PYTHONPATH"] = str(_dependency_site_packages())
    values.pop(ADOPTION_KEY, None)
    if key is not None:
        values[ADOPTION_KEY] = key
    return values


def _run_cli(
    environment: Path,
    repository: Path,
    *arguments: str,
    key: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_python(environment)), "-m", "skillroll", "--output=json", *arguments],
        cwd=repository,
        env=_subprocess_environment(environment, key=key),
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


def _run_action(
    environment: Path,
    repository: Path,
    *arguments: str,
    key: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    output = repository / ".skillroll-action-output"
    summary = repository / ".skillroll-action-summary.md"
    values = _subprocess_environment(environment, key=key)
    values["GITHUB_OUTPUT"] = str(output)
    values["GITHUB_STEP_SUMMARY"] = str(summary)
    completed = subprocess.run(
        [
            str(_python(environment)),
            "-m",
            "skillroll.github_action",
            *arguments,
        ],
        cwd=repository,
        env=values,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    outputs = dict(
        line.split("=", 1)
        for line in output.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    return completed, outputs


def _json_output(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith("{"):
            value = json.loads(line)
            assert isinstance(value, dict)
            return value
    raise AssertionError(f"No JSON result in output: {completed.stdout!r}")


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _write_eval(path: Path, *, impossible: bool) -> None:
    criterion = (
        "- Include the exact phrase `THIS PHRASE MUST NOT APPEAR` in the summary."
        if impossible
        else "- Include the incident identifier, service, status, and evidence."
    )
    assertions = (
        "  - final_output_contains: THIS PHRASE MUST NOT APPEAR\n" if impossible else ""
    )
    assertion_block = "assertions:\n" + assertions if assertions else ""
    path.write_text(
        f"""# Incident summary case

```skillroll
schema_version: 1
limits:
  max_turns: {MAX_TURNS}
  timeout_seconds: {MAX_TIMEOUT_SECONDS}
  max_output_tokens: {MAX_OUTPUT_TOKENS}
rules:
  - name: incident artifact
    tool_name: fetch-incident
    arguments:
      incident_id: INC-42
    result: >-
      incident_id: INC-42; service: payments; status: degraded; evidence:
      timeout rate above threshold
{assertion_block}
```

## Input

Summarize incident INC-42.

## World

The `fetch-incident` action returns the incident artifact described by the
rule. No other incident facts are available.

## Success criteria

{criterion}
""",
        encoding="utf-8",
    )


def _create_git_repository(repository: Path) -> None:
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "SkillRoll adoption test")
    _git(repository, "config", "user.email", "adoption-test@invalid.example")
    shutil.copytree(
        ROOT / "tests/fixtures/adopter-marketplace", repository, dirs_exist_ok=True
    )


def _build_environment(tmp_path: Path) -> Path:
    artifacts = tmp_path / "build artifacts"
    uv = shutil.which("uv") or str(Path(sys.base_prefix) / "bin" / "uv")
    build_environment = dict(os.environ)
    build_environment.pop(ADOPTION_KEY, None)
    build_environment["UV_CACHE_DIR"] = str(tmp_path / "uv cache")
    subprocess.run(
        [uv, "build", "--out-dir", str(artifacts)],
        cwd=ROOT,
        env=build_environment,
        capture_output=True,
        text=True,
        check=True,
    )
    environment = tmp_path / "clean installed environment"
    venv.EnvBuilder(with_pip=True).create(environment)
    subprocess.run(
        [
            str(_python(environment)),
            "-m",
            "pip",
            "install",
            "--no-deps",
            str(next(artifacts.glob("*.whl"))),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return environment


def test_adoption_contract_is_explicitly_bounded() -> None:
    assert MAX_CASES_PER_RUN == 1
    assert MAX_TURNS == 2
    assert MAX_OUTPUT_TOKENS == 1024
    assert MAX_TIMEOUT_SECONDS == 90


@pytest.mark.live
def test_existing_marketplace_user_journey_with_real_inference(
    tmp_path: Path,
) -> None:
    assert os.environ.get(ADOPTION_OPT_IN) == "1", (
        "Set SKILLROLL_ADOPTION_E2E=1 to authorize the live adoption check."
    )
    assert os.environ.get(ADOPTION_KEY), (
        "Set SKILLROLL_ADOPTION_API_KEY for the live adoption check."
    )
    key = os.environ[ADOPTION_KEY]
    repository = tmp_path / "existing marketplace with spaces"
    _create_git_repository(repository)
    base_commit = _commit(repository, "existing marketplace before SkillRoll")
    environment = _build_environment(tmp_path)

    initialized = _run_cli(
        environment,
        repository,
        "init",
        "--repo",
        str(repository),
        "--skills-path",
        "plugins",
        "--base-url",
        os.environ.get(ADOPTION_BASE_URL, DEFAULT_BASE_URL),
        "--model",
        os.environ.get(ADOPTION_MODEL, DEFAULT_MODEL),
        "--api-key-env",
        ADOPTION_KEY,
        "--github-workflow",
        "--action-ref",
        "hagaiw/skillroll@main",
        key=key,
    )
    assert initialized.returncode == 0, initialized.stdout
    assert (repository / ".claude-plugin/marketplace.json").is_file()
    assert "hagaiw/skillroll@main" in (
        repository / ".github/workflows/skillroll.yml"
    ).read_text(encoding="utf-8")

    config = repository / "skillroll.toml"
    config.write_text(
        config.read_text(encoding="utf-8")
        + '\n[guards]\ndisabled = ["SCG2001"]\n'
        + f"\n[inference.limits]\nmax_turns = {MAX_TURNS}\n"
        + f"timeout_seconds = {MAX_TIMEOUT_SECONDS}\n"
        + f"max_output_tokens = {MAX_OUTPUT_TOKENS}\n",
        encoding="utf-8",
    )
    setup_commit = _commit(repository, "add SkillRoll setup and workflow")

    eval_path = (
        repository
        / "plugins/incident-tools/skills/incident-summary/evals/incident.eval.md"
    )
    eval_path.parent.mkdir()
    _write_eval(eval_path, impossible=False)
    local = _run_cli(environment, repository, "eval", "--all", key=key)
    assert local.returncode == 0, local.stdout
    local_data = _json_output(local)
    assert local_data["outcome"] == "PASS"
    assert local_data["data"]["cases"][0]["outcome"] == "PASS"
    eval_commit = _commit(repository, "add and pass the first SkillRoll eval")

    _write_eval(eval_path, impossible=True)
    failing_commit = _commit(repository, "make the eval criterion fail")
    validation, validation_outputs = _run_action(
        environment,
        repository,
        "--mode",
        "validate",
        "--scope",
        "changed",
        "--base-sha",
        eval_commit,
        "--head-sha",
        failing_commit,
    )
    assert validation.returncode == 0, validation.stdout
    assert validation_outputs["selected-case-count"] == "1"

    failing, failing_outputs = _run_action(
        environment,
        repository,
        "--mode",
        "eval",
        "--scope",
        "changed",
        "--base-sha",
        eval_commit,
        "--head-sha",
        failing_commit,
        "--upload-artifact",
        "false",
        key=key,
    )
    assert failing.returncode == 1, failing.stdout
    failing_data = _json_output(failing)
    assert failing_data["outcome"] == "FAIL"
    assert failing_data["data"]["cases"][0]["outcome"] == "FAIL"
    assert failing_outputs["selected-case-count"] == "1"

    _write_eval(eval_path, impossible=False)
    fixed_commit = _commit(repository, "fix the eval criterion")
    fixed, fixed_outputs = _run_action(
        environment,
        repository,
        "--mode",
        "eval",
        "--scope",
        "changed",
        "--base-sha",
        failing_commit,
        "--head-sha",
        fixed_commit,
        key=key,
    )
    assert fixed.returncode == 0, fixed.stdout
    fixed_data = _json_output(fixed)
    assert fixed_data["outcome"] == "PASS"
    assert fixed_data["data"]["cases"][0]["outcome"] == "PASS"
    assert fixed_outputs["selected-case-count"] == "1"
    assert base_commit != setup_commit != eval_commit != failing_commit != fixed_commit
