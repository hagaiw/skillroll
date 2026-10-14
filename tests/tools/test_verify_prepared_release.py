"""The publishing phase binds source identity, fresh evidence, and exact bytes."""

from __future__ import annotations

import json
import runpy
import sys
import zipfile
from pathlib import Path

import pytest

from skillroll import __version__
from skillroll.release import artifact_manifest, unsigned_provenance
from tools.verify_prepared_release import main, verify


def fixture(root: Path, version: str = __version__) -> tuple[Path, Path]:
    artifacts, evidence = root / "dist", root / "evidence"
    artifacts.mkdir()
    evidence.mkdir()
    wheel = artifacts / f"skillroll-{__version__}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "skillroll.dist-info/METADATA", f"Name: skillroll\nVersion: {version}\n"
        )
    (artifacts / f"skillroll-{__version__}.tar.gz").write_bytes(b"source")
    manifest = artifact_manifest(artifacts.iterdir())
    (evidence / "SHA256SUMS.json").write_bytes(manifest)
    (evidence / "provenance.json").write_bytes(
        unsigned_provenance(__version__, "a" * 40, manifest)
    )
    digest = json.loads(manifest)[wheel.name]
    root.joinpath("release-gates.toml").write_text(
        f'schema_version=1\nversion="{__version__}"\n'
        '[[gates]]\nname="installed-live-e2e"\nstate="PASS"\n'
        'detail="https://github.com/hagaiw/skillroll/actions/runs/123; '
        f'wheel SHA256 {digest}; passed"\n'
        '[[gates]]\nname="claude-dependency-install"\nstate="PASS"\n'
        'detail="https://github.com/hagaiw/skillroll/actions/runs/123; '
        f'wheel SHA256 {digest}; passed"\n'
    )
    return artifacts, evidence


def test_prepared_release_binds_exact_artifacts_and_provenance(tmp_path: Path) -> None:
    artifacts, evidence = fixture(tmp_path)
    verify(tmp_path, artifacts, evidence, "a" * 40, "123")
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "--artifacts",
                str(artifacts),
                "--evidence",
                str(evidence),
                "--commit",
                "a" * 40,
                "--run-id",
                "123",
            ]
        )
        == 0
    )


@pytest.mark.parametrize("run", ["bad", "12", "124"])
def test_gates_must_belong_to_this_preparation_run(tmp_path: Path, run: str) -> None:
    artifacts, evidence = fixture(tmp_path)
    with pytest.raises(ValueError, match="preparation run"):
        verify(tmp_path, artifacts, evidence, "a" * 40, run)


def test_blocked_gates_are_never_publishable(tmp_path: Path) -> None:
    artifacts, evidence = fixture(tmp_path)
    gate = tmp_path / "release-gates.toml"
    gate.write_text(gate.read_text().replace('state="PASS"', 'state="BLOCKED"'))
    with pytest.raises(ValueError, match="preparation run"):
        verify(tmp_path, artifacts, evidence, "a" * 40, "123")


@pytest.mark.parametrize("manifest", ["[]", "{}", '{"one":"hash"}'])
def test_prepared_manifest_requires_two_packages(tmp_path: Path, manifest: str) -> None:
    artifacts, evidence = fixture(tmp_path)
    (evidence / "SHA256SUMS.json").write_text(manifest)
    with pytest.raises(ValueError, match="exactly one"):
        verify(tmp_path, artifacts, evidence, "a" * 40, "123")


@pytest.mark.parametrize("mode", ["missing", "extra", "wrongmanifest", "two_wheels"])
def test_artifact_inventory_cannot_change(tmp_path: Path, mode: str) -> None:
    artifacts, evidence = fixture(tmp_path)
    if mode == "missing":
        next(artifacts.glob("*.whl")).unlink()
    elif mode == "extra":
        (artifacts / "unexpected.txt").write_text("extra")
    elif mode == "two_wheels":
        (artifacts / f"skillroll-{__version__}-other.whl").write_bytes(b"other")
    else:
        manifest = json.loads((evidence / "SHA256SUMS.json").read_text())
        digest = manifest.pop(
            next(name for name in manifest if name.endswith(".tar.gz"))
        )
        manifest["other.tar.gz"] = digest
        (evidence / "SHA256SUMS.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="canonical version"):
        verify(tmp_path, artifacts, evidence, "a" * 40, "123")


def test_artifact_corruption_blocks_publication(tmp_path: Path) -> None:
    artifacts, evidence = fixture(tmp_path)
    next(artifacts.glob("*.tar.gz")).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksums"):
        verify(tmp_path, artifacts, evidence, "a" * 40, "123")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("commit", "b" * 40),
        ("version", f"{__version__}.post1"),
        ("artifacts", {}),
        ("signed", True),
    ],
)
def test_provenance_cannot_change(tmp_path: Path, key: str, value: object) -> None:
    artifacts, evidence = fixture(tmp_path)
    path = evidence / "provenance.json"
    provenance = json.loads(path.read_text())
    provenance[key] = value
    path.write_text(json.dumps(provenance))
    with pytest.raises(ValueError, match="provenance"):
        verify(tmp_path, artifacts, evidence, "a" * 40, "123")


@pytest.mark.parametrize("version", [__version__ + "0", f"{__version__}.post1"])
def test_wheel_version_uses_exact_equality(tmp_path: Path, version: str) -> None:
    artifacts, evidence = fixture(tmp_path, version)
    with pytest.raises(ValueError, match="Wheel metadata"):
        verify(tmp_path, artifacts, evidence, "a" * 40, "123")


def test_wheel_metadata_must_be_unique(tmp_path: Path) -> None:
    artifacts, evidence = fixture(tmp_path)
    with zipfile.ZipFile(next(artifacts.glob("*.whl")), "a") as archive:
        archive.writestr("other.dist-info/METADATA", "Version: wrong")
    manifest = artifact_manifest(artifacts.iterdir())
    (evidence / "SHA256SUMS.json").write_bytes(manifest)
    (evidence / "provenance.json").write_bytes(
        unsigned_provenance(__version__, "a" * 40, manifest)
    )
    gate = tmp_path / "release-gates.toml"
    import re

    digest = json.loads(manifest)[next(artifacts.glob("*.whl")).name]
    gate.write_text(
        re.sub(r"wheel SHA256 [0-9a-f]+;", f"wheel SHA256 {digest};", gate.read_text())
    )
    with pytest.raises(ValueError, match="Wheel metadata"):
        verify(tmp_path, artifacts, evidence, "a" * 40, "123")


def test_verifier_module_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts, evidence = fixture(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_prepared_release.py",
            "--root",
            str(tmp_path),
            "--artifacts",
            str(artifacts),
            "--evidence",
            str(evidence),
            "--commit",
            "a" * 40,
            "--run-id",
            "123",
        ],
    )
    monkeypatch.delitem(sys.modules, "tools.verify_prepared_release", raising=False)
    with pytest.raises(SystemExit) as result:
        runpy.run_module("tools.verify_prepared_release", run_name="__main__")
    assert result.value.code == 0


def test_gate_wheel_digest_cannot_be_replaced(tmp_path: Path) -> None:
    artifacts, evidence = fixture(tmp_path)
    path = tmp_path / "release-gates.toml"
    import re

    path.write_text(
        re.sub(
            r"wheel SHA256 [0-9a-f]+;",
            "wheel SHA256 " + "0" * 64 + ";",
            path.read_text(),
        )
    )
    with pytest.raises(ValueError, match="different wheel bytes"):
        verify(tmp_path, artifacts, evidence, "a" * 40, "123")
