from __future__ import annotations

import json
from pathlib import Path

from skillroll import __version__
from skillroll.marketplace import _no_symlink_path, validate_marketplace


def _write_plugin(
    root: Path,
    name: str,
    *,
    version: str = __version__,
    dependencies: list[dict[str, str]] | None = None,
) -> None:
    plugin = root / "plugins" / name
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": name,
                "description": f"{name} description",
                "version": version,
                "dependencies": [] if dependencies is None else dependencies,
            }
        ),
        encoding="utf-8",
    )


def _write_marketplace(root: Path, plugins: list[dict[str, str]]) -> None:
    metadata = root / ".claude-plugin"
    metadata.mkdir(exist_ok=True)
    (metadata / "marketplace.json").write_text(
        json.dumps(
            {"name": "skillroll", "owner": {"name": "SkillRoll"}, "plugins": plugins}
        ),
        encoding="utf-8",
    )


def test_validates_lockstep_local_marketplace_and_exact_dependency(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "flow-runner")
    _write_plugin(
        tmp_path,
        "change-review-flow",
        dependencies=[{"name": "flow-runner", "version": f"={__version__}"}],
    )
    _write_marketplace(
        tmp_path,
        [
            {"name": "flow-runner", "source": "./plugins/flow-runner"},
            {
                "name": "change-review-flow",
                "source": "./plugins/change-review-flow",
            },
        ],
    )

    report = validate_marketplace(tmp_path, __version__)

    assert report.is_valid
    assert tuple(plugin.name for plugin in report.plugins) == (
        "change-review-flow",
        "flow-runner",
    )
    assert report.plugins[0].dependencies == (("flow-runner", f"={__version__}"),)


def test_reports_malformed_and_unsafe_marketplace_boundaries(tmp_path: Path) -> None:
    report = validate_marketplace(tmp_path, __version__)
    assert report.diagnostics[0].code == "SCM1001"

    _write_marketplace(
        tmp_path,
        [
            {"name": "one", "source": "./plugins/one"},
            {"name": "one", "source": "../outside"},
            {"name": "two", "source": "./plugins/missing"},
        ],
    )
    report = validate_marketplace(tmp_path, __version__)
    assert {item.code for item in report.diagnostics} >= {"SCM1002", "SCM1003"}


def test_reports_manifest_identity_version_and_dependency_problems(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "flow-runner")
    _write_plugin(tmp_path, "broken", version="0.2.0", dependencies=[{"name": "x"}])
    _write_plugin(
        tmp_path,
        "cycle",
        dependencies=[{"name": "other", "version": f"={__version__}"}],
    )
    _write_plugin(
        tmp_path,
        "other",
        dependencies=[{"name": "cycle", "version": f"={__version__}"}],
    )
    _write_marketplace(
        tmp_path,
        [
            {"name": "flow-runner", "source": "./plugins/flow-runner"},
            {"name": "expected", "source": "./plugins/broken"},
            {"name": "cycle", "source": "./plugins/cycle"},
            {"name": "other", "source": "./plugins/other"},
        ],
    )

    report = validate_marketplace(tmp_path, __version__)

    codes = {item.code for item in report.diagnostics}
    assert {"SCM1004", "SCM1005", "SCM1006", "SCM1007"} <= codes


def test_reports_every_malformed_json_and_marketplace_entry_shape(
    tmp_path: Path,
) -> None:
    metadata = tmp_path / ".claude-plugin"
    metadata.mkdir()
    marketplace = metadata / "marketplace.json"
    marketplace.write_text("not json", encoding="utf-8")
    assert validate_marketplace(tmp_path, __version__).diagnostics[0].code == "SCM1001"

    marketplace.write_text("[]", encoding="utf-8")
    assert validate_marketplace(tmp_path, __version__).diagnostics[0].code == "SCM1001"

    marketplace.write_text('{"plugins": {}}', encoding="utf-8")
    assert validate_marketplace(tmp_path, __version__).diagnostics[0].code == "SCM1001"

    _write_plugin(tmp_path, "valid")
    _write_marketplace(
        tmp_path,
        [
            1,
            {"name": "", "source": "./plugins/valid"},
            {"name": "empty-source", "source": ""},
            {"name": "valid", "source": "./plugins/valid"},
            {"name": "valid", "source": "./plugins/valid"},
        ],
    )
    assert "SCM1002" in {
        item.code for item in validate_marketplace(tmp_path, __version__).diagnostics
    }


