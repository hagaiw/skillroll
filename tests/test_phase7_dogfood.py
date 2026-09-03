from __future__ import annotations

import json

from conftest import ROOT

from skillroll import __version__
from skillroll.commands import validate
from skillroll.marketplace import validate_marketplace
from skillroll.outcomes import Outcome
from skillroll.validation import validate_repository

EXPECTED_PLUGINS = {
    "flow-runner": ("flow-runner",),
    "change-review-flow": (
        "change-review-flow",
        "summarize-change",
        "assess-risk",
        "produce-review",
    ),
    "pr-overview": ("pr-overview",),
    "skillroll-authoring": ("skillroll-setup", "eval-author", "skill-improver"),
    "fact-check": ("fact-check",),
    "harness-prompts": (
        "executor-prompt",
        "world-simulator-prompt",
        "semantic-judge-prompt",
    ),
}

REQUIRED_REFERENCES = {
    (plugin, skill): "references/context.md"
    for plugin, skills in EXPECTED_PLUGINS.items()
    for skill in skills
}
REQUIRED_REFERENCES[("skillroll-authoring", "skill-improver")] = (
    "references/decision-map.md"
)


def test_dogfood_marketplace_has_the_exact_plugin_and_skill_inventory() -> None:
    report = validate_marketplace(ROOT, __version__)

    assert report.is_valid
    assert {item.name for item in report.plugins} == set(EXPECTED_PLUGINS)
    for plugin, expected_skills in EXPECTED_PLUGINS.items():
        root = ROOT / "plugins" / plugin / "skills"
        assert tuple(
            sorted(path.name for path in root.iterdir() if path.is_dir())
        ) == tuple(sorted(expected_skills))
        manifest = json.loads(
            (ROOT / "plugins" / plugin / ".claude-plugin" / "plugin.json").read_text()
        )
        assert manifest["version"] == __version__


def test_dogfood_skills_and_cases_validate_without_making_marketplace_required() -> (
    None
):
    report = validate_repository(ROOT)

    assert report.config is not None
    assert report.config.skills_path.as_posix() == "plugins"
    assert report.config.inference is not None
    assert report.config.inference.model == "openai/gpt-4.1-nano"
    assert not report.findings
    assert len(report.skills) == 14
    assert len(report.cases) == 48


def test_agentic_skills_link_required_references_without_review_leakage() -> None:
    runner = (
        (ROOT / "plugins/flow-runner/skills/flow-runner/SKILL.md")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "references/context.md" in runner
    assert "skill` action" in runner
    assert '{"name":"summarize-change"}' in runner
    assert "review" not in runner
    for plugin, skills in EXPECTED_PLUGINS.items():
        for skill in skills:
            path = ROOT / "plugins" / plugin / "skills" / skill / "SKILL.md"
            content = path.read_text(encoding="utf-8")
            assert content.startswith("---\nname: ")
            reference = REQUIRED_REFERENCES[(plugin, skill)]
            assert reference in content
            assert (path.parent / reference).is_file()


def test_setup_skill_gives_weaker_models_a_direct_first_use_path() -> None:
    content = (
        ROOT / "plugins/skillroll-authoring/skills/skillroll-setup/SKILL.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(content.split())
    assert "**Instruction-only skill:**" in content
    assert "do not call `Skill`, `Read`, `Write`, or any other tool" in normalized
    assert "## First-use path" in content
    assert "`skillroll init --skills-path <skills-folder> --yes`" in content
    assert (
        "`init` and `validate` do not need a configuration file or API key" in content
    )
    assert "does not execute them or simulate setup" in content
    assert "with a `Skill` action" in content


def test_dogfood_declared_renderer_check_runs_when_explicitly_permitted() -> None:
    result = validate.run(repo=str(ROOT), run_commands=True)

    assert result.outcome is Outcome.PASS
    assert result.summary == "Validated 14 skills and ran 3 repository checks."
