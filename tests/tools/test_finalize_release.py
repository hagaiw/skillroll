"""Only complete passing integration receipts can promote candidate release gates."""

from __future__ import annotations

import hashlib
import json
import runpy
import sys
import tomllib
from pathlib import Path

import pytest

from tools.finalize_release import finalize, main

SHA = "a" * 40
URL = "https://github.com/hagaiw/skillroll/actions/runs/123"
LIVE = "test_existing_marketplace_user_journey_with_real_inference"
CLAUDE = "test_official_cli_installs_the_exact_tagged_dependency"


@pytest.fixture
def candidate(tmp_path: Path) -> Path:
    (tmp_path / "src/skillroll").mkdir(parents=True)
    (tmp_path / "src/skillroll/_version.py").write_text('__version__ = "0.2.0rc1"\n')
    (tmp_path / "release-gates.toml").write_text('state = "BLOCKED"\n')
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist/skillroll-0.2.0rc1-py3-none-any.whl").write_bytes(b"wheel")
    (tmp_path / "dist/skillroll-0.2.0rc1.tar.gz").write_bytes(b"sdist")
    for name, case in (("live.xml", LIVE), ("claude.xml", CLAUDE)):
        (tmp_path / name).write_text(
            '<testsuites><testsuite tests="1" errors="0" failures="0" skipped="0">'
            f'<testcase name="{case}"/></testsuite></testsuites>'
        )
    return tmp_path


def run(checkout: Path, **changes: object) -> dict[str, str]:
    arguments = {
        "root": checkout,
        "live_report": checkout / "live.xml",
        "claude_report": checkout / "claude.xml",
        "candidate_commit": SHA,
        "run_url": URL,
        "artifacts": checkout / "dist",
    }
    arguments.update(changes)
    return finalize(**arguments)  # type: ignore[arg-type]


def test_records_fresh_version_commit_run_and_exact_wheel(candidate: Path) -> None:
    result = run(candidate)
    digest = hashlib.sha256(b"wheel").hexdigest()
    assert result == {"version": "0.2.0rc1", "wheel_sha256": digest}
    gates = tomllib.loads((candidate / "release-gates.toml").read_text())
    assert gates["schema_version"] == 1
    assert gates["version"] == "0.2.0rc1"
    assert [gate["name"] for gate in gates["gates"]] == [
        "installed-live-e2e",
        "claude-dependency-install",
    ]
    for gate in gates["gates"]:
        assert gate["state"] == "PASS"
        assert (
            SHA in gate["detail"] and URL in gate["detail"] and digest in gate["detail"]
        )


@pytest.mark.parametrize("receipt", ["live.xml", "claude.xml"])
@pytest.mark.parametrize(
    "contents",
    [
        "not XML",
        "<wrong/>",
        "<testsuites/>",
        '<testsuites><testcase name="CASE"/></testsuites>',
        '<testsuite><testcase name="wrong"/></testsuite>',
        '<testsuite><testcase name="CASE"/><testcase name="CASE"/></testsuite>',
        '<testsuite><testcase name="CASE"><failure/></testcase></testsuite>',
        '<testsuite><testcase name="CASE"><error/></testcase></testsuite>',
        '<testsuite><testcase name="CASE"><skipped/></testcase></testsuite>',
        '<testsuite failures="1"><testcase name="CASE"/></testsuite>',
        '<testsuite errors="1"><testcase name="CASE"/></testsuite>',
        '<testsuite skipped="1"><testcase name="CASE"/></testsuite>',
        '<testsuite tests="2"><testcase name="CASE"/></testsuite>',
    ],
)
def test_false_receipt_never_promotes_gates(
    candidate: Path, receipt: str, contents: str
) -> None:
    expected = LIVE if receipt == "live.xml" else CLAUDE
    (candidate / receipt).write_text(contents.replace("CASE", expected))
    before = (candidate / "release-gates.toml").read_bytes()
    with pytest.raises(ValueError):
        run(candidate)
    assert (candidate / "release-gates.toml").read_bytes() == before


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("candidate_commit", "a" * 39),
        ("candidate_commit", "A" * 40),
        ("candidate_commit", "a" * 41),
        ("candidate_commit", "b;command"),
        ("run_url", "https://github.com/other/skillroll/actions/runs/123"),
        ("run_url", URL + "\n"),
        ("run_url", "http://github.com/hagaiw/skillroll/actions/runs/123"),
        ("run_url", "https://github.com/hagaiw/skillroll/actions/runs/0"),
    ],
)
def test_unsafe_candidate_binding_is_rejected(
    candidate: Path, argument: str, value: str
) -> None:
    before = (candidate / "release-gates.toml").read_bytes()
    with pytest.raises(ValueError):
        run(candidate, **{argument: value})
    assert (candidate / "release-gates.toml").read_bytes() == before


def test_full_sha256_commit_is_supported(candidate: Path) -> None:
    run(candidate, candidate_commit="b" * 64)
    assert "b" * 64 in (candidate / "release-gates.toml").read_text()


