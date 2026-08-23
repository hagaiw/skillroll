"""Ordered precedence and complete transcript state for one simulated world."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from skillroll.diagnostics import JSONValue
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
)
from skillroll.inference.transport import ChatTransport, ModelUsage
from skillroll.models import DeterministicRule, InferenceLimits
from skillroll.world.bundle import BundleIndex, bundle_read
from skillroll.world.model import HistoryItem, WorldModelError, model_action
from skillroll.world.rules import canonical_json, matching_rule

MAX_WORLD_ACTIONS_PER_CASE = 64


class WorldActionError(Exception):
    """A safe no-result failure surfaced through the generic agent tool boundary."""

    def __init__(self, failure: InferenceFailure) -> None:
        self.failure = failure
        super().__init__(failure.summary)


@dataclass(frozen=True, slots=True)
class WorldEvent:
    """One immutable action and returned result in execution order."""

    index: int
    tool_name: str
    arguments: Mapping[str, JSONValue]
    result: str
    source: str
    rule_name: str | None = None
    model: str | None = None
    usage: ModelUsage | None = None
    omitted_history: int = 0


class WorldSession:
    """Provide bundle reads, exact rules, then one generative action result."""

    def __init__(
        self,
        profile: ResolvedInference,
        limits: InferenceLimits,
        world: str,
        bundle: BundleIndex,
        rules: tuple[DeterministicRule, ...],
        transport: ChatTransport,
    ) -> None:
        self._profile = profile
        self._limits = limits
        self._world = world
        self._bundle = bundle
        self._rules = rules
        self._transport = transport
        self._events: list[WorldEvent] = []
        self._lock = asyncio.Lock()

    @property
    def events(self) -> tuple[WorldEvent, ...]:
        """Return every complete result, never the compacted prompt view."""
        return tuple(self._events)

    def _validate(self, tool_name: str, arguments: Mapping[str, JSONValue]) -> None:
        if not tool_name or len(tool_name) > 200 or "\n" in tool_name:
            raise WorldActionError(
                InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "world_action tool_name must contain 1 to 200 characters on "
                    "one line.",
                )
            )
        try:
            encoded = canonical_json(arguments).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise WorldActionError(
                InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "world_action arguments must be a JSON object.",
                )
            ) from error
        if len(encoded) > 16 * 1024:
            raise WorldActionError(
                InferenceFailure(
                    InferenceFailureKind.EXECUTION_ERROR,
                    "world_action arguments are larger than 16 KiB.",
                )
            )

    def _append(
        self,
        tool_name: str,
        arguments: Mapping[str, JSONValue],
        result: str,
        source: str,
        rule_name: str | None = None,
        model: str | None = None,
        usage: ModelUsage | None = None,
        omitted_history: int = 0,
    ) -> str:
        self._events.append(
            WorldEvent(
                len(self._events),
                tool_name,
                arguments,
                result,
                source,
                rule_name,
                model,
                usage,
                omitted_history,
            )
        )
        return result

    async def __call__(self, tool_name: str, arguments: Mapping[str, JSONValue]) -> str:
        """Respond in strict precedence and prevent concurrent history races."""
        async with self._lock:
            self._validate(tool_name, arguments)
            if len(self._events) >= MAX_WORLD_ACTIONS_PER_CASE:
                observed = (
                    ", ".join(f"`{item.tool_name}`" for item in self._events) or "none"
                )
                raise WorldActionError(
                    InferenceFailure(
                        InferenceFailureKind.EXECUTION_ERROR,
                        f"This case reached SkillRoll's World-action safety limit "
                        f"of {MAX_WORLD_ACTIONS_PER_CASE} after "
                        f"{len(self._events)} completed action(s). No additional "
                        f"action could be simulated. Observed actions: {observed}.",
                    )
                )
            bundled = bundle_read(self._bundle, tool_name, arguments)
            if bundled is not None:
                return self._append(tool_name, arguments, bundled, "skill_bundle")
            rule = matching_rule(self._rules, tool_name, arguments)
            if rule is not None:
                return self._append(
                    tool_name, arguments, rule.result, "rule", rule.name
                )
            history = tuple(
                HistoryItem(item.tool_name, item.arguments, item.result)
                for item in self._events
            )
            try:
                reply = await model_action(
                    self._transport,
                    self._profile,
                    self._limits.max_output_tokens,
                    self._world,
                    history,
                    tool_name,
                    arguments,
                )
            except asyncio.CancelledError:
                raise
            except WorldModelError as error:
                raise WorldActionError(error.failure) from error
            return self._append(
                tool_name,
                arguments,
                reply.result,
                "world_model",
                model=reply.model,
                usage=reply.usage,
                omitted_history=reply.omitted_history,
            )
