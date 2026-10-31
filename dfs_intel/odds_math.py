"""American-odds conversions and parlay products. Pure functions. No I/O."""
from __future__ import annotations


def implied_prob(american: int) -> float:
    """Vigged implied probability of an American price. Not a no-vig chance."""
    american = int(american)
    if american == 0:
        raise ValueError("american odds of 0 are not a price")
    if american > 0:
        return 100.0 / (american + 100.0)
    return (-american) / ((-american) + 100.0)


def no_vig(ml_a: int, ml_b: int) -> tuple[float, float, float]:
    """Return (p_a, p_b, overround) after normalizing the two implied probabilities."""
    a, b = implied_prob(ml_a), implied_prob(ml_b)
    total = a + b
    return a / total, b / total, total - 1.0


def to_decimal(american: int) -> float:
    american = int(american)
    if american > 0:
        return 1.0 + american / 100.0
    if american == 0:
        raise ValueError("american odds of 0 are not a price")
    return 1.0 + 100.0 / abs(american)


def to_american(decimal: float) -> int | None:
    if decimal is None or decimal <= 1.0:
        return None
    if decimal >= 2.0:
        return int(round((decimal - 1.0) * 100))
    return int(round(-100.0 / (decimal - 1.0)))


def format_american(american: int | None) -> str:
    if american is None:
        return "unavailable"
    return f"+{american}" if american > 0 else str(int(american))


def combine_parlay(legs: list[dict], stake: float = 1.0) -> dict:
    """Product of listed decimal prices and of no-vig probabilities.

    `legs` items need `decimal` and `novig`. The decimal product is the product of
    the source moneylines (vig included). The implied chance multiplies no-vig
    probabilities and assumes independence. A book parlay price will differ.
    "Pays $50+ on $1" means total payout (stake included) >= $50 at a $1 stake,
    i.e. combined decimal odds >= 50. It does not depend on `stake`.
    """
    if stake < 0:
        raise ValueError("stake must be >= 0")
    if not legs:
        return {
            "legs": 0,
            "decimal": None,
            "american": None,
            "implied": None,
            "payout": None,
            "profit": None,
            "pays_50_on_1": False,
        }
    decimal = 1.0
    implied = 1.0
    for leg in legs:
        decimal *= float(leg["decimal"])
        implied *= float(leg["novig"])
    payout = stake * decimal
    return {
        "legs": len(legs),
        "decimal": decimal,
        "american": to_american(decimal),
        "implied": implied,
        "payout": payout,
        "profit": payout - stake,
        "pays_50_on_1": decimal >= 50.0,
    }


def presets_plus_5000(groups: list[dict]) -> dict | None:
    """One leg per group, longest model prices first, until the ticket is +5000 or longer.

    Legs marked thin are left out of the automatic ticket. One leg per group keeps
    the price a product of separate events.
    """
    picks = []
    for group in groups:
        cands = []
        for leg in group.get("legs") or []:
            prob = leg.get("model_p", leg.get("novig"))
            if leg.get("thin") or prob is None or not leg.get("decimal"):
                continue
            if prob <= 0 or prob >= 1:
                continue
            cands.append(leg)
        if not cands:
            continue
        picks.append(min(cands, key=lambda leg: leg.get("model_p", leg.get("novig"))))
    picks.sort(key=lambda leg: leg.get("model_p", leg.get("novig")))
    chosen = []
    priced = None
    for leg in picks:
        chosen.append(leg)
        priced = combine_parlay(chosen, 1.0)
        if (priced.get("american") or 0) >= 5000 or len(chosen) >= 8:
            break
    if not priced or (priced.get("american") or 0) < 5000:
        return None
    return {
        "id": "longshot-plus5000",
        "kind": "longshot",
        "n": len(chosen),
        "name": f"{len(chosen)}-leg +5000",
        "leg_ids": [leg["id"] for leg in chosen],
        "labels": [leg["label"] for leg in chosen],
        "decimal": priced["decimal"],
        "american": priced["american"],
        "american_fmt": format_american(priced["american"]),
        "implied": priced["implied"],
        "payout_on_1": priced["payout"],
        "profit_on_1": priced["profit"],
        "pays_50_on_1": True,
    }


def preset_parlays(groups: list[dict]) -> list[dict]:
    """3/5/7-leg favorite and longshot parlays from valid two-sided prices.

    Each group is one fight or one game: {"id", "label", "legs": [side, side]}.
    A side is {"id", "label", "american", "decimal", "novig"}.
    Favorites are the higher no-vig side of each group, chalkiest first.
    Longshots are the lower no-vig side, longest first.
    Groups with fewer than two priced sides are skipped.
    """
    favorites, longshots = [], []
    for group in groups:
        sides = [s for s in group.get("legs") or [] if s.get("novig") is not None and s.get("decimal")]
        if len(sides) < 2:
            continue
        fav = max(sides, key=lambda s: (s["novig"], -abs(s.get("american") or 0)))
        dog = min(sides, key=lambda s: (s["novig"], abs(s.get("american") or 0)))
        if fav["id"] == dog["id"]:
            continue
        favorites.append(fav)
        longshots.append(dog)
    favorites.sort(key=lambda s: -s["novig"])
    longshots.sort(key=lambda s: s["novig"])
    out = []
    for kind, pool in (("favorite", favorites), ("longshot", longshots)):
        for n in (3, 5, 7):
            if len(pool) < n:
                continue
            chosen = pool[:n]
            priced = combine_parlay(chosen, 1.0)
            out.append({
                "id": f"{kind}-{n}",
                "kind": kind,
                "n": n,
                "name": f"{n}-leg {kind}",
                "leg_ids": [s["id"] for s in chosen],
                "labels": [s["label"] for s in chosen],
                "decimal": priced["decimal"],
                "american": priced["american"],
                "implied": priced["implied"],
                "payout_on_1": priced["payout"],
                "profit_on_1": priced["profit"],
                "pays_50_on_1": priced["pays_50_on_1"],
            })
    return out
