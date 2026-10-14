"""Exercise prepared checkouts and artifact handoffs without live services."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ROOT
from packaging.version import Version

from skillroll import __version__
from tools.prepare_release import prepare


@pytest.mark.parametrize(
    ("bump", "version"),
    [
        ("patch", None),
        ("minor", None),
        ("major", None),
        ("patch", "9.9.9"),
        ("patch", "999.0.0"),
    ],
)
def test_prepared_candidate_checks_and_exact_artifact_handoff(
    tmp_path: Path, bump: str, version: str | None
) -> None:
    # Copy the source, not the editable installation: each child imports the
    # freshly prepared version in a new Python process.
    candidate = tmp_path / "candidate checkout"
    shutil.copytree(
        ROOT,
        candidate,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".skillroll",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "__pycache__",
            ".hypothesis",
            "dist",
            "coverage.json",
            ".coverage",
        ),
    )
    if version is not None and Version(version) <= Version(__version__):
        version = f"{Version(__version__).major + 1}.0.0"
    metadata = prepare(candidate, bump, version)
    environment = dict(os.environ)
    for name in (
        "SKILLROLL_API_KEY",
        "SKILLROLL_ADOPTION_API_KEY",
        "RELEASE_TOKEN",
        "GH_TOKEN",
        "ANTHROPIC_API_KEY",
    ):
        environment.pop(name, None)
    environment["PYTHONPATH"] = str(candidate / "src")
    environment["PYTEST_ADDOPTS"] = ""
    tests = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_phase7_marketplace.py",
            "tests/test_phase8_release.py",
            "tests/test_release_automation.py",
            "tests/tools/test_verify_prepared_release.py",
            "tests/test_release_gate_adapters.py",
        ],
        cwd=candidate,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert tests.returncode == 0, tests.stdout + tests.stderr
    uv = shutil.which("uv")
    assert uv is not None
    build = subprocess.run(
        [uv, "build", "--out-dir", "dist", "--clear", "--no-create-gitignore"],
        cwd=candidate,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    # Synthetic passing receipts are test fixtures, never actual gate evidence.
    # This checks prepare -> distributions -> receipts -> provenance -> verify.
    script = r"""
from pathlib import Path
from skillroll import __version__
from skillroll.release import (
    artifact_manifest, load_external_gates, write_rehearsal_evidence,
)
from tools.finalize_release import finalize
from tools.verify_prepared_release import verify
root = Path.cwd()
artifacts = root / 'dist'
manifest = root / 'candidate-SHA256SUMS.json'
manifest.write_bytes(artifact_manifest(artifacts.iterdir()))
reports = []
cases = [
    ('live', 'test_existing_marketplace_user_journey_with_real_inference'),
    ('claude', 'test_official_cli_installs_the_exact_tagged_dependency'),
]
for name, case in cases:
    path = root / (name + '.xml')
    path.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0">'
                    + '<testcase name="' + case + '"/></testsuite>')
    reports.append(path)
finalize(root, reports[0], reports[1], 'a' * 40,
         'https://github.com/hagaiw/skillroll/actions/runs/123', artifacts, manifest)
evidence = root / 'evidence'
write_rehearsal_evidence(
    root=root, artifacts=artifacts.iterdir(), output=evidence, commit='b' * 40,
    gates=load_external_gates(root / 'release-gates.toml'),
)
verify(root, artifacts, evidence, 'b' * 40, '123')
print(__version__)
"""
    handoff = subprocess.run(
        [sys.executable, "-c", script],
        cwd=candidate,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert handoff.returncode == 0, handoff.stdout + handoff.stderr
    assert handoff.stdout.strip() == metadata["version"]
