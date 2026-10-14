"""Prepare synchronized candidate release files without publishing or network access."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

from packaging.version import Version

_VERSION = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:rc[1-9][0-9]*)?\Z"
)
_CANONICAL = re.compile(r'^__version__ = "([^"\n]+)"$', re.MULTILINE)


def _read(root: Path, path: Path) -> str:
    """Reject missing files and symlinks, including symlinked parent directories."""
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"release input must not be a symlink: {relative}")
    if not path.is_file():
        raise ValueError(f"release input is not a regular file: {relative}")
    return path.read_text(encoding="utf-8")


def _version(value: str) -> Version:
    if not _VERSION.fullmatch(value):
        raise ValueError(f"invalid release version: {value!r}")
    return Version(value)


def _target(current: str, bump: str, explicit: str | None) -> str:
    parsed = _version(current)
    if explicit is None:
        major, minor, patch = parsed.release
        if bump == "major":
            target = f"{major + 1}.0.0"
        elif bump == "minor":
            target = f"{major}.{minor + 1}.0"
        else:
            target = f"{major}.{minor}.{patch + 1}"
    else:
        target = explicit
    if _version(target) <= parsed:
        raise ValueError(
            "release version must be strictly greater than current version"
        )
    return target


def _lock(source: str, current: str, target: str) -> str:
    """Change only a present version in the root editable package's lock entry."""
    data = tomllib.loads(source)
    entries = data.get("package", [])
    if not isinstance(entries, list) or not all(
        isinstance(item, dict) for item in entries
    ):
        raise ValueError("uv.lock packages must be an array of tables")
    packages = [item for item in entries if item.get("name") == "skillroll"]
    if len(packages) != 1 or packages[0].get("source") != {"editable": "."}:
        raise ValueError("uv.lock must contain exactly one editable skillroll package")
    locked = packages[0].get("version")
    if locked is None:
        # uv's dynamically versioned editable packages intentionally omit version.
        return source
    if locked != current:
        raise ValueError("uv.lock skillroll version differs from canonical version")
    blocks = source.split("[[package]]")
    for index, block in enumerate(blocks[1:], start=1):
        if re.search(r"^name\s*=\s*[\"']skillroll[\"']$", block, re.MULTILINE):
            blocks[index] = re.sub(
                r"^version\s*=\s*[\"'][^\"'\n]+[\"']$",
                f'version = "{target}"',
                block,
                flags=re.MULTILINE,
            )
    return "[[package]]".join(blocks)


def prepare(
    root: Path, bump: str = "patch", version: str | None = None
) -> dict[str, object]:
    """Validate every input before writing candidate metadata and clearing evidence."""
    resolved = root.resolve()
    if root.is_symlink() or not root.is_dir() or resolved == Path(resolved.anchor):
        raise ValueError("release root must be a regular checkout directory")
    # Resolve outer directory aliases (such as macOS /var) once. All candidate
    # inputs must then stay within this root, without symlinks inside the checkout.
    root = resolved
    canonical = root / "src/skillroll/_version.py"
    original = _read(root, canonical)
    matches = _CANONICAL.findall(original)
    if len(matches) != 1:
        raise ValueError(
            "canonical version must have exactly one __version__ assignment"
        )
    current = matches[0]
    if bump not in {"patch", "minor", "major"}:
        raise ValueError("bump must be patch, minor, or major")
    target = _target(current, bump, version)
    updates = {canonical: _CANONICAL.sub(f'__version__ = "{target}"', original)}
    manifests = sorted((root / "plugins").glob("*/.claude-plugin/plugin.json"))
    if not manifests:
        raise ValueError("release checkout has no plugin manifests")
    plugin_tags: list[str] = []
    for path in manifests:
        data = json.loads(_read(root, path))
        if not isinstance(data, dict) or data.get("version") != current:
            raise ValueError(f"plugin version differs from canonical version: {path}")
        dependencies = data.get("dependencies", [])
        if not isinstance(dependencies, list):
            raise ValueError(f"plugin dependencies must be an array: {path}")
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                raise ValueError(f"plugin dependency must be an object: {path}")
            if dependency.get("name") == "flow-runner":
                if dependency.get("version") != f"={current}":
                    raise ValueError(
                        f"flow-runner dependency must match current version: {path}"
                    )
                dependency["version"] = f"={target}"
        plugin_name = path.parent.parent.name
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", plugin_name):
            raise ValueError(f"plugin name is unsafe for a release tag: {path}")
        if data.get("name") != plugin_name:
            raise ValueError(f"plugin name must match its directory: {path}")
        plugin_tags.append(f"{plugin_name}--v{target}")
        data["version"] = target
        updates[path] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    lock = root / "uv.lock"
    updates[lock] = _lock(_read(root, lock), current, target)
    gates = root / "release-gates.toml"
    _read(root, gates)
    updates[gates] = (
        f'schema_version = 1\nversion = "{target}"\n'
        '\n[[gates]]\nname = "installed-live-e2e"\nstate = "BLOCKED"\n'
        'detail = "Candidate installed live E2E has not run."\n'
        '\n[[gates]]\nname = "claude-dependency-install"\nstate = "BLOCKED"\n'
        'detail = "Candidate Claude dependency installation has not run."\n'
    )
    references = [root / "README.md"]
    for directory, pattern in (
        ("docs", "*.md"),
        ("examples", "*.md"),
        (".github/workflows", "*.yml"),
        (".github/workflows", "*.yaml"),
    ):
        references.extend((root / directory).rglob(pattern))
    for path in references:
        source = _read(root, path)
        updates[path] = re.sub(
            re.escape(f"hagaiw/skillroll@v{current}") + r"(?![\w.])",
            f"hagaiw/skillroll@v{target}",
            source,
        )
    for path, contents in updates.items():
        path.write_text(contents, encoding="utf-8")
    return {
        "previous_version": current,
        "version": target,
        "tag": f"v{target}",
        "prerelease": _version(target).is_prerelease,
        "plugin_tags": plugin_tags,
        "changed_paths": [path.relative_to(root).as_posix() for path in updates],
    }


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--bump", choices=("patch", "minor", "major"), default="patch")
    parser.add_argument("--version")
    values = parser.parse_args(arguments)
    try:
        result = prepare(values.root, values.bump, values.version)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Release preparation failed: {error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
