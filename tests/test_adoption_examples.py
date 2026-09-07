"""Offline contracts for the checked-in adoption examples."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

from conftest import run_module
from markdown_it import MarkdownIt

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples"
NORMALIZER = (
    EXAMPLES
    / "prompt-reference-script-composition"
    / "skills"
    / "prompt-reference-script-composition"
    / "scripts"
    / "normalize-headings.py"
)


def test_each_example_validates_without_inference() -> None:
    for name in (
        "release-action-boundary",
        "support-text-judgment",
        "prompt-reference-script-composition",
    ):
        repository = EXAMPLES / name
        config = tomllib.loads(
            (repository / "skillroll.toml").read_text(encoding="utf-8")
        )
        assert config == {"schema_version": 1, "skills_path": "skills"}

        completed = run_module(
            "--output=json",
            "validate",
            "--repo",
            str(repository),
            "--all",
        )
        assert completed.returncode == 0, completed.stderr


def test_lead_fixtures_are_outside_discovery_root() -> None:
    example = EXAMPLES / "release-action-boundary"
    weak = example / "lead-weak.SKILL.md"
    repaired = example / "lead-repaired.SKILL.md"
    discovered = example / "skills" / "release-action-boundary" / "SKILL.md"

    assert weak.is_file()
    assert repaired.is_file()
    assert not weak.is_relative_to(example / "skills")
    assert not repaired.is_relative_to(example / "skills")
    assert "independent approval" in discovered.read_text(encoding="utf-8")
    assert "independent approval" not in weak.read_text(encoding="utf-8")
    assert "independent approval" in repaired.read_text(encoding="utf-8")

    completed = run_module("--output=json", "validate", "--repo", str(example), "--all")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["data"]["skills"] == ["release-action-boundary"]


def test_reddit_example_has_a_self_contained_first_use_path() -> None:
    readme = (EXAMPLES / "release-action-boundary" / "README.md").read_text(
        encoding="utf-8"
    )

    assert "skillroll validate --all" in readme
    assert (
        "skillroll eval --case release-action-boundary/evals/ci-still-running.eval.md"
    ) in readme
    assert "does not prove that a model follows the skill" in readme


def run_normalizer(text: str, working_directory: Path) -> str:
    completed = subprocess.run(
        [sys.executable, str(NORMALIZER)],
        cwd=working_directory,
        input=text.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    return completed.stdout.decode("utf-8")


def test_normalizer_is_utf8_idempotent_and_preserves_trailing_newline(
    tmp_path: Path,
) -> None:
    source = (
        "  ##  Café and 東京  ##  \nplain # text\n####### too many markers\n\n###\n"
    )
    normalized = run_normalizer(source, tmp_path)

    assert normalized == (
        "  ## Café and 東京  ##\nplain # text\n####### too many markers\n\n### \n"
    )
    assert normalized.endswith("\n")
    assert run_normalizer(normalized, tmp_path) == normalized


def test_normalizer_handles_empty_input_and_no_trailing_newline_outside_checkout(
    tmp_path: Path,
) -> None:
    assert run_normalizer("", tmp_path) == ""
    assert run_normalizer("# Heading ###", tmp_path) == "# Heading ###"
    assert run_normalizer("  # Heading  ###  ", tmp_path) == "  # Heading  ###"
    assert run_normalizer("# A#  # #", tmp_path) == "# A#  # #"
    assert not any(tmp_path.iterdir())


def test_normalizer_preserves_code_and_markdown_meaning(tmp_path: Path) -> None:
    source = (
        "# A#  # #\r\n"
        "    # indented code\r\n"
        "```shell\r\n"
        "##  fenced heading\r\n"
        "```\r\n"
        "## Heading ###\r\n"
    )
    normalized = run_normalizer(source, tmp_path)

    assert normalized == (
        "# A#  # #\r\n"
        "    # indented code\r\n"
        "```shell\r\n"
        "##  fenced heading\r\n"
        "```\r\n"
        "## Heading ###\r\n"
    )
    renderer = MarkdownIt("commonmark")
    assert renderer.render(normalized) == renderer.render(source)


def test_normalizer_preserves_nested_headings_and_raw_html(tmp_path: Path) -> None:
    source = (
        "1. Item\n\n"
        "   ##  Detail\n\n"
        "   more text\n\n"
        "<script>\n"
        "##  script content\n\n"
        "</script>\n\n"
        "<div>\n"
        "##  raw block content\n\n"
        "##  Real heading\n"
    )
    normalized = run_normalizer(source, tmp_path)

    assert "   ## Detail\n" in normalized
    assert "##  script content\n" in normalized
    assert "##  raw block content\n" in normalized
    assert normalized.endswith("## Real heading\n")
    renderer = MarkdownIt("commonmark")
    assert renderer.render(normalized) == renderer.render(source)
