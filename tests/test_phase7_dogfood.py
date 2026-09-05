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
    "skillroll-authoring": ("skillroll-setup", "skill-author", "eval-author"),
    "fact-check": ("fact-check",),
    "harness-prompts": (
        "executor-prompt",
        "world-simulator-prompt",
        "semantic-judge-prompt",
    ),
    "blind-skillroll-evaluation": (
        "select-blind-targets",
        "prepare-blind-trial",
        "author-blind-evals",
        "run-blind-evals",
        "blind-skillroll-evaluation",
    ),
}


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
    assert report.config.inference.default_profile == "blind-live"
    assert report.config.inference.profiles["blind-live"].models == (
        "openai/gpt-5.6-luna-pro",
    )
    assert report.config.inference.profiles["muse-spark"].models == (
        "meta/muse-spark-1.3-contributor",
    )
    assert not report.findings
    assert len(report.skills) == 19
    assert len(report.cases) == 63


def test_agentic_skills_link_context_without_flow_runner_review_leakage() -> None:
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
            assert "references/context.md" in content
            assert (path.parent / "references/context.md").is_file()


def test_blind_evaluation_collection_keeps_phase_and_evidence_boundaries() -> None:
    root = ROOT / "plugins/blind-skillroll-evaluation/skills"
    expected_cases = {
        "select-blind-targets": {
            "preregister-before-results.eval.md",
            "small-repositories-over-fame.eval.md",
        },
        "prepare-blind-trial": {
            "advisory-ci-without-secret-leak.eval.md",
            "pin-local-main-and-target.eval.md",
        },
        "author-blind-evals": {
            "fresh-context-without-outcome-leakage.eval.md",
            "replace-starters-before-freeze.eval.md",
        },
        "run-blind-evals": {
            "live-inference-is-the-signal.eval.md",
            "rerun-only-authoring-defect.eval.md",
        },
        "blind-skillroll-evaluation": {
            "coordinate-independent-small-repo-trials.eval.md",
            "report-mixed-results-and-product-fix.eval.md",
        },
    }

    for skill, cases in expected_cases.items():
        assert {path.name for path in (root / skill / "evals").glob("*.eval.md")} == (
            cases
        )

    selection = (root / "select-blind-targets/SKILL.md").read_text().lower()
    preparation = (root / "prepare-blind-trial/SKILL.md").read_text().lower()
    authoring = (root / "author-blind-evals/SKILL.md").read_text().lower()
    running = (root / "run-blind-evals/SKILL.md").read_text().lower()
    campaign = (root / "blind-skillroll-evaluation/SKILL.md").read_text().lower()

    assert "before any run outcomes" in selection
    assert "current local skillroll main" in preparation
    assert "do not read previous skillroll reports" in authoring
    assert "only completed model-backed evals test skill behavior" in running
    assert "use the installed `flow-runner`" in campaign


def test_setup_skill_gives_weaker_models_a_direct_first_use_path() -> None:
    content = (
        ROOT / "plugins/skillroll-authoring/skills/skillroll-setup/SKILL.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(content.split())
    assert "**Instruction-only skill:**" in content
    assert "do not call `Skill`, `Write`, or an execution tool" in normalized
    assert "A bounded `Read`" in content
    assert "## First-use path" in content
    assert "`skillroll init --skills-path <skills-folder> --yes`" in content
    assert (
        "`init` and `validate` do not need a configuration file or API key" in content
    )
    assert "does not execute the commands or simulate setup" in normalized
    assert "with a `Skill` action" in normalized


def test_dogfood_declared_renderer_check_runs_when_explicitly_permitted() -> None:
    result = validate.run(repo=str(ROOT), run_commands=True)

    assert result.outcome is Outcome.PASS
    assert result.summary == "Validated 19 skills and ran 3 repository checks."
