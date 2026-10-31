"""method-split-v0: no-vig win probability times a shrunk method/round split.

The split is the fighter's own win mix, pulled toward the weight-class base rate
with K=4 pseudo-wins. Timing legs stay on the observed ufc_timing base rates.
Same-fight legs share one distribution, so a parlay uses the joint, not a product.
"""
from __future__ import annotations

import re

from dfs_intel.odds_math import format_american, to_american, to_decimal
from dfs_intel.ufc_pipeline import norm_name

MODEL = "method-split-v0"
K = 4
THIN_WINS = 8
THIN_CLASS = 30
TIMING_KINDS = ("r1_le60", "any_le60", "last10")
TIMING_FLAGS = {
    "r1_le60": "finish_r1_le60",
    "any_le60": "finish_any_rnd_le60",
    "last10": "finish_last10",
}
TIMING_LABELS = {
    "r1_le60": "Finish in the first 60s of round 1",
    "any_le60": "Finish in the first 60s of any round",
    "last10": "Finish in the last 10s of any round",
}


def clean_weight_class(text: str | None) -> str:
    wc = re.sub(r"\b(UFC|Title|Bout|Interim|Tournament)\b", "", text or "", flags=re.I)
    return re.sub(r"\s+", " ", wc).strip()


def method_bucket(method: str | None) -> str | None:
    text = (method or "").lower()
    if "overturn" in text or "could not continue" in text or text.strip() in {"dq", "disqualification"}:
        return None
    if "ko" in text or "tko" in text:
        return "ko"
    if "sub" in text:
        return "sub"
    if "decision" in text:
        return "dec"
    return None


def _cell(method: str | None, rnd) -> tuple | None:
    bucket = method_bucket(method)
    if bucket is None:
        return None
    if bucket == "dec":
        return ("dec", None)
    try:
        round_n = int(rnd)
    except (TypeError, ValueError):
        return None
    if round_n < 1 or round_n > 5:
        return None
    return (bucket, round_n)


def _cells(scheduled_rounds: int | None) -> list[tuple]:
    rounds = scheduled_rounds if scheduled_rounds in (3, 5) else 5
    out = []
    for rnd in range(1, rounds + 1):
        out.append(("ko", rnd))
        out.append(("sub", rnd))
    out.append(("dec", None))
    return out


def shrink(count: float, n: float, prior: float, k: float = K) -> float:
    return (count + k * prior) / (n + k)


def build_split_table(fights) -> dict:
    """Count decisive wins by method and round. `fights` is an add_flags frame."""
    from collections import defaultdict

    cell_counts: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
    totals: dict[tuple, int] = defaultdict(int)
    fighter_counts: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
    fighter_n: dict[tuple, int] = defaultdict(int)
    by_norm: dict[str, set] = defaultdict(set)

    for row in fights.itertuples(index=False):
        winner = getattr(row, "winner", None)
        if not isinstance(winner, str) or not winner:
            continue
        cell = _cell(getattr(row, "method", None), getattr(row, "rnd", None))
        if cell is None:
            continue
        fmt = getattr(row, "format", None)
        fmt = fmt if isinstance(fmt, str) and fmt in ("3-round", "5-round") else None
        wc = getattr(row, "weight_class", None)
        wc = wc.strip() if isinstance(wc, str) and wc.strip() else None
        keys = [(None, None)]
        if fmt:
            keys.append((None, fmt))
        if wc:
            keys.append((wc, None))
        if wc and fmt:
            keys.append((wc, fmt))
        for key in keys:
            cell_counts[key][cell] += 1
            totals[key] += 1
        name_key = norm_name(winner)
        by_norm[name_key].add(winner)
        if fmt:
            fighter_counts[(name_key, fmt)][cell] += 1
            fighter_n[(name_key, fmt)] += 1
        fighter_counts[(name_key, None)][cell] += 1
        fighter_n[(name_key, None)] += 1

    priors = {}
    for key, n in totals.items():
        if not n:
            continue
        priors[key] = {"n": int(n), "p": {cell: cell_counts[key][cell] / n for cell in cell_counts[key]}}
    fighters = {}
    for key, n in fighter_n.items():
        fighters[key] = {"n": int(n), "counts": dict(fighter_counts[key])}
    return {
        "model": MODEL,
        "k": K,
        "priors": priors,
        "fighters": fighters,
        "by_norm": {key: sorted(names) for key, names in by_norm.items()},
    }


