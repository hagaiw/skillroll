"""Direct boundary tests for the Phase 1 validation building blocks.

These tests deliberately exercise author mistakes and filesystem failures that
are awkward to express through the command-line integration examples.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from skillroll import cli
from skillroll.config import load_config
from skillroll.discovery import discover_case_files, discover_skills
from skillroll.evals import parse_eval_case
from skillroll.markdown import first_metadata_fence, local_links, sections, title
from skillroll.models import InferenceSettings, Selection, Skill
from skillroll.paths import parse_relative_path, repository_identity, resolve_child
from skillroll.repository_io import (
    is_directory,
    is_regular,
    is_symlink,
    link_is_safe,
    readable_utf8,
    sorted_entries,
)
from skillroll.safe_yaml import MetadataError, load_metadata
from skillroll.validation import (
    command_result,
    selection_from_strings,
    validate_repository,
)


def write_config(
    root: Path, content: str = 'schema_version = 1\nskills_path = "skills"\n'
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "skillroll.toml").write_text(content, encoding="utf-8")
    (root / "skills").mkdir(exist_ok=True)
    return root


def make_skill(root: Path, name: str = "review") -> Skill:
    directory = root / "skills" / name
    (directory / "evals").mkdir(parents=True)
    skill_file = directory / "SKILL.md"
    skill_file.write_text("# Review\n", encoding="utf-8")
    return Skill(name, PurePosixPath(name), directory, skill_file, directory / "evals")


def case_source(metadata: str = "schema_version: 1") -> str:
    return (
        "# Case\n\n```skillroll\n"
        f"{metadata}\n"
        "```\n\n## Input\n\ninput\n\n## World\n\nworld\n"
        "\n## Success criteria\n\ncriterion\n"
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "../skills",
        "/skills",
        "skills\\review",
        "skills\x00review",
        "./skills",
        "skills//nested",
    ],
)
def test_path_parser_rejects_each_nonportable_or_unsafe_form(value: str) -> None:
    assert parse_relative_path(value) is None


def test_path_helpers_resolve_only_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "a" / "b"
    inside.mkdir(parents=True)
    assert resolve_child(root, PurePosixPath("a/b")) == inside.resolve()
    assert resolve_child(root, PurePosixPath("../outside")) is None
    assert repository_identity(root, inside) == PurePosixPath("a/b")


@pytest.mark.parametrize(
    "content",
    [
        'schema_version = true\nskills_path = "skills"\n',
        "schema_version = 1\nskills_path = 3\n",
        (
            'schema_version = 1\nskills_path = "skills"\n\n[guards]\n'
            'disabled = "SCG2001"\n'
        ),
        (
            'schema_version = 1\nskills_path = "skills"\n\n[inference]\n'
            'base_url = "https://x"\nmodel = "m"\n'
        ),
    ],
)
def test_config_rejects_remaining_schema_branches(tmp_path: Path, content: str) -> None:
    assert load_config(write_config(tmp_path / "repo", content)).value is None


def test_config_reports_non_directory_and_unreadable_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    assert load_config(root).value is None
    write_config(root)
    (root / "skills").rmdir()
    assert load_config(root).value is None
    monkeypatch.setattr(Path, "read_bytes", lambda _: (_ for _ in ()).throw(OSError()))
    assert load_config(root).value is None


def test_config_reports_invalid_utf8_and_toml(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "skillroll.toml").write_bytes(b"\xff")
    assert load_config(root).value is None
    (root / "skillroll.toml").write_text("not = [toml", encoding="utf-8")
    assert load_config(root).value is None


def test_config_accepts_valid_inference_and_default_guards(tmp_path: Path) -> None:
    root = write_config(
        tmp_path / "repo",
        """schema_version = 1
skills_path = "skills"

