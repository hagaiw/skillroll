"""The only Phase-3 writer for private, redacted run evidence."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from skillroll.artifacts.records import (
    RunFacts,
    report_bytes,
    run_bytes,
    transcript_bytes,
)
from skillroll.inference.profile import SecretRedactor
from skillroll.world.session import WorldEvent


class ArtifactError(Exception):
    """Evidence storage failed before a complete trustworthy record existed."""


def utc_now() -> str:
    """Return an injectable RFC3339 UTC timestamp."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _descriptor_safety_available() -> bool:
    """Whether this platform supports the no-follow descriptor operations we need."""
    return (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        # ``replace`` has the same dir-fd parameters as ``rename`` but is not
        # consistently listed in ``supports_dir_fd`` on macOS.
        and os.rename in os.supports_dir_fd
    )


class ArtifactStore:
    """Create one exclusive run directory and atomically replace each evidence file."""

    def __init__(
        self,
        repository_root: Path,
        redactor: SecretRedactor,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self._root = repository_root.resolve()
        self._redactor = redactor
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._clock = clock

    def create(self) -> tuple[str, Path, str]:
        """Reserve a safe exclusive run directory, retrying only ID collisions."""
        if not self._root.is_dir() or self._root.is_symlink():
            raise ArtifactError(
                "SkillRoll cannot save evidence because the selected repository "
                "folder is unsafe."
            )
        base = self._root / ".skillroll"
        runs = base / "runs"
        try:
            if base.exists() and (base.is_symlink() or not base.is_dir()):
                raise ArtifactError(
                    "SkillRoll cannot save evidence because .skillroll is not an "
                    "ordinary folder."
                )
            base.mkdir(exist_ok=True)
            if runs.exists() and (runs.is_symlink() or not runs.is_dir()):
                raise ArtifactError(
                    "SkillRoll cannot save evidence because .skillroll/runs is "
                    "not an ordinary folder."
                )
            runs.mkdir(exist_ok=True)
            for _ in range(3):
                run_id = f"run-{self._id_factory()}"
                destination = runs / run_id
                try:
                    destination.mkdir(mode=0o700)
                except FileExistsError:
                    continue
                return run_id, destination, self._clock()
        except OSError as error:
            raise ArtifactError(
                "SkillRoll could not create its private run-evidence folder."
            ) from error
        raise ArtifactError(
            "SkillRoll could not reserve a unique run-evidence directory."
        )

    def _safe(self, value: bytes) -> bytes:
        text = value.decode("utf-8")
        clean = self._redactor.redact(text)
        secret = self._redactor.secret.reveal()
        if secret and (secret in clean or quote(secret, safe="") in clean):
            raise ArtifactError(
                "SkillRoll refused to write evidence containing the configured API key."
            )
        return clean.encode("utf-8")

    def _expected_directory(self, directory: Path) -> Path:
        """Accept exactly the run directory that this store created under its root."""
        expected = self._root / ".skillroll" / "runs" / directory.name
        if directory != expected or not directory.name.startswith("run-"):
            raise ArtifactError(
                "SkillRoll refused to write evidence outside this repository's "
                ".skillroll/runs folder."
            )
        return expected

    def _open_run_directory(self, directory: Path) -> int:
        """Open an expected POSIX run directory through no-follow handles."""
        self._expected_directory(directory)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        directory_flag = getattr(os, "O_DIRECTORY", 0)
        flags = os.O_RDONLY | directory_flag | nofollow
        handles: list[int] = []
        try:
            handles.append(os.open(self._root, flags))
            handles.append(os.open(".skillroll", flags, dir_fd=handles[-1]))
            handles.append(os.open("runs", flags, dir_fd=handles[-1]))
            handles.append(os.open(directory.name, flags, dir_fd=handles[-1]))
        except OSError as error:
            for handle in reversed(handles):
                os.close(handle)
            raise ArtifactError(
                "SkillRoll could not safely reopen this run-evidence folder. "
                "It may have changed since the evaluation started; rerun the "
                "evaluation."
            ) from error
        for handle in handles[:-1]:
            os.close(handle)
        return handles[-1]

    def _checked_fallback_directory(self, directory: Path) -> Path:
        """Check every fallback path component without following an observed link."""
        expected = self._expected_directory(directory)
        for component in (
            self._root,
            self._root / ".skillroll",
            self._root / ".skillroll" / "runs",
            expected,
        ):
            try:
                mode = component.lstat().st_mode
            except OSError as error:
                raise ArtifactError(
                    "SkillRoll could not safely reopen this run-evidence folder. "
                    "It may have changed since the evaluation started; rerun the "
                    "evaluation."
                ) from error
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise ArtifactError(
                    "SkillRoll refused this run-evidence folder because one of "
                    "its folders changed or is a link. Rerun the evaluation."
                )
        return expected

    def _write(self, directory_fd: int, name: str, value: bytes) -> None:
        """Atomically replace one evidence file through an already-safe directory FD."""
        temporary: str | None = None
        try:
            for _ in range(3):
                candidate = f".{name}.{uuid.uuid4().hex}.tmp"
                try:
                    file_fd = os.open(
                        candidate,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_NOFOLLOW", 0),
                        0o600,
                        dir_fd=directory_fd,
                    )
                except FileExistsError:
                    continue
                temporary = candidate
                try:
                    remaining = memoryview(value)
                    while remaining:
                        written = os.write(file_fd, remaining)
                        remaining = remaining[written:]
                    os.fsync(file_fd)
                finally:
                    os.close(file_fd)
                os.replace(
                    temporary,
                    name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
                os.fsync(directory_fd)
                return
            raise FileExistsError
        except OSError as error:
            if temporary is not None:
                with suppress(OSError):
                    os.unlink(temporary, dir_fd=directory_fd)
            raise ArtifactError(
                f"SkillRoll could not atomically write {name} in the "
                "run-evidence folder."
            ) from error

    def _write_fallback(
        self,
        directory: Path,
        name: str,
        value: bytes,
        *,
        trusted_directory: bool = False,
    ) -> None:
        """Write one file on platforms without descriptor-relative operations.

        The fallback refuses every observed symlink and rechecks before replace.
        It cannot make the stronger POSIX guarantee against a malicious process
        swapping a parent directory in the tiny interval after that check.
        """
        temporary: Path | None = None
        try:
            for _ in range(3):
                candidate = directory / f".{name}.{uuid.uuid4().hex}.tmp"
                try:
                    candidate.lstat()
                except FileNotFoundError:
                    pass
                except OSError as error:
                    raise ArtifactError(
                        "SkillRoll could not safely inspect a temporary evidence file."
                    ) from error
                else:
                    continue
                try:
                    file_fd = os.open(
                        candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                    )
                except FileExistsError:
                    continue
                temporary = candidate
                try:
                    remaining = memoryview(value)
                    while remaining:
                        written = os.write(file_fd, remaining)
                        remaining = remaining[written:]
                    os.fsync(file_fd)
                finally:
                    os.close(file_fd)
                checked = (
                    directory
                    if trusted_directory
                    else self._checked_fallback_directory(directory)
                )
                try:
                    mode = temporary.lstat().st_mode
                except OSError as error:
                    raise ArtifactError(
                        "SkillRoll could not safely recheck a temporary evidence file."
                    ) from error
                if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                    raise ArtifactError(
                        "SkillRoll refused a changed temporary evidence file. "
                        "Rerun the evaluation."
                    )
                os.replace(temporary, checked / name)
                return
            raise FileExistsError
        except OSError as error:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink()
            raise ArtifactError(
                f"SkillRoll could not atomically write {name} in the "
                "run-evidence folder."
            ) from error

    def _check_log_name(self, name: str) -> str | None:
        """Accept only the documented check-log namespace below a run directory."""
        parts = name.split("/")
        if len(parts) != 2 or parts[0] != "checks":
            return None
        leaf = parts[1]
        if not leaf.endswith(("-stdout.log", "-stderr.log")):
            return None
        ordinal = leaf.partition("-")[0]
        return leaf if ordinal.isdecimal() else None

    def _open_check_logs(self, directory_fd: int) -> int:
        """Open or create the one fixed child directory for command logs."""
        try:
            os.mkdir("checks", 0o700, dir_fd=directory_fd)
        except FileExistsError:
            pass
        except OSError as error:
            raise ArtifactError(
                "SkillRoll could not create the repository-check log folder."
            ) from error
        try:
            return os.open(
                "checks",
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
        except OSError as error:
            raise ArtifactError(
                "SkillRoll could not safely open the repository-check log folder."
            ) from error

    def _fallback_check_logs(self, directory: Path) -> Path:
        """Create the fixed check-log folder after the fallback safety checks."""
        checked = self._checked_fallback_directory(directory)
        logs = checked / "checks"
        try:
            logs.mkdir(mode=0o700, exist_ok=True)
            mode = logs.lstat().st_mode
        except OSError as error:
            raise ArtifactError(
                "SkillRoll could not safely create the repository-check log folder."
            ) from error
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ArtifactError(
                "SkillRoll refused the repository-check log folder because it is not "
                "an ordinary folder."
            )
        return logs

    def write(
        self,
        directory: Path,
        facts: RunFacts,
        manifest: bytes,
        events: tuple[WorldEvent, ...],
    ) -> None:
        """Write all version-one files only after their complete render is available."""
        digest = hashlib.sha256(manifest).hexdigest()
        if digest != facts.input_manifest_sha256:
            raise ArtifactError(
                "SkillRoll refused inconsistent input-manifest evidence."
            )
        values = (
            ("inputs.json", self._safe(manifest)),
            ("transcript.jsonl", self._safe(transcript_bytes(events))),
            ("run.json", self._safe(run_bytes(facts))),
            ("report.md", self._safe(report_bytes(facts))),
        )
        if _descriptor_safety_available():
            directory_fd = self._open_run_directory(directory)
            try:
                for name, value in values:
                    self._write(directory_fd, name, value)
            finally:
                os.close(directory_fd)
        else:
            checked = self._checked_fallback_directory(directory)
            for name, value in values:
                self._write_fallback(checked, name, value)

    def append(self, directory: Path, values: tuple[tuple[str, bytes], ...]) -> None:
        """Atomically append named final evidence to an already-created run folder."""
        if any(
            not name
            or "\\" in name
            or name in {".", ".."}
            or ("/" in name and self._check_log_name(name) is None)
            for name, _ in values
        ):
            raise ArtifactError("SkillRoll refused an unsafe evidence file name.")
        safe_values = tuple((name, self._safe(value)) for name, value in values)
        if _descriptor_safety_available():
            directory_fd = self._open_run_directory(directory)
            try:
                for name, value in safe_values:
                    leaf = self._check_log_name(name)
                    if leaf is None:
                        self._write(directory_fd, name, value)
                    else:
                        logs_fd = self._open_check_logs(directory_fd)
                        try:
                            self._write(logs_fd, leaf, value)
                        finally:
                            os.close(logs_fd)
            finally:
                os.close(directory_fd)
        else:
            checked = self._checked_fallback_directory(directory)
            for name, value in safe_values:
                leaf = self._check_log_name(name)
                self._write_fallback(
                    checked if leaf is None else self._fallback_check_logs(directory),
                    name if leaf is None else leaf,
                    value,
                    trusted_directory=leaf is not None,
                )

    def create_experiment(self) -> tuple[str, Path]:
        """Reserve a safe parent folder for an authoring experiment."""
        if not self._root.is_dir() or self._root.is_symlink():
            raise ArtifactError(
                "SkillRoll cannot save experiment evidence because the selected "
                "repository folder is unsafe."
            )
        base = self._root / ".skillroll"
        experiments = base / "experiments"
        try:
            if base.exists() and (base.is_symlink() or not base.is_dir()):
                raise ArtifactError(
                    "SkillRoll cannot save experiment evidence because .skillroll "
                    "is not an ordinary folder."
                )
            base.mkdir(exist_ok=True)
            if experiments.exists() and (
                experiments.is_symlink() or not experiments.is_dir()
            ):
                raise ArtifactError(
                    "SkillRoll cannot save experiment evidence because "
                    ".skillroll/experiments is not an ordinary folder."
                )
            experiments.mkdir(exist_ok=True)
            for _ in range(3):
                experiment_id = f"experiment-{self._id_factory()}"
                destination = experiments / experiment_id
                try:
                    destination.mkdir(mode=0o700)
                except FileExistsError:
                    continue
                return experiment_id, destination
        except OSError as error:
            raise ArtifactError(
                "SkillRoll could not create its private experiment-evidence folder."
            ) from error
        raise ArtifactError(
            "SkillRoll could not reserve a unique experiment-evidence directory."
        )

    def write_experiment(self, directory: Path, result: bytes, report: bytes) -> None:
        """Write the two redacted files in a reserved experiment folder."""
        expected = self._root / ".skillroll" / "experiments" / directory.name
        if directory != expected or not directory.name.startswith("experiment-"):
            raise ArtifactError(
                "SkillRoll refused to write experiment evidence outside its "
                "private experiments folder."
            )
        try:
            mode = directory.lstat().st_mode
        except OSError as error:
            raise ArtifactError(
                "SkillRoll could not safely reopen the experiment-evidence folder."
            ) from error
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ArtifactError(
                "SkillRoll refused the experiment-evidence folder because it is "
                "not an ordinary folder."
            )
        for name, value in (("result.json", result), ("report.md", report)):
            clean = self._safe(value)
            temporary = directory / f".{name}.{uuid.uuid4().hex}.tmp"
            try:
                with temporary.open("xb") as opened:
                    opened.write(clean)
                    opened.flush()
                    os.fsync(opened.fileno())
                if temporary.is_symlink() or not temporary.is_file():
                    raise ArtifactError(
                        "SkillRoll refused a changed experiment evidence file."
                    )
                os.replace(temporary, directory / name)
            except ArtifactError:
                with suppress(OSError):
                    temporary.unlink()
                raise
            except OSError as error:
                with suppress(OSError):
                    temporary.unlink()
                raise ArtifactError(
                    f"SkillRoll could not atomically write {name} in the "
                    "experiment-evidence folder."
                ) from error
