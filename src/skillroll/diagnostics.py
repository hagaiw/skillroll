"""Immutable command results and deterministic renderers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from skillroll.outcomes import Outcome

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | tuple[JSONValue, ...] | Mapping[str, JSONValue]


def _freeze_json(value: object, path: str = "data") -> JSONValue:
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item, f"{path}[]") for item in value)
    if isinstance(value, Mapping):
        frozen: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} keys must be strings")
            frozen[key] = _freeze_json(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    raise TypeError(f"{path} must contain only JSON-compatible values")


def _plain_json(value: JSONValue) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class SourceLocation:
    path: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    summary: str
    affected: str | None = None
    location: SourceLocation | None = None
    details: tuple[str, ...] = ()
    risk: str | None = None
    next_action: str | None = None


@dataclass(frozen=True, slots=True)
class CommandResult:
    outcome: Outcome
    summary: str
    diagnostics: tuple[Diagnostic, ...] = ()
    data: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        frozen = _freeze_json(self.data)
        if not isinstance(frozen, Mapping):
            raise TypeError("data must be a mapping")
        object.__setattr__(self, "data", frozen)


def _location_text(location: SourceLocation) -> str:
    parts = [location.path or "unknown location"]
    if location.line is not None:
        parts.append(str(location.line))
    if location.column is not None:
        if location.line is None:
            parts.append("?")
        parts.append(str(location.column))
    return ":".join(parts)


def render_text(result: CommandResult) -> str:
    """Render a stable, readable result without terminal-specific styling."""
    lines = [f"{result.outcome.name} — {result.summary}"]
    for diagnostic in result.diagnostics:
        lines.extend(("", diagnostic.summary))
        if diagnostic.affected is not None:
            lines.append(f"Affected: {diagnostic.affected}")
        if diagnostic.location is not None:
            lines.append(f"Location: {_location_text(diagnostic.location)}")
        if diagnostic.details:
            lines.append("Details:")
            lines.extend(f"  - {detail}" for detail in diagnostic.details)
        if diagnostic.risk is not None:
            lines.append(f"Why this matters: {diagnostic.risk}")
        if diagnostic.next_action is not None:
            lines.append(f"What to do next: {diagnostic.next_action}")
    return "\n".join(lines) + "\n"


def render_json(result: CommandResult) -> str:
    """Render exactly one JSON object with a predictable shape."""
    diagnostics = [
        {
            "code": item.code,
            "summary": item.summary,
            "affected": item.affected,
            "location": None
            if item.location is None
            else {
                "path": item.location.path,
                "line": item.location.line,
                "column": item.location.column,
            },
            "details": list(item.details),
            "risk": item.risk,
            "next_action": item.next_action,
        }
        for item in result.diagnostics
    ]
    payload = {
        "outcome": result.outcome.name,
        "exit_code": result.outcome.exit_code,
        "summary": result.summary,
        "diagnostics": diagnostics,
        "data": _plain_json(result.data),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
