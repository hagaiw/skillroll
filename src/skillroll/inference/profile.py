"""Resolve a configured inference profile without leaking a credential."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import quote

from skillroll.models import InferenceLimits, InferenceSettings

MAX_FAILURE_DETAILS = 3
MAX_FAILURE_DETAIL_BYTES = 1024
_UNSAFE_DETAIL_MARKERS = (
    "authorization",
    "api-key",
    "x-api-key",
    "cookie",
    "set-cookie",
    "headers",
    "--- skill.md",
    "you are executing the skill below",
    "messages=",
    "prompt=",
    "instructions=",
)
_OMITTED_DETAIL = (
    "SkillRoll omitted provider headers or request content from this technical "
    "detail for safety."
)


class InferenceFailureKind(StrEnum):
    """Stable categories for configuration and endpoint failures."""

    MISSING_CONFIGURATION = "missing_configuration"
    MISSING_API_KEY = "missing_api_key"
    INVALID_CONFIGURATION = "invalid_configuration"
    UNAUTHORIZED = "unauthorized"
    RATE_LIMITED = "rate_limited"
    REQUEST_REJECTED = "request_rejected"
    SERVICE_FAILURE = "service_failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    MALFORMED_RESPONSE = "malformed_response"
    JUDGE_INTEGRITY = "judge_integrity"
    EXECUTION_ERROR = "execution_error"


class SecretValue:
    """A string wrapper that only reveals its value at an HTTP/SDK edge."""

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        self.__value = value

    def reveal(self) -> str:
        """Return the credential for the one authorized outbound client."""
        return self.__value

    def __str__(self) -> str:
        return "[redacted]"

    def __repr__(self) -> str:
        return "SecretValue([redacted])"


@dataclass(frozen=True, slots=True)
class SecretRedactor:
    """Remove the raw and URL-encoded forms of one secret from text."""

    secret: SecretValue

    def redact(self, text: str) -> str:
        value = self.secret.reveal()
        if not value:
            return text
        return text.replace(value, "[redacted]").replace(
            quote(value, safe=""), "[redacted]"
        )


@dataclass(frozen=True, slots=True)
class InferenceFailure:
    """A safe failure that can cross into a user-facing diagnostic."""

    kind: InferenceFailureKind
    summary: str
    details: tuple[str, ...] = ()
    stage: str | None = None


def bounded_failure_details(
    failure: InferenceFailure, redactor: SecretRedactor
) -> tuple[str, ...]:
    """Return a small, secret-safe subset of diagnostic-only failure details.

    Inference adapters already redact their configured credential. This boundary
    redacts again before an error reaches a terminal or artifact, omits opaque
    HTTP-header/request content, and bounds every retained value. It deliberately
    never receives a model prompt as an argument.
    """
    values: list[str] = []
    omitted = False
    for detail in failure.details[:MAX_FAILURE_DETAILS]:
        cleaned = redactor.redact(detail)
        if any(marker in cleaned.casefold() for marker in _UNSAFE_DETAIL_MARKERS):
            omitted = True
            continue
        encoded = cleaned.encode("utf-8")
        if len(encoded) > MAX_FAILURE_DETAIL_BYTES:
            suffix = " [truncated]"
            ceiling = MAX_FAILURE_DETAIL_BYTES - len(suffix.encode("utf-8"))
            cleaned = encoded[:ceiling].decode("utf-8", errors="ignore") + suffix
        if cleaned:
            values.append(cleaned)
    if omitted:
        values.append(_OMITTED_DETAIL)
    return tuple(values)


@dataclass(frozen=True, slots=True)
class ResolvedInference:
    """The one profile shared by execution, world simulation, and judging."""

    base_url: str
    model: str
    api_key: SecretValue
    limits: InferenceLimits
    profile_name: str | None = None
    profile_purpose: str | None = None


def _candidate_models(
    settings: InferenceSettings, profile_name: str | None
) -> tuple[tuple[str, str | None, str | None], ...] | InferenceFailure:
    if not settings.profiles:
        if profile_name is not None:
            return InferenceFailure(
                InferenceFailureKind.INVALID_CONFIGURATION,
                f"The model profile '{profile_name}' is not configured.",
                (
                    "Add that profile under [inference.profiles] or omit "
                    "--model-profile.",
                ),
            )
        return ((settings.model, None, None),)
    selected = profile_name or settings.default_profile
    if selected is None:
        if len(settings.profiles) == 1:
            selected = next(iter(settings.profiles))
        else:
            names = ", ".join(sorted(settings.profiles))
            return InferenceFailure(
                InferenceFailureKind.INVALID_CONFIGURATION,
                "This repository defines several model profiles but none was selected.",
                (f"Choose one with --model-profile; available profiles: {names}.",),
            )
    profile = settings.profiles.get(selected)
    if profile is None:
        names = ", ".join(sorted(settings.profiles))
        return InferenceFailure(
            InferenceFailureKind.INVALID_CONFIGURATION,
            f"The model profile '{selected}' is not configured.",
            (f"Choose one of the configured profiles: {names}.",),
        )
    return tuple((model, selected, profile.purpose) for model in profile.models)


def resolve_inference_candidates(
    settings: InferenceSettings | None,
    environment: Mapping[str, str] | None = None,
    profile_name: str | None = None,
) -> tuple[tuple[ResolvedInference, ...] | None, InferenceFailure | None]:
    """Resolve ranked candidates; callers may use them only for preflight."""
    if settings is None:
        return None, InferenceFailure(
            InferenceFailureKind.MISSING_CONFIGURATION,
            "This repository has no inference settings yet.",
            (
                "Add an [inference] section with base_url, api_key_env, and "
                "either model or profiles to skillroll.toml.",
            ),
        )
    values = os.environ if environment is None else environment
    value = values.get(settings.api_key_env, "")
    if not value.strip():
        return None, InferenceFailure(
            InferenceFailureKind.MISSING_API_KEY,
            f"The {settings.api_key_env} environment variable is empty or unavailable.",
            (
                "SkillRoll needs that variable only while it contacts your configured "
                "model endpoint.",
                f"Set {settings.api_key_env} in your shell or CI secret, then run "
                "doctor again.",
            ),
        )
    candidates = _candidate_models(settings, profile_name)
    if isinstance(candidates, InferenceFailure):
        return None, candidates
    secret = SecretValue(value)
    return (
        tuple(
            ResolvedInference(
                settings.base_url,
                model,
                secret,
                settings.limits,
                candidate_profile,
                purpose,
            )
            for model, candidate_profile, purpose in candidates
        ),
        None,
    )


def resolve_inference(
    settings: InferenceSettings | None,
    environment: Mapping[str, str] | None = None,
    profile_name: str | None = None,
) -> tuple[ResolvedInference | None, InferenceFailure | None]:
    """Resolve the named key once, returning only redacted failure data."""
    candidates, failure = resolve_inference_candidates(
        settings, environment, profile_name
    )
    if failure is not None:
        return None, failure
    assert candidates
    return candidates[0], None
