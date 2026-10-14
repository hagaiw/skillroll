"""Candidate preparation never promotes old evidence or edits provider versions."""

from __future__ import annotations

import json
import runpy
import sys
import tomllib
from pathlib import Path

import pytest

from tools.prepare_release import main, prepare


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    files = {
        "src/skillroll/_version.py": '__version__ = "0.1.2"\n',
        "plugins/flow-runner/.claude-plugin/plugin.json": (
            '{"name":"flow-runner","version":"0.1.2"}'
        ),
        "plugins/demo/.claude-plugin/plugin.json": (
            '{"name":"demo","version":"0.1.2","dependencies":['
            '{"name":"flow-runner","version":"=0.1.2"},'
            '{"name":"other","version":"=0.1.2"}]}'
        ),
        "uv.lock": (
            'version = 1\n[[package]]\nname = "other"\nversion = "0.1.2"\n'
            '[[package]]\nname = "skillroll"\nversion = "0.1.2"\n'
            'source = { editable = "." }\n[[package]]\nname = "last"\n'
            'version = "0.1.2"\n'
        ),
        "release-gates.toml": 'schema_version = 1\nversion = "0.1.2"\n',
        "README.md": (
            "hagaiw/skillroll@v0.1.2\nother@v0.1.2\nhagaiw/skillroll@v0.1.20\n"
        ),
        "docs/setup.md": "hagaiw/skillroll@v0.1.2\n",
        "examples/hello/README.md": "hagaiw/skillroll@v0.1.2\n",
        ".github/workflows/a.yml": "uses: hagaiw/skillroll@v0.1.2\n",
        ".github/workflows/b.yaml": "uses: hagaiw/skillroll@v0.1.2\n",
        "tests/provider.json": '{"version":"0.1.2"}',
    }
    root = tmp_path / "checkout"
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return root


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize(
    ("bump", "version", "expected"),
    [
        ("patch", None, "0.1.3"),
        ("minor", None, "0.2.0"),
        ("major", None, "1.0.0"),
        ("patch", "0.2.0rc1", "0.2.0rc1"),
    ],
)
def test_prepares_lockstep_metadata_and_clears_evidence(
    checkout: Path, bump: str, version: str | None, expected: str
) -> None:
    before = snapshot(checkout)
    result = prepare(checkout, bump, version)
    assert result["version"] == expected
    assert result["tag"] == f"v{expected}"
    assert result["prerelease"] == (version is not None)
    assert result["plugin_tags"] == [f"demo--v{expected}", f"flow-runner--v{expected}"]
    assert (
        checkout / "src/skillroll/_version.py"
    ).read_text() == f'__version__ = "{expected}"\n'
    manifest = json.loads(
        (checkout / "plugins/demo/.claude-plugin/plugin.json").read_text()
    )
    assert manifest["version"] == expected
    assert manifest["dependencies"] == [
        {"name": "flow-runner", "version": f"={expected}"},
        {"name": "other", "version": "=0.1.2"},
    ]
    lock = tomllib.loads((checkout / "uv.lock").read_text())
    assert [item["version"] for item in lock["package"]] == ["0.1.2", expected, "0.1.2"]
    assert snapshot(checkout)["tests/provider.json"] == before["tests/provider.json"]
    assert (
        (checkout / "README.md").read_text()
        == f"hagaiw/skillroll@v{expected}\nother@v0.1.2\nhagaiw/skillroll@v0.1.20\n"
    )
    for relative in (
        "docs/setup.md",
        "examples/hello/README.md",
        ".github/workflows/a.yml",
        ".github/workflows/b.yaml",
    ):
        assert f"hagaiw/skillroll@v{expected}" in (checkout / relative).read_text()
    gates = tomllib.loads((checkout / "release-gates.toml").read_text())
    assert gates["version"] == expected
    assert {gate["name"] for gate in gates["gates"]} == {
        "installed-live-e2e",
        "claude-dependency-install",
    }
    assert all(gate["state"] == "BLOCKED" for gate in gates["gates"])


