"""Focused boundaries for Phase 1 config, discovery, parser, and guards."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from skillroll.config import load_config
from skillroll.discovery import discover_case_files, discover_skills
from skillroll.evals import parse_eval_case
from skillroll.models import Skill
from skillroll.validation import (
    command_result,
    selection_from_strings,
    validate_repository,
)


def write_config(root: Path, content: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "skillroll.toml").write_text(content, encoding="utf-8")
    (root / "skills").mkdir(exist_ok=True)
    return root


@pytest.mark.parametrize(
    "content, code",
    [
        ('schema_version = 2\nskills_path = "skills"\n', "SCG1001"),
        ('schema_version = 1\nskills_path = "../skills"\n', "SCG1002"),
        ('schema_version = 1\nskills_path = "skills"\nunknown = 1\n', "SCG1001"),
        (
            'schema_version = 1\nskills_path = "skills"\n\n[guards]\n'
            'disabled = ["SCG1003"]\n',
            "SCG1001",
        ),
        (
            'schema_version = 1\nskills_path = "skills"\n\n[inference]\n'
            'base_url = "ftp://bad"\nmodel = "m"\napi_key_env = "1BAD"\n',
            "SCG1001",
        ),
    ],
)
def test_config_rejects_invalid_inputs(tmp_path: Path, content: str, code: str) -> None:
    result = load_config(write_config(tmp_path / "repository", content))
    assert result.value is None
    assert result.diagnostics[0].code == code


def test_config_accepts_all_optional_values_without_reading_environment(
    tmp_path: Path,
) -> None:
    root = write_config(
        tmp_path / "repository",
        """schema_version = 1
skills_path = "skills"

[guards]
disabled = ["SCG2001"]

[inference]
base_url = "https://example.test/v1"
model = "small"
api_key_env = "DO_NOT_READ"
""",
    )
    result = load_config(root)
    assert result.value is not None
    assert "SCG2001" in result.value.guards.disabled
    assert result.value.inference is not None
    assert result.value.inference.api_key_env == "DO_NOT_READ"


def make_skill(root: Path, name: str = "review") -> Skill:
    skill_root = root / "skills" / name
    (skill_root / "evals").mkdir(parents=True)
    skill_file = skill_root / "SKILL.md"
    skill_file.write_text("# Skill\n", encoding="utf-8")
    return Skill(
        name,
        PurePosixPath(name),
        skill_root,
        skill_file,
        skill_root / "evals",
    )


def valid_case() -> str:
    return """# Friendly title

```skillroll
schema_version: 1
```

## Input

Do the thing.

## World

The world is small.

## Success criteria

