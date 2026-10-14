"""Record fresh candidate gates only after both release integration checks pass."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from packaging.utils import parse_sdist_filename, parse_wheel_filename

from skillroll.release import artifact_manifest, release_metadata

_CASES = (
    "test_existing_marketplace_user_journey_with_real_inference",
    "test_official_cli_installs_the_exact_tagged_dependency",
)


def _regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"release input is not a regular nonsymlink file: {path}")


def _receipt(path: Path, expected: str) -> None:
    """Require a single named passing test, including consistent suite summaries."""
    _regular(path)
    try:
        document = ET.fromstring(path.read_bytes())
    except ET.ParseError as error:
        raise ValueError(f"release receipt is not valid JUnit XML: {path}") from error
    if document.tag not in {"testsuites", "testsuite"}:
        raise ValueError(f"release receipt must contain a JUnit test suite: {path}")
    suites = list(document.iter("testsuite"))
    if not suites or sum(len(suite.findall("testcase")) for suite in suites) != 1:
        raise ValueError(
            f"release receipt must contain one test inside a suite: {path}"
        )
    cases = list(document.iter("testcase"))
    if len(cases) != 1 or cases[0].get("name") != expected:
        raise ValueError(f"release receipt must contain exactly one {expected}: {path}")
    for element in document.iter():
        if element.tag in {"failure", "error", "skipped"}:
            raise ValueError(f"release integration check did not pass: {path}")
        for name in ("failures", "errors", "skipped"):
            if name in element.attrib and element.attrib[name] != "0":
                raise ValueError(f"release receipt reports {name}: {path}")
        if (
            element.tag in {"testsuite", "testsuites"}
            and "tests" in element.attrib
            and element.attrib["tests"] != "1"
        ):
            raise ValueError(f"release receipt has inconsistent test count: {path}")


def finalize(
    root: Path,
    live_report: Path,
    claude_report: Path,
    candidate_commit: str,
    run_url: str,
    artifacts: Path,
    expected_manifest: Path,
) -> dict[str, str]:
    """Validate integration receipts and artifacts before replacing blocked gates."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("release root must be a regular checkout directory")
    root = root.resolve()
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", candidate_commit):
        raise ValueError("candidate commit must be a full lowercase Git SHA")
    if not re.fullmatch(
        r"https://github\.com/hagaiw/skillroll/actions/runs/[1-9][0-9]*", run_url
    ):
        raise ValueError("release run URL must identify a SkillRoll Actions run")
    canonical = root / "src/skillroll/_version.py"
    gates = root / "release-gates.toml"
    for path in (canonical, gates):
        if any(parent.is_symlink() for parent in path.parents if parent != root):
            raise ValueError(f"release input parent must not be a symlink: {path}")
        _regular(path)
    versions = re.findall(
        r'^__version__ = "([^"\n]+)"$',
        canonical.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if len(versions) != 1:
        raise ValueError("candidate must contain exactly one canonical version")
    metadata = release_metadata(versions[0])
    _receipt(live_report, _CASES[0])
    _receipt(claude_report, _CASES[1])
    if artifacts.is_symlink() or not artifacts.is_dir():
        raise ValueError("candidate artifacts must be a regular directory")
    wheels = sorted(artifacts.glob("*.whl"))
    sources = sorted(artifacts.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("candidate artifacts require exactly one wheel and one sdist")
    wheel = wheels[0]
    source = sources[0]
    wheel_name, wheel_version, _, _ = parse_wheel_filename(wheel.name)
    source_name, source_version = parse_sdist_filename(source.name)
    if (
        wheel_name != "skillroll"
        or source_name != "skillroll"
        or str(wheel_version) != metadata.version
        or str(source_version) != metadata.version
    ):
        raise ValueError("candidate artifact names must match the canonical version")
    _regular(expected_manifest)
    actual = artifact_manifest(artifacts.iterdir())
    manifest = json.loads(actual)
    if (
        set(manifest) != {wheel.name, source.name}
        or expected_manifest.read_bytes() != actual
    ):
        raise ValueError("candidate artifacts changed since their preparation checks")
    digest = manifest[wheel.name]
    detail = (
        f"Version {metadata.version}; candidate {candidate_commit}; "
        f"run {run_url}; wheel SHA256 {digest}; passed."
    )
    contents = (
        f'schema_version = 1\nversion = "{metadata.version}"\n'
        '\n[[gates]]\nname = "installed-live-e2e"\nstate = "PASS"\n'
        f"detail = {json.dumps(detail)}\n"
        '\n[[gates]]\nname = "claude-dependency-install"\nstate = "PASS"\n'
        f"detail = {json.dumps(detail)}\n"
    )
    gates.write_text(contents, encoding="utf-8")
    return {"version": metadata.version, "wheel_sha256": digest}


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--claude-report", type=Path, required=True)
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--expected-manifest", type=Path, required=True)
    values = parser.parse_args(arguments)
    try:
        result = finalize(
            values.root,
            values.live_report,
            values.claude_report,
            values.candidate_commit,
            values.run_url,
            values.artifacts,
            values.expected_manifest,
        )
    except (OSError, ValueError) as error:
        parser.exit(2, f"Release evidence could not be recorded: {error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
