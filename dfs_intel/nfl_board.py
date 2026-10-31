"""NFL weeks for the site: nflverse schedule, moneylines, trailing DK averages.

Does not contact NFL.com, Pro-Football-Reference, or DraftKings.
Play-by-play is not downloaded, so DST and kicker projections are left unavailable.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from dfs_intel.nfl_dk import dk_offense
from dfs_intel.nfl_pipeline import fetch, kickoff_utc
from dfs_intel.odds_math import format_american, no_vig, to_decimal

PT = ZoneInfo("America/Los_Angeles")
SKILL = ("QB", "RB", "WR", "TE")
TRAIL_N = 8
MODEL = "trailing-average-v0"


def season_years(today: datetime | None = None) -> tuple[list[int], list[int]]:
    """(schedule years, stat years). January and February still belong to the prior season."""
    today = today or datetime.now(PT)
    primary = today.year if today.month >= 3 else today.year - 1
    schedule = [primary]
    stats = [primary - 1, primary]
    return schedule, stats


def _load_frames(years: list[int], kind: str, refresh: bool) -> tuple[pd.DataFrame | None, str | None, str | None]:
    frames = []
    errors = []
    observed = None
    for year in years:
        try:
            df, obs = fetch(kind, year, refresh=refresh)
        except Exception as exc:
            errors.append(f"{year}: {exc}")
            continue
        frames.append(df)
        observed = obs.isoformat() if hasattr(obs, "isoformat") else str(obs)
    if not frames:
        return None, None, "; ".join(errors) or "no seasons returned"
    return pd.concat(frames, ignore_index=True), observed, ("; ".join(errors) or None)


def load_nfl(refresh: bool = True, today: datetime | None = None) -> dict:
    schedule_years, stat_years = season_years(today)
    sched, sched_obs, sched_err = _load_frames(schedule_years, "schedules", refresh)
    if sched is None:
        return {"status": "unavailable", "error": sched_err or "schedule unavailable", "source": "nflverse:schedules"}
    stats, stats_obs, stats_err = _load_frames(stat_years, "player_stats", refresh)
    rosters, rost_obs, rost_err = _load_frames(schedule_years, "rosters_weekly", refresh)
    points = _with_dk(stats) if stats is not None else None
    season = int(max(schedule_years))
    reg = sched[(sched["season"] == season) & (sched["game_type"] == "REG")].copy()
    if reg.empty:
        return {
            "status": "unavailable",
            "error": f"no regular-season games in nflverse schedules for {season}",
            "source": "nflverse:schedules",
            "observed_at": sched_obs,
        }
    weeks = []
    for week in sorted(int(w) for w in reg["week"].dropna().unique()):
        weeks.append(build_week(
            reg, points, rosters, season, week,
            schedule_observed=sched_obs, stats_observed=stats_obs, roster_observed=rost_obs,
        ))
    return {
        "status": "ok",
        "season": season,
        "source_schedule": "nflverse:schedules",
        "source_stats": "nflverse:player_stats",
        "source_rosters": "nflverse:rosters_weekly",
        "schedule_observed_at": sched_obs,
        "stats_observed_at": stats_obs,
        "roster_observed_at": rost_obs,
        "schedule_error": sched_err,
        "stats_error": stats_err,
        "roster_error": rost_err,
        "stats_status": "ok" if points is not None else "unavailable",
        "roster_status": "ok" if rosters is not None else "unavailable",
        "model": MODEL,
        "trail_games": TRAIL_N,
        "weeks": weeks,
        "stats_frame": points,
    }


def _with_dk(stats: pd.DataFrame) -> pd.DataFrame:
    use = stats[stats["position"].isin([*SKILL, "FB"])].copy()
    use["dk_points"] = dk_offense(use)
    return use


def trailing_averages(stats: pd.DataFrame, season: int, week: int, n: int = TRAIL_N) -> pd.DataFrame:
    """Mean DK points over up to `n` prior regular-season games. Excludes the target week."""
    if stats is None or stats.empty:
        return pd.DataFrame()
    hist = stats[(stats["season_type"] == "REG") & (
        (stats["season"] < season) | ((stats["season"] == season) & (stats["week"] < week))
    )].copy()
    if hist.empty:
        return pd.DataFrame()
    hist = hist.sort_values(["player_id", "season", "week"])
    rows = []
    for pid, group in hist.groupby("player_id", sort=False):
        tail = group.tail(n)
        last = tail.iloc[-1]
        first = tail.iloc[0]
        pos = last["position"]
        rows.append({
            "player_id": str(pid),
            "player": last.get("player_display_name") or "",
            "position": "RB" if pos == "FB" else pos,
            "games": int(len(tail)),
            "dk_avg": round(float(tail["dk_points"].mean()), 2),
            "from_season": int(first["season"]),
            "from_week": int(first["week"]),
            "through_season": int(last["season"]),
            "through_week": int(last["week"]),
        })
    return pd.DataFrame(rows)


def _money(value) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _games(reg: pd.DataFrame, season: int, week: int) -> list[dict]:
    slate = reg[(reg["season"] == season) & (reg["week"] == week)].copy()
    slate["kickoff_utc"] = kickoff_utc(slate)
    games = []
    for row in slate.sort_values("kickoff_utc").itertuples(index=False):
        ko = row.kickoff_utc
        ko_pt = None if pd.isna(ko) else ko.tz_convert(PT).isoformat()
        away_ml, home_ml = _money(row.away_moneyline), _money(row.home_moneyline)
        priced = None
        if away_ml is not None and home_ml is not None:
            pa, ph, over = no_vig(away_ml, home_ml)
            priced = {
                "novig_away": pa,
                "novig_home": ph,
                "overround": over,
                "decimal_away": to_decimal(away_ml),
                "decimal_home": to_decimal(home_ml),
                "valid": over < 0.15,
            }
        home_score = None if pd.isna(row.home_score) else int(row.home_score)
        away_score = None if pd.isna(row.away_score) else int(row.away_score)
        if home_score is None and away_score is None:
            score_status = "not_played"
        elif home_score is None or away_score is None:
            score_status = "unavailable"
        else:
            score_status = "final"
        games.append({
            "game_id": row.game_id,
            "away": row.away_team,
            "home": row.home_team,
            "kickoff_pt": ko_pt,
            "gameday": str(row.gameday),
            "gametime_et": None if pd.isna(row.gametime) else str(row.gametime),
            "away_score": away_score,
            "home_score": home_score,
            "score_status": score_status,
            "away_moneyline": away_ml,
            "home_moneyline": home_ml,
            "away_moneyline_american": format_american(away_ml) if away_ml is not None else None,
            "home_moneyline_american": format_american(home_ml) if home_ml is not None else None,
            "priced": priced,
            "spread_line": None if pd.isna(row.spread_line) else float(row.spread_line),
            "total_line": None if pd.isna(row.total_line) else float(row.total_line),
            "away_qb": None if pd.isna(getattr(row, "away_qb_name", None)) else str(row.away_qb_name),
            "home_qb": None if pd.isna(getattr(row, "home_qb_name", None)) else str(row.home_qb_name),
        })
    return games


def _roster_slice(rosters: pd.DataFrame | None, season: int, week: int, teams: set[str]) -> tuple[pd.DataFrame | None, str]:
    if rosters is None or rosters.empty:
        return None, "unavailable"
    have = rosters[rosters["season"] == season]
    weeks = sorted(int(w) for w in have["week"].dropna().unique())
    if not weeks:
        return None, "unavailable"
    if week in weeks:
        use = week
        note = f"nflverse weekly roster for {season} week {week}, status ACT"
    else:
        prior = [w for w in weeks if w <= week]
        use = prior[-1] if prior else weeks[-1]
        note = (
            f"nflverse has no {season} week {week} roster. Using week {use}, status ACT. "
            "This is not a confirmed inactive list for the target week."
        )
    sl = have[(have["week"] == use) & (have["status"] == "ACT") & (have["team"].isin(teams))].copy()
    sl = sl[sl["position"].isin(SKILL)]
    return sl, note


def build_week(reg, stats, rosters, season: int, week: int, schedule_observed, stats_observed, roster_observed) -> dict:
    games = _games(reg, season, week)
    teams = {g["away"] for g in games} | {g["home"] for g in games}
    opp = {}
    for g in games:
        opp[g["away"]] = g["home"]
        opp[g["home"]] = g["away"]
    projections = []
    missing_history = 0
    roster_note = "unavailable"
    if stats is None:
        proj_status = "unavailable"
    else:
        proj_status = "ok"
        trail = trailing_averages(stats, season, week)
        by_id = trail.set_index("player_id") if not trail.empty else None
        roster, roster_note = _roster_slice(rosters, season, week, teams)
        if roster is None:
            proj_status = "unavailable"
            roster_note = "roster unavailable; projections not assigned to a slate"
        else:
            for row in roster.itertuples(index=False):
                pid = str(row.gsis_id) if not pd.isna(row.gsis_id) else ""
                hit = None if by_id is None or not pid or pid not in by_id.index else by_id.loc[pid]
                if hit is None:
                    missing_history += 1
                    continue
                if isinstance(hit, pd.DataFrame):
                    hit = hit.iloc[-1]
                projections.append({
                    "player_id": pid,
                    "player": row.full_name or hit["player"],
                    "position": row.position if row.position in SKILL else hit["position"],
                    "team": row.team,
                    "opponent": opp.get(row.team),
                    "games": int(hit["games"]),
                    "dk_avg": float(hit["dk_avg"]),
                    "from_season": int(hit["from_season"]),
                    "from_week": int(hit["from_week"]),
                    "through_season": int(hit["through_season"]),
                    "through_week": int(hit["through_week"]),
                })
    by_pos = {pos: [] for pos in SKILL}
    for row in sorted(projections, key=lambda r: (-r["dk_avg"], r["player"])):
        by_pos.setdefault(row["position"], []).append(row)
    top = {pos: rows[:12] for pos, rows in by_pos.items()}
    finals = sum(1 for g in games if g["score_status"] == "final")
    if games and finals == len(games):
        state = "final"
    elif finals:
        state = "in_progress"
    else:
        state = "upcoming"
    kickoffs = [g["kickoff_pt"] for g in games if g["kickoff_pt"]]
    return {
        "season": season,
        "week": week,
        "slug": f"{season}-week-{week:02d}",
        "state": state,
        "games": games,
        "first_kickoff_pt": min(kickoffs) if kickoffs else None,
        "last_kickoff_pt": max(kickoffs) if kickoffs else None,
        "projections_status": proj_status,
        "roster_note": roster_note,
        "missing_history": missing_history,
        "top": top,
        "schedule_observed_at": schedule_observed,
        "stats_observed_at": stats_observed,
        "roster_observed_at": roster_observed,
        "model": MODEL,
        "trail_games": TRAIL_N,
        "dst_note": "DST and kicker DK projections are unavailable. This refresh does not download play-by-play, and kicker scoring is not in the offense table.",
    }