def test_dynamic_lock_entry_stays_dynamic(checkout: Path) -> None:
    path = checkout / "uv.lock"
    path.write_text('[[package]]\nname = "skillroll"\nsource = { editable = "." }\n')
    before = path.read_bytes()
    prepare(checkout)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "version",
    [
        "0.1.2",
        "0.1.1",
        "v0.2.0",
        "0.2",
        "00.2.0",
        "0.2.0-dev",
        "0.2.0rc01",
        "0.2.0rc0",
        "0.2.0a1",
        "0.2.0b1",
        "0.2.0\n",
        "0.2.0; bad",
    ],
)
def test_invalid_target_never_mutates(checkout: Path, version: str) -> None:
    before = snapshot(checkout)
    with pytest.raises(ValueError):
        prepare(checkout, version=version)
    assert snapshot(checkout) == before


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        ("src/skillroll/_version.py", "bad"),
        ("src/skillroll/_version.py", '__version__ = "bad"\n'),
        ("plugins/demo/.claude-plugin/plugin.json", "[]"),
        (
            "plugins/demo/.claude-plugin/plugin.json",
            '{"version":"0.1.2","dependencies":{}}',
        ),
        (
            "plugins/demo/.claude-plugin/plugin.json",
            '{"version":"0.1.2","dependencies":[1]}',
        ),
        (
            "plugins/demo/.claude-plugin/plugin.json",
            '{"version":"0.1.2","dependencies":[{"name":"flow-runner","version":"=0.0.1"}]}',
        ),
        (
            "plugins/demo/.claude-plugin/plugin.json",
            '{"name":"wrong","version":"0.1.2"}',
        ),
        ("uv.lock", '[[package]]\nname = "other"\n'),
        (
            "uv.lock",
            '[[package]]\nname = "skillroll"\nversion = "9.9.9"\n'
            'source = { editable = "." }\n',
        ),
        (
            "uv.lock",
            '[[package]]\nname = "skillroll"\nsource = { registry = "other" }\n',
        ),
        (
            "uv.lock",
            '[[package]]\nname = "skillroll"\nsource = { editable = "." }\n'
            '[[package]]\nname = "skillroll"\nsource = { editable = "." }\n',
        ),
        ("uv.lock", "not = [toml"),
        ("uv.lock", "package = {}"),
        ("uv.lock", "package = [1]"),
    ],
)
def test_bad_checkout_never_partially_mutates(
    checkout: Path, relative: str, source: str
) -> None:
    (checkout / relative).write_text(source)
    before = snapshot(checkout)
    with pytest.raises(ValueError):
        prepare(checkout)
    assert snapshot(checkout) == before


def test_missing_input_and_invalid_bump_are_safe(checkout: Path) -> None:
    before = snapshot(checkout)
    with pytest.raises(ValueError, match="bump"):
        prepare(checkout, "bad")
    assert snapshot(checkout) == before
    (checkout / "README.md").unlink()
    before = snapshot(checkout)
    with pytest.raises(ValueError, match="regular file"):
        prepare(checkout)
    assert snapshot(checkout) == before


def test_no_plugins_and_invalid_root(checkout: Path, tmp_path: Path) -> None:
    for path in checkout.glob("plugins/*/.claude-plugin/plugin.json"):
        path.unlink()
    with pytest.raises(ValueError, match="no plugin"):
        prepare(checkout)
    with pytest.raises(ValueError, match="root"):
        prepare(tmp_path / "missing")
    with pytest.raises(ValueError, match="root"):
        prepare(Path(tmp_path.resolve().anchor))
    # A slash-only Windows root is drive-relative until resolved.
    with pytest.raises(ValueError, match="root"):
        prepare(Path("/"))


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows symlinks need special privilege"
)
@pytest.mark.parametrize("kind", ["root", "file", "directory"])
def test_symlinks_are_rejected_without_mutating_target(
    checkout: Path, tmp_path: Path, kind: str
) -> None:
    before = snapshot(checkout)
    root = checkout
    if kind == "root":
        root = tmp_path / "alias"
        root.symlink_to(checkout, target_is_directory=True)
    elif kind == "file":
        path = checkout / "README.md"
        target = tmp_path / "readme"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
    else:
        path = checkout / "docs"
        path.rename(tmp_path / "docs")
        path.symlink_to(tmp_path / "docs", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink|root"):
        prepare(root)
    # The canonical source has never changed, even when a later input is unsafe.
    assert (checkout / "src/skillroll/_version.py").read_bytes() == before[
        "src/skillroll/_version.py"
    ]


def test_cli_json_output_and_entrypoint(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--root", str(checkout), "--bump", "minor"]) == 0
    assert json.loads(capsys.readouterr().out)["version"] == "0.2.0"
    monkeypatch.setattr(sys, "argv", ["prepare_release.py", "--root", str(checkout)])
    monkeypatch.delitem(sys.modules, "tools.prepare_release", raising=False)
    with pytest.raises(SystemExit) as raised:
        runpy.run_module("tools.prepare_release", run_name="__main__")
    assert raised.value.code == 0
    assert json.loads(capsys.readouterr().out)["version"] == "0.2.1"


def test_cli_failure_returns_two(checkout: Path) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--root", str(checkout), "--version", "bad"])
    assert raised.value.code == 2


def test_lock_whitespace_and_quotes_do_not_hide_version(checkout: Path) -> None:
    lock = checkout / "uv.lock"
    lock.write_text(
        "[[package]]\nname='skillroll'\nversion='0.1.2'\nsource={editable='.'}\n"
    )
    prepare(checkout)
    assert tomllib.loads(lock.read_text())["package"][0]["version"] == "0.1.3"


def test_unsafe_plugin_directory_is_rejected(checkout: Path) -> None:
    manifest = checkout / "plugins/bad+name/.claude-plugin/plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"name":"bad+name","version":"0.1.2"}')
    before = snapshot(checkout)
    with pytest.raises(ValueError, match="unsafe"):
        prepare(checkout)
    assert snapshot(checkout) == before


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows symlinks need special privilege"
)
def test_outer_directory_alias_resolves_to_checkout(
    checkout: Path, tmp_path: Path
) -> None:
    alias = tmp_path / "outer-alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    assert prepare(alias / "checkout")["version"] == "0.1.3"
    assert (
        '__version__ = "0.1.3"' in (checkout / "src/skillroll/_version.py").read_text()
    )
