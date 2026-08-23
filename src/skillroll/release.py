"""Pure release identity, artifact, and readiness checks."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from skillroll._version import __version__

_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(rc[1-9][0-9]*)?$"
)
_ACTION_OWNER = "hagaiw/skillroll"
_REQUIRED_GATES = {"installed-live-e2e", "claude-dependency-install"}
_GATE_STATES = {"PASS", "BLOCKED", "SKIPPED", "ERROR"}
_REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


class ArtifactError(ValueError):
    """An artifact manifest is malformed or cannot be verified safely."""


class ReadinessError(ValueError):
    """Release gate input cannot safely become a readiness report."""


@dataclass(frozen=True, slots=True)
class ReleaseMetadata:
    """One parsed version and the tag identity it requires."""

    version: str
    tag: str
    major: int
    prerelease: bool


@dataclass(frozen=True, slots=True)
class ReleaseFileReport:
    """Known release-field agreement without scanning prose or fixtures."""

    problems: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.problems


@dataclass(frozen=True, slots=True)
class ExternalGate:
    """A manually evidenced release requirement with an explicit state."""

    name: str
    state: str
    detail: str

    def __post_init__(self) -> None:
        if self.state not in _GATE_STATES:
            raise ReadinessError(
                f"{self.name} has an unsupported state: {self.state!r}."
            )
        if not self.detail or any(ord(character) < 32 for character in self.detail):
            raise ReadinessError(
                f"{self.name} has unsafe or empty release-gate detail."
            )


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """Whether the immutable candidate may enter its publish-only job."""

    gates: tuple[ExternalGate, ...]

    def __post_init__(self) -> None:
        names = tuple(item.name for item in self.gates)
        if set(names) != _REQUIRED_GATES or len(names) != len(set(names)):
            raise ReadinessError(
                "Readiness reports require exactly one installed-live-e2e and "
                "one claude-dependency-install gate."
            )

    @property
    def publishable(self) -> bool:
        return all(item.state == "PASS" for item in self.gates)

    def render(self) -> str:
        lines = ["# SkillRoll release readiness", ""]
        lines.extend(
            f"- {item.name}: {item.state} — {item.detail}" for item in self.gates
        )
        lines.extend(
            ("", f"Publication: {'READY' if self.publishable else 'BLOCKED'}", "")
        )
        return "\n".join(lines)


def release_metadata(version: str = __version__) -> ReleaseMetadata:
    """Parse the limited release-version grammar used by tags and Action refs."""
    matched = _VERSION.fullmatch(version)
    if matched is None:
        raise ValueError(
            "Release versions must use MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCHrcN."
        )
    return ReleaseMetadata(
        version, f"v{version}", int(matched.group(1)), bool(matched.group(4))
    )


def exact_action_ref(metadata: ReleaseMetadata) -> str:
    """Return the immutable Action reference matching exactly one package build."""
    return f"{_ACTION_OWNER}@{metadata.tag}"


def moving_major_ref(metadata: ReleaseMetadata) -> str | None:
    """Expose a moving ref only for a stable 1.0+ release."""
    return None if metadata.major == 0 or metadata.prerelease else f"v{metadata.major}"


def _version_from_source(path: Path) -> str | None:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None
    matched = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)
    return None if matched is None else matched.group(1)


def _plugin_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(root.glob("plugins/*/.claude-plugin/plugin.json")))


def validate_release_files(root: Path) -> ReleaseFileReport:
    """Check only known build/plugin release fields for one canonical version."""
    problems: list[str] = []
    version_path = root / "src/skillroll/_version.py"
    version = _version_from_source(version_path)
    if version is None:
        return ReleaseFileReport(
            ("src/skillroll/_version.py has no canonical version.",)
        )
    try:
        metadata = release_metadata(version)
    except ValueError as error:
        return ReleaseFileReport((str(error),))
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        problems.append("pyproject.toml could not be read as release metadata.")
    else:
        hatch = project.get("tool", {}).get("hatch", {})
        if (
            project.get("project", {}).get("dynamic") != ["version"]
            or hatch.get("version", {}).get("path") != "src/skillroll/_version.py"
        ):
            problems.append("pyproject.toml must read its version from _version.py.")
    for path in _plugin_files(root):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            problems.append(f"{path.relative_to(root)} is not valid plugin metadata.")
            continue
        if value.get("version") != metadata.version:
            problems.append(
                f"{path.relative_to(root)} does not match {metadata.version}."
            )
        dependencies = value.get("dependencies", [])
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if (
                    isinstance(dependency, dict)
                    and dependency.get("name") == "flow-runner"
                    and dependency.get("version") != f"={metadata.version}"
                ):
                    problems.append(
                        f"{path.relative_to(root)} has a mismatched flow-runner "
                        "dependency."
                    )
    return ReleaseFileReport(tuple(problems))


def artifact_manifest(paths: Iterable[Path]) -> bytes:
    """Render a stable SHA-256 manifest for files already chosen by the caller."""
    values: dict[str, str] = {}
    for path in sorted(paths, key=lambda item: item.name):
        if not path.is_file() or path.is_symlink():
            raise ArtifactError(f"Artifact {path.name} is not a regular file.")
        if path.name in values:
            raise ArtifactError(f"Artifact filename {path.name} occurs more than once.")
        values[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return (json.dumps(values, sort_keys=True, separators=(",", ":")) + "\n").encode()


def verify_artifact_manifest(manifest: bytes, directory: Path) -> tuple[str, ...]:
    """Return mismatched/missing filenames without reading outside one directory."""
    try:
        values = json.loads(manifest.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactError("Artifact checksum manifest is not valid JSON.") from error
    if not isinstance(values, dict) or any(
        not isinstance(name, str) or not isinstance(digest, str)
        for name, digest in values.items()
    ):
        raise ArtifactError("Artifact checksum manifest must map filenames to hashes.")
    mismatched: list[str] = []
    for name, expected in values.items():
        path = directory / name
        if (
            "/" in name
            or "\\" in name
            or path.is_symlink()
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            mismatched.append(name)
    return tuple(sorted(mismatched))


def unsigned_provenance(version: str, commit: str, manifest: bytes) -> bytes:
    """Record local rehearsal facts without claiming a hosted signed attestation."""
    try:
        artifacts = json.loads(manifest.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactError("Artifact checksum manifest is not valid JSON.") from error
    if not isinstance(artifacts, Mapping):
        raise ArtifactError("Artifact checksum manifest must be a JSON object.")
    return (
        json.dumps(
            {
                "artifacts": dict(artifacts),
                "commit": commit,
                "format_version": 1,
                "signed": False,
                "version": release_metadata(version).version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def spdx_sbom(
    version: str, dependencies: Sequence[str], *, source_name: str = "skillroll"
) -> bytes:
    """Render a small deterministic SPDX 2.3 SBOM for direct runtime packages."""
    metadata = release_metadata(version)
    packages: list[dict[str, object]] = [
        {
            "SPDXID": "SPDXRef-Package-skillroll",
            "copyrightText": "NOASSERTION",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "MIT",
            "name": source_name,
            "versionInfo": metadata.version,
        }
    ]
    relationships: list[dict[str, str]] = [
        {
            "relatedSpdxElement": "SPDXRef-Package-skillroll",
            "relationshipType": "DESCRIBES",
            "spdxElementId": "SPDXRef-DOCUMENT",
        }
    ]
    for index, dependency in enumerate(sorted(set(dependencies)), start=1):
        matched = _REQUIREMENT_NAME.match(dependency)
        if matched is None:
            raise ArtifactError(
                f"Runtime dependency is not a valid requirement: {dependency!r}."
            )
        name = matched.group(1)
        identifier = f"SPDXRef-Dependency-{index}"
        packages.append(
            {
                "SPDXID": identifier,
                "copyrightText": "NOASSERTION",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "name": name,
            }
        )
        relationships.append(
            {
                "relatedSpdxElement": identifier,
                "relationshipType": "DEPENDS_ON",
                "spdxElementId": "SPDXRef-Package-skillroll",
            }
        )
    return (
        json.dumps(
            {
                "SPDXID": "SPDXRef-DOCUMENT",
                "creationInfo": {
                    "created": "1970-01-01T00:00:00Z",
                    "creators": ["Tool: skillroll release rehearsal"],
                },
                "dataLicense": "CC0-1.0",
                "documentNamespace": (
                    f"https://github.com/hagaiw/skillroll/releases/tag/{metadata.tag}"
                ),
                "documentDescribes": ["SPDXRef-Package-skillroll"],
                "name": f"skillroll-{metadata.version}",
                "packages": packages,
                "relationships": relationships,
                "spdxVersion": "SPDX-2.3",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def runtime_dependencies(root: Path) -> tuple[str, ...]:
    """Read direct package requirements without resolving or contacting an index."""
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ArtifactError("pyproject.toml could not be read for the SBOM.") from error
    dependencies = project.get("project", {}).get("dependencies")
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) for item in dependencies
    ):
        raise ArtifactError("pyproject.toml has no readable runtime dependency list.")
    return tuple(sorted(dependencies))


def write_rehearsal_evidence(
    *,
    root: Path,
    artifacts: Iterable[Path],
    output: Path,
    commit: str,
    gates: Iterable[ExternalGate],
) -> ReadinessReport:
    """Write deterministic local evidence; callers decide whether BLOCKED stops."""
    output.mkdir(parents=True, exist_ok=True)
    manifest = artifact_manifest(artifacts)
    metadata = release_metadata()
    (output / "SHA256SUMS.json").write_bytes(manifest)
    (output / "sbom.spdx.json").write_bytes(
        spdx_sbom(metadata.version, runtime_dependencies(root))
    )
    (output / "provenance.json").write_bytes(
        unsigned_provenance(metadata.version, commit, manifest)
    )
    report = readiness_report(tuple(gates))
    (output / "readiness.md").write_text(report.render(), encoding="utf-8")
    return report


def readiness_report(gates: tuple[ExternalGate, ...]) -> ReadinessReport:
    """Normalize the two required external gates without giving them a bypass."""
    return ReadinessReport(tuple(sorted(gates, key=lambda item: item.name)))


def load_external_gates(
    path: Path, *, version: str = __version__
) -> tuple[ExternalGate, ...]:
    """Read strict, version-bound release evidence from reviewed TOML."""
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ReadinessError("Release-gate evidence is not readable TOML.") from error
    if set(value) != {"schema_version", "version", "gates"}:
        raise ReadinessError("Release-gate evidence has unsupported top-level fields.")
    if value["schema_version"] != 1:
        raise ReadinessError("Release-gate evidence requires schema_version = 1.")
    if value["version"] != release_metadata(version).version:
        raise ReadinessError(
            "Release-gate evidence does not match the canonical package version."
        )
    raw_gates = value["gates"]
    if not isinstance(raw_gates, list):
        raise ReadinessError("Release-gate evidence must contain a gates array.")
    gates: list[ExternalGate] = []
    for item in raw_gates:
        if not isinstance(item, dict) or set(item) != {"name", "state", "detail"}:
            raise ReadinessError("Each release gate requires name, state, and detail.")
        if not all(isinstance(item[key], str) for key in ("name", "state", "detail")):
            raise ReadinessError("Release-gate name, state, and detail must be text.")
        gates.append(ExternalGate(item["name"], item["state"], item["detail"]))
    return readiness_report(tuple(gates)).gates
