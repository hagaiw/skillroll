"""Strict, side-effect-free ``skillroll.toml`` loading."""

from __future__ import annotations

import json
import re
import tomllib
from math import isfinite
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import urlparse

from skillroll.diagnostics import Diagnostic, JSONValue, SourceLocation
from skillroll.models import (
    GuardId,
    GuardSettings,
    InferenceLimits,
    InferenceSettings,
    InferenceWire,
    ModelPricing,
    ModelProfile,
    ParsedResult,
    PricingSettings,
    SkillRollConfig,
)
from skillroll.paths import parse_relative_path, resolve_child

_ROOT_KEYS = frozenset(
    {"schema_version", "skills_path", "guards", "inference", "pricing"}
)
_GUARD_KEYS = frozenset({"disabled"})
_INFERENCE_KEYS = frozenset(
    {
        "base_url",
        "model",
        "api_key_env",
        "limits",
        "profiles",
        "default_profile",
        "extra_body",
        "wire",
        "supports_temperature",
    }
)
_LIMIT_KEYS = frozenset({"max_turns", "timeout_seconds", "max_output_tokens"})
_PROFILE_KEYS = frozenset({"purpose", "models"})
_PRICING_KEYS = frozenset({"currency", "models"})
_MODEL_PRICING_KEYS = frozenset(
    {"input_per_million", "output_per_million", "cache_read_per_million"}
)
_POLICY_IDS = frozenset({"SCG2001"})
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PROFILE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,63}$")


def parse_skills_path(value: str) -> PurePosixPath | None:
    """Parse the one configuration path that may deliberately name the root."""
    if value == ".":
        return PurePosixPath(".")
    return parse_relative_path(value)


def _diagnostic(code: str, summary: str, path: Path, action: str) -> Diagnostic:
    return Diagnostic(
        code,
        summary,
        affected=path.name,
        location=SourceLocation(path.name),
        next_action=action,
    )


def _config_error(path: Path, summary: str) -> ParsedResult[SkillRollConfig]:
    return ParsedResult(
        None,
        (
            _diagnostic(
                "SCG1001",
                summary,
                path,
                "Run `skillroll init` to create a minimal configuration, or "
                "compare this file with the README example.",
            ),
        ),
    )


def is_safe_inference_url(value: str) -> bool:
    """Accept the one generic endpoint policy used by config and local setup."""
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    return parsed.scheme == "https" or parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }


def _inference_limits(value: object) -> InferenceLimits | None:
    if value is None:
        return InferenceLimits()
    if not isinstance(value, dict) or set(value) - _LIMIT_KEYS:
        return None
    max_turns = value.get("max_turns", 8)
    timeout_seconds = value.get("timeout_seconds", 90)
    max_output_tokens = value.get("max_output_tokens", 8192)
    if (
        isinstance(max_turns, bool)
        or not isinstance(max_turns, int)
        or not 1 <= max_turns <= 32
        or isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 10 <= timeout_seconds <= 600
        or isinstance(max_output_tokens, bool)
        or not isinstance(max_output_tokens, int)
        or not 256 <= max_output_tokens <= 16384
    ):
        return None
    return InferenceLimits(max_turns, timeout_seconds, max_output_tokens)


def _model_profiles(value: object) -> dict[str, ModelProfile] | None:
    if value is None:
        return {}
    if not isinstance(value, dict) or not value:
        return None
    parsed: dict[str, ModelProfile] = {}
    for name, settings in value.items():
        if (
            not isinstance(name, str)
            or _PROFILE_NAME.fullmatch(name) is None
            or not isinstance(settings, dict)
            or set(settings) != _PROFILE_KEYS
        ):
            return None
        purpose = settings.get("purpose")
        models = settings.get("models")
        if (
            not isinstance(purpose, str)
            or not purpose.strip()
            or "\n" in purpose
            or "\r" in purpose
            or len(purpose.encode("utf-8")) > 512
            or not isinstance(models, list)
            or not 1 <= len(models) <= 8
            or any(not isinstance(model, str) for model in models)
        ):
            return None
        normalized_models = tuple(model.strip() for model in models)
        if any(
            not model
            or "\n" in model
            or "\r" in model
            or len(model.encode("utf-8")) > 200
            for model in normalized_models
        ) or len(set(normalized_models)) != len(normalized_models):
            return None
        parsed[name] = ModelProfile(purpose.strip(), normalized_models)
    return parsed


