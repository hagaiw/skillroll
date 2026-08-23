"""Hash records for the exact local inputs used by an attempt."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class InputHash:
    """One original-byte identity in the version-one inputs manifest."""

    identity: PurePosixPath
    kind: str
    sha256: str
    bytes: int


def hash_bytes(identity: PurePosixPath, kind: str, value: bytes) -> InputHash:
    """Record a SHA-256 digest over original bytes, never normalized text."""
    return InputHash(identity, kind, hashlib.sha256(value).hexdigest(), len(value))


def classify_bundle_path(path: PurePosixPath) -> str:
    """Classify a bundled path without making claims about its content."""
    if path.name == "SKILL.md":
        return "skill_instruction"
    if path.parts[0] == "references":
        return "reference"
    if path.parts[0] == "scripts":
        return "script"
    if path.parts[0] == "assets":
        return "asset"
    return "bundle_file"


def hash_file(identity: PurePosixPath, kind: str, path: Path) -> InputHash:
    """Hash one already-approved local input without decoding or normalizing it."""
    try:
        return hash_bytes(identity, kind, path.read_bytes())
    except OSError as error:
        raise ValueError(
            f"SkillRoll could not hash required input {identity}."
        ) from error
