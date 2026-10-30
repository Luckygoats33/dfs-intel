"""Compute DK NFL Classic points from stored nflverse facts, and validate against nflverse fantasy_points_ppr."""
from __future__ import annotations
import json
import numpy as np, pandas as pd
from .scoring import nfl_offense_points, nfl_dst_points
from .storage import refresh_views, append_facts, DATA


def offense_inputs(w: pd.DataFrame) -> pd.DataFrame:
    f = lambda c: w[c].fillna(0) if c in w else 0
    return pd.DataFrame({
        "pass_yds": f("passing_yards"), "pass_td": f("passing_tds"), "pass_int": f("passing_interceptions"),
        "rush_yds": f("rushing_yards"), "rush_td": f("rushing_tds"), "rec": f("receptions"),
        "rec_yds": f("receiving_yards"), "rec_td": f("receiving_tds"), "return_td": f("special_teams_tds"),
        "fumbles_lost": f("sack_fumbles_lost") + f("rushing_fumbles_lost") + f("receiving_fumbles_lost"),
        "two_pt": f("passing_2pt_conversions") + f("rushing_2pt_conversions") + f("receiving_2pt_conversions"),
        "off_fumble_rec_td": f("fumble_recovery_tds"),
    })


def dk_offense(w):
    x = offense_inputs(w)
    return np.array([nfl_offense_points(**r) for r in x.to_dict("records")])


def validate(con=None):
    """nflverse PPR: 0.04/pass yd, 4 pass TD, -2 INT, 0.1 rush/rec yd, 6 TD, 1/rec, 2 per 2pt, -2 fumble lost,
    6 ST TD. Convert ours to that system by removing DK-only differences, then compare."""
    con = con or refresh_views()
    w = con.execute("SELECT * FROM nfl_player_week WHERE revision=1 AND position IN ('QB','RB','FB','WR','TE')").df()
    x = offense_inputs(w); dk = dk_offense(w)
    bonus = 3 * ((x.pass_yds >= 300).astype(int) + (x.rush_yds >= 100) + (x.rec_yds >= 100))
    # DK -> nflverse-PPR equivalent: drop bonuses, INT -1 -> -2, fumble lost -1 -> -2
    to_ppr = dk - bonus - x.pass_int - x.fumbles_lost
    ppr = w["fantasy_points_ppr"].fillna(0)
    diff = (to_ppr - ppr).round(2)
    raw_mis = float(((dk - ppr).abs() > 0.011).mean())
    mis = diff.abs() > 0.011
    w2 = w.assign(dk=dk, adj=to_ppr, diff=diff)
    causes = {}
    m = w2[mis]
    if len(m):
        causes["has_fumble_recovery_td"] = int((m.fumble_recovery_tds.fillna(0) > 0).sum())
        causes["has_2pt"] = int((offense_inputs(m).two_pt > 0).sum())
        causes["has_special_teams_td"] = int((m.special_teams_tds.fillna(0) > 0).sum())
        causes["fumbles_lost_total_vs_component_mismatch"] = int((m.fumbles_lost_total.fillna(0) != offense_inputs(m).fumbles_lost).sum())
    out = {"rows": len(w), "raw_mismatch_rate_dk_vs_ppr": raw_mis,
           "adjusted_mismatch_rate": float(mis.mean()), "adjusted_mismatches": int(mis.sum()),
           "mismatch_causes_overlap": causes,
           "sample_mismatches": m.assign(diff=diff[mis])[["player_display_name", "season", "week", "fantasy_points_ppr", "adj", "diff"]].head(10).to_dict("records")}
    return out, w2


def dst_from_pbp(con=None) -> pd.DataFrame:
    con = con or refresh_views()
    q = """
    WITH p AS (SELECT * FROM nfl_pbp WHERE revision=1),
    d AS (
      SELECT game_id, season, week, season_type, defteam AS team,
        sum(coalesce(sack,0)) sacks,
        sum(coalesce(interception,0)) ints,
        sum(CASE WHEN fumble_lost=1 AND fumble_recovery_1_team=defteam THEN 1 ELSE 0 END) fum_rec,
        sum(CASE WHEN touchdown=1 AND td_team=defteam THEN 1 ELSE 0 END) def_st_tds,
        sum(CASE WHEN safety=1 THEN 1 ELSE 0 END) safeties,
        sum(CASE WHEN punt_blocked=1 OR field_goal_result='blocked' OR extra_point_result='blocked' THEN 1 ELSE 0 END) blocks,
        sum(coalesce(defensive_two_point_conv,0)+coalesce(defensive_extra_point_conv,0)) two_pt_ret
      FROM p WHERE defteam IS NOT NULL AND play_type IS NOT NULL GROUP BY ALL),
    nonoff AS (SELECT game_id, defteam AS scorer, count(*) n FROM p WHERE touchdown=1 AND td_team=defteam GROUP BY ALL),
    s AS (SELECT game_id, home_team, away_team, home_score, away_score, gameday FROM nfl_schedules WHERE revision=1 AND home_score IS NOT NULL)
    SELECT d.*, CASE WHEN d.team=s.home_team THEN s.away_score ELSE s.home_score END AS opp_score,
           coalesce(n.n,0) AS opp_nonoffense_tds
    FROM d JOIN s USING (game_id)
    LEFT JOIN nonoff n ON n.game_id=d.game_id AND n.scorer = CASE WHEN d.team=s.home_team THEN s.away_team ELSE s.home_team END
    """
    g = con.execute(q).df()
    # approximation: remove 6 pts per opponent defensive/return TD (and assume the PAT made, +1) from PA
    g["points_allowed"] = (g.opp_score - 7 * g.opp_nonoffense_tds).clip(lower=0)
    g["dk_points"] = [nfl_dst_points(sacks=r.sacks, ints=r.ints, fumble_recoveries=r.fum_rec, return_tds=r.def_st_tds,
                                     safeties=r.safeties, blocked_kicks=r.blocks, two_pt_returns=r.two_pt_ret,
                                     points_allowed=int(r.points_allowed)) for r in g.itertuples()]
    return g


def build_points_table():
    con = refresh_views()
    rep, w = validate(con)
    ko = con.execute("SELECT game_id, effective_at FROM nfl_schedules WHERE revision=1").df().set_index("game_id")["effective_at"]
    pts = w[["player_id", "player_display_name", "position", "team", "opponent_team", "season", "week", "season_type", "game_id"]].assign(dk_points=w["dk"])
    pts["slot_id"] = pts["player_id"]
    dst = dst_from_pbp(con)
    dpts = dst.assign(player_id=None, player_display_name=dst.team + " DST", position="DST", opponent_team=None, slot_id="DST_" + dst.team)[
        ["player_id", "player_display_name", "position", "team", "opponent_team", "season", "week", "season_type", "game_id", "dk_points", "slot_id"]]
    allp = pd.concat([pts, dpts], ignore_index=True)
    con.close()
    s = append_facts("nfl_dk_points", allp, ["slot_id", "season", "week", "season_type"], "derived:dk_scoring_v1(nflverse)",
                     "game_id", allp["game_id"].map(ko))
    rep["dst_rows"] = len(dpts); rep["load"] = s
    (DATA / "results" / "nfl_scoring_validation.json").write_text(json.dumps(rep, indent=1, default=str))
    return rep


if __name__ == "__main__":
    print(json.dumps(build_points_table(), indent=1, default=str))
