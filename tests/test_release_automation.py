"""Exercise candidate guards offline, without publishing or creating tags."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from conftest import ROOT

from skillroll import __version__


def workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())


@pytest.mark.parametrize(
    ("event", "publish", "ref", "version", "tag_commit", "error"),
    [
        ("workflow_dispatch", "true", "refs/heads/main", __version__, None, None),
        (
            "workflow_dispatch",
            "true",
            "refs/heads/other",
            __version__,
            None,
            "Publish from main only",
        ),
        (
            "workflow_dispatch",
            "true",
            "refs/heads/main",
            "",
            None,
            "Confirm the canonical version",
        ),
        (
            "workflow_dispatch",
            "true",
            "refs/heads/main",
            "9.9.9",
            None,
            "Confirm the canonical version",
        ),
        ("workflow_dispatch", "false", "refs/heads/other", "", None, None),
        ("pull_request", "true", "refs/heads/main", "", None, None),
        ("release", "true", "refs/tags/v0.1.2", "", "candidate", None),
        (
            "workflow_dispatch",
            "true",
            "refs/heads/main",
            __version__,
            "old",
            "Release tag already points at another commit",
        ),
    ],
)
def test_candidate_guards(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    event: str,
    publish: str,
    ref: str,
    version: str,
    tag_commit: str | None,
    error: str | None,
) -> None:
    step = next(
        s for s in workflow()["jobs"]["build"]["steps"] if s.get("id") == "candidate"
    )
    source = step["run"].split("<<'PYTHON'\n", 1)[1].rsplit("PYTHON", 1)[0]
    output = tmp_path / "outputs"
    monkeypatch.chdir(ROOT)
    environment = dict(
        EVENT_NAME=event,
        PUBLISH=publish,
        SELECTED_REF=ref,
        REQUESTED_VERSION=version,
        GITHUB_OUTPUT=str(output),
    )
    tag_result = subprocess.CompletedProcess(
        [], 1 if tag_commit is None else 0, stdout=tag_commit or ""
    )
    with (
        patch.dict(os.environ, environment),
        patch("subprocess.check_output", return_value="candidate\n"),
        patch("subprocess.run", return_value=tag_result),
    ):
        if error:
            with pytest.raises(AssertionError, match=error):
                exec(source, {})
            assert not output.exists()
        else:
            exec(source, {})
            assert output.read_text() == (
                f"tag=v{__version__}\ncommit=candidate\nprerelease=false\n"
            )


def test_release_automation_preserves_publication_boundaries() -> None:
    data = workflow()
    jobs = data["jobs"]
    build = jobs["build"]
    assert "merged == true" in build["if"]
    assert "head.repo.full_name == github.repository" in build["if"]
    assert "contains(github.event.pull_request.labels.*.name, 'release')" in build["if"]
    assert data["concurrency"]["cancel-in-progress"] is False
    checkout = build["steps"][0]["with"]
    assert "merge_commit_sha" in checkout["ref"]
    assert checkout["persist-credentials"] is False
    assert any(
        "uv run skillroll validate --all" in s.get("run", "") for s in build["steps"]
    )
    for job in ("attest", "publish-pypi"):
        assert "needs.build.outputs.publish == 'true'" in jobs[job]["if"]
        assert "needs.build.outputs.publishable == 'true'" in jobs[job]["if"]
    release = jobs["github-release"]
    assert release["needs"] == ["build", "publish-pypi"]
    assert release["permissions"] == {"contents": "write"}
    assert not any("uses" in s for s in release["steps"])
    assert (
        release["steps"][0]["env"]["RELEASE_COMMIT"]
        == "${{ needs.build.outputs.commit }}"
    )
    assert '--target "$RELEASE_COMMIT"' in release["steps"][0]["run"]


@pytest.mark.parametrize("status", [0, 1, 2, 3, 127])
def test_offline_validation_only_accepts_pass_or_incomplete(status: int) -> None:
    step = next(
        s
        for s in workflow()["jobs"]["build"]["steps"]
        if s.get("name") == "Validate eval structure without repository commands"
    )
    bash = "bash"
    if os.name == "nt":
        # PATH may resolve bash to the WSL launcher without a distribution.
        # GitHub's Windows runners provide a working Git Bash alongside Git.
        git = shutil.which("git")
        assert git is not None, "Git for Windows is required"
        bash = str(Path(git).resolve().parent.parent / "bin" / "bash.exe")
        assert Path(bash).is_file(), f"Git Bash not found: {bash}"
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-e"],
        input=f"uv() {{ return {status}; }}\n" + step["run"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == (0 if status in (0, 2) else status), (
        result.stdout,
        result.stderr,
    )
