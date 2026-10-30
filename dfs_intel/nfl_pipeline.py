"""NFL historical pipeline from nflverse (GitHub release files via nflreadpy).
Raw downloads cached in data/raw_cache/nflverse/ so nothing is fetched twice (use --refresh to re-pull,
which will produce revision>1 rows only where nflverse corrected values)."""
from __future__ import annotations
import argparse, datetime as dt
import pandas as pd, nflreadpy as nfl
from .storage import RAW, append_facts, utcnow

CACHE = RAW / "nflverse"
LOADERS = {
    "schedules": lambda s: nfl.load_schedules(s),
    "player_stats": lambda s: nfl.load_player_stats(s, summary_level="week"),
    "rosters_weekly": lambda s: nfl.load_rosters_weekly(s),
    "snap_counts": lambda s: nfl.load_snap_counts(s),
    "pbp": lambda s: nfl.load_pbp(s),
}


def fetch(name, season, refresh=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{name}_{season}.parquet"
    if f.exists() and not refresh:
        return pd.read_parquet(f), pd.Timestamp(dt.datetime.fromtimestamp(f.stat().st_mtime, dt.timezone.utc))
    df = LOADERS[name]([season]).to_pandas()
    df.to_parquet(f, index=False)
    return df, utcnow()


def kickoff_utc(sched: pd.DataFrame) -> pd.Series:
    t = sched["gametime"].fillna("13:00")
    local = pd.to_datetime(sched["gameday"] + " " + t)
    return local.dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")


def run(seasons, refresh=False, skip_pbp=False):
    out = {}
    for s in seasons:
        sched, obs = fetch("schedules", s, refresh)
        sched = sched.copy(); sched["kickoff_utc"] = kickoff_utc(sched)
        ko = sched.set_index("game_id")["kickoff_utc"]
        wk_start = sched[sched.game_type == "REG"].groupby("week")["kickoff_utc"].min()
        out[("nfl_schedules", s)] = append_facts("nfl_schedules", sched, ["game_id"], "nflverse:schedules", "game_id", sched["kickoff_utc"], obs)

        ps, obs = fetch("player_stats", s, refresh)
        out[("nfl_player_week", s)] = append_facts("nfl_player_week", ps, ["player_id", "season", "week", "season_type"],
                                                   "nflverse:player_stats", "game_id", ps["game_id"].map(ko), obs)
        try:
            ro, obs = fetch("rosters_weekly", s, refresh)
            ro = ro.copy(); ro["roster_key"] = ro["gsis_id"].fillna(ro.get("espn_id")).fillna(ro["full_name"]).astype(str)
            eff = ro["week"].map(wk_start).fillna(wk_start.min() if len(wk_start) else pd.NaT)
            out[("nfl_rosters_weekly", s)] = append_facts("nfl_rosters_weekly", ro, ["season", "week", "team", "roster_key"],
                                                          "nflverse:rosters_weekly", "roster_key", eff, obs)
        except Exception as e:
            out[("nfl_rosters_weekly", s)] = f"ERR {e}"
        try:
            sn, obs = fetch("snap_counts", s, refresh)
            out[("nfl_snap_counts", s)] = append_facts("nfl_snap_counts", sn, ["game_id", "pfr_player_id"],
                                                       "nflverse:snap_counts", "game_id", sn["game_id"].map(ko), obs)
        except Exception as e:
            out[("nfl_snap_counts", s)] = f"ERR {e}"
        if not skip_pbp:
            pbp, obs = fetch("pbp", s, refresh)
            out[("nfl_pbp", s)] = append_facts("nfl_pbp", pbp, ["game_id", "play_id"], "nflverse:pbp", "game_id",
                                               pbp["game_id"].map(ko), obs)
        print(s, {k[0]: v for k, v in out.items() if k[1] == s}, flush=True)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2021-2026")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--skip-pbp", action="store_true")
    a = ap.parse_args()
    lo, hi = map(int, a.seasons.split("-")) if "-" in a.seasons else (int(a.seasons),) * 2
    run(range(lo, hi + 1), a.refresh, a.skip_pbp)
