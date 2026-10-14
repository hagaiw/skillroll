"""Exercise release preflight and preserve artifact/credential boundaries."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import ROOT


def complete() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/new-release.yml").read_text())


@pytest.mark.parametrize(
    ("event", "ref", "dry", "token", "accepted"),
    [
        ("workflow_dispatch", "refs/heads/main", "false", "configured", True),
        ("workflow_dispatch", "refs/heads/main", "false", "", False),
        ("workflow_dispatch", "refs/heads/main", "true", "", True),
        ("workflow_dispatch", "refs/heads/other", "true", "", False),
        ("pull_request", "refs/heads/main", "", "configured", True),
        ("pull_request", "refs/heads/main", "", "", False),
    ],
)
def test_preflight_before_paid_checks(
    event: str, ref: str, dry: str, token: str, accepted: bool
) -> None:
    bash = "bash"
    if os.name == "nt":
        git = shutil.which("git")
        assert git is not None
        bash = str(Path(git).resolve().parent.parent / "bin/bash.exe")
    source = complete()["jobs"]["authorize"]["steps"][0]["run"]
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-e"],
        input=source,
        env={
            **os.environ,
            "EVENT_NAME": event,
            "SELECTED_REF": ref,
            "DRY_RUN": dry,
            "RELEASE_TOKEN": token,
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted, result.stderr


def test_complete_release_keeps_credentials_and_tested_bytes_separate() -> None:
    jobs = complete()["jobs"]
    assert jobs["prepare"]["needs"] == "authorize"
    assert jobs["gates"]["needs"] == "prepare"
    assert "github.sha" in jobs["prepare"]["steps"][0]["with"]["ref"]
    assert (
        jobs["prepare"]["outputs"]["manifest"] == "${{ steps.freeze.outputs.sha256 }}"
    )
    assert any(
        "--no-create-gitignore" in s.get("run", "") for s in jobs["prepare"]["steps"]
    )
    assert "!inputs.dry_run" in jobs["gates"]["if"]
    assert jobs["publish"]["needs"] == ["prepare", "gates"]
    for name in ("prepare", "gates"):
        assert "RELEASE_TOKEN" not in str(jobs[name])
        checkouts = [s for s in jobs[name]["steps"] if "checkout@" in s.get("uses", "")]
        assert all(s["with"]["persist-credentials"] is False for s in checkouts)
    gate = next(
        s
        for s in jobs["gates"]["steps"]
        if "SKILLROLL_RELEASE_WHEEL" in s.get("env", {})
    )
    assert (
        "/dist/skillroll-${{ needs.prepare.outputs.version }}"
        in (gate["env"]["SKILLROLL_RELEASE_WHEEL"])
    )
    assert "--junitxml=installed-live.xml" in gate["run"]
    final = next(s for s in jobs["gates"]["steps"] if s.get("id") == "finalize")
    assert '[ "$(git diff --name-only)" = release-gates.toml ]' in final["run"]
    assert final["env"]["MANIFEST_SHA256"] == "${{ needs.prepare.outputs.manifest }}"
    assert "sha256sum --check --strict" in final["run"]
    assert "--expected-manifest candidate-SHA256SUMS.json" in final["run"]
    assert "git bundle create verified-candidate.bundle HEAD" in final["run"]
    publish = jobs["publish"]["steps"]
    assert not any("checkout@" in s.get("uses", "") for s in publish)
    persist = next(s for s in publish if s.get("id") == "dispatch")["run"]
    assert "git -C handoff push --atomic --force-with-lease=" in persist
    assert '[ "$remote" = "$BASE" ]' in persist
    assert "gh workflow run release.yml" in persist
    assert '--ref "$TAG"' in persist
    assert '-f candidate_run="$GITHUB_RUN_ID"' in persist
    assert "AUTHORIZATION: basic" in persist
    assert "mapfile" not in persist  # macOS ships Bash 3.2.
    assert publish[-1]["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert jobs["publish"]["permissions"]["checks"] == "read"
    wait = publish[-1]["run"]
    assert "run['databaseId'] not in previous" in wait
    assert "run['displayTitle'] == expected" in wait
    assert 'gh run watch "$run" --repo "$GH_REPO" --exit-status' in wait


def test_publisher_checks_preparation_origin_before_artifact_handoff() -> None:
    publisher = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    steps = publisher["jobs"]["build"]["steps"]
    origin = next(s for s in steps if s.get("name") == "Verify preparation run origin")
    assert ".github/workflows/new-release.yml" in origin["run"]
    assert "job['conclusion'] == 'success'" in origin["run"]
    assert "for name in ['prepare', 'gates']" in origin["run"]
    download = next(
        s for s in steps if s.get("with", {}).get("name") == "verified-release"
    )
    verify = next(s for s in steps if "verify_prepared_release.py" in s.get("run", ""))
    assert steps.index(origin) < steps.index(download) < steps.index(verify)
    assert '--commit "$GITHUB_SHA" --run-id "$CANDIDATE_RUN"' in verify["run"]


@pytest.mark.parametrize("conflict", ["", "main", "tag"])
@pytest.mark.parametrize("stdout_newlines", ["native", "crlf"])
def test_atomic_persistence_never_partially_pushes_or_dispatches(
    tmp_path: Path, conflict: str, stdout_newlines: str
) -> None:
    """Run the real handoff script against a disposable local bare repository."""
    import json
    import sys

    def git(directory: Path, *args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(directory), *args], text=True, stderr=subprocess.PIPE
        ).strip()

    candidate = tmp_path / "candidate"
    candidate.mkdir()
    git(candidate, "init", "-q")
    git(candidate, "config", "user.name", "Release test")
    git(candidate, "config", "user.email", "release-test@invalid.example")
    (candidate / "version").write_text("base")
    git(candidate, "add", ".")
    git(candidate, "commit", "-qm", "base")
    base = git(candidate, "rev-parse", "HEAD")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    git(candidate, "push", str(remote), f"{base}:refs/heads/main")
    (candidate / "version").write_text("candidate")
    git(candidate, "commit", "-qam", "candidate")
    commit = git(candidate, "rev-parse", "HEAD")
    git(
        candidate,
        "bundle",
        "create",
        str(tmp_path / "verified-candidate.bundle"),
        "HEAD",
    )
    if conflict == "main":
        (candidate / "version").write_text("unrelated")
        git(candidate, "commit", "-qam", "unrelated main update")
        git(candidate, "push", str(remote), "HEAD:refs/heads/main")
    elif conflict == "tag":
        git(candidate, "push", str(remote), f"{base}:refs/tags/v1.2.3")
    before = git(remote, "show-ref")
    (tmp_path / "release-metadata.json").write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "tag": "v1.2.3",
                "plugin_tags": ["flow-runner--v1.2.3", "sample--v1.2.3"],
            }
        )
    )
    config = tmp_path / "gitconfig"
    subprocess.run(
        [
            "git",
            "config",
            "--file",
            str(config),
            f"url.{remote.as_uri()}.insteadOf",
            "https://github.com/local/repo.git",
        ],
        check=True,
    )
    step = next(
        s for s in complete()["jobs"]["publish"]["steps"] if s.get("id") == "dispatch"
    )
    source = step["run"].replace(
        "python - <<'PYTHON'", f"\"{sys.executable}\" - <<'PYTHON'"
    )
    if stdout_newlines == "crlf":
        source = source.replace(
            "sys.stdout.buffer.write(",
            "sys.stdout.reconfigure(newline='\\r\\n'); sys.stdout.buffer.write(",
        )
    bash = "bash"
    if os.name == "nt":
        executable = shutil.which("git")
        assert executable is not None
        bash = str(Path(executable).resolve().parent.parent / "bin/bash.exe")
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-e"],
        input='gh() { if [ "$1" = run ]; then echo "[]"; '
        "else echo dispatched >> dispatch-receipt; fi; }\n" + source,
        cwd=tmp_path,
        env={
            **os.environ,
            "GH_TOKEN": "dummy",
            "GH_REPO": "local/repo",
            "BASE": base,
            "COMMIT": commit,
            "TAG": "v1.2.3",
            "VERSION": "1.2.3",
            "GITHUB_RUN_ID": "123",
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GIT_CONFIG_GLOBAL": str(config),
            "GIT_CONFIG_NOSYSTEM": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    if conflict:
        assert result.returncode != 0
        assert git(remote, "show-ref") == before
        assert not (tmp_path / "dispatch-receipt").exists()
        if conflict == "main":
            assert "main advanced; no publication dispatched." in result.stdout
        else:
            assert "rejected" in result.stderr
    else:
        assert result.returncode == 0, (result.stdout, result.stderr)
        for ref in [
            "heads/main",
            "tags/v1.2.3",
            "tags/flow-runner--v1.2.3",
            "tags/sample--v1.2.3",
        ]:
            assert git(remote, "rev-parse", f"refs/{ref}") == commit
        assert (tmp_path / "dispatch-receipt").read_text() == "dispatched\n"
