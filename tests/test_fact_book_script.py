"""Deterministic contracts for the fact-check helper script."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[1]
    / "plugins"
    / "fact-check"
    / "skills"
    / "fact-check"
    / "scripts"
    / "fact_book.py"
)


def fact_book_module():
    spec = importlib.util.spec_from_file_location("fact_book", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_valid_sample_and_lifecycle_replacements() -> None:
    module = fact_book_module()
    valid = module._sample_book()
    assert module.validate_text(valid) == []
    replacement = valid.replace(
        "- Statement: The value is 1.",
        """- Status: superseded
- Updated: 2026-08-19
- Statement: The value was 1.""",
    )
    assert module.validate_text(replacement)


def test_validator_rejects_empty_sources_and_record_content_outside_heading() -> None:
    module = fact_book_module()
    valid = module._sample_book()
    empty_source = valid.replace(
        "- Source: file: example.py#L1 — value = 1", "- Source: "
    )
    outside_heading = valid.replace(
        "### R-001 — Stable fact",
        "- Statement: this is outside a record\n\n### R-001 — Stable fact",
    )
    assert any(
        "concrete Source" in error for error in module.validate_text(empty_source)
    )
    assert any(
        "under a valid R-### heading" in error
        for error in module.validate_text(outside_heading)
    )


def test_validator_rejects_duplicate_and_invalid_supersedes_targets() -> None:
    module = fact_book_module()
    valid = module._sample_book()
    record = valid[valid.index("### R-001 — Stable fact") :]
    duplicate = valid + "\n" + record
    missing = valid.replace(
        "- Statement: The value is 1.",
        "- Supersedes: R-999\n- Statement: The value is 1.",
    )
    self_reference = valid.replace(
        "- Statement: The value is 1.",
        "- Supersedes: R-001\n- Statement: The value is 1.",
    )
    assert any("repeated" in error for error in module.validate_text(duplicate))
    assert any(
        "target R-999 is missing" in error for error in module.validate_text(missing)
    )
    assert any(
        "cannot refer to itself" in error
        for error in module.validate_text(self_reference)
    )


def test_validator_rejects_obvious_date_order_errors() -> None:
    module = fact_book_module()
    invalid = module._sample_book().replace(
        "- Created: 2026-08-18", "- Created: 2026-08-19", 1
    )
    errors = module.validate_text(invalid)
    assert any("Created cannot be after Updated" in error for error in errors)
    invalid_session = module._sample_book().replace(
        "- Started: 2026-08-18", "- Started: 2026-08-19"
    )
    assert any(
        "Started cannot be after Last updated" in error
        for error in module.validate_text(invalid_session)
    )


def test_init_is_atomic_and_preserves_existing_book(tmp_path: Path) -> None:
    target = tmp_path / "FACTS.md"
    first = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "init",
            str(target),
            "--scope",
            "test scope",
            "--date",
            "2026-08-18",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    original = target.read_text(encoding="utf-8")
    second = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "init",
            str(target),
            "--scope",
            "replacement",
            "--date",
            "2026-08-19",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0
    assert "Initialized" in first.stdout
    assert second.returncode == 2
    assert target.read_text(encoding="utf-8") == original
