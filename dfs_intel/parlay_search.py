"""Sample conflict-safe parlays inside a payout band. One slot per fight or game."""
from __future__ import annotations

import random

from dfs_intel.method_split import joint_probability


def _weight(slot: dict) -> float:
    edge = slot.get("edge") or 0.0
    return max(1e-6, float(slot["p"])) * (1.0 + max(0.0, edge) * 8.0)


def _slot_from_legs(legs: list[dict], group: dict, probability: float) -> dict:
    decimal = 1.0
    edges = []
    for leg in legs:
        decimal *= float(leg["decimal"])
        if leg.get("edge") is not None:
            edges.append(leg["edge"])
    return {
        "legs": legs,
        "p": probability,
        "decimal": decimal,
        "group_id": group["id"],
        "group_label": group.get("label") or "",
        "sport": group.get("sport"),
        "edge": (sum(edges) / len(edges)) if edges else None,
    }


def slots_for_group(group: dict, same_event: bool = False, per_group: int = 6) -> list[dict]:
    """A few long prices and a few higher probabilities, so every tier is reachable."""
    legs = [leg for leg in group.get("legs") or [] if leg.get("decimal") and 0 < float(leg.get("p") or 0) < 1]
    if not legs:
        return []
    by_p = sorted(legs, key=lambda leg: -float(leg["p"]))[:3]
    by_price = sorted(legs, key=lambda leg: -float(leg["decimal"]))[:4]
    seen = set()
    chosen = []
    for leg in by_p + by_price:
        if leg["id"] in seen:
            continue
        seen.add(leg["id"])
        chosen.append(leg)
        if len(chosen) >= per_group:
            break
    slots = [_slot_from_legs([leg], group, float(leg["p"])) for leg in chosen]
    atoms = group.get("atoms") or []
    if same_event and atoms and len(chosen) >= 2:
        pairs = []
        for i, left in enumerate(chosen):
            for right in chosen[i + 1:]:
                result = joint_probability(atoms, [left, right], group.get("timing_p"))
                if result.get("status") != "ok" or not result.get("p"):
                    continue
                pairs.append(_slot_from_legs([left, right], group, float(result["p"])))
        pairs.sort(key=lambda slot: -slot["p"])
        slots.extend(pairs[:3])
    return slots


def sample_parlays(groups: list[dict], *, min_decimal: float, max_decimal: float | None,
                   min_legs: int = 2, max_legs: int = 8, limit: int = 16, seed: int = 1,
                   same_event: bool = False) -> list[dict]:
    """Weighted draws. Higher model probability and positive edge are more likely."""
    rng = random.Random(seed)
    pools = []
    for group in groups:
        slots = slots_for_group(group, same_event=same_event)
        if slots:
            pools.append({"id": group["id"], "slots": slots})
    if len(pools) < min_legs:
        return []
    found = []
    seen = set()
    attempts = max(40, limit * 25)
    for _ in range(attempts):
        if len(found) >= limit:
            break
        order = pools[:]
        rng.shuffle(order)
        chosen = []
        decimal = 1.0
        used = set()
        for pool in order:
            if len(chosen) >= max_legs:
                break
            leg_count = sum(len(slot["legs"]) for slot in chosen)
            if leg_count >= min_legs and decimal >= min_decimal and (max_decimal is None or decimal < max_decimal):
                break
            room = []
            for slot in pool["slots"]:
                next_n = leg_count + len(slot["legs"])
                next_dec = decimal * slot["decimal"]
                if next_n > max_legs:
                    continue
                if max_decimal is not None and next_dec >= max_decimal and not (leg_count >= min_legs and decimal >= min_decimal):
                    continue
                if max_decimal is not None and next_dec >= max_decimal:
                    continue
                room.append(slot)
            if not room:
                continue
            weights = [_weight(slot) for slot in room]
            pick = rng.choices(room, weights=weights, k=1)[0]
            chosen.append(pick)
            decimal *= pick["decimal"]
            used.add(pool["id"])
        leg_count = sum(len(slot["legs"]) for slot in chosen)
        if leg_count < min_legs or decimal < min_decimal:
            continue
        if max_decimal is not None and decimal >= max_decimal:
            continue
        legs = []
        for slot in chosen:
            for leg in slot["legs"]:
                stamped = dict(leg)
                stamped["fight"] = slot.get("group_label") or ""
                legs.append(stamped)
        key = tuple(sorted(leg["id"] for leg in legs))
        if key in seen:
            continue
        seen.add(key)
        prob = 1.0
        for slot in chosen:
            prob *= slot["p"]
        edges = [slot["edge"] for slot in chosen if slot.get("edge") is not None]
        found.append({
            "key": "|".join(key),
            "legs": legs,
            "n": len(legs),
            "p": prob,
            "decimal": decimal,
            "edge": (sum(edges) / len(edges)) if edges else None,
            "same": any(len(slot["legs"]) > 1 and slot.get("sport") != "nfl" for slot in chosen),
            "nfl_same": any(len(slot["legs"]) > 1 and slot.get("sport") == "nfl" for slot in chosen),
            "group_ids": [slot["group_id"] for slot in chosen],
        })
    found.sort(key=lambda ticket: -ticket["p"])
    return found[:limit]
