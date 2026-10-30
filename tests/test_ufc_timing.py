import pandas as pd
from dfs_intel.ufc_timing import add_flags, american_odds, rates, fighter_counts


def _df():
    return pd.DataFrame({
        "fighter_a": ["A", "B", "C", "A", "E"], "fighter_b": ["X", "Y", "Z", "W", "V"], "winner": ["A", "Y", "C", "W", None],
        "method": ["KO/TKO", "Submission", "Decision - Unanimous", "KO/TKO", "KO/TKO"],
        "round": [1, 2, 3, 1, 4], "time": ["0:45", "4:55", "5:00", "1:01", "0:30"],
        "time_format": ["3 Rnd (5-5-5)"] * 4 + ["5 Rnd (5-5-5-5-5)"],
        "weightclass": ["Lightweight Bout"] * 4 + ["UFC Lightweight Title Bout"]})


def test_flags_and_rates():
    f = add_flags(_df())
    assert list(f.finish_r1_le60) == [True, False, False, False, False]
    assert list(f.finish_any_rnd_le60) == [True, False, False, False, True]
    assert list(f.finish_last10) == [False, True, False, False, False]  # decision at 5:00 is not a finish
    r = rates(f).iloc[0]
    assert r.n_fights == 5 and r.finish_any_rnd_le60_mean == 0.4
    assert set(f.weight_class) == {"Lightweight"}
    c = fighter_counts(f, "A")
    assert c["n_fights"] == 2 and c["finish_r1_le60"] == 1 and c["finish_r1_le60_won"] == 1


def test_american_odds():
    assert american_odds(0.2) == "+400" and american_odds(0.75) == "-300" and american_odds(0.5) == "+100"
