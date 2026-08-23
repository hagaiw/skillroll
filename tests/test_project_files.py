from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_python_and_package_metadata() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert (ROOT / ".python-version").read_text() == "3.12\n"
    assert project["project"]["requires-python"] == ">=3.12"
    assert project["project"]["dynamic"] == ["version"]
    assert project["project"]["license"] == "MIT"
    assert project["project"]["scripts"] == {"skillroll": "skillroll.cli:entrypoint"}
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/skillroll"
    ]
    assert project["tool"]["hatch"]["version"]["path"] == "src/skillroll/_version.py"
    assert set(project["dependency-groups"]["dev"]) == {
        "coverage[toml]>=7.15",
        "hatchling>=1.27",
        "mypy>=2.3",
        "pytest>=9.0",
        "ruff>=0.15",
        "hypothesis>=6.0",
        "types-PyYAML>=6.0",
    }


def test_coverage_configuration_has_no_exclusions() -> None:
    configuration = (ROOT / ".coveragerc").read_text()
    assert "branch = True" in configuration
    assert "src/skillroll" in configuration
    assert "tools" in configuration
    assert "fail_under = 100" in configuration
    assert "omit" not in configuration


def test_uv_lock_exists() -> None:
    assert (ROOT / "uv.lock").is_file()


def test_live_external_checks_are_separate_from_the_default_suite() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    pytest_options = project["tool"]["pytest"]["ini_options"]
    assert pytest_options["addopts"] == "-m 'not live and not external'"
    assert any(value.startswith("live:") for value in pytest_options["markers"])
    assert any(value.startswith("external:") for value in pytest_options["markers"])

    for relative, marker in {
        "tests/test_adoption_real_e2e.py": "@pytest.mark.live",
        "tests/test_phase7_live_e2e.py": "@pytest.mark.live",
        "tests/test_phase7_claude_cli_e2e.py": "@pytest.mark.external",
    }.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert marker in source
        assert "@pytest.mark.skipif" not in source


def test_security_policy_has_private_reporting_and_safe_disclosure_guidance() -> None:
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "security/advisories/new" in policy
    assert "7 calendar days" in policy
    assert "API keys" in policy
    assert "Supported versions" in policy


def test_public_docs_and_agent_indexes_keep_canonical_guides_discoverable() -> None:
    required = (
        "PHILOSOPHY.md",
        "README.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "GOVERNANCE.md",
        "SECURITY.md",
        "SUPPORT.md",
        ".github/CODEOWNERS",
        "docs/index.md",
        "docs/writing-evals.md",
        "docs/configuration.md",
        "docs/github-actions.md",
        "docs/results.md",
        "docs/security.md",
    )
    for relative in required:
        assert (ROOT / relative).is_file(), relative

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    docs_index = (ROOT / "docs/index.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert all(path in readme for path in ("docs/index.md", "CONTRIBUTING.md"))
    assert "PHILOSOPHY.md" in readme
    assert all(
        path in docs_index
        for path in (
            "writing-evals.md",
            "configuration.md",
            "github-actions.md",
            "results.md",
            "security.md",
        )
    )
    assert all(
        path in agents
        for path in (
            "PHILOSOPHY.md",
            "docs/index.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
        )
    )
    assert "AGENTS.md" in claude

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/internal/" in gitignore
    assert "internal/" not in readme
    assert "internal/" not in docs_index


def test_readme_inference_config_is_complete() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    inference_example = readme.split("Configure an OpenAI-compatible", 1)[1].split(
        "Export the configured key", 1
    )[0]
    assert "schema_version = 1" in inference_example
    assert 'skills_path = "skills"' in inference_example
    assert "[inference]" in inference_example


def test_eval_authoring_guide_nests_case_limits_under_limits_mapping() -> None:
    guide = (ROOT / "docs/writing-evals.md").read_text(encoding="utf-8")

    assert "limits:\n  max_turns: 4\n  timeout_seconds: 90" in guide
    assert "not valid\ntop-level metadata keys" in guide
    assert "schema_version: 1\nmax_turns:" not in guide


def test_limit_guidance_covers_judge_and_final_turn_budget() -> None:
    guide = (ROOT / "docs/writing-evals.md").read_text(encoding="utf-8")
    results = (ROOT / "docs/results.md").read_text(encoding="utf-8")
    skill = (
        ROOT / "plugins/skillroll-authoring/skills/eval-author/SKILL.md"
    ).read_text(encoding="utf-8")

    for text in (guide, results, skill):
        assert "max_output_tokens" in text
        assert any(
            phrase in text
            for phrase in ("semantic judge", "semantic-judge", "semantic judgment")
        )
        assert "final response" in text

    assert "non-scoring diagnostic" in results
    assert "does not replace the\noriginal result" in results


def test_output_limit_guidance_matches_the_runtime_default_and_diagnostic() -> None:
    results = (ROOT / "docs/results.md").read_text(encoding="utf-8")

    assert "repository default is 8,192" in results
    assert "one to three concise criteria" in results
    assert "technical\n`ERROR`, not a skill `FAIL`" in results
    assert "suggested\nnext tier" in results


def test_philosophy_is_the_concise_change_filter() -> None:
    philosophy = (ROOT / "PHILOSOPHY.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert len(philosophy.split()) < 300
    assert all(
        principle in philosophy
        for principle in (
            "catch regressions in nondeterministic skills",
            "not a formal proof system",
            "Manual testing should be useful immediately",
            "CI warning should come before CI gating",
            "Separate concerns: judgment in skills",
            "Compose complexity",
            "stop before implementation",
        )
    )
    assert "Every change\nmust preserve" in agents
    assert "ask for\nclarification" in agents
    assert "## Development process" in agents
    assert "maintaining a project history" in agents
    assert "review the result" in agents


def test_public_model_guidance_keeps_changing_routes_as_sanity_only() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs/configuration.md").read_text(encoding="utf-8")
    assert "setup checks" in readme
    assert "model and capacity can change" in guide
    assert "never switches\nmodels mid-case" in guide
    assert "SkillRoll does not fetch prices" in guide


def test_public_docs_do_not_claim_the_conflicting_pypi_install() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "uv tool install skillroll\n" not in readme
    assert "uv tool install ." in readme


def test_ci_is_read_only_secretless_and_cross_platform() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "permissions:\n  contents: read" in workflow
    assert "secrets." not in workflow
    assert "pull_request_target" not in workflow
    assert "write" not in workflow
    assert all(name in workflow for name in ("quality:", "test:", "package:"))
    assert all(
        system in workflow
        for system in ("ubuntu-latest", "macos-latest", "windows-latest")
    )
    assert "uv sync --all-groups --locked" in workflow
    assert "coverage report --show-missing --fail-under=100" in workflow
    assert "python tools/check_function_coverage.py" in workflow
    assert "ruff format --check ." in workflow
    assert "mypy --strict src tools" in workflow
    assert "uv build" in workflow
    assert "actionlint" in workflow
    assert "curl" not in workflow
