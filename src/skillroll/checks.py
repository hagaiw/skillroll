"""Explicitly permitted repository-check execution with useful safety language."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from skillroll.inference.profile import SecretRedactor
from skillroll.models import DeclaredCheck, EvalCase, SkillRollConfig

MAX_STREAM_BYTES = 64 * 1024
COMMAND_TIMEOUT_SECONDS = 120
_TRUNCATED = "\n[SkillRoll truncated this stream after 64 KiB.]\n"

type CheckOutcome = Literal["PASS", "FAIL", "SKIPPED", "ERROR"]


@dataclass(frozen=True, slots=True)
class CheckRequest:
    case: EvalCase
    check: DeclaredCheck
    mode: Literal["validate", "eval"]
    repository_root: Path
    run_directory: Path | None


@dataclass(frozen=True, slots=True)
class CheckResult:
    check: DeclaredCheck
    outcome: CheckOutcome
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float | None
    detail: str | None = None
    started: bool = False


class CheckRunner(Protocol):
    async def run(
        self, request: CheckRequest, environment: Mapping[str, str]
    ) -> CheckResult: ...


def check_environment(
    config: SkillRollConfig, request: CheckRequest, environment: Mapping[str, str]
) -> dict[str, str]:
    """Create documented stable variables without ever forwarding the API key name."""
    values = dict(environment)
    if config.inference is not None:
        values.pop(config.inference.api_key_env, None)
    values.update(
        {
            "SKILLROLL_MODE": request.mode,
            "SKILLROLL_REPOSITORY_ROOT": str(request.repository_root.resolve()),
            "SKILLROLL_SKILL": request.case.skill.identity.as_posix(),
            "SKILLROLL_CASE": request.case.identity.as_posix(),
            "SKILLROLL_EVAL_FILE": str(request.case.path.resolve()),
        }
    )
    if request.run_directory is not None:
        values.update(
            {
                "SKILLROLL_RUN_DIR": str(request.run_directory),
                "SKILLROLL_RUN_JSON": str(request.run_directory / "run.json"),
                "SKILLROLL_INPUTS_JSON": str(request.run_directory / "inputs.json"),
                "SKILLROLL_TRANSCRIPT_JSONL": str(
                    request.run_directory / "transcript.jsonl"
                ),
                "SKILLROLL_EXECUTION_JSON": str(
                    request.run_directory / "execution.json"
                ),
                "SKILLROLL_JUDGE_JSON": str(request.run_directory / "judge.json"),
            }
        )
    return values


def skipped_check(request: CheckRequest) -> CheckResult:
    """Record a skipped check without starting a process."""
    action = (
        f"skillroll {request.mode} --case "
        f"{request.case.identity.as_posix()} --run-commands"
    )
    detail = (
        f"Skill “{request.case.skill.name}”, check “{request.check.name}” from "
        f"{request.case.identity.as_posix()} was not run.\n\n"
        "It would run this command in this repository:\n"
        f"{request.check.command}\n\n"
        "SkillRoll paused because repository commands can change files, use the "
        "network, or access local accounts. The model key is removed, but other "
        "files and credentials may still be available.\n\n"
        "After you review and trust this repository, run:\n"
        f"{action}"
    )
    return CheckResult(request.check, "SKIPPED", None, "", "", None, detail)


def redact_check_result(result: CheckResult, redactor: SecretRedactor) -> CheckResult:
    """Remove the configured inference credential before check facts escape.

    Repository commands deliberately receive normal local environment variables,
    except for the configured inference key.  A command can still independently
    discover or print that key, so every captured stream and detail is redacted
    before it becomes an artifact or a diagnostic.
    """
    return CheckResult(
        result.check,
        result.outcome,
        result.exit_code,
        redactor.redact(result.stdout),
        redactor.redact(result.stderr),
        result.duration_seconds,
        None if result.detail is None else redactor.redact(result.detail),
        result.started,
    )


async def _bounded_stream(stream: asyncio.StreamReader | None) -> str:
    if stream is None:
        return ""
    chunks: list[bytes] = []
    remaining = MAX_STREAM_BYTES
    truncated = False
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            break
        accepted = chunk[:remaining]
        chunks.append(accepted)
        remaining -= len(accepted)
        if len(chunk) > len(accepted):
            truncated = True
    text = b"".join(chunks).decode("utf-8", errors="replace")
    return text + (_TRUNCATED if truncated else "")


class HostCheckRunner:
    """The sole normal subprocess adapter; it intentionally is not a sandbox."""

    def __init__(self, timeout_seconds: int = COMMAND_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    async def _collect_after_stop(
        self,
        process: asyncio.subprocess.Process,
        stdout_task: asyncio.Task[str],
        stderr_task: asyncio.Task[str],
    ) -> tuple[str, str, str | None]:
        """Stop a process and collect its streams without an unbounded cleanup wait."""
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        except OSError as error:
            return "", "", f"SkillRoll could not stop the repository check: {error}."
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            except OSError as error:
                return (
                    "",
                    "",
                    f"SkillRoll could not stop the repository check: {error}.",
                )
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                return (
                    "",
                    "",
                    "SkillRoll could not stop the repository check within 5 seconds.",
                )
        try:
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        except Exception as error:
            return (
                "",
                "",
                f"SkillRoll could not collect repository-check output: {error}.",
            )
        return stdout, stderr, None

    async def run(
        self, request: CheckRequest, environment: Mapping[str, str]
    ) -> CheckResult:
        started = time.monotonic()
        try:
            process = await asyncio.create_subprocess_shell(
                request.check.command,
                cwd=request.repository_root,
                env=dict(environment),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except asyncio.CancelledError:
            raise
        except OSError as error:
            return CheckResult(
                request.check,
                "ERROR",
                None,
                "",
                "",
                None,
                f"SkillRoll could not start this repository check: {error}.",
            )
        stdout_task = asyncio.create_task(_bounded_stream(process.stdout))
        stderr_task = asyncio.create_task(_bounded_stream(process.stderr))
        try:
            await asyncio.wait_for(process.wait(), self._timeout_seconds)
        except TimeoutError:
            stdout, stderr, cleanup_error = await self._collect_after_stop(
                process, stdout_task, stderr_task
            )
            return CheckResult(
                request.check,
                "ERROR",
                None,
                stdout,
                stderr,
                time.monotonic() - started,
                cleanup_error
                or "The repository check did not finish within "
                f"{self._timeout_seconds} seconds.",
                True,
            )
        except asyncio.CancelledError:
            await self._collect_after_stop(process, stdout_task, stderr_task)
            raise
        try:
            stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        except Exception as error:
            return CheckResult(
                request.check,
                "ERROR",
                process.returncode,
                "",
                "",
                time.monotonic() - started,
                f"SkillRoll could not collect repository-check output: {error}.",
                True,
            )
        duration = time.monotonic() - started
        outcome: CheckOutcome = "PASS" if process.returncode == 0 else "FAIL"
        return CheckResult(
            request.check,
            outcome,
            process.returncode,
            stdout,
            stderr,
            duration,
            None,
            True,
        )