[inference]
base_url = "https://example.test/path"
model = "model"
api_key_env = "KEY_2"
""",
    )
    result = load_config(root)
    assert result.is_valid
    assert result.value is not None
    assert result.value.inference == InferenceSettings(
        "https://example.test/path", "model", "KEY_2"
    )


def test_config_rejects_removed_reference_guard(tmp_path: Path) -> None:
    root = write_config(
        tmp_path / "repo",
        'schema_version = 1\nskills_path = "skills"\n\n[guards]\n'
        "max_reference_depth = true\n",
    )
    result = load_config(root)
    assert result.value is None


def test_config_rejects_a_non_mapping_guards_value(tmp_path: Path) -> None:
    root = write_config(
        tmp_path / "repo", 'schema_version = 1\nskills_path = "skills"\nguards = 1\n'
    )
    assert load_config(root).value is None


def test_discovery_detects_duplicates_missing_and_symlinks(tmp_path: Path) -> None:
    root = write_config(tmp_path / "repo")
    make_skill(root, "one")
    make_skill(root / "skills" / "nested", "one")
    internal_target = root / "skills" / "one" / "SKILL.md"
    (root / "skills" / "internal-link").symlink_to(internal_target)
    (root / "skills" / "external-link").symlink_to(tmp_path / "outside")
    config = load_config(root).value
    assert config is not None
    result = discover_skills(config)
    assert [skill.identity.as_posix() for skill in result.skills] == [
        "nested/skills/one",
        "one",
    ]
    assert len(result.diagnostics) == 1
    assert result.skipped_safe_symlinks == (PurePosixPath("skills/internal-link"),)


def test_discovery_reports_an_empty_skills_directory(tmp_path: Path) -> None:
    root = write_config(tmp_path / "repo")
    config = load_config(root).value
    assert config is not None
    assert discover_skills(config).diagnostics[0].code == "SCG1004"


def test_discovery_case_directory_symlink_and_non_regular_entries(
    tmp_path: Path,
) -> None:
    root = write_config(tmp_path / "repo")
    skill = make_skill(root)
    (skill.evals_directory / "a.eval.md").mkdir()
    (skill.evals_directory / "link.eval.md").symlink_to(skill.skill_file)
    assert discover_case_files(skill) == ()
    (skill.evals_directory / "a.eval.md").rmdir()
    (skill.evals_directory / "link.eval.md").unlink()
    skill.evals_directory.rmdir()
    skill.evals_directory.symlink_to(skill.root)
    assert discover_case_files(skill) == ()


@pytest.mark.parametrize(
    "metadata",
    [
        "schema_version: 1\nchecks: bad",
        "schema_version: 1\nchecks:\n- name: x\n  command: x",
        "schema_version: 1\nchecks:\n- name: x\n  command: x\n  covers: []",
    ],
)
def test_eval_parser_rejects_invalid_checks(tmp_path: Path, metadata: str) -> None:
    root = write_config(tmp_path / "repo")
    skill = make_skill(root)
    path = skill.evals_directory / "case.eval.md"
    path.write_text(case_source(metadata), encoding="utf-8")
    assert parse_eval_case(path, skill).value is None


def test_eval_parser_catches_repeated_checks_and_covers_and_missing_fence(
    tmp_path: Path,
) -> None:
    root = write_config(tmp_path / "repo")
    skill = make_skill(root)
    (skill.root / "scripts").mkdir()
    (skill.root / "scripts" / "x.py").write_text("", encoding="utf-8")
    path = skill.evals_directory / "case.eval.md"
    path.write_text(
        case_source(
            "schema_version: 1\nchecks:\n- name: x\n  command: x\n"
            "  covers: [scripts/x.py, scripts/x.py]\n- name: x\n"
            "  command: x\n  covers: [scripts/x.py]"
        ),
        encoding="utf-8",
    )
    assert parse_eval_case(path, skill).value is None


def test_eval_parser_accepts_missing_safe_check_cover(tmp_path: Path) -> None:
    root = write_config(tmp_path / "repo")
    skill = make_skill(root)
    path = skill.evals_directory / "case.eval.md"
    path.write_text(
        case_source(
            "schema_version: 1\nchecks:\n- name: generated\n"
            "  command: python tools/render.py\n"
            "  covers: [tools/render.py]"
        ),
        encoding="utf-8",
    )
    parsed = parse_eval_case(path, skill)
    assert parsed.value is not None


@pytest.mark.parametrize("cover", ["../outside.py", "/absolute.py", "tools/*.py"])
def test_eval_parser_rejects_unsafe_check_cover_paths(
    tmp_path: Path, cover: str
) -> None:
    root = write_config(tmp_path / "repo")
    skill = make_skill(root)
    path = skill.evals_directory / "case.eval.md"
    path.write_text(
        case_source(
            "schema_version: 1\nchecks:\n- name: unsafe\n"
            "  command: python tools/render.py\n"
            f"  covers: [{cover}]"
        ),
        encoding="utf-8",
    )
    assert parse_eval_case(path, skill).value is None


def test_eval_parser_reports_invalid_yaml_metadata(tmp_path: Path) -> None:
    root = write_config(tmp_path / "repo")
    skill = make_skill(root)
    path = skill.evals_directory / "case.eval.md"
    path.write_text(case_source("schema_version: ["), encoding="utf-8")
    assert parse_eval_case(path, skill).value is None
    path.write_text("## Input\n\nx\n", encoding="utf-8")
    assert parse_eval_case(path, skill).value is None


def test_eval_parser_detects_size_read_failure_multiple_fences_and_empty_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_config(tmp_path / "repo")
    skill = make_skill(root)
    path = skill.evals_directory / "case.eval.md"
    path.write_text(
        case_source() + "\n```skillroll\nschema_version: 1\n```", encoding="utf-8"
    )
    assert parse_eval_case(path, skill).value is None
    path.write_text(case_source().replace("\nworld\n", "\n\n"), encoding="utf-8")
    assert parse_eval_case(path, skill).value is None
    monkeypatch.setattr("skillroll.evals.readable_utf8", lambda _: None)
    assert parse_eval_case(path, skill).value is None


def test_eval_parser_rejects_large_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_config(tmp_path / "repo")
    skill = make_skill(root)
    monkeypatch.setattr(
        "skillroll.evals.readable_utf8", lambda _: "x" * (1024 * 1024 + 1)
    )
    assert parse_eval_case(skill.evals_directory / "case.eval.md", skill).value is None


@pytest.mark.parametrize(
    "source, expected",
    [
        ("# Title\n\n```skillroll\na: 1\n```", True),
        ("text\n\n```skillroll\na: 1\n```", False),
        ("# Title\n\n```yaml\na: 1\n```", False),
    ],
)
def test_markdown_fence_positions(source: str, expected: bool) -> None:
    assert (first_metadata_fence(source) is not None) is expected


def test_markdown_sections_title_and_local_links() -> None:
    source = (
        "# T\n\n## A\n\na\n\n## A\n\nb\n\n[ok](a%20b.md?q#x) "
        "[web](https://x) [anchor](#a) [root](/a)"
    )
    assert sections(source)["A"] == ("", 7)
    assert title(source) == "T"
    assert local_links(source) == ("a b.md",)
    assert title("## no title") is None


def test_markdown_ignores_link_tokens_without_a_text_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Link:
        type = "link_open"

        def attrGet(self, _: str) -> None:
            return None

    class EmptyLink:
        type = "link_open"

        def attrGet(self, _: str) -> str:
            return "?query"

    class Inline:
        type = "inline"
        children = [Link(), EmptyLink()]

    monkeypatch.setattr("skillroll.markdown.tokens", lambda _: (Inline(),))
    assert local_links("ignored") == ()


def test_markdown_section_scan_ignores_a_heading_without_source_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Heading:
        type = "heading_open"
        tag = "h2"

        def __init__(self, source_map: list[int] | None) -> None:
            self.map = source_map

    monkeypatch.setattr(
        "skillroll.markdown.tokens", lambda _: (Heading([0, 1]), Heading(None))
    )
    assert sections("## Input\n\ntext")["Input"] == ("text", 1)


@pytest.mark.parametrize(
    "source",
    [
        "a: &x value\nb: *x",
        "a: 1\na: 2",
        "[one, two",
        "---\na: 1\n---\na: 2",
        "- list",
    ],
)
def test_safe_yaml_rejects_unsafe_or_wrong_shape(source: str) -> None:
    with pytest.raises(MetadataError):
        load_metadata(source)


def test_safe_yaml_accepts_mapping_and_limits_size_and_depth() -> None:
    assert load_metadata("schema_version: 1") == {"schema_version": 1}
    with pytest.raises(MetadataError):
        load_metadata("x" * (64 * 1024 + 1))
    nested = "x: " * 21 + "1"
    with pytest.raises(MetadataError):
        load_metadata(nested)
    too_many = "\n".join(f"key{index}: {index}" for index in range(1001))
    with pytest.raises(MetadataError):
        load_metadata(too_many)


def test_safe_yaml_rejects_non_text_keys_and_defensive_non_mapping_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(MetadataError):
        load_metadata("1: value")
    monkeypatch.setattr("skillroll.safe_yaml.yaml.load", lambda *_, **__: [])
    with pytest.raises(MetadataError):
        load_metadata("key: value")


def test_external_missing_cyclic_and_deep_links_do_not_gate_validation(
    tmp_path: Path,
) -> None:
    root = write_config(tmp_path / "repo")
    skill = make_skill(root)
    references = skill.root / "references"
    references.mkdir()
    skill.skill_file.write_text(
        "[missing](missing.md) [sibling](../other/reference.md) "
        "[a](references/a.md) [cycle](references/cycle-a.md)",
        encoding="utf-8",
    )
    (references / "a.md").write_text("[b](b.md)", encoding="utf-8")
    (references / "b.md").write_text("end", encoding="utf-8")
    (references / "cycle-a.md").write_text("[b](cycle-b.md)", encoding="utf-8")
    (references / "cycle-b.md").write_text("[a](cycle-a.md)", encoding="utf-8")
    current = references / "deep-start.md"
    skill.skill_file.write_text(
        skill.skill_file.read_text(encoding="utf-8")
        + " [deep](references/deep-start.md)",
        encoding="utf-8",
    )
    for index in range(8):
        next_path = references / f"deep-{index}.md"
        current.write_text(f"[next]({next_path.name})", encoding="utf-8")
        current = next_path
    current.write_text("end", encoding="utf-8")
    report = validate_repository(root)
    assert not any(finding.guard_id == "SCG1006" for finding in report.findings)


def test_one_case_is_advice_and_script_files_do_not_create_findings(
    tmp_path: Path,
) -> None:
    root = write_config(tmp_path / "repo")
    skill = make_skill(root)
    (skill.root / "scripts").mkdir()
    (skill.root / "scripts" / "x.py").write_text("", encoding="utf-8")
    (skill.evals_directory / "one.eval.md").write_text(case_source(), encoding="utf-8")
    report = validate_repository(root)
    result = command_result(report)
    assert result.outcome.name == "PASS"
    assert any(finding.is_advisory for finding in report.findings)
    assert result.data["advice"][0]["next_action"]
    assert result.data["blocking_problems"] == ()


def test_skipped_external_symlink_is_advice_not_a_gate(tmp_path: Path) -> None:
    root = write_config(tmp_path / "repo")
    make_skill(root)
    (tmp_path / "outside").mkdir()
    (root / "skills" / "external-link").symlink_to(tmp_path / "outside")
    config = load_config(root).value
    assert config is not None
    report = validate_repository(root)
    result = command_result(report)
    assert result.outcome.name == "PASS"
    assert any(item.code == "SCG1003" for item in result.diagnostics)


def test_selected_symlink_remains_blocked(tmp_path: Path) -> None:
    root = write_config(tmp_path / "repo")
    make_skill(root)
    (root / "skills" / "link").symlink_to(root / "skills" / "review")
    result = command_result(
        validate_repository(root, selection_from_strings("link", None))
    )
    assert result.outcome.name == "ERROR"


def test_repository_io_handles_missing_paths_and_links(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert sorted_entries(missing) == ()
    assert (
        not is_regular(missing)
        and not is_directory(missing)
        and not is_symlink(missing)
    )
    assert readable_utf8(missing) is None
    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_text("ok", encoding="utf-8")
    link = root / "link"
    link.symlink_to(target)
    assert link_is_safe(root, link)


def test_repository_io_handles_os_errors_and_reports_current_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "x"
    monkeypatch.setattr(Path, "is_symlink", lambda _: (_ for _ in ()).throw(OSError()))
    assert not is_symlink(path)
    monkeypatch.setattr(
        Path, "resolve", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError())
    )
    assert not link_is_safe(path, path)
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *_, **__: (_ for _ in ()).throw(
            UnicodeDecodeError("utf-8", b"x", 0, 1, "bad")
        ),
    )
    assert readable_utf8(path) is None
    monkeypatch.setattr("skillroll.repository_io.os.getcwd", lambda: "/current")
    from skillroll.repository_io import current_directory

    assert current_directory() == Path("/current")


def test_validation_selection_error_case_selection_and_command_summary(
    tmp_path: Path,
) -> None:
    root = write_config(tmp_path / "repo")
    skill = make_skill(root)
    for name in ("one", "two"):
        (skill.evals_directory / f"{name}.eval.md").write_text(
            case_source(), encoding="utf-8"
        )
    case_report = validate_repository(
        root, selection_from_strings(None, "review/evals/one.eval.md")
    )
    assert len(case_report.cases) == 1
    missing_report = validate_repository(root, Selection(PurePosixPath("missing")))
    assert command_result(missing_report).outcome.name == "ERROR"
    unsafe_backslash = validate_repository(
        root, selection_from_strings("review\\nested", None)
    )
    assert command_result(unsafe_backslash).outcome.name == "ERROR"
    missing_case = validate_repository(
        root, selection_from_strings(None, "review/evals/missing.eval.md")
    )
    assert command_result(missing_case).outcome.name == "ERROR"


def test_validation_collects_invalid_case_without_reference_policy(
    tmp_path: Path,
) -> None:
    root = write_config(tmp_path / "repo")
    skill = make_skill(root)
    (skill.evals_directory / "bad.eval.md").write_text("not an eval", encoding="utf-8")
    references = skill.root / "references"
    references.mkdir()
    skill.skill_file.write_text("[a](references/a.md)", encoding="utf-8")
    (references / "a.md").write_text("[b](b.md)", encoding="utf-8")
    (references / "b.md").write_text("ok", encoding="utf-8")
    report = validate_repository(root)
    assert any(finding.guard_id == "SCG1005" for finding in report.findings)
    assert not any(finding.guard_id == "SCG1006" for finding in report.findings)


def test_validation_reports_disabled_policy_in_direct_summary(tmp_path: Path) -> None:
    root = write_config(
        tmp_path / "repo",
        (
            'schema_version = 1\nskills_path = "skills"\n\n[guards]\n'
            'disabled = ["SCG2001"]\n'
        ),
    )
    skill = make_skill(root)
    (skill.evals_directory / "one.eval.md").write_text(case_source(), encoding="utf-8")
    result = command_result(validate_repository(root))
    assert "Disabled policy guards: SCG2001." in result.summary


def test_validation_reports_each_disabled_policy_once(tmp_path: Path) -> None:
    root = write_config(
        tmp_path / "repo",
        (
            'schema_version = 1\nskills_path = "skills"\n\n[guards]\n'
            'disabled = ["SCG2001"]\n'
        ),
    )
    for name in ("one", "two"):
        skill = make_skill(root, name)
        (skill.evals_directory / "case.eval.md").write_text(
            case_source(), encoding="utf-8"
        )
    result = command_result(validate_repository(root))
    assert result.data["disabled_guards"] == ("SCG2001",)
    assert result.summary.count("SCG2001") == 1


def test_cli_validate_direct_and_unimplemented_command_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = cli.main(
        ["validate", "--repo", "/definitely/missing"], stdout=None, stderr=None
    )
    assert result == 3
    monkeypatch.setattr(cli, "COMMANDS", {})
    assert cli.main(["eval"], stdout=None, stderr=None) == 3
