from __future__ import annotations

from pathlib import Path

from conftest import ROOT

from tools.release_rehearsal import main


def test_rehearsal_writes_publishable_evidence_for_current_passed_gates(
    tmp_path: Path,
) -> None:
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
