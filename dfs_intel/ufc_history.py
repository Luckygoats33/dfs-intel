"""UFC history for the site, from the GitHub mirror the pipeline already uses.

Source: github.com/Greco1899/scrape_ufc_stats (a community scrape of UFCStats).
This module does not contact ufcstats.com.
"""
from __future__ import annotations

from dfs_intel.evaluate import brier, log_loss
from dfs_intel.ufc_pipeline import MIRROR_SRC, _mirror_csv, id_from_url, norm_name
from dfs_intel.ufc_timing import FLAGS, add_flags, american_odds, fighter_counts, rates

LABELS = {
    "finish_r1_le60": "Finish within first 60s of round 1",
    "finish_any_rnd_le60": "Finish within first 60s of any round",
    "finish_last10": "Finish in last 10s of any round",
}


def load_mirror(since: str = "2022-01-01", refresh: bool = False) -> dict:
    import pandas as pd
    from datetime import datetime, timezone

    observed = datetime.now(timezone.utc)
    ev = _mirror_csv("ufc_event_details", refresh=refresh)
    ev = ev.rename(columns={"EVENT": "name", "URL": "url", "DATE": "date", "LOCATION": "location"})
    ev["event_id"] = ev["url"].map(id_from_url)
    ev["event_date"] = pd.to_datetime(ev["date"], errors="coerce")
    ev = ev[ev.event_date >= pd.Timestamp(since)].copy()
    res = _mirror_csv("ufc_fight_results", refresh=refresh)
    res = res.rename(columns=str.lower).rename(columns={"time format": "time_format", "url": "fight_url", "event": "event_name"})
    res["fight_id"] = res["fight_url"].map(id_from_url)
    res = res.merge(ev[["name", "event_id", "event_date"]], left_on="event_name", right_on="name", how="inner").drop(columns="name")
    ab = res["bout"].str.split(r"\s+vs\.\s+", n=1, expand=True)
    res["fighter_a"] = ab[0]
    res["fighter_b"] = ab[1]
    parts = res["outcome"].str.split("/", expand=True)
    res["winner"] = None
    if parts.shape[1] >= 2:
        res.loc[parts[0] == "W", "winner"] = res.loc[parts[0] == "W", "fighter_a"]
        res.loc[parts[1] == "W", "winner"] = res.loc[parts[1] == "W", "fighter_b"]
    flagged = add_flags(res)
    bios = _bios(refresh)
    elo, metrics = walkforward_elo(flagged)
    return {
        "status": "ok",
        "source": MIRROR_SRC,
        "observed_at": observed.isoformat(),
        "since": since,
        "n_fights": int(len(flagged)),
        "date_min": flagged.event_date.min().strftime("%Y-%m-%d") if len(flagged) else None,
        "date_max": flagged.event_date.max().strftime("%Y-%m-%d") if len(flagged) else None,
        "fights": flagged,
        "timing": timing_tables(flagged),
        "elo": elo,
        "elo_metrics": metrics,
        "bios": bios,
        "by_norm": _name_index(flagged),
    }


def _bios(refresh: bool) -> dict:
    """norm_name -> list of bio dicts (duplicates kept, not collapsed)."""
    details = _mirror_csv("ufc_fighter_details", refresh=refresh)
    tott = _mirror_csv("ufc_fighter_tott", refresh=refresh)
    details["fighter_id"] = details["URL"].map(id_from_url)
    tott["fighter_id"] = tott["URL"].map(id_from_url)
    merged = details.merge(tott.drop(columns=["URL"]), on="fighter_id", how="left")
    out: dict[str, list] = {}
    for row in merged.itertuples(index=False):
        first = getattr(row, "FIRST", "") or ""
        last = getattr(row, "LAST", "") or ""
        name = f"{first} {last}".strip()
        key = norm_name(name)
        if not key:
            continue
        out.setdefault(key, []).append({
            "name": name,
            "nickname": getattr(row, "NICKNAME", "") or "",
            "height": getattr(row, "HEIGHT", "") or "",
            "reach": getattr(row, "REACH", "") or "",
            "stance": getattr(row, "STANCE", "") or "",
            "dob": getattr(row, "DOB", "") or "",
            "url": getattr(row, "URL", "") or "",
        })
    return out


def _name_index(fights) -> dict[str, list[str]]:
    names = set(fights["fighter_a"].dropna()) | set(fights["fighter_b"].dropna())
    out: dict[str, list[str]] = {}
    for name in names:
        out.setdefault(norm_name(name), []).append(str(name))
    return out


def elo_label(metrics: dict | None) -> str:
    """Name the baseline the way the walk-forward result supports."""
    if not metrics or not metrics.get("n_fights"):
        return "elo-baseline-v0"
    gap = metrics["coin_log_loss"] - metrics["elo_log_loss"]
    if metrics.get("beats_coin") and gap < 0.02:
        return "elo-baseline-v0, barely beats 50/50"
    return "elo-baseline-v0"