# Keys that skillroll controls directly inside the request body. Allowing them in
# extra_body would let a config silently override the harness's own typed
# parameters in unpredictable ways. The set covers both wires, so the guarantee
# holds whichever endpoint a repository selects: `messages`/`max_tokens`/
# `response_format` belong to Chat Completions, `input`/`max_output_tokens`/`text`
# to Responses.
_EXTRA_BODY_RESERVED_KEYS = frozenset(
    {
        "model",
        "messages",
        "input",
        "tools",
        "tool_choice",
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
        "stream",
        "response_format",
        "text",
        "temperature",
    }
)
_EXTRA_BODY_MAX_DEPTH = 4
_EXTRA_BODY_MAX_BYTES = 8192


def _extra_body_value(value: object, depth: int) -> bool:
    """Return True iff *value* is a JSON-ish scalar or bounded nested structure."""
    if depth > _EXTRA_BODY_MAX_DEPTH:
        return False
    if isinstance(value, float):
        return isfinite(value)
    if value is None or isinstance(value, str | bool | int):
        return True
    if isinstance(value, list):
        return all(_extra_body_value(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(k, str) and k and _extra_body_value(v, depth + 1)
            for k, v in value.items()
        )
    return False


def _extra_body(value: object) -> dict[str, JSONValue] | None:
    """Validate an optional [inference.extra_body] table.

    Returns an empty dict when the section is absent, a validated dict of
    provider-specific parameters on success, or None on any validation error.
    Reserved keys (those skillroll already sets in the request body) are
    rejected to prevent accidental harness hijacking.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        return None
    if not value:
        # An empty table is valid; nothing to forward.
        return {}
    for key in value:
        if not isinstance(key, str) or not key:
            return None
        if key in _EXTRA_BODY_RESERVED_KEYS:
            return None
    for v in value.values():
        if not _extra_body_value(v, depth=1):
            return None
    # Every key and value was validated above, so serialisation cannot fail.
    serialized = json.dumps(value)
    if len(serialized.encode("utf-8")) > _EXTRA_BODY_MAX_BYTES:
        return None
    return cast(dict[str, JSONValue], dict(value))


def _inference_wire(value: object) -> InferenceWire | None:
    """Validate the optional inference.wire setting.

    Returns the Chat Completions default when the key is absent, the selected
    wire on success, or None on any validation error.
    """
    if value is None:
        return InferenceWire.CHAT_COMPLETIONS
    if not isinstance(value, str):
        return None
    try:
        return InferenceWire(value)
    except ValueError:
        return None


def _pricing(value: object) -> PricingSettings | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - _PRICING_KEYS:
        return None
    currency = value.get("currency", "USD")
    models = value.get("models")
    if (
        not isinstance(currency, str)
        or not re.fullmatch(r"[A-Z]{3}", currency)
        or not isinstance(models, dict)
        or not models
    ):
        return None
    parsed: dict[str, ModelPricing] = {}
    for model, settings in models.items():
        if (
            not isinstance(model, str)
            or not model
            or not isinstance(settings, dict)
            or set(settings) - _MODEL_PRICING_KEYS
        ):
            return None
        input_rate = settings.get("input_per_million")
        output_rate = settings.get("output_per_million")
        cache_rate = settings.get("cache_read_per_million")
        if (
            isinstance(input_rate, bool)
            or not isinstance(input_rate, int | float)
            or not isfinite(float(input_rate))
            or input_rate < 0
            or isinstance(output_rate, bool)
            or not isinstance(output_rate, int | float)
            or not isfinite(float(output_rate))
            or output_rate < 0
            or (
                cache_rate is not None
                and (
                    isinstance(cache_rate, bool)
                    or not isinstance(cache_rate, int | float)
                    or not isfinite(float(cache_rate))
                    or cache_rate < 0
                )
            )
        ):
            return None
        parsed[model] = ModelPricing(
            float(input_rate),
            float(output_rate),
            None if cache_rate is None else float(cache_rate),
        )
    return PricingSettings(currency, parsed)


def load_config(repository_root: Path) -> ParsedResult[SkillRollConfig]:
    """Load exactly the config in ``repository_root``; never search parents."""
    root = repository_root.resolve()
    config_path = root / "skillroll.toml"
    if not root.is_dir():
        return _config_error(
            config_path, "The selected repository directory does not exist."
        )
    try:
        raw = config_path.read_bytes()
    except FileNotFoundError:
        return _config_error(
            config_path, "SkillRoll could not find skillroll.toml here."
        )
    except OSError:
        return _config_error(
            config_path, "SkillRoll could not read skillroll.toml here."
        )
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return _config_error(config_path, "skillroll.toml is not valid UTF-8 TOML.")
    if not isinstance(data, dict) or set(data) - _ROOT_KEYS:
        return _config_error(config_path, "skillroll.toml contains an unknown setting.")
    if data.get("schema_version") != 1 or isinstance(data.get("schema_version"), bool):
        return _config_error(config_path, "schema_version must be the integer 1.")
    skills_value = data.get("skills_path")
    if not isinstance(skills_value, str):
        return _config_error(
            config_path, "skills_path must be a non-empty relative path."
        )
    skills_path = parse_skills_path(skills_value)
    skills_root = None if skills_path is None else resolve_child(root, skills_path)
    if skills_path is None or skills_root is None:
        return ParsedResult(
            None,
            (
                _diagnostic(
                    "SCG1002",
                    "skills_path must stay inside the selected repository.",
                    config_path,
                    "Use a relative path inside this repository, such as skills.",
                ),
            ),
        )
    if not skills_root.is_dir() or skills_root.is_symlink():
        return _config_error(
            config_path,
            "skills_path must name a readable directory in this repository.",
        )
    guard_value = data.get("guards", {})
    if not isinstance(guard_value, dict) or set(guard_value) - _GUARD_KEYS:
        return _config_error(
            config_path, "The guards section contains an unknown setting."
        )
    disabled_value = guard_value.get("disabled", [])
    if (
        not isinstance(disabled_value, list)
        or any(not isinstance(item, str) for item in disabled_value)
        or len(set(disabled_value)) != len(disabled_value)
        or not set(disabled_value) <= _POLICY_IDS
    ):
        return _config_error(
            config_path,
            "guards.disabled must list unique policy guard IDs such as SCG2001.",
        )
    inference_value = data.get("inference")
    inference: InferenceSettings | None = None
    if inference_value is not None:
        if (
            not isinstance(inference_value, dict)
            or set(inference_value) - _INFERENCE_KEYS
            or not {"base_url", "api_key_env"} <= set(inference_value)
        ):
            return _config_error(
                config_path,
                "The inference section must contain base_url, api_key_env, and "
                "either model or profiles, plus optional limits.",
            )
        base_url = inference_value.get("base_url")
        model = inference_value.get("model")
        api_key_env = inference_value.get("api_key_env")
        limits = _inference_limits(inference_value.get("limits"))
        profiles = _model_profiles(inference_value.get("profiles"))
        default_profile = inference_value.get("default_profile")
        extra_body = _extra_body(inference_value.get("extra_body"))
        wire = _inference_wire(inference_value.get("wire"))
        supports_temperature = inference_value.get("supports_temperature", True)
        valid_model = model is None or (
            isinstance(model, str)
            and bool(model.strip())
            and "\n" not in model
            and "\r" not in model
            and len(model.encode("utf-8")) <= 200
        )
        if (
            not isinstance(base_url, str)
            or not valid_model
            or not isinstance(api_key_env, str)
            or not base_url
            or not api_key_env
            or not is_safe_inference_url(base_url)
            or _ENVIRONMENT_NAME.fullmatch(api_key_env) is None
            or limits is None
            or profiles is None
            or extra_body is None
            or wire is None
            or not isinstance(supports_temperature, bool)
            or (
                default_profile is not None
                and (
                    not isinstance(default_profile, str)
                    or default_profile not in profiles
                )
            )
            or (model is None and not profiles)
            or (model is not None and bool(profiles))
        ):
            return _config_error(
                config_path,
                "Inference settings need a safe HTTPS URL (or local test URL), "
                "a model or named model profiles, an environment-variable name, "
                "valid limits, and, if present, wire set to chat_completions or "
                "responses.",
            )
        if model is None:
            assert profiles
            model = next(iter(profiles.values())).models[0]
        else:
            model = model.strip()
        inference = InferenceSettings(
            base_url,
            model,
            api_key_env,
            limits,
            profiles,
            default_profile,
            extra_body,
            wire,
            supports_temperature,
        )
    pricing = _pricing(data.get("pricing"))
    if data.get("pricing") is not None and pricing is None:
        return _config_error(
            config_path,
            "The pricing section must provide a currency and non-negative per-"
            "million-token rates for at least one model.",
        )
    disabled: frozenset[GuardId] = frozenset(disabled_value)
    return ParsedResult(
        SkillRollConfig(
            root,
            skills_path,
            skills_root,
            GuardSettings(disabled),
            inference,
            config_path,
            pricing,
        ),
        (),
    )
