"""Token cost estimation.

Prices change frequently, so no vendor prices are hard-coded. Configure them per organization in the
provider credential's `config.pricing` as USD per 1M tokens, e.g.
    {"pricing": {"gpt-4o-mini": {"input": 0.15, "output": 0.6}}}
Keys match exact model names or prefixes. Unknown models are tracked with cost 0.
"""

from __future__ import annotations

from typing import Any


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int, pricing: dict[str, Any] | None) -> float:
    if not pricing:
        return 0.0
    entry = pricing.get(model)
    if entry is None:
        matches = [k for k in pricing if model.startswith(k)]
        entry = pricing[max(matches, key=len)] if matches else None
    if not entry:
        return 0.0
    return round(
        (prompt_tokens * float(entry.get("input", 0)) + completion_tokens * float(entry.get("output", 0))) / 1_000_000,
        6,
    )
