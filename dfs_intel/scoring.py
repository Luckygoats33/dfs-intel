"""Pure DK scoring functions. All rule values come from dk_scoring_config."""
from __future__ import annotations
from dataclasses import dataclass
from .dk_scoring_config import NFL_CLASSIC as N, UFC_CLASSIC as U


def nfl_offense_points(pass_yds=0, pass_td=0, pass_int=0, rush_yds=0, rush_td=0, rec=0, rec_yds=0,
                       rec_td=0, return_td=0, fumbles_lost=0, two_pt=0, off_fumble_rec_td=0) -> float:
    p = (pass_yds * N["pass_yd"] + pass_td * N["pass_td"] + pass_int * N["pass_int"]
         + rush_yds * N["rush_yd"] + rush_td * N["rush_td"]
         + rec * N["reception"] + rec_yds * N["rec_yd"] + rec_td * N["rec_td"]
         + return_td * N["return_td"] + fumbles_lost * N["fumble_lost"] + two_pt * N["two_pt"]
         + off_fumble_rec_td * N["off_fumble_recovery_td"])
    if pass_yds >= 300: p += N["pass_300_bonus"]
    if rush_yds >= 100: p += N["rush_100_bonus"]
    if rec_yds >= 100: p += N["rec_100_bonus"]
    return round(p, 2)


def dst_points_allowed_score(points_allowed: int) -> float:
    for cap, pts in N["dst_pa_tiers"]:
        if points_allowed <= cap:
            return pts
    raise ValueError(points_allowed)


def nfl_dst_points(sacks=0, ints=0, fumble_recoveries=0, return_tds=0, int_return_tds=0, fumble_return_tds=0,
                   blocked_kick_return_tds=0, safeties=0, blocked_kicks=0, two_pt_returns=0, points_allowed=0) -> float:
    p = (sacks * N["dst_sack"] + ints * N["dst_int"] + fumble_recoveries * N["dst_fumble_recovery"]
         + return_tds * N["dst_return_td"] + int_return_tds * N["dst_int_return_td"]
         + fumble_return_tds * N["dst_fumble_return_td"] + blocked_kick_return_tds * N["dst_blocked_kick_return_td"]
         + safeties * N["dst_safety"] + blocked_kicks * N["dst_blocked_kick"] + two_pt_returns * N["dst_2pt_or_xp_return"])
    return round(p + dst_points_allowed_score(points_allowed), 2)


@dataclass
class UFCResult:
    won: bool = False
    method: str = ""        # e.g. 'KO/TKO', 'Submission', 'Decision - Unanimous', 'DQ', 'Overturned'
    end_round: int = 0
    end_time_sec: int = 0   # elapsed seconds in the final round


def is_decision(method: str) -> bool:
    return "decision" in (method or "").lower()


def ufc_points(strikes=0, sig_strikes=0, control_sec=0, takedowns=0, reversals=0, knockdowns=0,
               result: UFCResult | None = None) -> float:
    """strikes = total landed strikes (incl. significant); sig_strikes = significant landed."""
    p = (strikes * U["strike"] + sig_strikes * U["sig_strike"] + control_sec * U["control_per_sec"]
         + takedowns * U["takedown"] + reversals * U["reversal"] + knockdowns * U["knockdown"])
    r = result or UFCResult()
    m = (r.method or "").lower()
    if r.won and "overturned" not in m and "no contest" not in m:
        if is_decision(m):
            p += U["win_decision"]
        else:
            p += U["win_round"].get(r.end_round, 0.0)
            if r.end_round == 1 and r.end_time_sec <= U["quick_win_seconds"]:
                p += U["quick_win_bonus"]
    return round(p, 2)