def test_reports_bad_plugin_json_dependency_shape_and_unknown_dependency(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "bad-json")
    _write_plugin(tmp_path, "no-dependency")
    _write_plugin(tmp_path, "bad-dependency", dependencies=[])
    _write_plugin(tmp_path, "bad-list", dependencies=[])
    _write_plugin(
        tmp_path,
        "unknown-dependency",
        dependencies=[{"name": "absent", "version": f"={__version__}"}],
    )
    bad_json = tmp_path / "plugins/bad-json/.claude-plugin/plugin.json"
    bad_json.write_text("[]", encoding="utf-8")
    bad_dependency = tmp_path / "plugins/bad-dependency/.claude-plugin/plugin.json"
    no_dependency = tmp_path / "plugins/no-dependency/.claude-plugin/plugin.json"
    no_dependency.write_text(
        json.dumps(
            {
                "name": "no-dependency",
                "description": "no dependencies are needed",
                "version": __version__,
            }
        ),
        encoding="utf-8",
    )
    bad_dependency.write_text(
        json.dumps(
            {
                "name": "bad-dependency",
                "description": "broken dependency",
                "version": __version__,
                "dependencies": [1],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "plugins/bad-list/.claude-plugin/plugin.json").write_text(
        json.dumps(
            {
                "name": "bad-list",
                "description": "broken dependency list",
                "version": __version__,
                "dependencies": "not-a-list",
            }
        ),
        encoding="utf-8",
    )
    _write_marketplace(
        tmp_path,
        [
            {"name": "bad-json", "source": "./plugins/bad-json"},
            {"name": "no-dependency", "source": "./plugins/no-dependency"},
            {
                "name": "bad-dependency",
                "source": "./plugins/bad-dependency",
            },
            {"name": "bad-list", "source": "./plugins/bad-list"},
            {
                "name": "unknown-dependency",
                "source": "./plugins/unknown-dependency",
            },
        ],
    )

    codes = {
        item.code for item in validate_marketplace(tmp_path, __version__).diagnostics
    }
    assert {"SCM1003", "SCM1006"} <= codes


def test_rejects_symlink_sources_and_manifest_files_without_following_them(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "real")
    linked = tmp_path / "plugins" / "linked"
    linked.symlink_to(tmp_path / "plugins" / "real", target_is_directory=True)
    _write_marketplace(
        tmp_path,
        [{"name": "linked", "source": "./plugins/linked"}],
    )
    assert "SCM1002" in {
        item.code for item in validate_marketplace(tmp_path, __version__).diagnostics
    }

    _write_marketplace(tmp_path, [{"name": "real", "source": "./plugins/real"}])
    real_manifest = tmp_path / "plugins/real/.claude-plugin/plugin.json"
    external_manifest = tmp_path / "external-plugin.json"
    external_manifest.write_text(real_manifest.read_text(encoding="utf-8"))
    real_manifest.unlink()
    real_manifest.symlink_to(external_manifest)
    assert "SCM1003" in {
        item.code for item in validate_marketplace(tmp_path, __version__).diagnostics
    }

    root_manifest = tmp_path / ".claude-plugin/marketplace.json"
    external_root = tmp_path / "external-marketplace.json"
    external_root.write_text(root_manifest.read_text(encoding="utf-8"))
    root_manifest.unlink()
    root_manifest.symlink_to(external_root)
    assert validate_marketplace(tmp_path, __version__).diagnostics[0].code == "SCM1001"


def test_rejects_nonportable_names_and_duplicate_or_self_dependencies(
    tmp_path: Path,
) -> None:
    _write_plugin(tmp_path, "valid-name")
    _write_plugin(
        tmp_path,
        "duplicate-dependency",
        dependencies=[
            {"name": "valid-name", "version": f"={__version__}"},
            {"name": "valid-name", "version": f"={__version__}"},
        ],
    )
    _write_plugin(
        tmp_path,
        "self-dependency",
        dependencies=[{"name": "self-dependency", "version": f"={__version__}"}],
    )
    _write_marketplace(
        tmp_path,
        [
            {"name": "Invalid_Name", "source": "./plugins/valid-name"},
            {
                "name": "duplicate-dependency",
                "source": "./plugins/duplicate-dependency",
            },
            {
                "name": "self-dependency",
                "source": "./plugins/self-dependency",
            },
        ],
    )

    codes = {
        item.code for item in validate_marketplace(tmp_path, __version__).diagnostics
    }
    assert {"SCM1002", "SCM1006"} <= codes


def test_rejects_path_outside_root_and_invalid_exact_dependency_version(
    tmp_path: Path,
) -> None:
    assert not _no_symlink_path(tmp_path, tmp_path.parent)
    _write_plugin(
        tmp_path,
        "bad-version",
        dependencies=[{"name": "valid-name", "version": "not-exact"}],
    )
    _write_marketplace(
        tmp_path,
        [{"name": "bad-version", "source": "./plugins/bad-version"}],
    )

    assert "SCM1006" in {
        item.code for item in validate_marketplace(tmp_path, __version__).diagnostics
    }
