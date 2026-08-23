from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from skillroll.diagnostics import (
    CommandResult,
    Diagnostic,
    SourceLocation,
    render_json,
    render_text,
)
from skillroll.outcomes import Outcome


def test_models_are_immutable_and_data_is_deeply_frozen() -> None:
    source = {"nested": [1, {"safe": True}]}
    result = CommandResult(Outcome.PASS, "done", data=source)
    source["new"] = "later"
    assert "new" not in result.data
    with pytest.raises(TypeError):
        result.data["new"] = "no"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.summary = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("bad", [{1: "value"}, {"x": object()}, []])
def test_result_rejects_non_json_data(bad: object) -> None:
    with pytest.raises(TypeError):
        CommandResult(Outcome.ERROR, "bad", data=bad)  # type: ignore[arg-type]


def test_text_renderer_includes_present_sections_in_order() -> None:
    result = CommandResult(
        Outcome.FAIL,
        "A check failed.",
        (
            Diagnostic(
                "SC0999",
                "A readable problem.",
                affected="example skill",
                location=SourceLocation("skills/example/SKILL.md", 4, 2),
                details=("first", "second"),
                risk="The skill may behave incorrectly.",
                next_action="Edit the named file.",
            ),
        ),
    )
    assert render_text(result) == (
        "FAIL — A check failed.\n\n"
        "[SC0999] A readable problem.\n"
        "Affected: example skill\n"
        "Location: skills/example/SKILL.md:4:2\n"
        "Details:\n  - first\n  - second\n"
        "Why: The skill may behave incorrectly.\n"
        "Next: Edit the named file.\n"
    )


def test_text_renderer_does_not_repeat_the_result_summary() -> None:
    result = CommandResult(
        Outcome.ERROR,
        "The command failed.",
        (Diagnostic("SC0001", "The command failed.", next_action="Try again."),),
    )

    assert render_text(result) == (
        "ERROR — The command failed.\n\n[SC0001]\nNext: Try again.\n"
    )


@pytest.mark.parametrize(
    ("location", "rendered"),
    [
        (SourceLocation(), "unknown location"),
        (SourceLocation("file.md"), "file.md"),
        (SourceLocation("file.md", 2), "file.md:2"),
        (SourceLocation("file.md", column=3), "file.md:?:3"),
    ],
)
def test_location_combinations_are_predictable(
    location: SourceLocation, rendered: str
) -> None:
    result = CommandResult(
        Outcome.ERROR, "stopped", (Diagnostic("SC", "problem", location=location),)
    )
    assert f"Location: {rendered}\n" in render_text(result)


def test_json_renderer_has_exact_shape_and_utf8() -> None:
    result = CommandResult(
        Outcome.PASS,
        "✓ ready",
        (Diagnostic("SC", "fine", details=("one",)),),
        {"items": [1, None]},
    )
    text = render_json(result)
    assert "✓" in text
    assert text.endswith("\n")
    assert list(json.loads(text)) == [
        "outcome",
        "exit_code",
        "summary",
        "diagnostics",
        "data",
    ]
    assert json.loads(text)["diagnostics"][0] == {
        "code": "SC",
        "summary": "fine",
        "affected": None,
        "location": None,
        "details": ["one"],
        "risk": None,
        "next_action": None,
    }


def test_json_renderer_serializes_a_full_location() -> None:
    result = CommandResult(
        Outcome.ERROR,
        "no",
        (Diagnostic("SC", "no", location=SourceLocation("x", 1, 2)),),
    )
    assert json.loads(render_json(result))["diagnostics"][0]["location"] == {
        "path": "x",
        "line": 1,
        "column": 2,
    }
