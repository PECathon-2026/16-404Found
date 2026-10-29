"""Per-model price table (USD per 1M tokens) and cost computation.

Unknown models cost 0.0 with a warning: cost accounting must never crash a mission.
Haiku 5.5 has a second rate card for prompts over 100K tokens (model-migration.md,
"Migrating to Claude Haiku 5.5"); the long-prompt card is applied automatically.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Price:
    input: float
    output: float
    cache_read: float
    cache_write: float  # 5-minute TTL write


PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": Price(2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": Price(0.10, 0.50, 0.01, 0.125),
}

# Prompts above this many tokens are billed on a higher card (Haiku 5.5 only).
LONG_PROMPT_THRESHOLD = 100_000
LONG_PRICES: dict[str, Price] = {
    "claude-haiku-5-5": Price(0.50, 2.50, 0.05, 0.625),
}


def _lookup(model: str) -> str | None:
    if model in PRICES:
        return model
    for key in PRICES:  # tolerate date-suffixed ids, e.g. claude-opus-5-5-20260101
        if model.startswith(key):
            return key
    return None


def has_price(model: str) -> bool:
    return _lookup(model) is not None


def cost_usd(model: str, usage_counts: Mapping[str, int]) -> float:
    """Cost for ``usage_counts`` with keys tokens_in/tokens_out/tokens_cached_read/tokens_cache_write.

    ``tokens_in`` is the uncached input (the API's ``input_tokens``). Thinking tokens are already part
    of ``tokens_out`` and are not billed twice.
    """
    key = _lookup(model)
    if key is None:
        log.warning("no price for model %r; cost reported as 0.0", model)
        return 0.0
    t_in = int(usage_counts.get("tokens_in", 0) or 0)
    t_out = int(usage_counts.get("tokens_out", 0) or 0)
    t_read = int(usage_counts.get("tokens_cached_read", 0) or 0)
    t_write = int(usage_counts.get("tokens_cache_write", 0) or 0)
    price = PRICES[key]
    if key in LONG_PRICES and (t_in + t_read + t_write) > LONG_PROMPT_THRESHOLD:
        price = LONG_PRICES[key]
    total = (
        t_in * price.input + t_out * price.output + t_read * price.cache_read + t_write * price.cache_write
    )
    return total / 1_000_000
