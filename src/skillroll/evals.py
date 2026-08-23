"""Pure-ish evaluation-case parsing and declared-check validation."""

from __future__ import annotations

import json
import math
from pathlib import Path, PurePosixPath
from typing import Any, cast

from skillroll.diagnostics import Diagnostic, JSONValue, SourceLocation
from skillroll.markdown import (
    first_metadata_fence,
    location,
    metadata_fence_count,
    sections,
    title,
)
from skillroll.models import (
    Assertion,
    AssertionKind,
    CaseLimits,
    DeclaredCheck,
    DeterministicRule,
    EvalCase,
    ParsedResult,
    Skill,
)
from skillroll.paths import parse_relative_path
from skillroll.repository_io import readable_utf8
from skillroll.safe_yaml import MetadataError, load_metadata

_REQUIRED_SECTIONS = ("Input", "World", "Success criteria")
_RULE_KEYS = frozenset({"name", "tool_name", "arguments", "result"})
_LIMIT_KEYS = frozenset({"max_turns", "timeout_seconds", "max_output_tokens"})
_CASE_LIMITS = {"max_turns": 32, "timeout_seconds": 600, "max_output_tokens": 16384}
_ASSERTION_KINDS = frozenset(
    {
        "final_output_contains",
        "final_output_not_contains",
        "final_output_equals",
    }
)
_REMOVED_ASSERTION_KINDS = frozenset(
    {"action_occurred", "action_count_at_most", "action_count_at_least"}
)


def _utf8_text(value: object, *, allow_empty: bool, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and (allow_empty or bool(value))
        and len(value.encode("utf-8")) <= maximum
    )


def _error(path: Path, summary: str, line: int | None = None) -> Diagnostic:
    return Diagnostic(
        "SCG1005",
        summary,
        affected=path.name,
        location=None if line is None else SourceLocation(path.name, line, 1),
        next_action="Compare this file with an eval created by `skillroll new`.",
    )


def _parse_checks(
    value: object, path: Path, skill: Skill, metadata_line: int
) -> tuple[tuple[DeclaredCheck, ...], tuple[Diagnostic, ...]]:
    if value is None:
        return (), ()
    if not isinstance(value, list):
        return (), (_error(path, "`checks` must be a list.", metadata_line),)
    checks: list[DeclaredCheck] = []
    errors: list[Diagnostic] = []
    names: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"name", "command", "covers"}:
            errors.append(
                _error(
                    path,
                    "Each check must contain only `name`, `command`, and `covers`.",
                    metadata_line,
                )
            )
            continue
        name = item.get("name")
        command = item.get("command")
        covers_value = item.get("covers")
        if (
            not isinstance(name, str)
            or not name.strip()
            or "\n" in name
            or not isinstance(command, str)
            or not command.strip()
            or "\n" in command
            or not isinstance(covers_value, list)
            or not covers_value
            or any(not isinstance(cover, str) for cover in covers_value)
        ):
            errors.append(
                _error(
                    path,
                    "Each check needs a one-line `name` and `command`, plus a "
                    "non-empty `covers` list.",
                    metadata_line,
                )
            )
            continue
        if name in names:
            errors.append(
                _error(path, f"The check named '{name}' is repeated.", metadata_line)
            )
            continue
        names.add(name)
        covers: list[PurePosixPath] = []
        for cover in covers_value:
            parsed = parse_relative_path(cover)
            if parsed is None or any(character in cover for character in "*?["):
                errors.append(
                    _error(
                        path,
                        f"The check '{name}' covers an unsafe repository-relative "
                        f"path: {cover!r}.",
                        metadata_line,
                    )
                )
                continue
            if parsed in covers:
                errors.append(
                    _error(
                        path,
                        f"The check '{name}' repeats {cover!r} in covers.",
                        metadata_line,
                    )
                )
                continue
            covers.append(parsed)
        if covers:
            checks.append(
                DeclaredCheck(
                    name, command, tuple(covers), location(path.name, metadata_line)
                )
            )
    return tuple(checks), tuple(errors)


def _json_value(value: object) -> JSONValue | None:
    """Freeze a YAML value only when it is a finite JSON-shaped value."""
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        values = tuple(_json_value(item) for item in value)
        return (
            None
            if any(
                item is None and original is not None
                for item, original in zip(values, value, strict=True)
            )
            else values
        )
    if isinstance(value, dict):
        frozen: dict[str, JSONValue] = {}
        for key, item in value.items():
            normalized = _json_value(item)
            if not isinstance(key, str) or (normalized is None and item is not None):
                return None
            frozen[key] = normalized
        return frozen
    return None


