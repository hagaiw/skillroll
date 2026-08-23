"""Offline release-hardening contracts; no test creates a tag or publishes."""

from __future__ import annotations

import hashlib
import json
import runpy
import sys
from pathlib import Path

import pytest
from conftest import ROOT

from skillroll import __version__
from skillroll.github_workflow import DEFAULT_ACTION_REF, render_workflow
from skillroll.release import (
    ArtifactError,
    ExternalGate,
    ReadinessError,
    ReleaseMetadata,
    artifact_manifest,
    exact_action_ref,
    load_external_gates,
    moving_major_ref,
    readiness_report,
    release_metadata,
    runtime_dependencies,
    spdx_sbom,
    unsigned_provenance,
    validate_release_files,
    verify_artifact_manifest,
    write_rehearsal_evidence,
)


def test_release_metadata_drives_exact_pre_one_action_reference() -> None:
    metadata = release_metadata(__version__)

    assert metadata == ReleaseMetadata(__version__, f"v{__version__}", 0, False)
    assert exact_action_ref(metadata) == f"hagaiw/skillroll@v{__version__}"
    assert moving_major_ref(metadata) is None
    assert exact_action_ref(metadata) == DEFAULT_ACTION_REF
    assert DEFAULT_ACTION_REF in render_workflow(DEFAULT_ACTION_REF, None).decode()


@pytest.mark.parametrize(
    ("value", "expected"), [("1.0.0", "v1"), ("2.4.6", "v2"), ("1.0.0rc1", None)]
)
def test_release_metadata_allows_moving_ref_only_for_stable_one_plus(
    value: str, expected: str | None
) -> None:
    metadata = release_metadata(value)

    assert moving_major_ref(metadata) == expected


@pytest.mark.parametrize("value", ["v1.0.0", "1.0", "01.0.0", "1.0.0-dev"])
def test_release_metadata_rejects_non_pep440_semver_values(value: str) -> None:
    with pytest.raises(ValueError):
        release_metadata(value)


def test_release_files_are_lockstep_and_known_field_mismatch_is_reported(
    tmp_path: Path,
) -> None:
    root = tmp_path / "release"
    for source in ("pyproject.toml", "src", "plugins"):
        target = ROOT / source
        if target.is_dir():
            import shutil

            shutil.copytree(target, root / source)
        else:
            (root / source).parent.mkdir(parents=True, exist_ok=True)
            (root / source).write_bytes(target.read_bytes())
    assert validate_release_files(root).is_valid

    plugin = root / "plugins/flow-runner/.claude-plugin/plugin.json"
    plugin.write_text(
        plugin.read_text().replace('"0.1.0"', '"0.2.0"'), encoding="utf-8"
    )
    report = validate_release_files(root)
    assert not report.is_valid
    assert any("flow-runner" in item for item in report.problems)


def test_artifact_manifest_verifies_bytes_and_unsigned_provenance_is_honest(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "skillroll-0.1.0.whl"
    source = tmp_path / "skillroll-0.1.0.tar.gz"
    wheel.write_bytes(b"wheel")
    source.write_bytes(b"source")

    manifest = artifact_manifest((wheel, source))
    assert verify_artifact_manifest(manifest, tmp_path) == ()
    wheel.write_bytes(b"changed")
    assert verify_artifact_manifest(manifest, tmp_path) == (wheel.name,)
    with pytest.raises(ArtifactError):
        verify_artifact_manifest(b"not json", tmp_path)

    provenance = json.loads(unsigned_provenance(__version__, "abc123", manifest))
    assert provenance["signed"] is False
    assert provenance["version"] == __version__
    assert provenance["artifacts"][source.name] == hashlib.sha256(b"source").hexdigest()


def test_readiness_refuses_publication_until_each_external_gate_passes() -> None:
    blocked = readiness_report(
        (
            ExternalGate("installed-live-e2e", "BLOCKED", "package/source mismatch"),
            ExternalGate("claude-dependency-install", "BLOCKED", "needs tag"),
        )
    )
    passed = readiness_report(
        (
            ExternalGate("installed-live-e2e", "PASS", "passed"),
            ExternalGate("claude-dependency-install", "PASS", "passed"),
        )
    )

    assert not blocked.publishable
    assert "BLOCKED" in blocked.render()
    assert passed.publishable


def test_version_bound_release_gate_file_is_strict_and_current(tmp_path: Path) -> None:
    gates = load_external_gates(ROOT / "release-gates.toml")

    assert [item.name for item in gates] == [
        "claude-dependency-install",
        "installed-live-e2e",
    ]
    assert all(item.state == "PASS" for item in gates)
    with pytest.raises(ReadinessError, match="readable TOML"):
        load_external_gates(tmp_path / "missing.toml")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("not = [toml", "readable TOML"),
        ("schema_version=1\nversion='0.1.0'\ngates=[]\nextra=1", "top-level"),
        ("schema_version=2\nversion='0.1.0'\ngates=[]", "schema_version"),
        ("schema_version=1\nversion='9.9.9'\ngates=[]", "canonical"),
        ("schema_version=1\nversion='0.1.0'\ngates='bad'", "gates array"),
        (
            "schema_version=1\nversion='0.1.0'\ngates=[1]",
            "name, state, and detail",
        ),
        (
            "schema_version=1\nversion='0.1.0'\n"
            "gates=[{name='installed-live-e2e',state='PASS'}]",
            "name, state, and detail",
        ),
        (
            "schema_version=1\nversion='0.1.0'\n"
            "gates=[{name=1,state='PASS',detail='x'}]",
            "must be text",
        ),
    ],
)
def test_release_gate_file_rejects_stale_or_malformed_evidence(
    tmp_path: Path, source: str, message: str
) -> None:
    path = tmp_path / "gates.toml"
    path.write_text(source, encoding="utf-8")

    with pytest.raises(ReadinessError, match=message):
        load_external_gates(path)


