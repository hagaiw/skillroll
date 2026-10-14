"""Offline regressions for candidate release gate integration adapters."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import test_adoption_real_e2e as adoption
import test_phase7_claude_cli_e2e as claude

from skillroll import __version__


def test_supplied_release_wheel_does_not_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = tmp_path / "candidate.whl"
    wheel.touch()
    monkeypatch.setenv(adoption.RELEASE_WHEEL, str(wheel))
    monkeypatch.setattr(
        adoption.subprocess, "run", lambda *args, **kwargs: pytest.fail("build")
    )
    assert adoption._candidate_wheel(tmp_path) == wheel


@pytest.mark.parametrize(
    "kind", ["missing", "directory", "extension", "symlink", "relative"]
)
def test_supplied_release_wheel_rejects_invalid_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    wheel = tmp_path / "candidate.whl"
    if kind == "directory":
        wheel.mkdir()
    elif kind == "extension":
        wheel = tmp_path / "candidate.tar.gz"
        wheel.touch()
    elif kind == "symlink":
        target = tmp_path / "real.whl"
        target.touch()
        wheel.symlink_to(target)
    elif kind == "relative":
        wheel = Path("candidate.whl")
    monkeypatch.setenv(adoption.RELEASE_WHEEL, str(wheel))
    with pytest.raises(AssertionError):
        adoption._candidate_wheel(tmp_path)


def test_developer_adoption_still_builds_without_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(adoption.RELEASE_WHEEL, raising=False)
    monkeypatch.setenv(adoption.ADOPTION_KEY, "do-not-forward")

    def run(arguments: list[str], **kwargs: object) -> None:
        assert arguments[1:3] == ["build", "--out-dir"]
        assert adoption.ADOPTION_KEY not in kwargs["env"]
        assert kwargs["cwd"] == adoption.ROOT
        assert kwargs["timeout"] == 180
        artifacts = Path(arguments[3])
        artifacts.mkdir()
        (artifacts / "candidate.whl").touch()

    monkeypatch.setattr(adoption.subprocess, "run", run)
    assert adoption._candidate_wheel(tmp_path).name == "candidate.whl"


@pytest.mark.parametrize("problem", [None, "outside", "version"])
def test_installed_candidate_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str | None
) -> None:
    environment = tmp_path / "venv"
    origin = environment / "lib/site-packages/skillroll/__init__.py"
    if problem == "outside":
        origin = tmp_path / "source/skillroll/__init__.py"

    def run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert arguments[0] == str(adoption._python(environment))
        assert kwargs["cwd"] == tmp_path
        assert kwargs["timeout"] == 90
        return subprocess.CompletedProcess(
            arguments,
            0,
            json.dumps(
                {
                    "path": str(origin),
                    "version": "wrong" if problem == "version" else __version__,
                }
            ),
        )

    monkeypatch.setattr(
        adoption, "_dependency_site_packages", lambda: tmp_path / "dependencies"
    )
    monkeypatch.setattr(adoption.subprocess, "run", run)
    if problem:
        with pytest.raises(AssertionError):
            adoption._verify_installed_candidate(environment, tmp_path)
    else:
        adoption._verify_installed_candidate(environment, tmp_path)


def test_clean_environment_installs_exact_supplied_wheel_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wheel = tmp_path / "candidate.whl"
    wheel.touch()
    monkeypatch.setenv(adoption.RELEASE_WHEEL, str(wheel))
    monkeypatch.setattr(
        adoption, "_dependency_site_packages", lambda: tmp_path / "dependencies"
    )
    created: list[Path] = []
    verified: list[tuple[Path, Path]] = []
    monkeypatch.setattr(
        adoption.venv.EnvBuilder, "create", lambda self, path: created.append(path)
    )
    monkeypatch.setattr(
        adoption,
        "_verify_installed_candidate",
        lambda env, cwd: verified.append((env, cwd)),
    )

    def run(arguments: list[str], **kwargs: object) -> None:
        assert "PYTHONPATH" not in kwargs["env"]
        assert adoption.ADOPTION_KEY not in kwargs["env"]
        assert arguments[1:] == ["-m", "pip", "install", "--no-deps", str(wheel)]
        assert kwargs["cwd"] == tmp_path
        assert kwargs["timeout"] == 180

    monkeypatch.setattr(adoption.subprocess, "run", run)
    environment = adoption._build_environment(tmp_path)
    assert created == [environment]
    assert verified == [(environment, tmp_path)]


@pytest.mark.parametrize("problem", [None, "wrong_commit", "wrong_version", "untagged"])
def test_claude_gate_uses_candidate_version_and_disposable_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str | None
) -> None:
    monkeypatch.setattr(claude.shutil, "which", lambda command: "/fake/claude")
    calls: list[tuple[str, ...]] = []
    candidate_commit = "a" * 40
    dependency_version = f"{__version__}-{candidate_commit[:12]}"
    if problem == "wrong_commit":
        dependency_version = f"{__version__}-bbbbbbbbbbbb"
    elif problem == "wrong_version":
        dependency_version = f"{__version__}.post1-{candidate_commit[:12]}"
    elif problem == "untagged":
        dependency_version = __version__

    def run(
        arguments: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        assert kwargs["cwd"] == tmp_path / "candidate repository"
        assert kwargs["timeout"] == 90
        output = ""
        if arguments[-2:] == ("rev-parse", "HEAD"):
            output = candidate_commit + "\n"
        if arguments[0] == "claude":
            env = kwargs["env"]
            assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "claude config")
            assert env["CLAUDE_CODE_PLUGIN_CACHE_DIR"] == str(tmp_path / "plugin cache")
            if arguments[2] == "install":
                output = "Installation completed with changed CLI wording."
            elif arguments[2] == "list":
                output = json.dumps(
                    [
                        {
                            "id": name + "@skillroll",
                            "version": version,
                            "enabled": True,
                            "installPath": str(tmp_path / name),
                        }
                        for name, version in [
                            ("change-review-flow", __version__),
                            ("flow-runner", dependency_version),
                        ]
                    ]
                )
        return subprocess.CompletedProcess(arguments, 0, output)

    monkeypatch.setattr(claude.subprocess, "run", run)
    if problem:
        with pytest.raises(AssertionError):
            claude.test_official_cli_installs_the_exact_tagged_dependency(tmp_path)
    else:
        claude.test_official_cli_installs_the_exact_tagged_dependency(tmp_path)
    assert any(args[-2:] == ("tag", f"flow-runner--v{__version__}") for args in calls)
    assert len([args for args in calls if args[0] == "claude"]) == 3