@pytest.mark.parametrize(
    "name",
    [
        "live.xml",
        "claude.xml",
        "src/skillroll/_version.py",
        "dist/skillroll-0.2.0rc1-py3-none-any.whl",
        "dist/skillroll-0.2.0rc1.tar.gz",
    ],
)
def test_missing_receipt_or_artifact_is_blocking(candidate: Path, name: str) -> None:
    (candidate / name).unlink()
    with pytest.raises(ValueError):
        run(candidate)
    assert (candidate / "release-gates.toml").read_text() == 'state = "BLOCKED"\n'


@pytest.mark.parametrize(
    "text",
    [
        "bad",
        '__version__ = "bad"\n',
        '__version__ = "0.2.0rc1"\n__version__ = "0.3.0"\n',
    ],
)
def test_invalid_canonical_version_is_blocking(candidate: Path, text: str) -> None:
    (candidate / "src/skillroll/_version.py").write_text(text)
    with pytest.raises(ValueError):
        run(candidate)
    assert (candidate / "release-gates.toml").read_text() == 'state = "BLOCKED"\n'


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("skillroll-0.2.0rc1-py3-none-any.whl", "other-0.2.0rc1-py3-none-any.whl"),
        ("skillroll-0.2.0rc1-py3-none-any.whl", "skillroll-0.1.2-py3-none-any.whl"),
        ("skillroll-0.2.0rc1.tar.gz", "other-0.2.0rc1.tar.gz"),
        ("skillroll-0.2.0rc1.tar.gz", "skillroll-0.1.2.tar.gz"),
        ("skillroll-0.2.0rc1-py3-none-any.whl", "invalid.whl"),
        ("skillroll-0.2.0rc1.tar.gz", "invalid.tar.gz"),
    ],
)
def test_wrong_artifact_name_is_blocking(candidate: Path, old: str, new: str) -> None:
    (candidate / "dist" / old).rename(candidate / "dist" / new)
    with pytest.raises(ValueError):
        run(candidate)
    assert (candidate / "release-gates.toml").read_text() == 'state = "BLOCKED"\n'


@pytest.mark.parametrize("name", ["other-0.1.0-py3-none-any.whl", "other-0.1.0.tar.gz"])
def test_extra_artifact_is_blocking(candidate: Path, name: str) -> None:
    (candidate / "dist" / name).write_bytes(b"extra")
    with pytest.raises(ValueError):
        run(candidate)


def test_missing_root_gates_and_artifact_directory(candidate: Path) -> None:
    with pytest.raises(ValueError, match="root"):
        run(candidate, root=candidate / "missing")
    with pytest.raises(ValueError, match="directory"):
        run(candidate, artifacts=candidate / "missing")
    (candidate / "release-gates.toml").unlink()
    with pytest.raises(ValueError, match="regular"):
        run(candidate)


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows symlinks need special privilege"
)
@pytest.mark.parametrize(
    "name",
    [
        "root",
        "src",
        "src/skillroll/_version.py",
        "release-gates.toml",
        "live.xml",
        "dist",
        "dist/skillroll-0.2.0rc1-py3-none-any.whl",
        "dist/skillroll-0.2.0rc1.tar.gz",
    ],
)
def test_symlink_inputs_are_blocking(candidate: Path, name: str) -> None:
    target = candidate / name if name != "root" else candidate
    alias = candidate.parent / ("aliased-" + target.name)
    target.rename(alias)
    target.symlink_to(alias, target_is_directory=alias.is_dir())
    with pytest.raises(ValueError):
        run(candidate)
    actual_gates = (
        alias
        if name == "release-gates.toml"
        else (
            alias / "release-gates.toml"
            if name == "root"
            else candidate / "release-gates.toml"
        )
    )
    assert actual_gates.read_text() == 'state = "BLOCKED"\n'


def cli(root: Path) -> list[str]:
    return [
        "--root",
        str(root),
        "--live-report",
        str(root / "live.xml"),
        "--claude-report",
        str(root / "claude.xml"),
        "--candidate-commit",
        SHA,
        "--run-url",
        URL,
        "--artifacts",
        str(root / "dist"),
    ]


def test_cli_and_module_entrypoint(
    candidate: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(cli(candidate)) == 0
    assert json.loads(capsys.readouterr().out)["version"] == "0.2.0rc1"
    monkeypatch.setattr(sys, "argv", ["finalize_release.py", *cli(candidate)])
    monkeypatch.delitem(sys.modules, "tools.finalize_release", raising=False)
    with pytest.raises(SystemExit) as raised:
        runpy.run_module("tools.finalize_release", run_name="__main__")
    assert raised.value.code == 0


def test_cli_failure_exits_two(candidate: Path) -> None:
    (candidate / "live.xml").write_text("bad")
    with pytest.raises(SystemExit) as raised:
        main(cli(candidate))
    assert raised.value.code == 2