- Finish correctly.
"""


def test_discovery_is_nested_sorted_and_skips_hidden_directories(
    tmp_path: Path,
) -> None:
    root = write_config(
        tmp_path / "repository", 'schema_version = 1\nskills_path = "skills"\n'
    )
    make_skill(root, "zebra")
    nested = make_skill(root, "alpha")
    (root / "skills" / ".hidden").mkdir()
    (root / "skills" / ".hidden" / "SKILL.md").write_text("ignored", encoding="utf-8")
    config = load_config(root).value
    assert config is not None
    result = discover_skills(config)
    assert [skill.identity.as_posix() for skill in result.skills] == ["alpha", "zebra"]
    assert nested.name == "alpha"


def test_parser_accepts_valid_case_and_rejects_metadata_and_sections(
    tmp_path: Path,
) -> None:
    root = write_config(
        tmp_path / "repository", 'schema_version = 1\nskills_path = "skills"\n'
    )
    skill = make_skill(root)
    path = skill.evals_directory / "example.eval.md"
    path.write_text(valid_case(), encoding="utf-8")
    parsed = parse_eval_case(path, skill)
    assert parsed.value is not None
    assert parsed.value.title == "Friendly title"
    assert parsed.value.identity.as_posix() == "review/evals/example.eval.md"
    path.write_text(
        "```skillroll\nschema_version: 1\nunknown: value\n```\n\n## Input\n\nx\n",
        encoding="utf-8",
    )
    invalid = parse_eval_case(path, skill)
    assert invalid.value is None
    assert {item.code for item in invalid.diagnostics} == {"SCG1005"}


def test_parser_accepts_repository_relative_check_paths_and_direct_case_discovery(
    tmp_path: Path,
) -> None:
    root = write_config(
        tmp_path / "repository", 'schema_version = 1\nskills_path = "skills"\n'
    )
    skill = make_skill(root)
    (skill.root / "scripts").mkdir()
    (skill.root / "scripts" / "render.py").write_text("pass\n", encoding="utf-8")
    direct = skill.evals_directory / "direct.eval.md"
    direct.write_text(
        valid_case().replace(
            "schema_version: 1",
            "schema_version: 1\nchecks:\n  - name: Test renderer\n"
            "    command: pytest scripts/render.py\n"
            "    covers: [scripts/render.py]",
        ),
        encoding="utf-8",
    )
    nested = skill.evals_directory / "nested"
    nested.mkdir()
    (nested / "ignored.eval.md").write_text(valid_case(), encoding="utf-8")
    assert discover_case_files(skill) == (direct,)
    parsed = parse_eval_case(direct, skill)
    assert parsed.value is not None
    assert parsed.value.checks[0].covers == (PurePosixPath("scripts/render.py"),)


def test_markdown_links_do_not_gate_validation(tmp_path: Path) -> None:
    root = write_config(
        tmp_path / "repository", 'schema_version = 1\nskills_path = "skills"\n'
    )
    skill = make_skill(root)
    skill.skill_file.write_text("[next](references/a.md)\n", encoding="utf-8")
    references = skill.root / "references"
    references.mkdir()
    (references / "a.md").write_text("[back](a.md)\n", encoding="utf-8")
    result = validate_repository(root)
    assert all(finding.guard_id == "SCG2001" for finding in result.findings)
    skill.skill_file.write_text("[missing](references/no.md)\n", encoding="utf-8")
    assert all(
        finding.guard_id == "SCG2001" for finding in validate_repository(root).findings
    )


def test_minimum_case_guard_distinguishes_zero_cases_from_one(tmp_path: Path) -> None:
    root = write_config(
        tmp_path / "repository", 'schema_version = 1\nskills_path = "skills"\n'
    )
    empty = make_skill(root, "empty")
    covered = make_skill(root, "covered")
    (covered.evals_directory / "one.eval.md").write_text(valid_case(), encoding="utf-8")

    findings = {
        finding.diagnostic.affected: finding.diagnostic
        for finding in validate_repository(root).findings
        if finding.guard_id == "SCG2001"
    }

    assert findings[empty.name].summary == "The 'empty' skill has no valid eval cases."
    assert "Add a focused" in (findings[empty.name].next_action or "")
    assert findings[covered.name].summary == (
        "The 'covered' skill has fewer than two valid eval cases."
    )
    assert "one case is still runnable" in (findings[covered.name].next_action or "")


def test_declared_check_can_cover_safe_missing_non_script_path(tmp_path: Path) -> None:
    root = write_config(
        tmp_path / "repository", 'schema_version = 1\nskills_path = "skills"\n'
    )
    skill = make_skill(root)
    path = skill.evals_directory / "example.eval.md"
    path.write_text(
        valid_case().replace(
            "schema_version: 1",
            "schema_version: 1\nchecks:\n  - name: generated artifact\n"
            "    command: python tools/render.py\n"
            "    covers: [tools/render.py]",
        ),
        encoding="utf-8",
    )
    parsed = parse_eval_case(path, skill)
    assert parsed.value is not None
    assert parsed.value.checks[0].covers == (PurePosixPath("tools/render.py"),)


def test_selection_paths_and_outcomes_are_reported(tmp_path: Path) -> None:
    root = write_config(
        tmp_path / "repository", 'schema_version = 1\nskills_path = "skills"\n'
    )
    skill = make_skill(root)
    for name in ("one", "two"):
        (skill.evals_directory / f"{name}.eval.md").write_text(
            valid_case(), encoding="utf-8"
        )
    result = command_result(
        validate_repository(root, selection_from_strings("review", None))
    )
    assert result.outcome.name == "PASS"
    unsafe = command_result(
        validate_repository(root, selection_from_strings("../review", None))
    )
    assert unsafe.outcome.name == "ERROR"
    assert selection_from_strings(None, "review/evals/one.eval.md").case is not None


def test_case_limits_are_checked_against_configured_profile_offline(
    tmp_path: Path,
) -> None:
    root = write_config(
        tmp_path / "repository",
        """schema_version = 1
skills_path = "skills"

[inference]
base_url = "https://example.test/v1"
model = "small"
api_key_env = "DO_NOT_READ"

[inference.limits]
max_turns = 2
timeout_seconds = 30
max_output_tokens = 256
""",
    )
    skill = make_skill(root)
    path = skill.evals_directory / "over-limit.eval.md"
    path.write_text(
        valid_case().replace(
            "schema_version: 1", "schema_version: 1\nlimits: {max_turns: 3}"
        ),
        encoding="utf-8",
    )
    report = validate_repository(root)
    assert any(
        finding.guard_id == "SCG1005"
        and "above the configured" in finding.diagnostic.summary
        for finding in report.findings
    )
    assert command_result(report).outcome.name == "FAIL"


def test_case_limits_are_not_checked_without_inference_profile(tmp_path: Path) -> None:
    root = write_config(
        tmp_path / "repository",
        'schema_version = 1\nskills_path = "skills"\n',
    )
    skill = make_skill(root)
    (skill.evals_directory / "over-limit.eval.md").write_text(
        valid_case().replace(
            "schema_version: 1", "schema_version: 1\nlimits: {max_turns: 32}"
        ),
        encoding="utf-8",
    )
    report = validate_repository(root)
    assert not any(finding.guard_id == "SCG1005" for finding in report.findings)
