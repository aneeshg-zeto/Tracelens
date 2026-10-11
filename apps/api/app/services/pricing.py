"""Versioned token pricing.

Costs are only computed when the provider reported token usage and the model
matches a pricing entry. Unknown models produce cost_status="unavailable" and a
null cost, never a silent zero.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings

BUNDLED = Path(__file__).resolve().parents[1] / "pricing" / "pricing.json"
_SNAPSHOT_SUFFIX = re.compile(r"^-(\d{4}-?\d{2}-?\d{2}|\d{8}|latest|v\d+(:\d+)?)$")
PROVIDER_ALIASES = {"azure_openai": "openai", "azure": "openai", "anthropic_bedrock": "anthropic"}


@dataclass(frozen=True)
class ModelPrice:
    key: str
    input: Decimal
    output: Decimal
    cached_input: Decimal | None


@dataclass(frozen=True)
class PricingTable:
    version: str
    models: dict[str, ModelPrice]


@dataclass(frozen=True)
class CostResult:
    cost_usd: Decimal | None
    status: str | None  # reported | calculated | unavailable | None (no usage)
    pricing_version: str | None


@lru_cache
def load_pricing() -> PricingTable:
    path = Path(get_settings().pricing_file) if get_settings().pricing_file else BUNDLED
    data: dict[str, Any] = json.loads(path.read_text())
    models = {
        key.lower(): ModelPrice(
            key=key,
            input=Decimal(str(entry["input"])),
            output=Decimal(str(entry["output"])),
            cached_input=Decimal(str(entry["cached_input"]))
            if entry.get("cached_input") is not None
            else None,
        )
        for key, entry in data["models"].items()
    }
    return PricingTable(version=str(data["version"]), models=models)


def find_price(
    provider: str | None, model: str | None, table: PricingTable | None = None
) -> ModelPrice | None:
    if not model:
        return None
    table = table or load_pricing()
    model_l = model.lower().strip()
    if "/" in model_l and not provider:
        provider, model_l = model_l.split("/", 1)
    providers = [PROVIDER_ALIASES.get((provider or "").lower(), (provider or "").lower())]
    if not providers[0]:
        providers = sorted({k.split("/", 1)[0] for k in table.models})
    best: ModelPrice | None = None
    best_len = -1
    for prov in providers:
        for key, price in table.models.items():
            kp, km = key.split("/", 1)
            if kp != prov:
                continue
            matches = model_l == km or (model_l.startswith(km) and _SNAPSHOT_SUFFIX.match(model_l[len(km) :]))
            if matches and len(km) > best_len:
                best, best_len = price, len(km)
    return best


def compute_cost(
    *,
    provider: str | None,
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_tokens: int | None,
    reported_cost: float | None,
) -> CostResult:
    if reported_cost is not None:
        return CostResult(Decimal(str(reported_cost)), "reported", None)
    if input_tokens is None and output_tokens is None:
        return CostResult(None, None, None)
    table = load_pricing()
    price = find_price(provider, model, table)
    if price is None:
        return CostResult(None, "unavailable", table.version)
    million = Decimal(1_000_000)
    inp = Decimal(input_tokens or 0)
    cached = Decimal(min(cached_tokens or 0, input_tokens or 0))
    out = Decimal(output_tokens or 0)
    cached_rate = price.cached_input if price.cached_input is not None else price.input
    cost = ((inp - cached) * price.input + cached * cached_rate + out * price.output) / million
    return CostResult(cost.quantize(Decimal("0.00000001")), "calculated", table.version)
