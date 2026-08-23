"""Pure exact matching for deterministic simulated-world responses."""

from __future__ import annotations

import json
from collections.abc import Mapping

from skillroll.diagnostics import JSONValue
from skillroll.models import DeterministicRule


def canonical_json(value: JSONValue) -> str:
    """Serialize JSON values in the stable form used for exact matching."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def matching_rule(
    rules: tuple[DeterministicRule, ...],
    tool_name: str,
    arguments: Mapping[str, JSONValue],
) -> DeterministicRule | None:
    """Return the first full action match, never interpreting patterns."""
    expected = canonical_json(arguments)
    for rule in rules:
        if rule.tool_name == tool_name and canonical_json(rule.arguments) == expected:
            return rule
    return None
