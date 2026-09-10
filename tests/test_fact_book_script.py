"""Deterministic contracts for the fact-check helper script."""

from __future__ import annotations

import datetime as dt
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

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
    assert "- Scope: test scope" in original
    assert "- Started: 2026-08-18" in original
    assert "- Last updated: 2026-08-18" in original
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


def conclusion_book() -> str:
    valid = fact_book_module()._sample_book()
    return (
        valid
        + """
### R-002 — Value is positive

- Kind: conclusion
- Status: active
- Confidence: high
- Created: 2026-08-18
- Updated: 2026-08-18
- Last verified: 2026-08-18
- Derived from: R-001
- Reasoning: R-001 establishes value = 1; 1 is greater than zero.
- Context: The test scope.
- Statement: The value is positive.
"""
    )


def test_record_kinds_and_legacy_compatibility() -> None:
    module = fact_book_module()
    for kind in ("fact", "lead", "attribution"):
        book = module._sample_book().replace("- Status:", f"- Kind: {kind}\n- Status:")
        assert module.validate_text(book) == []
    assert module.validate_text(module._sample_book()) == []
    assert module.validate_text(conclusion_book()) == []
    invalid = module._sample_book().replace("- Status:", "- Kind: analysis\n- Status:")
    assert any("Kind" in error for error in module.validate_text(invalid))


@pytest.mark.parametrize("dependency", ["R-999", "R-002", "bad", "R-001, R-001", ""])
def test_conclusion_rejects_invalid_dependencies(dependency: str) -> None:
    book = conclusion_book().replace(
        "Derived from: R-001", f"Derived from: {dependency}"
    )
    assert fact_book_module().validate_text(book)


@pytest.mark.parametrize("kind", ["lead", "attribution"])
def test_conclusion_cannot_promote_unverified_premises(kind: str) -> None:
    book = conclusion_book().replace("- Status:", f"- Kind: {kind}\n- Status:", 1)
    assert any("premise" in error for error in fact_book_module().validate_text(book))


def test_conclusion_requires_reasoning_and_active_premises() -> None:
    module = fact_book_module()
    book = conclusion_book()
    assert module.validate_text(book.replace("- Reasoning:", "- Note:"))
    stale = book.replace("- Status: active", "- Status: stale", 1)
    assert any("active" in error for error in module.validate_text(stale))
    assert (
        module.validate_text(stale.replace("- Status: active", "- Status: stale")) == []
    )


def test_conclusion_cycles_and_transitive_dependencies() -> None:
    module = fact_book_module()
    book = conclusion_book()
    record = book[book.index("### R-002") :].replace("R-002", "R-003")
    chain = book + record.replace("Derived from: R-001", "Derived from: R-002")
    assert module.validate_text(chain) == []
    cycle = chain.replace("Derived from: R-001", "Derived from: R-003")
    assert any("cycle" in error for error in module.validate_text(cycle))


def test_human_config_provenance_is_not_independent_verification() -> None:
    module = fact_book_module()
    pasted = module._sample_book().replace(
        "file: example.py#L1 — value = 1",
        "`human-config: operator console` — pasted value = 1",
    )
    assert module.validate_text(pasted)
    medium = pasted.replace("Confidence: high", "Confidence: medium")
    assert any("Note" in error for error in module.validate_text(medium))
    assert (
        module.validate_text(medium + "- Note: Reproduce by reading the console.\n")
        == []
    )
    attributed = pasted.replace("- Status:", "- Kind: attribution\n- Status:")
    assert module.validate_text(attributed) == []


def test_warnings_are_opt_in_date_bounded_and_non_mutating(tmp_path: Path) -> None:
    module = fact_book_module()
    book = module._sample_book() + "- Review by: 2026-08-19\n"
    target = tmp_path / "FACTS.md"
    target.write_text(book)
    assert module.validate_text(book) == []
    assert module.warning_messages(book, dt.date(2026, 8, 19)) == []
    assert len(module.warning_messages(book, dt.date(2026, 8, 20))) == 1
    for status in ("stale", "disputed", "superseded"):
        assert (
            module.warning_messages(
                book.replace("Status: active", f"Status: {status}"),
                dt.date(2026, 8, 20),
            )
            == []
        )
    for options in ([], ["--warn", "--as-of", "2026-08-20"]):
        run = subprocess.run(
            [sys.executable, str(SCRIPT), "check", str(target), *options],
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0
        assert ("WARN" in run.stderr) == bool(options)
    assert target.read_text() == book


def test_absolute_helper_from_unrelated_workspace(tmp_path: Path) -> None:
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "init", "FACTS.md", "--scope", "workspace test"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0
    checked = subprocess.run(
        [sys.executable, str(SCRIPT), "check", "FACTS.md"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0


def test_warnings_preserve_structural_errors_and_reject_bad_dates(
    tmp_path: Path,
) -> None:
    target = tmp_path / "FACTS.md"
    target.write_text(fact_book_module()._sample_book() + "- Supersedes: R-999\n")
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "check", str(target), "--warn"],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1
    assert "target R-999 is missing" in run.stderr
    for date in ("2026-02-30", "20260820", "tomorrow"):
        run = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "check",
                str(target),
                "--warn",
                "--as-of",
                date,
            ],
            capture_output=True,
            text=True,
        )
        assert run.returncode == 2
        assert "--as-of must be an ISO date" in run.stderr


def test_missing_review_deadline_does_not_invent_expiry() -> None:
    module = fact_book_module()
    for suffix in ("", "- Review by: not set\n"):
        assert (
            module.warning_messages(module._sample_book() + suffix, dt.date(2099, 1, 1))
            == []
        )


def test_conclusion_does_not_accept_empty_optional_source_or_fact_derivation() -> None:
    module = fact_book_module()
    assert module.validate_text(conclusion_book() + "- Source: \n")
    assert module.validate_text(module._sample_book() + "- Derived from: R-001\n")
