from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ROOT

from skillroll import prompt_resources
from skillroll.prompt_resources import load_harness_prompt
from skillroll.runtime.execution import (
    omitted_skill_instructions,
    text_only_omitted_skill_instructions,
    text_only_wrapped_instructions,
    wrapped_instructions,
)
from skillroll.world import model as world_model

_PLUGIN_PROMPTS = {
    "executor": "plugins/harness-prompts/skills/executor-prompt/references/system.md",
    "executor_omission": (
        "plugins/harness-prompts/skills/executor-prompt/references/omission.md"
    ),
    "executor_text_only": (
        "plugins/harness-prompts/skills/executor-prompt/references/text-only.md"
    ),
    "executor_text_only_omission": (
        "plugins/harness-prompts/skills/executor-prompt/references/text-only-omission.md"
    ),
    "world": (
        "plugins/harness-prompts/skills/world-simulator-prompt/references/system.md"
    ),
    "judge": (
        "plugins/harness-prompts/skills/semantic-judge-prompt/references/system.md"
    ),
}


def test_runtime_prompt_resources_match_reviewable_harness_skills() -> None:
    """The packaged runtime contracts stay visible beside their dogfood evals."""
    for name, relative in _PLUGIN_PROMPTS.items():
        assert load_harness_prompt(name) == (ROOT / relative).read_text(
            encoding="utf-8"
        ).rstrip("\n")

    assert load_harness_prompt("world") == world_model._SYSTEM


def test_executor_contract_keeps_dynamic_skill_text_at_the_call_site() -> None:
    instructions = wrapped_instructions("A selected skill body.")
    assert instructions == load_harness_prompt("executor") + "\nA selected skill body."
    assert omitted_skill_instructions() == load_harness_prompt("executor_omission")
    assert text_only_omitted_skill_instructions() == load_harness_prompt(
        "executor_text_only_omission"
    )
    assert text_only_wrapped_instructions("raw").endswith("raw")
    assert "no tools" in load_harness_prompt("executor_text_only")
    assert "Success criteria" not in load_harness_prompt("executor")
    assert "evals/" not in load_harness_prompt("executor")


def test_judge_contract_is_loaded_without_case_or_criteria_text() -> None:
    prompt = load_harness_prompt("judge")
    assert "Success criteria" in prompt
    assert "Return exactly one JSON object" in prompt
    assert "bounded-world-action.eval.md" not in prompt
    assert "No open incidents found" not in prompt
    assert "A promise or offer to do work later" in prompt
    assert "contradicts the claimed evidence" in prompt
    assert "Do not repair code" in prompt
    assert "an empty action transcript does not erase" in prompt
    assert "When a criterion requires factual accuracy" in prompt
    assert "Do not create an external-grounding requirement" in prompt
    assert "may be established by the Final output itself" in prompt
    assert "timing, quantity, cause, and attribution" in prompt


def test_semantic_judge_dogfood_skill_cannot_delegate_its_decision() -> None:
    skill = (
        ROOT / "plugins/harness-prompts/skills/semantic-judge-prompt/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "**Instruction-only boundary:**" in skill
    assert "Do not call `world_action`" in skill
    assert "returned prose is not judge evidence" in skill


def test_prompt_resources_are_regular_repository_files() -> None:
    for relative in _PLUGIN_PROMPTS.values():
        path = ROOT / Path(relative)
        assert path.is_file() and not path.is_symlink()


def test_prompt_loader_handles_empty_invalid_and_missing_resources(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.md"
    empty = tmp_path / "empty.md"
    invalid = tmp_path / "invalid.md"
    empty.write_text("\n", encoding="utf-8")
    invalid.write_bytes(b"\xff")

    assert prompt_resources._read(missing) is None
    assert prompt_resources._read(empty) is None
    assert prompt_resources._read(invalid) is None


def test_prompt_loader_uses_packaged_resources_before_source_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packaged = (
        tmp_path
        / "package"
        / "_harness_prompts"
        / "world-simulator-prompt"
        / "references"
    )
    packaged.mkdir(parents=True)
    source = ROOT / _PLUGIN_PROMPTS["world"]
    (packaged / "system.md").write_text(
        source.read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(
        prompt_resources.resources,
        "files",
        lambda _package: tmp_path / "package",
    )

    assert load_harness_prompt("world") == source.read_text(encoding="utf-8").rstrip(
        "\n"
    )


def test_prompt_loader_uses_only_exact_source_fallback_or_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        prompt_resources.resources,
        "files",
        lambda _package: ROOT / "not-a-packaged-resource",
    )
    assert load_harness_prompt("world") == (ROOT / _PLUGIN_PROMPTS["world"]).read_text(
        encoding="utf-8"
    ).rstrip("\n")

    monkeypatch.setattr(prompt_resources, "_read", lambda _path: None)
    with pytest.raises(RuntimeError, match="packaged harness prompt"):
        load_harness_prompt("world")
