from __future__ import annotations

import json
import os
import shutil
import site
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

from conftest import ROOT


def _executable(environment: Path, name: str) -> Path:
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    return scripts / f"{name}{suffix}"


def _case_source(title: str) -> str:
    return f"""# {title}

```skillroll
schema_version: 1
```

## Input

Explain this small request.

## World

The external service answers successfully.

## Success criteria

- Give the requested explanation.
"""


def _dependency_site_packages() -> Path:
    """Use test-installed dependencies without exposing checkout source code."""
    candidates = tuple(Path(candidate) for candidate in site.getsitepackages())
    dependency_root = next(
        (candidate for candidate in candidates if (candidate / "markdown_it").is_dir()),
        None,
    )
    assert dependency_root is not None
    return dependency_root


def _uv_build_environment(tmp_path: Path) -> dict[str, str]:
    """Keep uv builds on the running Python and inside the test workspace."""
    variables = os.environ.copy()
    variables["UV_CACHE_DIR"] = str(tmp_path / "uv-cache")
    variables["UV_PYTHON"] = sys.executable
    variables["UV_NO_MANAGED_PYTHON"] = "1"
    variables["UV_PYTHON_INSTALL_DIR"] = str(tmp_path / "uv-python")
    return variables


def _run_installed(
    environment: Path, repository: Path, *arguments: str
) -> subprocess.CompletedProcess[str]:
    variables = os.environ.copy()
    variables["PYTHONPATH"] = str(_dependency_site_packages())
    return subprocess.run(
        [str(_executable(environment, "skillroll")), "--output=json", *arguments],
        cwd=repository,
        env=variables,
        check=False,
        capture_output=True,
        text=True,
    )


