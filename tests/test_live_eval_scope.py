"""Repository-specific live-eval exemptions keep unknown changes conservative."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from conftest import ROOT


@pytest.mark.parametrize(
    ("paths", "required"),
    [
        ([], False),
        (
            [
                ".github/workflows/release.yml",
                "tests/test_release_automation.py",
                "docs/releasing.md",
                ".github/CONTRIBUTING.md",
            ],
            False,
        ),
        ([".github/workflows/ci.yml"], False),
        (["README.md"], False),
        (["plugins/demo/skills/demo/SKILL.md"], True),
        (["plugins/harness-prompts/skills/executor-prompt/references/system.md"], True),
        (["src/skillroll/github.py"], True),
        (["skillroll.toml"], True),
        (["uv.lock"], True),
        (["action.yml"], True),
        ([".github/workflows/skillroll.yml"], True),
        ([".github/workflows/unknown.yml"], True),
        (["docs/guide.md", "plugins/demo/skills/demo/evals/test.eval.md"], True),
        (["plugins/demo/SKILL.md", "docs/moved-skill.md"], True),
        (["unknown-file"], True),
    ],
)
def test_live_scope(paths: list[str], required: bool, tmp_path: Path) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/skillroll.yml").read_text())
    validate = workflow["jobs"]["validate"]
    step = next(s for s in validate["steps"] if s.get("id") == "live-scope")
    output = tmp_path / "output"
    result = subprocess.CompletedProcess(
        [], 0, stdout=("\0".join(paths) + "\0").encode()
    )
    with (
        patch.dict(
            os.environ, GITHUB_OUTPUT=str(output), BASE_SHA="base", HEAD_SHA="head"
        ),
        patch("subprocess.run", return_value=result) as run,
    ):
        exec(step["run"], {})
    assert output.read_text() == f"required={str(required).lower()}\n"
    assert "--no-renames" in run.call_args.args[0]
    assert run.call_args.kwargs["check"] is True
    assert (
        "needs.validate.outputs.live-required == 'true'"
        in workflow["jobs"]["live-eval"]["if"]
    )
    assert (
        validate["outputs"]["live-required"]
        == "${{ steps.live-scope.outputs.required }}"
    )


def test_unreadable_diff_fails_instead_of_skipping(tmp_path: Path) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/skillroll.yml").read_text())
    step = next(
        s for s in workflow["jobs"]["validate"]["steps"] if s.get("id") == "live-scope"
    )
    output = tmp_path / "output"
    with (
        patch.dict(
            os.environ, GITHUB_OUTPUT=str(output), BASE_SHA="base", HEAD_SHA="head"
        ),
        patch("subprocess.run", side_effect=subprocess.CalledProcessError(128, "git")),
        pytest.raises(subprocess.CalledProcessError),
    ):
        exec(step["run"], {})
    assert not output.exists()