def walkforward_elo(fights, k: float = 32.0) -> tuple[dict, dict]:
    """Cold-start Elo. Quality is scored after a 10-event warm-up, sides flipped
    by fight_id so UFCStats' winner-first listing is not the metric."""
    import numpy as np

    ordered = fights.sort_values(["event_date", "fight_id"])
    events = list(dict.fromkeys(ordered["event_id"].tolist()))
    warmup = set(events[:10])
    elo: dict[str, float] = {}
    recs = []
    for row in ordered.itertuples(index=False):
        a, b = row.fighter_a, row.fighter_b
        if not isinstance(a, str) or not isinstance(b, str):
            continue
        ra, rb = elo.get(a, 1500.0), elo.get(b, 1500.0)
        pa = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        winner = row.winner if isinstance(row.winner, str) else None
        if winner not in (a, b):
            continue
        y = 1.0 if winner == a else 0.0
        if row.event_id not in warmup:
            fid = str(row.fight_id)
            flip = fid[-1] in "13579bdfBDF" if fid else False
            recs.append((1.0 - y, 1.0 - pa) if flip else (y, pa))
        elo[a] = ra + k * (y - pa)
        elo[b] = rb - k * (y - pa)
    if not recs:
        metrics = {"n_fights": 0, "note": "no scored fights"}
    else:
        y = np.array([a for a, _ in recs])
        p = np.array([b for _, b in recs])
        elo_ll, coin_ll = log_loss(y, p), log_loss(y, np.full_like(p, 0.5))
        metrics = {
            "model": "elo-baseline-v0",
            "k": k,
            "start_rating": 1500,
            "warmup_events_excluded": 10,
            "n_fights": int(len(y)),
            "elo_log_loss": elo_ll,
            "coin_log_loss": coin_ll,
            "elo_brier": brier(y, p),
            "coin_brier": brier(y, np.full_like(p, 0.5)),
            "beats_coin": bool(elo_ll < coin_ll),
            "note": (
                "Sides are randomly oriented by the last fight_id character because the "
                "mirror lists winners first. Ratings start at 1500 with no pre-window history. "
                "The first 10 events are warm-up and are not scored."
            ),
        }
    return elo, metrics


def timing_tables(fights) -> dict:
    def pack(frame, by=None):
        table = rates(frame, by).reset_index()
        rows = []
        for rec in table.to_dict("records"):
            row = {"n_fights": int(rec["n_fights"])}
            if by:
                key = rec.get(by)
                row[by] = None if key is None or (isinstance(key, float) and key != key) else str(key)
            for fl in FLAGS:
                count = int(rec[f"{fl}_sum"])
                n = int(rec["n_fights"])
                rate = float(rec[f"{fl}_mean"]) if n else None
                row[fl] = {
                    "count": count,
                    "n": n,
                    "rate": rate,
                    "fair_american": american_odds(rate) if rate not in (None, 0) else "n/a",
                }
            rows.append(row)
        return rows

    overall = pack(fights)
    return {
        "labels": LABELS,
        "definition": (
            "Finish = KO/TKO, Submission, or TKO - Doctor's Stoppage. "
            "DQ, Overturned, and Could Not Continue stay in the denominator and out of the numerator. "
            "Last 10s = a finish at 4:50 or later in a 5:00 round. "
            "Fair American odds are the no-vig price of the historical rate, not a market quote."
        ),
        "overall": overall[0] if overall else None,
        "by_format": pack(fights.dropna(subset=["format"]), "format"),
        "by_weight_class": sorted(pack(fights, "weight_class"), key=lambda r: -r["n_fights"]),
    }


def lookup_fighter(history: dict, name: str) -> dict:
    """Match a UFC.com name to mirror fight-end counts. Ambiguous names stay ambiguous."""
    if history.get("status") != "ok" or not name:
        return {"status": "unavailable", "query": name}
    key = norm_name(name)
    cands = history["by_norm"].get(key) or []
    # Prefer an exact display-name hit when normalization collides.
    exact = [c for c in cands if c == name]
    use = exact or cands
    if not use:
        return {"status": "none", "query": name, "n_fights": 0}
    fights = history["fights"]
    rows = []
    for cand in sorted(set(use)):
        rows.append(fighter_counts(fights, cand))
    rating = None
    if len(use) == 1:
        rating = history["elo"].get(use[0])
    return {
        "status": "ambiguous" if len(set(use)) > 1 else "matched",
        "query": name,
        "matches": rows,
        "elo": rating,
        "elo_is_prior": rating is None and len(set(use)) == 1,
    }


def lookup_bio(history: dict, name: str) -> dict:
    if history.get("status") != "ok" or not name:
        return {"status": "unavailable", "query": name}
    hits = history["bios"].get(norm_name(name)) or []
    if not hits:
        return {"status": "none", "query": name}
    if len(hits) > 1:
        return {"status": "ambiguous", "query": name, "candidates": hits}
    return {"status": "matched", "query": name, "bio": hits[0]}
