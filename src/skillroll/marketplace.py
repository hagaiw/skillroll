"""Validation for the optional, dogfood-only Claude marketplace layout."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from skillroll.diagnostics import Diagnostic
from skillroll.repository_io import is_directory, is_regular, is_symlink

_PLUGIN_NAME = re.compile(r"[a-z][a-z0-9-]{0,62}")


@dataclass(frozen=True, slots=True)
class MarketplacePlugin:
    """One local plugin identity declared by a marketplace manifest."""

    name: str
    source: Path
    version: str
    dependencies: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class MarketplaceReport:
    """The optional marketplace contract, separate from skill discovery."""

    plugins: tuple[MarketplacePlugin, ...]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def is_valid(self) -> bool:
        return not self.diagnostics


def _diagnostic(code: str, summary: str, path: Path) -> Diagnostic:
    return Diagnostic(
        code,
        summary,
        affected=path.as_posix(),
        next_action="Correct the named Claude marketplace file, then validate again.",
    )


def _no_symlink_path(root: Path, path: Path) -> bool:
    """Require every component beneath a trusted root to be ordinary."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current /= part
        if is_symlink(current):
            return False
    return True


def _read_object(
    root: Path, path: Path, code: str
) -> tuple[dict[str, object] | None, Diagnostic | None]:
    if not _no_symlink_path(root, path) or not is_regular(path):
        return None, _diagnostic(
            code, "This marketplace JSON file must be a regular non-symlink file.", path
        )
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, _diagnostic(
            code, "This marketplace JSON file is not readable JSON.", path
        )
    if not isinstance(parsed, dict):
        return None, _diagnostic(
            code, "This marketplace JSON file must contain an object.", path
        )
    return parsed, None


def _safe_source(root: Path, value: object) -> Path | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    source = PurePosixPath(value)
    if source.is_absolute() or ".." in source.parts:
        return None
    candidate = root.joinpath(*source.parts)
    if not _no_symlink_path(root, candidate):
        return None
    return candidate


def _valid_name(value: object) -> bool:
    return isinstance(value, str) and _PLUGIN_NAME.fullmatch(value) is not None


def _dependencies(value: object) -> tuple[tuple[str, str], ...] | None:
    if value is None:
        return ()
    if not isinstance(value, list):
        return None
    result: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"name", "version"}:
            return None
        name = item.get("name")
        version = item.get("version")
        if (
            not _valid_name(name)
            or not isinstance(version, str)
            or not version.startswith("=")
            or len(version) == 1
        ):
            return None
        assert isinstance(name, str)
        if name in {existing for existing, _ in result}:
            return None
        result.append((name, version))
    return tuple(result)


def _has_cycle(plugins: tuple[MarketplacePlugin, ...]) -> bool:
    dependencies = {
        item.name: {name for name, _ in item.dependencies} for item in plugins
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> bool:
        if name in visiting:
            return True
        if name in visited:
            return False
        visiting.add(name)
        cyclic = any(
            target in dependencies and visit(target) for target in dependencies[name]
        )
        visiting.remove(name)
        visited.add(name)
        return cyclic

    return any(visit(name) for name in dependencies)


def validate_marketplace(root: Path, version: str) -> MarketplaceReport:
    """Validate a local Claude catalog without making it a core requirement."""
    repository = root.resolve()
    manifest_path = repository / ".claude-plugin" / "marketplace.json"
    manifest, initial = _read_object(repository, manifest_path, "SCM1001")
    if initial is not None:
        return MarketplaceReport((), (initial,))
    assert manifest is not None
    entries = manifest.get("plugins")
    if not isinstance(entries, list):
        return MarketplaceReport(
            (),
            (
                _diagnostic(
                    "SCM1001", "marketplace.json needs a plugins list.", manifest_path
                ),
            ),
        )
    findings: list[Diagnostic] = []
    plugins: list[MarketplacePlugin] = []
    declared_names: set[str] = set()
    declared_sources: set[Path] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            findings.append(
                _diagnostic(
                    "SCM1002",
                    "A marketplace plugin entry must be an object.",
                    manifest_path,
                )
            )
            continue
        name = entry.get("name")
        source = _safe_source(repository, entry.get("source"))
        if not _valid_name(name) or source is None:
            findings.append(
                _diagnostic(
                    "SCM1002",
                    "A marketplace plugin needs a safe name and source path.",
                    manifest_path,
                )
            )
            continue
        assert isinstance(name, str)
        if name in declared_names or source in declared_sources:
            findings.append(
                _diagnostic(
                    "SCM1002",
                    "Marketplace plugin names and source paths must be unique.",
                    manifest_path,
                )
            )
            continue
        declared_names.add(name)
        declared_sources.add(source)
        plugin_path = source / ".claude-plugin" / "plugin.json"
        if not is_directory(source) or not _no_symlink_path(repository, plugin_path):
            findings.append(
                _diagnostic(
                    "SCM1003",
                    "This marketplace plugin source has no regular plugin.json file.",
                    plugin_path,
                )
            )
            continue
        plugin_manifest, error = _read_object(repository, plugin_path, "SCM1003")
        if error is not None:
            findings.append(error)
            continue
        assert plugin_manifest is not None
        actual_name = plugin_manifest.get("name")
        actual_version = plugin_manifest.get("version")
        if actual_name != name:
            findings.append(
                _diagnostic(
                    "SCM1004",
                    "plugin.json name must match its marketplace entry.",
                    plugin_path,
                )
            )
        if (
            not isinstance(actual_version, str)
            or not actual_version
            or actual_version != version
        ):
            findings.append(
                _diagnostic(
                    "SCM1005",
                    "plugin.json version must match SkillRoll's lockstep version.",
                    plugin_path,
                )
            )
        dependencies = _dependencies(plugin_manifest.get("dependencies"))
        if dependencies is None:
            findings.append(
                _diagnostic(
                    "SCM1006",
                    "plugin.json dependencies must be exact name/version objects.",
                    plugin_path,
                )
            )
            dependencies = ()
        elif actual_name in {dependency_name for dependency_name, _ in dependencies}:
            findings.append(
                _diagnostic(
                    "SCM1006",
                    "A plugin must not declare itself as a dependency.",
                    plugin_path,
                )
            )
            dependencies = ()
        if (
            isinstance(actual_name, str)
            and actual_name == name
            and actual_version == version
        ):
            plugins.append(
                MarketplacePlugin(name, source, actual_version, dependencies)
            )
    known = {item.name for item in plugins}
    for declared_plugin in plugins:
        if any(
            name not in known or expected != f"={version}"
            for name, expected in declared_plugin.dependencies
        ):
            findings.append(
                _diagnostic(
                    "SCM1006",
                    "A plugin dependency must name a local lockstep plugin.",
                    declared_plugin.source / ".claude-plugin" / "plugin.json",
                )
            )
    if _has_cycle(tuple(plugins)):
        findings.append(
            _diagnostic(
                "SCM1007",
                "Marketplace plugin dependencies must not form a cycle.",
                manifest_path,
            )
        )
    return MarketplaceReport(
        tuple(sorted(plugins, key=lambda item: item.name)), tuple(findings)
    )
