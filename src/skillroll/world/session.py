"""Ordered precedence and complete transcript state for one simulated world."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter

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
TOOL_INPUT_SOURCES = frozenset({"rejected", "recovered"})
_MAX_RECORDED_INPUT_CHARS = 2048


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
        self._world_seconds = 0.0
        self._world_inference_made = False
        self._world_inference_attempts = 0
        self._world_missing_usage = 0

    @property
    def events(self) -> tuple[WorldEvent, ...]:
        """Return every complete result, never the compacted prompt view."""
        return tuple(self._events)

    @property
    def world_seconds(self) -> float:
        """Wall time spent handling World callbacks, including failed calls."""
        return self._world_seconds

    @property
    def world_inference_made(self) -> bool:
        """Whether any generative World request started, including failures."""
        return self._world_inference_made

    @property
    def world_inference_attempts(self) -> int:
        """Number of generative World requests started, including failures."""
        return self._world_inference_attempts

    @property
    def world_missing_usage(self) -> int:
        """Number of World requests without complete provider usage evidence."""
        return self._world_missing_usage

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

    def record_tool_input(self, source: str, raw: str, reason: str) -> None:
        """Record a malformed world_action input that was rejected or repaired."""
        self._append(
            "world_action",
            {"raw": raw[:_MAX_RECORDED_INPUT_CHARS]},
            reason,
            source,
        )

    async def __call__(self, tool_name: str, arguments: Mapping[str, JSONValue]) -> str:
        """Respond in strict precedence and prevent concurrent history races."""
        return await self._dispatch(tool_name, arguments)

    async def _dispatch(
        self, tool_name: str, arguments: Mapping[str, JSONValue]
    ) -> str:
        """Apply precedence while serializing stateful action history."""
        async with self._lock:
            started = perf_counter()
            try:
                return await self._process(tool_name, arguments)
            finally:
                self._world_seconds += perf_counter() - started

    async def _process(self, tool_name: str, arguments: Mapping[str, JSONValue]) -> str:
        """Apply precedence to one action while the caller holds the lock."""
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
            return self._append(tool_name, arguments, rule.result, "rule", rule.name)
        history = tuple(
            HistoryItem(item.tool_name, item.arguments, item.result)
            for item in self._events
            if item.source not in TOOL_INPUT_SOURCES
        )
        self._world_inference_made = True
        self._world_inference_attempts += 1
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
            self._world_missing_usage += 1
            raise
        except WorldModelError as error:
            self._world_missing_usage += 1
            raise WorldActionError(error.failure) from error
        if reply.usage is None:
            self._world_missing_usage += 1
        return self._append(
            tool_name,
            arguments,
            reply.result,
            "world_model",
            model=reply.model,
            usage=reply.usage,
            omitted_history=reply.omitted_history,
        )
