"""Verify the exact checked artifacts handed off by the complete-release workflow."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from email.parser import Parser
from pathlib import Path

from skillroll.release import (
    load_external_gates,
    release_metadata,
    verify_artifact_manifest,
)


def verify(
    root: Path, artifacts: Path, evidence: Path, commit: str, run_id: str
) -> None:
    """Bind version, final commit, fresh gate run, and package bytes before signing."""
    canonical = root / "src/skillroll/_version.py"
    if canonical.is_symlink() or not canonical.is_file():
        raise ValueError("Candidate version must be a regular nonsymlink file.")
    versions = re.findall(
        r'^__version__ = "([^"\n]+)"$', canonical.read_text(), re.MULTILINE
    )
    if len(versions) != 1:
        raise ValueError("Candidate must contain exactly one canonical version.")
    metadata = release_metadata(versions[0])
    gates = load_external_gates(root / "release-gates.toml", version=metadata.version)
    marker = f"https://github.com/hagaiw/skillroll/actions/runs/{run_id};"
    if not run_id.isdigit() or any(
        g.state != "PASS" or marker not in g.detail for g in gates
    ):
        raise ValueError("Release gates do not match the successful preparation run.")
    manifest = (evidence / "SHA256SUMS.json").read_bytes()
    files = json.loads(manifest)
    if not isinstance(files, dict) or len(files) != 2:
        raise ValueError("Release manifest must contain exactly one wheel and sdist.")
    wheel = tuple(artifacts.glob(f"skillroll-{metadata.version}-*.whl"))
    source = artifacts / f"skillroll-{metadata.version}.tar.gz"
    if (
        len(wheel) != 1
        or set(files) != {wheel[0].name, source.name}
        or set(path.name for path in artifacts.iterdir()) != set(files)
    ):
        raise ValueError("Release artifacts do not match the canonical version.")
    if verify_artifact_manifest(manifest, artifacts):
        raise ValueError("Release artifact checksums do not match.")
    if any(
        f"wheel SHA256 {files[wheel[0].name]};" not in gate.detail for gate in gates
    ):
        raise ValueError("Release gate evidence is for different wheel bytes.")
    provenance = json.loads((evidence / "provenance.json").read_bytes())
    if (
        provenance.get("commit") != commit
        or provenance.get("version") != metadata.version
        or provenance.get("artifacts") != files
        or provenance.get("signed") is not False
    ):
        raise ValueError(
            "Release provenance does not match the tagged commit and artifacts."
        )
    with zipfile.ZipFile(wheel[0]) as archive:
        names = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if (
            len(names) != 1
            or Parser().parsestr(archive.read(names[0]).decode())["Version"]
            != metadata.version
        ):
            raise ValueError("Wheel metadata does not match the canonical version.")


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(arguments)
    verify(args.root, args.artifacts, args.evidence, args.commit, args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
