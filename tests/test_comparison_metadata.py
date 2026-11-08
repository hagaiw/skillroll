"""Pure comparison metadata and argument-contract tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from importlib.metadata import PackageNotFoundError
from pathlib import Path, PurePosixPath
from typing import cast

import pytest

from skillroll.artifacts.hashes import InputHash
from skillroll.artifacts.records import canonical_json
from skillroll.commands import compare
from skillroll.config import load_config
from skillroll.evals import parse_eval_case
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    SecretRedactor,
    SecretValue,
)
from skillroll.models import EvalCase, Skill, SkillRollConfig


def _write_config(root: Path, *, profiles: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "skills").mkdir(exist_ok=True)
    model_setting = (
        """default_profile = "authoring"

[inference.profiles.authoring]
purpose = "Authoring evaluator."
models = ["provider/primary", "provider/fallback"]

[inference.profiles.audit]
purpose = "Audit evaluator."
models = ["provider/audit"]
"""
        if profiles
        else 'model = "provider/evaluator"\n'
    )
    profile_prefix = """[pricing]
currency = "USD"

[pricing.models."provider/evaluator"]
input_per_million = 0.4
output_per_million = 1.6
cache_read_per_million = 0.1

[pricing.models."provider/candidate"]
input_per_million = 0.2
output_per_million = 0.8
"""
    path = root / "skillroll.toml"
    path.write_text(
        """schema_version = 1
skills_path = "skills"

[inference]
base_url = "https://provider.example/v1"
api_key_env = "PRIVATE_PROVIDER_KEY"
limits = { max_turns = 6, timeout_seconds = 45, max_output_tokens = 512 }
wire = "responses"
supports_temperature = false
"""
        + model_setting
        + """
[inference.extra_body]
private_gateway_option = "sensitive-value"
"""
        + profile_prefix,
        encoding="utf-8",
    )


def _load_config(root: Path) -> SkillRollConfig:
    parsed = load_config(root)
    assert parsed.value is not None, parsed.diagnostics
    return parsed.value


def _config(root: Path, *, profiles: bool = False) -> SkillRollConfig:
    _write_config(root, profiles=profiles)
    return _load_config(root)


def _skill(root: Path) -> Skill:
    skill_root = root / "skills" / "review"
    evals = skill_root / "evals"
    evals.mkdir(parents=True, exist_ok=True)
    skill_file = skill_root / "SKILL.md"
    if not skill_file.exists():
        skill_file.write_text("Review the request carefully.\n", encoding="utf-8")
    return Skill(
        "review",
        PurePosixPath("skills/review"),
        skill_root,
        skill_file,
        evals,
    )


def _parse_case(skill: Skill, name: str = "case") -> EvalCase:
    path = skill.evals_directory / f"{name}.eval.md"
    parsed = parse_eval_case(path, skill)
    assert parsed.value is not None, parsed.diagnostics
    return parsed.value


def _case(
    skill: Skill,
    name: str = "case",
    metadata: str = "schema_version: 1",
) -> EvalCase:
    path = skill.evals_directory / f"{name}.eval.md"
    path.write_text(
        f"""# {name}

```skillroll
{metadata}
```

## Input

Write a short overview.

## World

The available information is accurate.

## Success criteria