def test_built_wheel_installs_and_runs_outside_checkout(tmp_path: Path) -> None:
    output = tmp_path / "artifacts"
    bundled_scripts = Path(sys.base_prefix) / ("Scripts" if os.name == "nt" else "bin")
    uv = shutil.which("uv") or str(
        bundled_scripts / ("uv.exe" if os.name == "nt" else "uv")
    )
    subprocess.run(
        [uv, "build", "--no-build-isolation", "--out-dir", str(output)],
        cwd=ROOT,
        env=_uv_build_environment(tmp_path),
        check=True,
    )
    wheels = list(output.glob("*.whl"))
    sdists = list(output.glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        assert "skillroll/cli.py" in names
        assert "skillroll/py.typed" in names
        assert "skillroll/_assets/setup-mascot.ansi" in names
        assert all(
            name in names
            for name in (
                "skillroll/_harness_prompts/executor-prompt/references/system.md",
                "skillroll/_harness_prompts/executor-prompt/references/omission.md",
                "skillroll/_harness_prompts/world-simulator-prompt/references/system.md",
                "skillroll/_harness_prompts/semantic-judge-prompt/references/system.md",
            )
        )
        assert any(name.endswith(".dist-info/licenses/LICENSE") for name in names)
        assert not any(name.startswith("tests/") for name in names)
        entry_points = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        assert (
            "skillroll = skillroll.cli:entrypoint"
            in archive.read(entry_points).decode()
        )

    environment = tmp_path / "environment"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = _executable(environment, "python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheels[0])],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    for arguments in (("--version",), ("--help",)):
        completed = subprocess.run(
            [str(_executable(environment, "skillroll")), *arguments],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0
    # The installed-wheel smoke deliberately omits optional runtime dependencies.
    # Eval parses Markdown and therefore belongs to the dependency-installed E2E.
    for command in ("init", "doctor"):
        completed = subprocess.run(
            [
                str(_executable(environment, "skillroll")),
                "--output",
                "json",
                command,
            ],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 3
        assert completed.stderr == ""
        expected = "SCG1001" if command == "doctor" else "SCI1001"
        assert json.loads(completed.stdout)["diagnostics"][0]["code"] == expected


def test_installed_wheel_initializes_and_validates_spaced_skill_repositories(
    tmp_path: Path,
) -> None:
    """Exercise local commands without importing SkillRoll from the checkout."""
    output = tmp_path / "artifacts"
    bundled_scripts = Path(sys.base_prefix) / ("Scripts" if os.name == "nt" else "bin")
    uv = shutil.which("uv") or str(
        bundled_scripts / ("uv.exe" if os.name == "nt" else "uv")
    )
    subprocess.run(
        [uv, "build", "--no-build-isolation", "--out-dir", str(output)],
        cwd=ROOT,
        env=_uv_build_environment(tmp_path),
        check=True,
    )
    wheel = next(output.glob("*.whl"))
    environment = tmp_path / "clean environment"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = _executable(environment, "python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    generic = tmp_path / "generic plugin repo"
    review = generic / "plugins" / "review"
    review.mkdir(parents=True)
    (review / "SKILL.md").write_text("# Review\n", encoding="utf-8")
    manifest = generic / ".claude-plugin"
    manifest.mkdir()
    (manifest / "marketplace.json").write_text("{}\n", encoding="utf-8")
    (generic / ".gitignore").write_bytes(b"# mine\r\n")
    initialized = _run_installed(
        environment,
        generic,
        "init",
        "--repo",
        str(generic),
        "--skills-path",
        "plugins",
        "--starter-evals",
        "review",
    )
    assert initialized.returncode == 0
    data = json.loads(initialized.stdout)["data"]
    assert data["skills_path"] == "plugins"
    assert data["changed_paths"] == [
        "skillroll.toml",
        ".gitignore",
        "plugins/review/evals/first-use.eval.md",
        "plugins/review/evals/edge-case.eval.md",
    ]
    assert (generic / ".gitignore").read_bytes() == b"# mine\r\n.skillroll/runs/\r\n"
    assert (review / "evals" / "first-use.eval.md").exists()
    assert _run_installed(environment, generic, "validate", "--all").returncode == 0
    rerun = _run_installed(environment, generic, "init", "--skills-path", "plugins")
    assert rerun.returncode == 0
    assert json.loads(rerun.stdout)["data"]["changed_paths"] == []

    root_level = tmp_path / "root level skills"
    root_level.mkdir()
    (root_level / "SKILL.md").write_text("# Root skill\n", encoding="utf-8")
    root_init = _run_installed(environment, root_level, "init", "--yes")
    assert root_init.returncode == 0
    assert 'skills_path = "."' in (root_level / "skillroll.toml").read_text(
        encoding="utf-8"
    )
    evals = root_level / "evals"
    evals.mkdir()
    for name in ("ordinary", "edge"):
        (evals / f"{name}.eval.md").write_text(_case_source(name), encoding="utf-8")
    assert _run_installed(environment, root_level, "validate", "--all").returncode == 0
    missing_profile = _run_installed(environment, root_level, "eval", "--all")
    assert missing_profile.returncode == 3
    assert json.loads(missing_profile.stdout)["diagnostics"][0]["code"] == (
        "SCEMISSING_CONFIGURATION"
    )

    no_skill = tmp_path / "empty repository"
    no_skill.mkdir()
    assert _run_installed(environment, no_skill, "init", "--yes").returncode == 3
    malformed = tmp_path / "malformed repository"
    malformed.mkdir()
    (malformed / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (malformed / "skillroll.toml").write_text("not = [toml", encoding="utf-8")
    assert _run_installed(environment, malformed, "init", "--yes").returncode == 3

    explicit = tmp_path / "noninteractive explicit"
    example = explicit / "skills" / "example"
    example.mkdir(parents=True)
    (example / "SKILL.md").write_text("# Example\n", encoding="utf-8")
    assert (
        _run_installed(
            environment, explicit, "init", "--skills-path", "skills"
        ).returncode
        == 0
    )
    automatic = tmp_path / "noninteractive automatic"
    automatic_example = automatic / "skills" / "example"
    automatic_example.mkdir(parents=True)
    (automatic_example / "SKILL.md").write_text("# Example\n", encoding="utf-8")
    assert (
        _run_installed(
            environment, automatic, "init", "--yes", "--openrouter-free"
        ).returncode
        == 0
    )
    assert (explicit / "skillroll.toml").read_bytes() != (
        automatic / "skillroll.toml"
    ).read_bytes()
    automatic_config = (automatic / "skillroll.toml").read_text(encoding="utf-8")
    assert 'base_url = "https://openrouter.ai/api/v1"' in automatic_config
    assert 'model = "openrouter/free"' in automatic_config
    assert 'api_key_env = "SKILLROLL_API_KEY"' in automatic_config


def test_module_and_direct_main_are_equivalent() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    module = subprocess.run(
        [sys.executable, "-m", "skillroll", "--output", "json", "eval"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    script = subprocess.run(
        [
            sys.executable,
            "-c",
            "from skillroll.cli import entrypoint; entrypoint()",
            "--output",
            "json",
            "eval",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert (module.returncode, module.stdout, module.stderr) == (
        script.returncode,
        script.stdout,
        script.stderr,
    )


def test_installed_wheel_validates_the_dogfood_marketplace_without_source_imports(
    tmp_path: Path,
) -> None:
    output = tmp_path / "artifacts"
    bundled_scripts = Path(sys.base_prefix) / ("Scripts" if os.name == "nt" else "bin")
    uv = shutil.which("uv") or str(
        bundled_scripts / ("uv.exe" if os.name == "nt" else "uv")
    )
    subprocess.run(
        [uv, "build", "--no-build-isolation", "--out-dir", str(output)],
        cwd=ROOT,
        env=_uv_build_environment(tmp_path),
        check=True,
    )
    environment = tmp_path / "clean environment"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = _executable(environment, "python")
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
        check=True,
        capture_output=True,
        text=True,
    )
    repository = tmp_path / "dogfood marketplace"
    repository.mkdir()
    for name in ("plugins", ".claude-plugin"):
        shutil.copytree(ROOT / name, repository / name)
    shutil.copy2(ROOT / "skillroll.toml", repository / "skillroll.toml")

    completed = _run_installed(
        environment, repository, "validate", "--all", "--run-commands"
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["summary"] == (
        "Validated 13 skills and ran 3 repository checks."
    )
