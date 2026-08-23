"""OpenRouter inference composed from the provider-neutral chat transport."""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from typing import Any, Self, cast
from urllib.parse import urlparse

from skillroll.inference import transport as transport_module
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
    SecretRedactor,
)
from skillroll.inference.transport import (
    ChatRequest,
    ChatResponse,
    ChatTransport,
    OpenAIChatTransport,
    TransportFailure,
)


@dataclass(frozen=True, slots=True)
class OpenRouterCost:
    """Authoritative charged cost returned for one OpenRouter generation."""

    generation_id: str
    amount: float
    unit: str = "credits"
    source: str = "openrouter_generation"


@dataclass(frozen=True, slots=True)
class OpenRouterInferenceResult:
    """One ordinary chat response paired with its OpenRouter charged cost."""

    response: ChatResponse
    cost: OpenRouterCost


def _generation_cost(payload: object, generation_id: str) -> OpenRouterCost:
    """Parse the documented GET /generation total_cost without guessing."""
    if not isinstance(payload, dict):
        raise ValueError("OpenRouter generation metadata was not an object.")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("id") != generation_id:
        raise ValueError(
            "OpenRouter generation metadata did not match the response id."
        )
    amount = data.get("total_cost")
    if (
        isinstance(amount, bool)
        or not isinstance(amount, int | float)
        or not math.isfinite(float(amount))
        or amount < 0
    ):
        raise ValueError("OpenRouter generation metadata did not include a valid cost.")
    return OpenRouterCost(generation_id, float(amount))


async def _generation_metadata(
    client: Any,
    module: Any,
    generation_id: str,
    retry_delays: tuple[float, ...],
    ordinal: int = 0,
) -> object:
    """Fetch eventually consistent metadata without retrying inference."""
    try:
        return await client.get(
            "/generation",
            cast_to=dict[str, Any],
            options={"params": {"id": generation_id}},
        )
    except module.APIStatusError as error:
        if error.status_code != 404 or ordinal >= len(retry_delays):
            raise
        delay = retry_delays[ordinal]
        if delay:
            await asyncio.sleep(delay)
        return await _generation_metadata(
            client, module, generation_id, retry_delays, ordinal + 1
        )


class OpenRouterInference:
    """Reuse SkillRoll chat inference, then fetch exact OpenRouter cost metadata."""

    def __init__(
        self,
        profile: ResolvedInference,
        *,
        transport: ChatTransport | None = None,
        metadata_client: object | None = None,
        cost_retry_delays: tuple[float, ...] = (0.5, 1.5, 4.0),
    ) -> None:
        parsed_url = urlparse(profile.base_url)
        if parsed_url.scheme != "https" or parsed_url.hostname != "openrouter.ai":
            raise ValueError(
                "OpenRouterInference requires an https://openrouter.ai API base URL."
            )
        self._profile = profile
        self._redactor = SecretRedactor(profile.api_key)
        self._transport = transport or OpenAIChatTransport.from_profile(profile)
        self._owns_transport = transport is None
        if metadata_client is None:
            client_type = transport_module.AsyncOpenAI
            if client_type is None:
                from openai import AsyncOpenAI as imported_client

                client_type = imported_client
            metadata_client = client_type(
                api_key=profile.api_key.reveal(),
                base_url=profile.base_url,
                timeout=profile.limits.timeout_seconds,
                max_retries=0,
            )
        self._metadata_client = metadata_client
        self._cost_retry_delays = cost_retry_delays

    async def complete(self, request: ChatRequest) -> OpenRouterInferenceResult:
        """Run one existing chat request and retrieve its authoritative charged cost."""
        response = await self._transport.complete(request)
        generation_id = response.response_id
        if not generation_id:
            raise self._failure(
                InferenceFailureKind.MALFORMED_RESPONSE,
                "OpenRouter did not return a generation id for cost lookup.",
                ValueError("missing response id"),
            )
        module = transport_module.openai
        if module is None:
            import openai as imported_openai

            module = imported_openai
        try:
            client = cast(Any, self._metadata_client)
            payload = await _generation_metadata(
                client, module, generation_id, self._cost_retry_delays
            )
            return OpenRouterInferenceResult(
                response, _generation_cost(payload, generation_id)
            )
        except asyncio.CancelledError:
            raise
        except module.AuthenticationError as error:
            raise self._failure(
                InferenceFailureKind.UNAUTHORIZED,
                "OpenRouter rejected the API key during cost lookup.",
                error,
            ) from error
        except module.RateLimitError as error:
            raise self._failure(
                InferenceFailureKind.RATE_LIMITED,
                "OpenRouter rate-limited the generation cost lookup.",
                error,
            ) from error
        except module.APITimeoutError as error:
            raise self._failure(
                InferenceFailureKind.TIMEOUT,
                "OpenRouter did not return generation cost before the timeout.",
                error,
            ) from error
        except module.APIStatusError as error:
            kind = (
                InferenceFailureKind.SERVICE_FAILURE
                if error.status_code >= 500
                else InferenceFailureKind.REQUEST_REJECTED
            )
            raise self._failure(
                kind, "OpenRouter rejected the generation cost lookup.", error
            ) from error
        except (json.JSONDecodeError, ValueError, TypeError) as error:
            raise self._failure(
                InferenceFailureKind.MALFORMED_RESPONSE,
                "OpenRouter returned generation cost metadata "
                "SkillRoll could not read.",
                error,
            ) from error
        except module.APIError as error:
            raise self._failure(
                InferenceFailureKind.SERVICE_FAILURE,
                "SkillRoll could not retrieve OpenRouter generation cost.",
                error,
            ) from error

    def _failure(
        self, kind: InferenceFailureKind, summary: str, error: Exception
    ) -> TransportFailure:
        return TransportFailure(
            InferenceFailure(kind, summary, (self._redactor.redact(str(error)),))
        )

    async def close(self) -> None:
        """Close both request-scoped clients created by this service."""
        if self._owns_transport:
            await self._transport.close()
        client = cast(Any, self._metadata_client)
        await client.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


async def openrouter_inference(
    profile: ResolvedInference, request: ChatRequest
) -> OpenRouterInferenceResult:
    """Convenience endpoint for one OpenRouter completion plus exact charged cost."""
    async with OpenRouterInference(profile) as service:
        return await service.complete(request)
