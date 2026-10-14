from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ROOT

from skillroll.release import ExternalGate
from tools.release_rehearsal import main


def test_rehearsal_writes_publishable_evidence_for_current_passed_gates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "tools.release_rehearsal.load_external_gates",
        lambda path: (
            ExternalGate("installed-live-e2e", "PASS", "verified test fixture"),
            ExternalGate("claude-dependency-install", "PASS", "verified test fixture"),
        ),
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "skillroll-0.1.0.whl").write_bytes(b"wheel")
    output = tmp_path / "output"

    assert (
        main(
            [
                "--root",
                str(ROOT),
                "--artifacts",
                str(artifacts),
                "--output",
                str(output),
                "--commit",
                "candidate",
            ]
        )
        == 0
    )
    assert (output / "readiness.md").is_file()
    readiness = (output / "readiness.md").read_text(encoding="utf-8")
    assert "installed-live-e2e: PASS" in readiness
    assert "claude-dependency-install: PASS" in readiness
    assert "Publication: READY" in readiness
