from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: Decimal   # USD per 1M input tokens
    output_per_million: Decimal  # USD per 1M output tokens

    def calculate(self, tokens_in: int, tokens_out: int) -> Decimal:
        return (
            Decimal(tokens_in)  * self.input_per_million  / 1_000_000 +
            Decimal(tokens_out) * self.output_per_million / 1_000_000
        )


# Single source of truth for model pricing.
# Update here when a provider changes rates — no other file needs to change.
_REGISTRY: dict[str, ModelPricing] = {
    # OpenRouter — free tier
    "nvidia/nemotron-3-super-120b-a12b:free": ModelPricing(
        input_per_million=Decimal("0"),
        output_per_million=Decimal("0"),
    ),
    # OpenAI (pricing as of 2025-06)
    "gpt-4o-mini": ModelPricing(
        input_per_million=Decimal("0.15"),
        output_per_million=Decimal("0.60"),
    ),
    "gpt-4o": ModelPricing(
        input_per_million=Decimal("2.50"),
        output_per_million=Decimal("10.00"),
    ),
}


def get_cost(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    """Return estimated USD cost for a single LLM call.

    Returns Decimal("0") for unknown models rather than raising — new models
    should be added to _REGISTRY, but a missing entry must never crash a query.
    """
    pricing = _REGISTRY.get(model)
    if pricing is None:
        return Decimal("0")
    return pricing.calculate(tokens_in, tokens_out)
