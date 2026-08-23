"""Official Claude CLI smoke for the dogfood marketplace dependency."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import ROOT


@pytest.mark.external
def test_official_cli_installs_the_exact_tagged_dependency(tmp_path: Path) -> None:
    """Keep every Claude and Git write in a disposable isolated directory."""
    assert shutil.which("claude") is not None, (
        "Install the Claude CLI before running external integration checks."
    )
    repository = tmp_path / "candidate repository"
    shutil.copytree(ROOT / ".claude-plugin", repository / ".claude-plugin")
    shutil.copytree(ROOT / "plugins", repository / "plugins")
    environment = dict(os.environ)
    environment.update(
        {
            "CLAUDE_CONFIG_DIR": str(tmp_path / "claude config"),
            "CLAUDE_CODE_PLUGIN_CACHE_DIR": str(tmp_path / "plugin cache"),
            "DISABLE_AUTOUPDATER": "1",
        }
    )
    git_commands = (
        ("init", "-q"),
        ("config", "user.name", "SkillRoll test"),
        ("config", "user.email", "skillroll-test@invalid.example"),
        ("add", "."),
        ("commit", "-q", "-m", "candidate fixture"),
        ("tag", "flow-runner--v0.1.1"),
    )
    for arguments in git_commands:
        subprocess.run(
            ("git", "-C", str(repository), *arguments),
            check=True,
            capture_output=True,
            text=True,
        )

    subprocess.run(
        ("claude", "plugin", "marketplace", "add", str(repository)),
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    installed = subprocess.run(
        (
            "claude",
            "plugin",
            "install",
            "change-review-flow@skillroll",
            "--scope",
            "user",
        ),
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    listed = subprocess.run(
        ("claude", "plugin", "list", "--json"),
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    plugins = {item["id"]: item for item in json.loads(listed.stdout)}
    assert "+ 1 dependency: flow-runner" in installed.stdout
    assert plugins["change-review-flow@skillroll"]["version"] == "0.1.1"
    assert plugins["change-review-flow@skillroll"]["enabled"] is True
    assert plugins["flow-runner@skillroll"]["version"].startswith("0.1.1-")
    assert plugins["flow-runner@skillroll"]["enabled"] is True
    for item in plugins.values():
        assert str(tmp_path) in item["installPath"]