def _prior_block(table: dict, weight_class: str, fmt: str | None):
    order = [(weight_class or None, fmt), (None, fmt), (weight_class or None, None), (None, None)]
    seen = []
    for key in order:
        block = table["priors"].get(key)
        if block and block["n"] > 0:
            seen.append((key, block))
    for key, block in seen:
        if block["n"] >= THIN_CLASS:
            return block, key, False
    if seen:
        return seen[0][1], seen[0][0], True
    return None, None, True


def _fighter_block(table: dict, name: str, fmt: str | None):
    key = norm_name(name)
    names = table["by_norm"].get(key) or []
    if len(names) > 1:
        return {"n": 0, "counts": {}}, True, "More than one mirror fighter shares this normalized name."
    block = table["fighters"].get((key, fmt)) or {"n": 0, "counts": {}}
    return block, False, ""


def shrunk_distribution(counts: dict, n: int, prior: dict, cells: list[tuple], k: float = K) -> dict:
    raw = {cell: shrink(counts.get(cell, 0), n, prior.get(cell, 0.0), k) for cell in cells}
    total = sum(raw.values())
    if total <= 0:
        return {}
    if abs(total - 1.0) > 1e-9:
        raw = {cell: value / total for cell, value in raw.items()}
    return raw


def _timing_choice(fights, weight_class: str, fmt: str | None, kind: str) -> dict:
    flag = TIMING_FLAGS[kind]
    scopes = []
    if weight_class and fmt:
        scopes.append((fights[(fights.weight_class == weight_class) & (fights["format"] == fmt)], f"{weight_class}, {fmt}"))
    if fmt:
        scopes.append((fights[fights["format"] == fmt], fmt))
    if weight_class:
        scopes.append((fights[fights.weight_class == weight_class], weight_class))
    scopes.append((fights, "all fights in the mirror window"))
    for frame, label in scopes:
        n = int(len(frame))
        if n <= 0:
            continue
        rate = float(frame[flag].mean())
        if n >= THIN_CLASS or label == "all fights in the mirror window":
            return {"p": rate, "n": n, "scope": label, "thin": n < THIN_CLASS}
    return {"p": None, "n": 0, "scope": "unavailable", "thin": True}


def fight_model(table: dict | None, fights, name_a: str, name_b: str, p_a: float | None, p_b: float | None,
                weight_class: str, scheduled_rounds: int | None) -> dict:
    """Atoms sum to 1 when both no-vig win probabilities are present."""
    fmt = {3: "3-round", 5: "5-round"}.get(scheduled_rounds)
    cells = _cells(scheduled_rounds)
    timing = {kind: _timing_choice(fights, weight_class, fmt, kind) if fights is not None else {"p": None, "n": 0, "scope": "unavailable", "thin": True}
              for kind in TIMING_KINDS}
    empty = {"atoms": [], "timing": timing, "thin": True, "note": "method split unavailable", "rounds": scheduled_rounds, "fmt": fmt}
    if table is None or p_a is None or p_b is None:
        empty["note"] = "No valid no-vig win probability, so method-split-v0 has nothing to scale."
        return empty
    prior_block, prior_key, class_thin = _prior_block(table, weight_class, fmt)
    if prior_block is None:
        empty["note"] = "No decisive wins in the mirror window."
        return empty
    prior = prior_block["p"]
    atoms = []
    thin = class_thin
    notes = []
    sides = {}
    if class_thin:
        notes.append(f"weight-class sample {prior_block['n']} is under {THIN_CLASS}")
    for side, name, p_win in (("a", name_a, p_a), ("b", name_b, p_b)):
        block, ambiguous, amb_note = _fighter_block(table, name, fmt if fmt else None)
        n = 0 if ambiguous else int(block["n"])
        counts = {} if ambiguous else block["counts"]
        side_thin = class_thin or ambiguous or n < THIN_WINS
        side_note = amb_note or (f"{n} decisive wins in this format" + (f" (under {THIN_WINS})" if n < THIN_WINS else ""))
        if class_thin:
            side_note = f"{side_note}; class n={prior_block['n']}"
        sides[side] = {"n": n, "thin": side_thin, "note": side_note}
        if side_thin:
            thin = True
            notes.append(side_note)
        dist = shrunk_distribution(counts, n, prior, cells)
        for method, rnd in cells:
            prob = p_win * dist.get((method, rnd), 0.0)
            if prob <= 0:
                continue
            atoms.append({
                "id": f"{side}:{method}:{rnd if rnd else 'dec'}",
                "side": side,
                "name": name,
                "method": method,
                "round": rnd,
                "p": prob,
            })
    return {
        "atoms": atoms,
        "timing": timing,
        "thin": thin,
        "class_n": prior_block["n"],
        "prior_key": {"weight_class": prior_key[0], "format": prior_key[1]},
        "note": " ".join(dict.fromkeys(notes)),
        "sides": sides,
        "rounds": scheduled_rounds,
        "fmt": fmt,
        "model": MODEL,
        "k": K,
    }


