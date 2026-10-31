"""trail-quantile-v0: empirical distribution of recent nflverse stat lines.

Lines are not taken from a sportsbook. The default line is the trailing mean,
rounded down to the next half-point, so the user can move it. Passing touchdowns
are not counted as anytime-TD scores.
"""
from __future__ import annotations

import math

import pandas as pd

from dfs_intel.odds_math import format_american, to_american
from dfs_intel.ufc_pipeline import norm_name

MODEL = "trail-quantile-v0"
TRAIL_N = 8
THIN_GAMES = 4

MARKETS = (
    ("passing", "pass_yds", "Passing yards", "passing_yards", "attempts"),
    ("rushing", "rush_yds", "Rushing yards", "rushing_yards", "carries"),
    ("receiving", "rec_yds", "Receiving yards", "receiving_yards", "targets"),
    ("receptions", "rec", "Receptions", "receptions", "targets"),
    ("anytime-td", "td", "Anytime TD", None, None),
)


def default_line(samples: list[float], market: str) -> float:
    if market == "anytime-td":
        return 0.5
    if not samples:
        return 0.5
    return math.floor(sum(samples) / len(samples)) + 0.5


def side_probs(samples: list[float], line: float) -> dict:
    n = len(samples)
    if n == 0:
        return {"n": 0, "over": None, "under": None, "push": None}
    over = sum(value > line for value in samples) / n
    under = sum(value < line for value in samples) / n
    push = sum(value == line for value in samples) / n
    return {"n": n, "over": over, "under": under, "push": push}


def fair_price(prob: float | None) -> tuple[str | None, float | None]:
    if prob is None or prob <= 0 or prob >= 1:
        return None, None
    decimal = 1.0 / prob
    return format_american(to_american(decimal)), decimal


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _td_flag(frame: pd.DataFrame) -> pd.Series:
    score = _num(frame, "rushing_tds") + _num(frame, "receiving_tds") + _num(frame, "special_teams_tds")
    if "pt_return_tds" in frame:
        score = score + _num(frame, "pt_return_tds")
    return (score > 0).astype(float)


def player_samples(history: pd.DataFrame, player_id: str, column: str | None, n: int = TRAIL_N) -> list[float]:
    rows = history[history["player_id"].astype(str) == str(player_id)].sort_values(["season", "week"]).tail(n)
    if rows.empty:
        return []
    if column is None:
        return [float(value) for value in _td_flag(rows).tolist()]
    return [float(value) for value in _num(rows, column).tolist()]


def _tail(history: pd.DataFrame) -> pd.DataFrame:
    ordered = history.sort_values(["player_id", "season", "week"])
    return ordered.groupby("player_id", sort=False).tail(TRAIL_N)


def select_players(history: pd.DataFrame, team: str, qb_name: str | None) -> list[dict]:
    """Starters by opportunity: listed or most-used QB, top rushers, top targets."""
    if history.empty:
        return []
    tail = _tail(history)
    last = tail.sort_values(["season", "week"]).groupby("player_id", sort=False).tail(1)
    pool = tail[tail["player_id"].isin(last.loc[last["team"] == team, "player_id"])]
    if pool.empty:
        return []
    picked = []
    seen = set()

    def add(player_id, role):
        if player_id in seen:
            return
        row = last[last["player_id"] == player_id]
        if row.empty:
            return
        seen.add(player_id)
        rec = row.iloc[-1]
        picked.append({
            "player_id": str(player_id),
            "player": rec.get("player_display_name") or "",
            "position": rec.get("position") or "",
            "team": team,
            "role": role,
        })

    qbs = pool[pool["position"] == "QB"]
    chosen_qb = None
    if qb_name:
        wanted = norm_name(qb_name)
        for pid, name in qbs.groupby("player_id")["player_display_name"].last().items():
            if norm_name(name) == wanted:
                chosen_qb = pid
                break
    if chosen_qb is None and not qbs.empty:
        attempts = qbs.groupby("player_id")["attempts"].sum() if "attempts" in qbs else pd.Series(dtype=float)
        if len(attempts):
            chosen_qb = attempts.idxmax()
    if chosen_qb is not None:
        add(chosen_qb, "QB")
    rush = pool[pool["position"].isin(["RB", "FB"])]
    if not rush.empty and "carries" in rush:
        order = rush.groupby("player_id")["carries"].sum().sort_values(ascending=False)
        for pid in list(order.index)[:2]:
            add(pid, "RB")
    catch = pool[pool["position"].isin(["WR", "TE", "RB", "FB"])]
    if not catch.empty and "targets" in catch:
        order = catch.groupby("player_id")["targets"].sum().sort_values(ascending=False)
        for pid in list(order.index)[:3]:
            add(pid, "REC")
    return picked


def markets_for(role: str, position: str) -> list[str]:
    if role == "QB" or position == "QB":
        return ["passing", "rushing", "anytime-td"]
    if role == "RB":
        return ["rushing", "receiving", "receptions", "anytime-td"]
    return ["receiving", "receptions", "anytime-td"]


def build_game_props(history: pd.DataFrame, game: dict, observed_at: str) -> list[dict]:
    """One group of prop legs for a game. Samples travel with the leg so the line can move."""
    players = []
    for team, qb in ((game["away"], game.get("away_qb")), (game["home"], game.get("home_qb"))):
        players.extend(select_players(history, team, qb))
    legs = []
    by_type = {item[0]: item for item in MARKETS}
    for player in players:
        samples_cache = {}
        for market in markets_for(player["role"], player["position"]):
            kind, stat, label, column, opp_col = by_type[market]
            samples = player_samples(history, player["player_id"], None if market == "anytime-td" else column)
            if not samples:
                continue
            line = default_line(samples, market)
            probs = side_probs(samples, line)
            opp_mean = None
            if opp_col:
                opp_samples = player_samples(history, player["player_id"], opp_col)
                if opp_samples:
                    opp_mean = sum(opp_samples) / len(opp_samples)
            base = f"{game['game_id']}-{player['player_id']}-{stat}"
            thin = len(samples) < THIN_GAMES
            window = f"last {len(samples)} regular-season games before this week"
            for side in ("over", "under"):
                prob = probs[side]
                fair, decimal = fair_price(prob)
                if decimal is None:
                    continue
                legs.append({
                    "id": f"{base}-{side}",
                    "type": kind,
                    "label": f"{player['player']} {side} {line:g} {label}",
                    "kind": "model",
                    "model_p": prob,
                    "novig": prob,
                    "fair_american": fair,
                    "decimal": decimal,
                    "price_kind": "fair",
                    "market_american": None,
                    "source": MODEL,
                    "asof": observed_at,
                    "thin": thin,
                    "thin_note": f"{len(samples)} games" + (f", {opp_mean:.1f} {opp_col}/game" if opp_mean is not None else ""),
                    "atoms": None,
                    "timing": None,
                    "samples": samples,
                    "line": line,
                    "side": side,
                    "stat": stat,
                    "stat_label": label,
                    "player": player["player"],
                    "player_id": player["player_id"],
                    "pair": base,
                    "push": probs["push"],
                    "window": window,
                    "opportunity": opp_mean,
                    "opportunity_stat": opp_col,
                })
    return legs
