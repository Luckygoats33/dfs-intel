"""Precompute a tier band of parlays for each live UFC card and NFL week."""
from __future__ import annotations

from dfs_intel.odds_math import implied_prob
from dfs_intel.parlay_search import sample_parlays
from dfs_intel.tiers import american_of_decimal, tiers


def _edge(leg: dict) -> float | None:
    text = leg.get("market_american")
    prob = leg.get("model_p")
    if not text or prob is None:
        return None
    try:
        american = int(str(text).replace("+", ""))
    except ValueError:
        return None
    return float(prob) - implied_prob(american)


def groups_from_slate(slate: dict) -> list[dict]:
    groups = []
    for group in slate.get("groups") or []:
        legs = []
        for leg in group.get("legs") or []:
            if not leg.get("decimal") or not leg.get("model_p"):
                continue
            if not 0 < float(leg["model_p"]) < 1:
                continue
            legs.append({
                "id": leg["id"],
                "label": leg.get("label") or "",
                "type": leg.get("type") or "",
                "p": float(leg["model_p"]),
                "decimal": float(leg["decimal"]),
                "edge": _edge(leg),
                "market_american": leg.get("market_american"),
                "fair_american": leg.get("fair_american"),
                "kind": leg.get("kind") or "model",
                "thin": bool(leg.get("thin")),
                "source": leg.get("source") or "",
                "why": _why(leg),
                "atoms": leg.get("atoms"),
                "timing": leg.get("timing"),
            })
        if legs:
            groups.append({
                "id": group["id"],
                "label": group.get("label") or "",
                "sport": group.get("sport") or slate.get("sport"),
                "atoms": group.get("atoms") or [],
                "timing_p": group.get("timing_p") or {},
                "legs": legs,
            })
    return groups


def _why(leg: dict) -> str:
    prob = leg.get("model_p")
    pct = f"{prob * 100:.1f}%" if isinstance(prob, (int, float)) else "unavailable"
    if leg.get("type") == "timing":
        return f"Observed rate {pct}."
    if leg.get("market_american") and leg.get("type") != "moneyline":
        return f"Model {pct} against the market {leg['market_american']}."
    if leg.get("type") == "moneyline":
        return f"No-vig {pct}."
    if leg.get("fair_american"):
        return f"Model {pct}, fair {leg['fair_american']}."
    return f"Model {pct}."


def _public_ticket(ticket: dict) -> dict:
    legs = []
    for leg in ticket["legs"]:
        fight = leg.get("fight") or ""
        label = leg["label"]
        if fight and fight.lower() not in label.lower():
            label = f"{label} ({fight})"
        legs.append({
            "id": leg["id"],
            "label": label,
            "type": leg["type"],
            "price": leg.get("market_american") or leg.get("fair_american") or "",
            "why": leg.get("why") or "",
            "kind": leg.get("kind") or "model",
            "thin": bool(leg.get("thin")),
            "p": round(float(leg["p"]), 4),
            "decimal": round(float(leg["decimal"]), 4),
            "edge": None if leg.get("edge") is None else round(float(leg["edge"]), 4),
            "market": bool(leg.get("market_american")),
        })
    return {
        "key": ticket["key"],
        "n": ticket["n"],
        "p": round(ticket["p"], 6),
        "decimal": round(ticket["decimal"], 4),
        "american": american_of_decimal(ticket["decimal"]),
        "edge": None if ticket["edge"] is None else round(ticket["edge"], 4),
        "same": ticket["same"],
        "nfl_same": ticket["nfl_same"],
        "min_p": round(min(leg["p"] for leg in legs), 4) if legs else None,
        "legs": legs,
    }


def parlays_by_tier(slate: dict, limit: int = 12) -> dict[str, list[dict]]:
    groups = groups_from_slate(slate)
    out = {}
    seed_base = int(str(slate.get("id") or "0").encode().hex()[:6] or "1", 16)
    for tier in tiers():
        seen = set()
        tickets = []
        for offset, same in ((0, False), (17, True)):
            drawn = sample_parlays(
                groups,
                min_decimal=tier["min_decimal"],
                max_decimal=tier["max_decimal"],
                min_legs=2,
                max_legs=10,
                limit=limit if not same else max(4, limit // 3),
                seed=seed_base + tier["american"] + offset,
                same_event=same,
            )
            for ticket in drawn:
                if ticket["key"] in seen:
                    continue
                seen.add(ticket["key"])
                tickets.append(_public_ticket(ticket))
        tickets.sort(key=lambda ticket: -ticket["p"])
        out[tier["id"]] = tickets[:limit]
    return out