def _fair(p: float | None) -> tuple[str | None, float | None]:
    if p is None or p <= 0 or p >= 1:
        return None, None
    decimal = 1.0 / p
    american = to_american(decimal)
    return format_american(american), decimal


def _sum_atoms(atoms, pred) -> float:
    return sum(atom["p"] for atom in atoms if pred(atom))


def catalog(model: dict, fight_id: str, markets: dict | None, observed_at: str, market_source: str | None,
            moneylines: dict | None = None) -> list[dict]:
    """Priced legs. UFC.com prices the moneyline. GAPOdds, when present, prices method props."""
    atoms = model.get("atoms") or []
    legs = []

    def add(leg_id, label, leg_type, prob, atom_ids, timing=None, market_american=None, thin=None, thin_note=None):
        if prob is None or prob <= 0 or prob >= 1:
            return
        fair_text, fair_dec = _fair(prob)
        price_dec = to_decimal(market_american) if market_american is not None else fair_dec
        legs.append({
            "id": f"{fight_id}-{leg_id}",
            "type": leg_type,
            "label": label,
            "kind": "market" if market_american is not None and leg_type == "moneyline" else "model",
            "model_p": prob,
            "novig": prob,
            "fair_american": fair_text,
            "decimal": price_dec,
            "price_kind": "market" if market_american is not None else "fair",
            "market_american": format_american(market_american) if market_american is not None else None,
            "market_source": market_source if market_american is not None else None,
            "source": "UFC.com no-vig win probability" if leg_type == "moneyline" else (MODEL if timing is None else "ufc_timing base rate"),
            "asof": observed_at,
            "thin": bool(model.get("thin") if thin is None else thin),
            "thin_note": thin_note if thin_note is not None else (model.get("note") or ""),
            "atoms": atom_ids,
            "timing": timing,
        })

    by_side = {"a": [a for a in atoms if a["side"] == "a"], "b": [a for a in atoms if a["side"] == "b"]}
    for side, group in by_side.items():
        if not group:
            continue
        name = group[0]["name"]
        market = (markets or {}).get(norm_name(name)) or {}
        ml_price = (moneylines or {}).get(side)
        side_meta = (model.get("sides") or {}).get(side) or {}
        add(f"ml-{side}", f"{name} wins", "moneyline", _sum_atoms(atoms, lambda a: a["side"] == side),
            [a["id"] for a in group], market_american=ml_price, thin=side_meta.get("thin"), thin_note=side_meta.get("note"))
        for method, word in (("ko", "KO/TKO"), ("sub", "submission"), ("dec", "decision")):
            ids = [a["id"] for a in group if a["method"] == method]
            add(f"{method}-{side}", f"{name} by {word}", "method",
                _sum_atoms(atoms, lambda a, s=side, m=method: a["side"] == s and a["method"] == m),
                ids, market_american=market.get(method), thin=side_meta.get("thin"), thin_note=side_meta.get("note"))
        if model.get("rounds"):
            for rnd in range(1, int(model["rounds"]) + 1):
                for method, word in (("ko", "KO/TKO"), ("sub", "submission")):
                    add(f"{method}-r{rnd}-{side}", f"{name} by {word} R{rnd}", "method-round",
                        _sum_atoms(atoms, lambda a, s=side, m=method, r=rnd: a["side"] == s and a["method"] == m and a["round"] == r),
                        [a["id"] for a in group if a["method"] == method and a["round"] == rnd],
                        thin=side_meta.get("thin"), thin_note=side_meta.get("note"))
    add("distance-yes", "Goes the distance", "distance",
        _sum_atoms(atoms, lambda a: a["method"] == "dec"),
        [a["id"] for a in atoms if a["method"] == "dec"])
    add("distance-no", "Does not go the distance", "distance",
        _sum_atoms(atoms, lambda a: a["method"] in ("ko", "sub")),
        [a["id"] for a in atoms if a["method"] in ("ko", "sub")])
    if model.get("rounds"):
        for rnd in range(1, int(model["rounds"]) + 1):
            add(f"end-r{rnd}", f"Fight ends in round {rnd}", "round",
                _sum_atoms(atoms, lambda a, r=rnd: a["method"] in ("ko", "sub") and a["round"] == r),
                [a["id"] for a in atoms if a["method"] in ("ko", "sub") and a["round"] == rnd])
    for kind in TIMING_KINDS:
        block = (model.get("timing") or {}).get(kind) or {}
        rate = block.get("p")
        if rate is None or rate <= 0 or rate >= 1:
            continue
        legs.append({
            "id": f"{fight_id}-timing-{kind}",
            "type": "timing",
            "label": TIMING_LABELS[kind],
            "kind": "observed",
            "model_p": rate,
            "novig": rate,
            "fair_american": _fair(rate)[0],
            "decimal": _fair(rate)[1],
            "price_kind": "fair",
            "market_american": None,
            "market_source": None,
            "source": f"ufc_timing {block.get('scope')}",
            "asof": observed_at,
            "thin": bool(block.get("thin")),
            "thin_note": f"n={block.get('n')} ({block.get('scope')})",
            "atoms": None,
            "timing": kind,
        })
    return legs