def test_spdx_sbom_is_deterministic_and_uses_direct_runtime_dependencies() -> None:
    dependencies = runtime_dependencies(ROOT)
    document = json.loads(spdx_sbom(__version__, dependencies))
    assert document["spdxVersion"] == "SPDX-2.3"
    assert document["name"] == f"skillroll-{__version__}"
    assert document["creationInfo"]["created"] == "1970-01-01T00:00:00Z"
    assert [item["name"] for item in document["packages"]][1:] == [
        "PyYAML",
        "markdown-it-py",
        "openai-agents",
    ]
    assert document["documentDescribes"] == ["SPDXRef-Package-skillroll"]
    assert all("licenseDeclared" in item for item in document["packages"])


def test_rehearsal_evidence_is_local_unsigned_and_preserves_blocked_gate(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "skillroll-0.1.0.whl").write_bytes(b"wheel")
    output = tmp_path / "evidence"
    report = write_rehearsal_evidence(
        root=ROOT,
        artifacts=tuple(artifacts.iterdir()),
        output=output,
        commit="candidate",
        gates=(
            ExternalGate("installed-live-e2e", "BLOCKED", "needs repair"),
            ExternalGate("claude-dependency-install", "BLOCKED", "needs tag"),
        ),
    )

    assert not report.publishable
    assert {path.name for path in output.iterdir()} == {
        "SHA256SUMS.json",
        "provenance.json",
        "readiness.md",
        "sbom.spdx.json",
    }
    assert json.loads((output / "provenance.json").read_text())["signed"] is False


def test_release_inputs_reject_duplicate_artifact_and_malformed_gate(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first" / "same.whl"
    second = tmp_path / "second" / "same.whl"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    with pytest.raises(ArtifactError, match="occurs more than once"):
        artifact_manifest((first, second))
    with pytest.raises(ReadinessError, match="unsupported state"):
        ExternalGate("installed-live-e2e", "MAYBE", "not allowed")
    with pytest.raises(ReadinessError, match="unsafe"):
        ExternalGate("installed-live-e2e", "PASS", "line one\nline two")
    with pytest.raises(ReadinessError, match="exactly one"):
        readiness_report((ExternalGate("installed-live-e2e", "PASS", "fine"),))


def test_release_file_and_artifact_error_paths_are_explicit(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert not validate_release_files(missing).is_valid

    invalid = tmp_path / "invalid"
    (invalid / "src/skillroll").mkdir(parents=True)
    (invalid / "src/skillroll/_version.py").write_text(
        '__version__ = "not-a-version"\n', encoding="utf-8"
    )
    assert not validate_release_files(invalid).is_valid
    (invalid / "src/skillroll/_version.py").write_text(
        '__version__ = "1.2.3"\n', encoding="utf-8"
    )
    (invalid / "pyproject.toml").write_text("not = [valid", encoding="utf-8")
    manifest = invalid / "plugins/demo/.claude-plugin/plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("not json", encoding="utf-8")
    report = validate_release_files(invalid)
    assert len(report.problems) == 2

    with pytest.raises(ArtifactError, match="not a regular"):
        artifact_manifest((invalid,))
    with pytest.raises(ArtifactError, match="map filenames"):
        verify_artifact_manifest(b"[]", tmp_path)
    with pytest.raises(ArtifactError, match="JSON object"):
        unsigned_provenance(__version__, "commit", b"[]")
    with pytest.raises(ArtifactError, match="not valid JSON"):
        unsigned_provenance(__version__, "commit", b"not json")
    with pytest.raises(ArtifactError, match="valid requirement"):
        spdx_sbom(__version__, ("!not-a-package",))


def test_release_checker_reports_known_build_and_dependency_mismatches(
    tmp_path: Path,
) -> None:
    (tmp_path / "src/skillroll").mkdir(parents=True)
    (tmp_path / "src/skillroll/_version.py").write_text(
        '__version__ = "1.2.3"\n', encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\ndynamic = []\n[tool.hatch.version]\npath = 'wrong.py'\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "plugins/demo/.claude-plugin/plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "dependencies": [{"name": "flow-runner", "version": "=1.0.0"}],
            }
        ),
        encoding="utf-8",
    )
    other = tmp_path / "plugins/other/.claude-plugin/plugin.json"
    other.parent.mkdir(parents=True)
    other.write_text('{"version":"1.2.3","dependencies":{}}', encoding="utf-8")

    report = validate_release_files(tmp_path)

    assert any("pyproject.toml must" in item for item in report.problems)
    assert any("mismatched flow-runner" in item for item in report.problems)


def test_release_runtime_dependency_read_errors_and_unsafe_filename(
    tmp_path: Path,
) -> None:
    with pytest.raises(ArtifactError, match="could not be read"):
        runtime_dependencies(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = {}\n")
    with pytest.raises(ArtifactError, match="no readable"):
        runtime_dependencies(tmp_path)
    assert verify_artifact_manifest(b'{"../outside":"hash"}', tmp_path) == (
        "../outside",
    )


def test_rehearsal_tool_module_entrypoint_is_covered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_rehearsal.py",
            "--root",
            str(ROOT),
            "--artifacts",
            str(artifacts),
            "--output",
            str(tmp_path / "output"),
            "--commit",
            "candidate",
        ],
    )
    monkeypatch.delitem(sys.modules, "tools.release_rehearsal", raising=False)
    with pytest.raises(SystemExit) as raised:
        runpy.run_module("tools.release_rehearsal", run_name="__main__")
    assert raised.value.code == 0
