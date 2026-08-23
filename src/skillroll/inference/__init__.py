"""The provider-neutral inference boundary and explicit provider extensions."""

from skillroll.inference.openrouter import (
    OpenRouterCost,
    OpenRouterInference,
    OpenRouterInferenceResult,
    openrouter_inference,
)

__all__ = [
    "OpenRouterCost",
    "OpenRouterInference",
    "OpenRouterInferenceResult",
    "openrouter_inference",
]
