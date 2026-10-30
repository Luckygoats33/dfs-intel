import numpy as np, pandas as pd, pytest
from pathlib import Path
from dfs_intel.evaluate import pinball, log_loss, brier, crps_from_quantiles, GRID
from dfs_intel import storage
from dfs_intel.slate_import import read_salary_csv, detect_sport, norm_name, read_contest_standings

EX = Path(__file__).resolve().parent.parent / "examples"


def test_pinball_hand():
    # y=10, pred=8, q=.9 -> .9*2 = 1.8 ; pred=12 -> .1*2=.2
    assert pinball(np.array([10.]), np.array([8.]), .9) == pytest.approx(1.8)
    assert pinball(np.array([10.]), np.array([12.]), .9) == pytest.approx(.2)


def test_crps_point_mass_equals_abs_error():
    q = np.full((1, len(GRID)), 7.0)
    assert crps_from_quantiles(np.array([10.]), q) == pytest.approx(3.0, rel=1e-6)


def test_logloss_brier():
    assert log_loss(np.array([1, 0]), np.array([.5, .5])) == pytest.approx(np.log(2))
    assert brier(np.array([1, 0]), np.array([.8, .3])) == pytest.approx((0.04 + 0.09) / 2)


def test_revisions_and_as_of(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "PARQ", tmp_path / "pq"); monkeypatch.setattr(storage, "META", tmp_path / "pq/_tables.json")
    monkeypatch.setattr(storage, "DB", tmp_path / "t.duckdb")
    t1, t2 = pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-02-01", tz="UTC")
    df = pd.DataFrame({"k": ["a", "b"], "v": [1.0, 2.0], "ev": ["e1", "e2"]})
    eff = pd.Series(pd.to_datetime(["2024-12-01", "2025-01-15"], utc=True))
    assert storage.append_facts("t", df, ["k"], "test", "ev", eff, t1) == {"new": 2, "revised": 0}
    assert storage.append_facts("t", df, ["k"], "test", "ev", eff, t1) == {"new": 0, "revised": 0}  # idempotent
    df2 = df.assign(v=[1.5, 2.0])
    assert storage.append_facts("t", df2, ["k"], "test", "ev", eff, t2) == {"new": 0, "revised": 1}
    # effective filter: only 'a' was true by 2025-01-10
    r = storage.facts_as_of("t", "2025-01-10")
    assert list(r.k) == ["a"] and r.v.iloc[0] == 1.0  # backtest mode: first-observed value
    s = storage.facts_as_of("t", "2025-03-01", mode="strict")
    assert s.set_index("k").v["a"] == 1.5 and s.set_index("k").revision["a"] == 2
    s = storage.facts_as_of("t", "2025-01-20", mode="strict")  # correction not yet observed
    assert s.set_index("k").v["a"] == 1.0


def test_salary_parse_nfl_and_ufc():
    n = read_salary_csv(EX / "EXAMPLE_DKSalaries_NFL_SYNTHETIC.csv")
    assert len(n) == 6 and detect_sport(n) == "NFL" and n.Salary.sum() == 34000
    assert str(n.game_start_utc.iloc[0]) == "2026-11-01 21:25:00+00:00"
    u = read_salary_csv(EX / "EXAMPLE_DKSalaries_UFC_SYNTHETIC.csv")
    assert detect_sport(u) == "UFC" and len(u) == 3


def test_norm_name():
    assert norm_name("Amon-Ra St. Brown") == "amon ra st brown"
    assert norm_name("Marvin Harrison Jr.") == "marvin harrison"
    assert norm_name("José Aldo") == "jose aldo"


def test_standings_stub(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS\n"
                 "1,1,x,0,150,QB A,,A,QB,12.5%,20\n")
    r = read_contest_standings(f)
    assert r["ownership"].own_pct.iloc[0] == 12.5