def _timing_ok(atom: dict, kind: str) -> bool:
    finish = atom["method"] in ("ko", "sub")
    if kind == "r1_le60":
        return finish and atom["round"] == 1
    if kind in ("any_le60", "last10"):
        return finish
    return False


def joint_probability(atoms: list[dict], legs: list[dict], timing_p: dict | None = None) -> dict:
    """Probability of every selected leg in one fight.

    Method legs are unions of atoms. Timing legs use the base rate when they are
    not cut by a narrower method constraint. An unidentified intersection is not
    replaced with a product.
    """
    if not legs:
        return {"status": "empty", "p": None, "reason": "no legs"}
    allowed = None
    kinds = []
    rates = dict(timing_p or {})
    for leg in legs:
        if leg.get("timing"):
            kinds.append(leg["timing"])
            if leg.get("model_p") is not None:
                rates[leg["timing"]] = leg["model_p"]
        if leg.get("atoms") is None:
            continue
        chosen = set(leg["atoms"])
        allowed = chosen if allowed is None else allowed & chosen
        if not allowed:
            return {"status": "contradictory", "p": 0.0, "reason": "Those legs cannot happen in the same fight."}
    if "r1_le60" in kinds and "last10" in kinds:
        return {"status": "contradictory", "p": 0.0, "reason": "A finish cannot be in the first 60s and the last 10s."}
    if "any_le60" in kinds and "last10" in kinds:
        return {"status": "contradictory", "p": 0.0, "reason": "A first-60s finish is not a last-10s finish."}
    tight = "r1_le60" if "r1_le60" in kinds else ("last10" if "last10" in kinds else ("any_le60" if "any_le60" in kinds else None))
    if tight:
        compatible = {atom["id"] for atom in atoms if _timing_ok(atom, tight)}
        if allowed is not None and not (allowed & compatible):
            return {"status": "contradictory", "p": 0.0, "reason": "That method result cannot land in this timing window."}
        if allowed is not None and not compatible <= allowed:
            return {
                "status": "unidentified",
                "p": None,
                "reason": "method-split-v0 does not say how the clock-time rate splits inside a method or a fighter. The joint is not the product.",
            }
        rate = rates.get(tight)
        if rate is None:
            return {"status": "unidentified", "p": None, "reason": "Timing base rate unavailable."}
        return {"status": "ok", "p": float(rate), "reason": "Timing base rate. It already implies the broader finish event selected with it."}
    if allowed is None:
        return {"status": "ok", "p": 1.0, "reason": "no constraint"}
    prob = sum(atom["p"] for atom in atoms if atom["id"] in allowed)
    return {"status": "ok", "p": prob, "reason": "Intersection of method-split-v0 atoms."}


def slate_probability(groups: list[dict]) -> dict:
    """Product of per-fight joints. Fights are treated as independent of each other."""
    if not groups:
        return {"status": "empty", "p": None, "reason": "no legs"}
    prob = 1.0
    correlated = False
    for group in groups:
        legs = group.get("selected") or []
        if not legs:
            continue
        if group.get("atoms"):
            result = joint_probability(group["atoms"], legs, group.get("timing_p"))
            if result["status"] != "ok":
                return result
            if len(legs) > 1:
                correlated = True
            prob *= result["p"]
        else:
            correlated = correlated or len(legs) > 1
            for leg in legs:
                if leg.get("model_p") is None:
                    return {"status": "unidentified", "p": None, "reason": "A selected leg has no probability."}
                prob *= float(leg["model_p"])
    return {
        "status": "ok",
        "p": prob,
        "reason": "Same-fight legs use the joint. Separate fights, and NFL props, are multiplied. Same-game NFL props are correlated, so that product is not a joint model.",
        "same_event_joint": correlated,
    }
