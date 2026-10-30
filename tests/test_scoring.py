import pytest
from dfs_intel.scoring import nfl_offense_points, nfl_dst_points, dst_points_allowed_score, ufc_points, UFCResult


def test_qb_line_with_300_bonus():
    # 312 pass yds (12.48) + 3 bonus + 2 TD (8) + 1 INT (-1) + 25 rush yds (2.5) = 24.98
    assert nfl_offense_points(pass_yds=312, pass_td=2, pass_int=1, rush_yds=25) == pytest.approx(24.98)


def test_bonus_thresholds_exact():
    assert nfl_offense_points(pass_yds=299) == pytest.approx(11.96)
    assert nfl_offense_points(pass_yds=300) == pytest.approx(15.0)
    assert nfl_offense_points(rush_yds=100) == pytest.approx(13.0)
    assert nfl_offense_points(rec=1, rec_yds=99) == pytest.approx(10.9)
    assert nfl_offense_points(rec=1, rec_yds=100) == pytest.approx(14.0)


def test_wr_full_line():
    # 7 rec (7) + 110 yds (11 + 3) + 1 TD (6) + 1 fumble lost (-1) + 2pt (2) + KR TD (6) = 34
    assert nfl_offense_points(rec=7, rec_yds=110, rec_td=1, fumbles_lost=1, two_pt=1, return_td=1) == pytest.approx(34.0)


@pytest.mark.parametrize("pa,exp", [(0, 10), (1, 7), (6, 7), (7, 4), (13, 4), (14, 1), (20, 1), (21, 0), (27, 0), (28, -1), (34, -1), (35, -4), (60, -4)])
def test_dst_tiers(pa, exp):
    assert dst_points_allowed_score(pa) == exp


def test_dst_game():
    # 4 sacks (4) + 2 INT (4) + 1 FR (2) + 1 pick-six (6) + safety (2) + PA 10 (4) = 22
    assert nfl_dst_points(sacks=4, ints=2, fumble_recoveries=1, int_return_tds=1, safeties=1, points_allowed=10) == 22


def test_ufc_decision_win():
    # 80 total strikes incl 50 sig: 80*.2 + 50*.2 = 26; ctrl 120s = 3.6; 2 TD = 10; win dec 30 -> 69.6
    assert ufc_points(80, 50, 120, 2, 0, 0, UFCResult(True, "Decision - Unanimous", 3, 300)) == pytest.approx(69.6)


def test_ufc_quick_ko():
    # 5 strikes all sig = 2.0; 1 KD = 10; R1 win 90; quick win (45s) 25 -> 127
    assert ufc_points(5, 5, 0, 0, 0, 1, UFCResult(True, "KO/TKO", 1, 45)) == pytest.approx(127.0)


def test_ufc_r1_not_quick_and_loser():
    assert ufc_points(10, 6, 0, 0, 0, 0, UFCResult(True, "Submission", 1, 61)) == pytest.approx(93.2)
    assert ufc_points(10, 6, 30, 1, 1, 0, UFCResult(False, "Submission", 1, 61)) == pytest.approx(3.2 + 0.9 + 10)


def test_ufc_late_round_and_nc():
    assert ufc_points(result=UFCResult(True, "KO/TKO", 4, 100)) == 40
    assert ufc_points(result=UFCResult(True, "KO/TKO", 3, 100)) == 45
    assert ufc_points(result=UFCResult(True, "Overturned", 1, 30)) == 0
