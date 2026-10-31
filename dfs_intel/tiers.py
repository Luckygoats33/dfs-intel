"""Payout tiers. +5000 is 50-to-1 profit: $51 back on a $1 stake."""
from __future__ import annotations

from dfs_intel.odds_math import format_american, to_american

# American odds floors. The next tier is the exclusive top of the band.
TIER_FLOORS = (5000, 10000, 25000, 50000, 100000, 500000)


def decimal_of(american: int) -> float:
    return 1.0 + american / 100.0


def tiers() -> list[dict]:
    out = []
    for index, floor in enumerate(TIER_FLOORS):
        hi = TIER_FLOORS[index + 1] if index + 1 < len(TIER_FLOORS) else None
        label = "+5000 (50 to 1)" if floor == 5000 else format_american(floor)
        out.append({
            "id": str(floor),
            "american": floor,
            "label": label,
            "min_decimal": decimal_of(floor),
            "max_decimal": decimal_of(hi) if hi else None,
            "max_american": hi,
        })
    return out


def tier_for_decimal(decimal: float) -> str | None:
    if decimal is None or decimal < decimal_of(TIER_FLOORS[0]):
        return None
    chosen = None
    for tier in tiers():
        if decimal + 1e-9 < tier["min_decimal"]:
            break
        if tier["max_decimal"] is not None and decimal >= tier["max_decimal"] - 1e-9:
            continue
        chosen = tier["id"]
    return chosen


def american_of_decimal(decimal: float) -> str:
    return format_american(to_american(decimal))
