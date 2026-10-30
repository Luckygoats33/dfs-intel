"""Walk-forward evaluation: for each NFL week / UFC event, models see only facts_as_of(<start of that slate>).
All results here are BASELINES."""
from __future__ import annotations
import json, math
import numpy as np, pandas as pd
from .storage import facts_as_of, refresh_views, DATA
from .scoring import ufc_points, UFCResult

QS = np.array([0.1, 0.25, 0.5, 0.75, 0.9])
GRID = np.linspace(0.01, 0.99, 99)


# ---------- metrics (pure) ----------
def pinball(y, q_pred, q):
    d = y - q_pred
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))


def crps_from_quantiles(y, qmat, grid=GRID):
    """CRPS ~= 2 * mean over quantile levels of pinball loss (dense grid approximation)."""
    return float(2 * np.mean([pinball(y, qmat[:, i], g) for i, g in enumerate(grid)]))


def log_loss(y, p, eps=1e-12):
    p = np.clip(p, eps, 1 - eps); return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(y, p):
    return float(np.mean((p - y) ** 2))


def calibration(y, p, bins=10):
    b = np.minimum((p * bins).astype(int), bins - 1)
    return [{"bin": f"{i/bins:.1f}-{(i+1)/bins:.1f}", "n": int((b == i).sum()), "mean_p": float(p[b == i].mean()),
             "freq": float(y[b == i].mean())} for i in range(bins) if (b == i).any()]


def dist_metrics(y, mu, resid_by_row):
    """mu: point forecast; resid_by_row: list of residual arrays (prior data only) to form each row's distribution."""
    qm = np.array([mu[i] + np.quantile(r, GRID) for i, r in enumerate(resid_by_row)])
    out = {f"pinball_q{q:g}": pinball(y, qm[:, int(round(q * 100)) - 1], q) for q in QS}
    out["crps"] = crps_from_quantiles(y, qm); out["mae_median"] = float(np.mean(np.abs(y - qm[:, 49])))
    out["coverage_10_90"] = float(np.mean((y >= qm[:, 9]) & (y <= qm[:, 89])))
    return out


# ---------- NFL ----------
def run_nfl(n_games=8):
    con = refresh_views()
    sched = con.execute("SELECT season, week, min(effective_at) start FROM nfl_schedules WHERE revision=1 AND game_type='REG' AND home_score IS NOT NULL AND season>=2022 GROUP BY 1,2 ORDER BY 1,2").df()
    allp = con.execute("SELECT * FROM nfl_dk_points").df()
    ys, mus, pools, meta = [], [], [], []
    for s, w, start in sched.itertuples(index=False):
        as_of = start - pd.Timedelta(seconds=1)
        hist = facts_as_of("nfl_dk_points", as_of, where="season_type='REG'", con=con).sort_values("effective_at")
        g = hist.groupby("slot_id").dk_points
        mu = g.apply(lambda x: x.tail(n_games).mean())
        hist["prior_mu"] = g.transform(lambda x: x.shift(1).rolling(n_games, min_periods=1).mean())
        rp = hist.dropna(subset=["prior_mu"]).tail(40000)
        pool = {p: (d.dk_points - d.prior_mu).values for p, d in rp.groupby("position")}
        act = allp[(allp.season == s) & (allp.week == w) & (allp.season_type == "REG") & (allp.revision == 1)]
        act = act[act.slot_id.isin(mu.index) & act.position.isin(pool)]
        for r in act.itertuples():
            ys.append(r.dk_points); mus.append(mu[r.slot_id]); pools.append(pool[r.position]); meta.append((s, w, r.position))
    y, m = np.array(ys), np.array(mus)
    out = {"model": "BASELINE trailing-average DK points (last %d games) + position residual quantiles" % n_games,
           "n": len(y), "weeks": int(len(sched)), "range": f"{sched.season.min()} wk{sched.week.iloc[0]} - {sched.season.max()} wk{sched.week.iloc[-1]}"}
    out.update(dist_metrics(y, m, pools))
    md = pd.DataFrame(meta, columns=["season", "week", "position"]).assign(y=y, mu=m)
    out["mae_mean_by_position"] = md.assign(ae=(md.y - md.mu).abs()).groupby("position").ae.mean().round(3).to_dict()
    return out


def run_nfl_salary_baseline():
    """Salary-only baseline: points ~ a + b*salary by position, fit on PRIOR slates' salaries joined to realized DK points.
    Requires dk_salaries table (from data/inbox imports) with matched IDs."""
    con = refresh_views()
    if "dk_salaries" not in [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()]:
        return {"model": "BASELINE salary-only", "status": "NOT RUN - no DK salary files imported yet"}
    sal = con.execute("SELECT * FROM dk_salaries WHERE sport='NFL'").df()
    pts = con.execute("SELECT slot_id, game_id, dk_points, effective_at FROM nfl_dk_points WHERE revision=1").df()
    if sal.empty: return {"model": "BASELINE salary-only", "status": "NOT RUN - no NFL salaries"}
    return {"model": "BASELINE salary-only", "status": f"{sal.slate_id.nunique()} slates loaded; needs >=2 completed slates to walk forward"}


