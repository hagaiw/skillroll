"""Load the fixed model-facing prompt resources shipped with SkillRoll."""

from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Literal

PromptName = Literal["executor", "executor_omission", "world", "judge"]

_PROMPT_PATHS: dict[PromptName, tuple[str, ...]] = {
    "executor": ("executor-prompt", "references", "system.md"),
    "executor_omission": ("executor-prompt", "references", "omission.md"),
    "world": ("world-simulator-prompt", "references", "system.md"),
    "judge": ("semantic-judge-prompt", "references", "system.md"),
}


def _read(path: Path | Traversable) -> str | None:
    """Read one packaged resource without accepting a caller-provided path."""
    if not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if not value.strip():
        return None
    # Markdown files conventionally end with a newline; prompt contracts use
    # the historical no-trailing-newline form so existing requests stay byte
    # stable after extraction from Python.
    return value.rstrip("\n")


def load_harness_prompt(name: PromptName) -> str:
    """Return one fixed prompt contract from the installed package resources.

    Source checkouts use the exact repository path for the same resources until
    a wheel is built. This fallback is deterministic and actor-specific; the
    runtime never searches a configured skills repository or discovers files by
    name. A built installation must contain the force-included package copy.
    """
    parts = _PROMPT_PATHS[name]
    packaged = resources.files("skillroll").joinpath("_harness_prompts", *parts)
    value = _read(packaged)
    if value is not None:
        return value

    checkout = (
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "harness-prompts"
        / "skills"
        / parts[0]
        / parts[1]
        / parts[2]
    )
    value = _read(checkout)
    if value is not None:
        return value
    raise RuntimeError(
        f"SkillRoll's packaged harness prompt resource is unavailable: {name}."
    )
