"""Observed (historical) UFC fight-end timing frequencies. Descriptive only - NOT predictions."""
from __future__ import annotations
import re
import pandas as pd
from .storage import facts_as_of

FINISH_METHODS = {"KO/TKO", "Submission", "TKO - Doctor's Stoppage"}  # excludes DQ, Overturned, Could Not Continue


def parse_clock(t) -> int | None:
    m = re.match(r"\s*(\d+):(\d{2})", str(t))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def round_lengths(time_format) -> list[int]:
    m = re.search(r"\(([\d\-]+)\)", str(time_format))
    return [int(x) * 60 for x in m.group(1).split("-")] if m else []


def american_odds(p: float) -> str:
    if p <= 0 or p >= 1: return "n/a"
    return f"+{round(100 * (1 - p) / p)}" if p <= 0.5 else f"-{round(100 * p / (1 - p))}"


def add_flags(f: pd.DataFrame) -> pd.DataFrame:
    f = f.copy()
    f["finish"] = f["method"].isin(FINISH_METHODS)
    f["end_sec"] = f["time"].map(parse_clock)
    f["rnd"] = pd.to_numeric(f["round"], errors="coerce")
    rl = f["time_format"].map(round_lengths)
    f["round_len"] = [l[int(r) - 1] if l and 0 < r <= len(l) else None for l, r in zip(rl, f["rnd"])]
    f["finish_r1_le60"] = f.finish & (f.rnd == 1) & (f.end_sec <= 60)
    f["finish_any_rnd_le60"] = f.finish & (f.end_sec <= 60)
    f["finish_last10"] = f.finish & (f.round_len == 300) & (f.end_sec >= 290)
    f["format"] = f["time_format"].str.extract(r"^(\d) Rnd")[0].map({"3": "3-round", "5": "5-round"})
    wc = f["weightclass"].str.replace(r"\b(UFC|Title|Bout|Interim|Tournament)\b", "", regex=True)
    f["weight_class"] = wc.str.replace(r"\s+", " ", regex=True).str.strip()
    return f


FLAGS = ["finish_r1_le60", "finish_any_rnd_le60", "finish_last10"]


def rates(f: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    g = f.groupby(by) if by else f.assign(_all="all").groupby("_all")
    out = g[FLAGS].agg(["sum", "mean"]); out.columns = [f"{a}_{b}" for a, b in out.columns]
    out.insert(0, "n_fights", g.size())
    return out


def fighter_counts(f: pd.DataFrame, name: str) -> dict:
    m = f[(f.fighter_a == name) | (f.fighter_b == name)]
    won = m.winner == name
    d = {"fighter": name, "n_fights": len(m)}
    for fl in FLAGS:
        d[fl] = int(m[fl].sum()); d[fl + "_won"] = int((m[fl] & won).sum())
    return d


def load(as_of="2026-10-31"):
    return add_flags(facts_as_of("ufc_fights", as_of))