- The overview is useful.
""",
        encoding="utf-8",
    )
    return _parse_case(skill, name)


def _hashes(config: SkillRollConfig, cases: tuple[EvalCase, ...]) -> dict[str, str]:
    return {
        item.identity.as_posix(): item.sha256
        for item in compare._current_input_hashes(config, cases)
    }


@pytest.mark.parametrize(
    "models",
    [
        (),
        ("only-one",),
        tuple(f"provider/model-{index}" for index in range(9)),
        ("", "provider/candidate"),
        ("   ", "provider/candidate"),
        ("provider/line\nbreak", "provider/candidate"),
        ("provider/line\rbreak", "provider/candidate"),
        ("é" * 101, "provider/candidate"),
        (" provider/baseline ", "provider/baseline"),
        ("provider/baseline", None),
    ],
)
def test_comparison_arguments_reject_invalid_candidates(
    models: tuple[object, ...],
) -> None:
    assert compare._valid_arguments(cast(tuple[str, ...], models), 1, 0) is not None


def test_comparison_arguments_accept_trimmed_unique_candidates_and_limits() -> None:
    assert (
        compare._valid_arguments((" provider/base ", "provider/candidate"), 1, 0)
        is None
    )
    assert compare._valid_arguments(("é" * 100, "provider/candidate"), 1, 0) is None
    assert (
        compare._valid_arguments(
            tuple(f"provider/model-{index}" for index in range(8)), 10, 2**32 - 1
        )
        is None
    )


@pytest.mark.parametrize("samples", [0, 11, True, 1.5])
def test_comparison_arguments_reject_invalid_sample_counts(samples: object) -> None:
    assert compare._valid_arguments(("baseline", "candidate"), samples, 0) is not None  # type: ignore[arg-type]


@pytest.mark.parametrize("seed", [-1, 2**32, True, 1.5])
def test_comparison_arguments_reject_invalid_seeds(seed: object) -> None:
    assert compare._valid_arguments(("baseline", "candidate"), 1, seed) is not None  # type: ignore[arg-type]


def test_schedule_is_seeded_and_contains_each_planned_attempt_once(
    tmp_path: Path,
) -> None:
    skill = _skill(tmp_path)
    cases = (_case(skill, "first"), _case(skill, "second"))
    models = ("provider/baseline", "provider/candidate")
    first = compare._schedule(cases, models, samples=3, seed=123)
    repeat = compare._schedule(cases, models, samples=3, seed=123)
    changed_seed = compare._schedule(cases, models, samples=3, seed=124)

    assert first == repeat
    assert first != changed_seed
    expected = {
        (sample, case.identity.as_posix(), model)
        for sample in range(1, 4)
        for case in cases
        for model in models
    }
    observed = {
        (item["sample"], item["case"], item["executor_model"]) for item in first
    }
    assert len(first) == len(expected)
    assert observed == expected
    assert [item["sequence"] for item in first] == list(range(1, len(expected) + 1))
    assert all(item["status"] == "NOT_RUN" for item in first)


def test_current_input_hashes_cover_config_case_and_skill_bundle(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    skill = _skill(tmp_path)
    case = _case(skill)
    selected = (case,)
    original = _hashes(config, selected)
    assert set(original) == {
        "skillroll.toml",
        "skills/review/SKILL.md",
        "skills/review/evals/case.eval.md",
    }

    config_path = tmp_path / "skillroll.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "provider/evaluator", "provider/evaluator-v2"
        ),
        encoding="utf-8",
    )
    changed_config = _hashes(_load_config(tmp_path), selected)
    assert changed_config["skillroll.toml"] != original["skillroll.toml"]
    assert (
        changed_config["skills/review/SKILL.md"] == original["skills/review/SKILL.md"]
    )

    case_path = skill.evals_directory / "case.eval.md"
    case_path.write_text(
        case_path.read_text(encoding="utf-8").replace(
            "short overview", "clear overview"
        ),
        encoding="utf-8",
    )
    changed_case = _hashes(_load_config(tmp_path), (_parse_case(skill),))
    assert (
        changed_case["skills/review/evals/case.eval.md"]
        != changed_config["skills/review/evals/case.eval.md"]
    )

    skill.skill_file.write_text(
        "Review the request and cite evidence.\n", encoding="utf-8"
    )
    changed_bundle = _hashes(_load_config(tmp_path), (_parse_case(skill),))
    assert (
        changed_bundle["skills/review/SKILL.md"]
        != changed_case["skills/review/SKILL.md"]
    )

    references = skill.root / "references"
    references.mkdir()
    (references / "guide.md").write_text("Check a second source.\n", encoding="utf-8")
    with_reference = _hashes(_load_config(tmp_path), (_parse_case(skill),))
    assert "skills/review/references/guide.md" in with_reference


def test_current_input_hashes_reuses_bundle_and_rejects_inconsistent_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path)
    skill = _skill(tmp_path)
    cases = (_case(skill, "first"), _case(skill, "second"))
    original_build = compare.build_bundle
    built: list[Path] = []

    def count_build(root: Path):
        built.append(root)
        return original_build(root)

    inconsistent = iter(
        (
            InputHash(PurePosixPath("shared-source"), "asset", "a" * 64, 1),
            InputHash(PurePosixPath("shared-source"), "asset", "b" * 64, 1),
        )
    )
    monkeypatch.setattr(compare, "build_bundle", count_build)
    monkeypatch.setattr(compare, "input_hashes", lambda *_: (next(inconsistent),))

    with pytest.raises(ValueError, match="inconsistent bytes for input shared-source"):
        compare._current_input_hashes(config, cases)

    assert built == [skill.root]


def test_harness_fingerprint_fails_if_installed_source_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = Path(compare.__file__).resolve()
    original_read_bytes = Path.read_bytes

    def fail_source(path: Path) -> bytes:
        if path.resolve() == source_path:
            raise OSError("source is unreadable")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_source)
    with pytest.raises(ValueError, match="could not fingerprint its installed"):
        compare._harness_fingerprint()


def test_harness_fingerprint_falls_back_to_version_file_and_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from skillroll._version import __version__

    original_version = compare.importlib.metadata.version

    def missing_selected_distributions(name: str) -> str:
        if name in {"skillroll", "openai"}:
            raise PackageNotFoundError(name)
        return original_version(name)

    monkeypatch.setattr(
        compare.importlib.metadata, "version", missing_selected_distributions
    )
    fingerprint = compare._harness_fingerprint()

    assert fingerprint["package_version"] == __version__
    dependencies = cast(dict[str, str | None], fingerprint["dependency_versions"])
    assert dependencies["openai"] is None


def test_harness_fingerprint_records_hashes_and_versions_without_source_text() -> None:
    fingerprint = compare._harness_fingerprint()

    assert isinstance(fingerprint["package_version"], str)
    source_files = fingerprint["source_files"]
    assert isinstance(source_files, list) and source_files
    assert all(
        set(item) == {"identity", "sha256", "bytes"}
        and len(cast(str, item["sha256"])) == 64
        for item in source_files
    )
    prompts = fingerprint["effective_prompt_sha256"]
    assert isinstance(prompts, dict)
    assert set(prompts) == {"executor", "executor_omission", "world", "judge"}
    assert all(
        isinstance(value, str) and len(value) == 64 for value in prompts.values()
    )
    payload = {
        "package_version": fingerprint["package_version"],
        "source_files": source_files,
        "effective_prompt_sha256": prompts,
    }
    assert (
        fingerprint["source_fingerprint_sha256"]
        == hashlib.sha256(canonical_json(payload)).hexdigest()
    )
    dependencies = fingerprint["dependency_versions"]
    assert isinstance(dependencies, dict)
    assert {
        "openai-agents",
        "openai",
        "pydantic",
        "httpx",
        "markdown-it-py",
        "PyYAML",
    } <= set(dependencies)
    assert all(
        value is None or isinstance(value, str) for value in dependencies.values()
    )
    assert set(fingerprint) == {
        "package_version",
        "source_files",
        "effective_prompt_sha256",
        "source_fingerprint_sha256",
        "dependency_versions",
    }


def test_profile_candidates_choose_the_requested_or_default_profile(
    tmp_path: Path,
) -> None:
    plain = _config(tmp_path / "plain")
    assert compare._profile_candidates(plain, None) == ("provider/evaluator",)
    assert compare._profile_candidates(plain, "unknown") == ()
    assert compare._profile_candidates(replace(plain, inference=None), None) == ()

    profiled = _config(tmp_path / "profiles", profiles=True)
    assert compare._profile_candidates(profiled, None) == (
        "provider/primary",
        "provider/fallback",
    )
    assert compare._profile_candidates(profiled, "authoring") == (
        "provider/primary",
        "provider/fallback",
    )
    assert compare._profile_candidates(profiled, "audit") == ("provider/audit",)
    assert compare._profile_candidates(profiled, "unknown") == ()

    inference = profiled.inference
    assert inference is not None
    without_default = replace(
        profiled, inference=replace(inference, default_profile=None)
    )
    assert compare._profile_candidates(without_default, None) == ()
    single = replace(
        without_default,
        inference=replace(
            inference,
            profiles={"authoring": inference.profiles["authoring"]},
            default_profile=None,
        ),
    )
    assert compare._profile_candidates(single, None) == (
        "provider/primary",
        "provider/fallback",
    )


def test_configured_limits_fall_back_when_case_raises_a_repository_limit(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    skill = _skill(tmp_path)
    inference = config.inference
    assert inference is not None
    assert compare._configured_limits(config, _case(skill, "normal")) == {
        "max_turns": inference.limits.max_turns,
        "timeout_seconds": inference.limits.timeout_seconds,
        "max_output_tokens": inference.limits.max_output_tokens,
    }
    case = _case(
        skill,
        metadata="schema_version: 1\nlimits: {max_turns: 7}",
    )
    assert compare._configured_limits(config, case) == {
        "max_turns": inference.limits.max_turns,
        "timeout_seconds": inference.limits.timeout_seconds,
        "max_output_tokens": inference.limits.max_output_tokens,
    }


def test_failure_and_usage_metadata_are_redacted_and_type_safe() -> None:
    redactor = SecretRedactor(SecretValue("failure-token"))
    failure = InferenceFailure(
        InferenceFailureKind.TIMEOUT,
        "Timeout after failure-token.",
        (
            "Retry after failure-token.",
            "Authorization: private header content",
        ),
    )
    data = compare._failure_data(failure, redactor)

    assert data["kind"] == "timeout"
    assert data["stage"] == "preflight"
    assert data["summary"] == "Timeout after [redacted]."
    assert data["details"] == [
        "Retry after [redacted].",
        (
            "SkillRoll omitted provider headers or request content from this "
            "technical detail for safety."
        ),
    ]
    assert "failure-token" not in json.dumps(data)
    assert compare._usage_calls({"calls": "provider response"}) == []
    calls = [{"requested_model": "candidate"}, "ignored"]
    parsed = compare._usage_calls({"calls": calls})
    assert parsed == [{"requested_model": "candidate"}]
    assert parsed[0] is not calls[0]


def test_pricing_snapshot_and_extra_body_fingerprint_are_scoped_and_hashed(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    snapshot = compare._pricing_snapshot(
        config,
        (
            "provider/candidate",
            "provider/evaluator",
            "provider/candidate",
            "provider/unpriced",
        ),
    )
    assert snapshot == {
        "currency": "USD",
        "models": {
            "provider/candidate": {
                "input_per_million": 0.2,
                "output_per_million": 0.8,
                "cache_read_per_million": None,
            },
            "provider/evaluator": {
                "input_per_million": 0.4,
                "output_per_million": 1.6,
                "cache_read_per_million": 0.1,
            },
            "provider/unpriced": None,
        },
    }

    inference = config.inference
    assert inference is not None
    raw_base_url = (
        "https://private-user:private-pass@provider.example/v1"
        "?token=query-secret#fragment-secret"
    )
    inference = replace(inference, base_url=raw_base_url)
    inference_data = compare._inference_settings_data(
        replace(config, inference=inference)
    )
    assert inference_data == {
        "status": "configured",
        "base_url": "https://provider.example/v1",
        "base_url_sha256": hashlib.sha256(
            inference.base_url.encode("utf-8")
        ).hexdigest(),
        "wire": inference.wire.value,
        "supports_temperature": False,
        "limits": {
            "max_turns": 6,
            "timeout_seconds": 45,
            "max_output_tokens": 512,
        },
        "extra_body_sha256": hashlib.sha256(
            canonical_json(inference.extra_body)
        ).hexdigest(),
    }
    serialized_inference = json.dumps(inference_data)
    assert "private-user" not in serialized_inference
    assert "private-pass" not in serialized_inference
    assert "query-secret" not in serialized_inference
    assert "fragment-secret" not in serialized_inference
    assert "sensitive-value" not in serialized_inference
    assert "PRIVATE_PROVIDER_KEY" not in serialized_inference
    assert compare._inference_settings_data(replace(config, inference=None)) == {
        "status": "unavailable"
    }

    ipv6_endpoint = "https://[2001:db8::5]:8443/v1"
    ipv6_settings = replace(inference, base_url=ipv6_endpoint)
    ipv6_data = compare._inference_settings_data(
        replace(config, inference=ipv6_settings)
    )
    assert ipv6_data["base_url"] == ipv6_endpoint
    assert (
        ipv6_data["base_url_sha256"]
        == hashlib.sha256(ipv6_endpoint.encode("utf-8")).hexdigest()
    )
    assert compare._pricing_snapshot(replace(config, pricing=None), ("model",)) == {
        "currency": None,
        "models": {},
    }