def _canonical_json(value: JSONValue) -> str:
    """Render a JSON value exactly as matching and prompt code will see it."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_rules(
    value: object, path: Path, metadata_line: int
) -> tuple[tuple[DeterministicRule, ...], tuple[Diagnostic, ...]]:
    if value is None:
        return (), ()
    if not isinstance(value, list):
        return (), (_error(path, "`rules` must be a list.", metadata_line),)
    rules: list[DeterministicRule] = []
    errors: list[Diagnostic] = []
    names: set[str] = set()
    matches: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != _RULE_KEYS:
            errors.append(
                _error(
                    path,
                    "Each rule must contain only `name`, `tool_name`, `arguments`, "
                    "and `result`.",
                    metadata_line,
                )
            )
            continue
        name = item["name"]
        tool_name = item["tool_name"]
        result = item["result"]
        arguments = _json_value(item["arguments"])
        valid_name = (
            isinstance(name, str)
            and 1 <= len(name) <= 120
            and name.strip()
            and "\n" not in name
            and "\r" not in name
        )
        valid_tool = (
            isinstance(tool_name, str)
            and 1 <= len(tool_name) <= 200
            and tool_name.strip()
            and "\n" not in tool_name
            and "\r" not in tool_name
        )
        valid_result = (
            isinstance(result, str)
            and bool(result)
            and len(result.encode("utf-8")) <= 16 * 1024
        )
        valid_arguments = isinstance(arguments, dict)
        if not (valid_name and valid_tool and valid_result and valid_arguments):
            errors.append(
                _error(
                    path,
                    "Each rule needs a short one-line name and tool name, a JSON "
                    "object of arguments, and non-empty result text no larger "
                    "than 16 KiB.",
                    metadata_line,
                )
            )
            continue
        assert (
            isinstance(name, str)
            and isinstance(tool_name, str)
            and isinstance(result, str)
        )
        assert isinstance(arguments, dict)
        canonical = _canonical_json(arguments)
        if len(canonical.encode("utf-8")) > 16 * 1024:
            errors.append(
                _error(
                    path,
                    f"The rule '{name}' has arguments larger than 16 KiB.",
                    metadata_line,
                )
            )
            continue
        if name in names:
            errors.append(
                _error(path, f"The rule named '{name}' is repeated.", metadata_line)
            )
            continue
        match = (tool_name, canonical)
        if match in matches:
            errors.append(
                _error(
                    path,
                    f"The rule '{name}' duplicates an earlier exact action mapping.",
                    metadata_line,
                )
            )
            continue
        names.add(name)
        matches.add(match)
        rules.append(DeterministicRule(name, tool_name, arguments, result))
    return tuple(rules), tuple(errors)


def _parse_limits(
    value: object, path: Path, metadata_line: int
) -> tuple[CaseLimits, tuple[Diagnostic, ...]]:
    if value is None:
        return CaseLimits(), ()
    if not isinstance(value, dict) or not value or set(value) - _LIMIT_KEYS:
        return CaseLimits(), (
            _error(
                path,
                "metadata limits must contain one or more supported integer "
                "limits only.",
                metadata_line,
            ),
        )
    parsed: dict[str, int] = {}
    errors: list[Diagnostic] = []
    for name, maximum in _CASE_LIMITS.items():
        if name not in value:
            continue
        item = value[name]
        if (
            isinstance(item, bool)
            or not isinstance(item, int)
            or not 1 <= item <= maximum
        ):
            errors.append(
                _error(
                    path,
                    f"metadata limits.{name} must be an integer from 1 to {maximum}.",
                    metadata_line,
                )
            )
        else:
            parsed[name] = item
    return CaseLimits(**parsed), tuple(errors)


def _parse_assertions(
    value: object, path: Path, metadata_line: int
) -> tuple[tuple[Assertion, ...], tuple[Diagnostic, ...]]:
    """Parse the small literal assertion vocabulary before any inference runs."""
    if value is None:
        return (), ()
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        return (), (
            _error(
                path,
                "metadata assertions must be a list with 1 to 32 items.",
                metadata_line,
            ),
        )
    parsed: list[Assertion] = []
    errors: list[Diagnostic] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or len(item) != 1:
            errors.append(
                _error(
                    path,
                    "Each assertion must be one supported predicate.",
                    metadata_line,
                )
            )
            continue
        kind, expected = next(iter(item.items()))
        if not isinstance(kind, str) or kind not in _ASSERTION_KINDS:
            message = (
                "Action assertions are not supported. Put intent and outcome in "
                "Success criteria; inspect transcript actions as evidence."
                if kind in _REMOVED_ASSERTION_KINDS
                else "This assertion predicate is not supported."
            )
            errors.append(_error(path, message, metadata_line))
            continue
        assertion_kind = cast(AssertionKind, kind)
        assertion: Assertion | None = None
        if kind in {"final_output_contains", "final_output_not_contains"}:
            if _utf8_text(expected, allow_empty=False, maximum=16 * 1024):
                assertion = Assertion(assertion_kind, expected_text=expected)
        elif kind == "final_output_equals" and _utf8_text(
            expected, allow_empty=True, maximum=64 * 1024
        ):
            assertion = Assertion(assertion_kind, expected_text=expected)
        if assertion is None:
            errors.append(
                _error(
                    path, f"The {kind} assertion has an invalid value.", metadata_line
                )
            )
            continue
        canonical = _canonical_json(cast(JSONValue, _assertion_data(assertion)))
        if canonical in seen:
            errors.append(_error(path, "This assertion is repeated.", metadata_line))
            continue
        seen.add(canonical)
        parsed.append(assertion)
    return tuple(parsed), tuple(errors)


def _assertion_data(assertion: Assertion) -> dict[str, object]:
    """Use one stable representation solely to reject exact duplicate metadata."""
    return {assertion.kind: assertion.expected_text}


def parse_eval_case(path: Path, skill: Skill) -> ParsedResult[EvalCase]:
    """Parse one direct case without executing its declared command."""
    source = readable_utf8(path)
    if source is None:
        return ParsedResult(
            None, (_error(path, "SkillRoll could not read this eval case."),)
        )
    if len(source.encode("utf-8")) > 1024 * 1024:
        return ParsedResult(
            None, (_error(path, "This eval case is larger than 1 MiB."),)
        )
    errors: list[Diagnostic] = []
    fence = first_metadata_fence(source)
    if fence is None:
        errors.append(
            _error(
                path,
                "The first content after an optional title must be a "
                "```skillroll metadata block.",
            )
        )
        metadata: dict[str, Any] = {}
        fence_line = 1
    else:
        fence_line = fence.line
        if metadata_fence_count(source) != 1:
            errors.append(
                _error(
                    path,
                    "An eval case needs exactly one skillroll metadata block.",
                    fence_line,
                )
            )
        try:
            metadata = load_metadata(fence.content)
        except MetadataError as error:
            metadata = {}
            errors.append(
                _error(path, f"The skillroll metadata is invalid: {error}.", fence_line)
            )
    if set(metadata) - {"schema_version", "checks", "assertions", "rules", "limits"}:
        errors.append(
            _error(
                path,
                "The metadata contains a setting SkillRoll does not support yet.",
                fence_line,
            )
        )
    if metadata.get("schema_version") != 1 or isinstance(
        metadata.get("schema_version"), bool
    ):
        errors.append(
            _error(path, "metadata schema_version must be the integer 1.", fence_line)
        )
    checks, check_errors = _parse_checks(
        metadata.get("checks"), path, skill, fence_line
    )
    errors.extend(check_errors)
    assertions, assertion_errors = _parse_assertions(
        metadata.get("assertions"), path, fence_line
    )
    errors.extend(assertion_errors)
    rules, rule_errors = _parse_rules(metadata.get("rules"), path, fence_line)
    limits, limit_errors = _parse_limits(metadata.get("limits"), path, fence_line)
    errors.extend(rule_errors)
    errors.extend(limit_errors)
    found_sections = sections(source)
    section_values: dict[str, str] = {}
    for section_name in _REQUIRED_SECTIONS:
        found = found_sections.get(section_name)
        if found is None:
            errors.append(
                _error(path, f"This eval case needs one ## {section_name} section.")
            )
        elif not found[0].strip():
            errors.append(
                _error(path, f"The ## {section_name} section needs content.", found[1])
            )
        else:
            section_values[section_name] = found[0]
    if errors:
        return ParsedResult(None, tuple(errors))
    identity = skill.identity / PurePosixPath("evals") / path.name
    return ParsedResult(
        EvalCase(
            path=path,
            identity=identity,
            skill=skill,
            title=title(source),
            input_markdown=section_values["Input"],
            world_markdown=section_values["World"],
            success_criteria_markdown=section_values["Success criteria"],
            checks=checks,
            assertions=assertions,
            rules=rules,
            limits=limits,
        ),
        (),
    )