# ---------- UFC ----------
def ufc_fighter_fights(con):
    f = con.execute("SELECT * FROM ufc_fights WHERE revision=1").df()
    r = con.execute("SELECT * FROM ufc_fight_rounds WHERE revision=1").df()
    tot = r.groupby(["fight_id", "fighter_name"]).agg(kd=("kd", "sum"), sig=("sig_landed", "sum"), tot=("total_landed", "sum"),
                                                       td=("td_landed", "sum"), rev=("rev", "sum"), ctrl=("ctrl_sec", "sum")).reset_index()
    tot = tot.merge(f[["fight_id", "event_id", "event_date", "effective_at", "winner", "method", "round", "time", "fighter_a", "fighter_b", "fighter_a_id", "fighter_b_id"]], on="fight_id")
    tot["fighter_key"] = np.where(tot.fighter_name == tot.fighter_a, tot.fighter_a_id, tot.fighter_b_id)
    tot["fighter_key"] = tot["fighter_key"].fillna("name:" + tot.fighter_name)
    tot["dk_points"] = [ufc_points(r.tot, r.sig, r.ctrl or 0, r.td, r.rev, r.kd,
                        UFCResult(won=(r.winner == r.fighter_name), method=r.method, end_round=int(r.round),
                                  end_time_sec=int(r.time.split(":")[0]) * 60 + int(r.time.split(":")[1])))
                       for r in tot.itertuples()]
    return f, tot


def run_ufc(k=32.0):
    con = refresh_views()
    fights, ff = ufc_fighter_fights(con)
    events = fights.groupby("event_id").effective_at.min().sort_values()
    # ---- win prob: Elo (from 2022 start, cold) vs 50/50, walk-forward by event
    elo, recs = {}, []
    ff_sorted = ff.sort_values("effective_at")
    ys, mus, pools = [], [], []
    first = events.index[:10]  # warm-up: skip first 10 events for scoring metrics
    for ev, t in events.items():
        evf = fights[fights.event_id == ev]
        for r in evf.itertuples():
            a = r.fighter_a_id if isinstance(r.fighter_a_id, str) else "name:" + r.fighter_a
            b = r.fighter_b_id if isinstance(r.fighter_b_id, str) else "name:" + r.fighter_b
            ra, rb = elo.get(a, 1500.0), elo.get(b, 1500.0)
            pa = 1 / (1 + 10 ** ((rb - ra) / 400))
            if r.winner in (r.fighter_a, r.fighter_b):
                y = 1.0 if r.winner == r.fighter_a else 0.0
                if ev not in first:  # orient each fight by a hash of its id so 'side A' is not the UFCStats winner-first listing
                    flip = int(r.fight_id[-1], 16) % 2 == 1
                    recs.append((1 - y, 1 - pa) if flip else (y, pa))
                elo[a] = ra + k * (y - pa); elo[b] = rb - k * (y - pa)
        if ev in first: continue
        # ---- DK points: trailing avg of fighter's prior DK points (as-of strictly before event)
        as_of = t - pd.Timedelta(seconds=1)
        hist = ff_sorted[ff_sorted.effective_at <= as_of]
        mu_f = hist.groupby("fighter_key").dk_points.mean(); gmean = hist.dk_points.mean()
        pool = (hist.dk_points - gmean).values
        cur = ff[ff.event_id == ev]
        for r in cur.itertuples():
            ys.append(r.dk_points); mus.append(mu_f.get(r.fighter_key, gmean)); pools.append(pool)
    y, p = np.array([a for a, _ in recs]), np.array([b for _, b in recs])
    # NB: "fighter_a" on UFCStats is usually the winner (listed first), so a 50/50 baseline is the honest reference.
    win = {"n_fights": len(y), "share_side_a_won_after_random_orientation": float(y.mean()),
           "elo": {"log_loss": log_loss(y, p), "brier": brier(y, p), "calibration": calibration(y, p)},
           "coin_flip_50_50": {"log_loss": log_loss(y, np.full_like(p, .5)), "brier": brier(y, np.full_like(p, .5))},
           "note": "Sides randomly oriented by fight_id hash (UFCStats lists winners first). Elo K=%g starts cold at 2022-01 (no pre-2022 history loaded); first 10 events are warm-up and not scored." % k}
    pts = {"model": "BASELINE trailing-average DK points per fighter (all prior UFC fights since 2022; global mean for debutants)",
           "n": len(ys)}
    pts.update(dist_metrics(np.array(ys), np.array(mus), pools))
    return {"win_prob": win, "dk_points": pts}


def main():
    res = {"generated_note": "ALL NUMBERS ARE BASELINES", "nfl_trailing_avg": run_nfl(), "nfl_salary_only": run_nfl_salary_baseline(), "ufc": run_ufc()}
    (DATA / "results" / "walkforward_baselines.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
