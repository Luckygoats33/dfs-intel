"""Every DraftKings scoring value lives here. DK's site is NOT fetched by this project.

Sources (secondary, public; checked 2026-10-30):
  [K]  model knowledge of DK NFL Classic rules (long-stable since ~2014)
  [RW] RotoWire "DFS 101: Reviewing DraftKings MMA Scoring Changes" + RotoWire UFC previews
  [P6] pick6.draftkings.com/pick6-rules-and-scoring-ufc as surfaced via web search snippet
       (not fetched by the pipeline; Pick6 page, which may differ from Classic DFS)
  [DFF] dailyfantasyfocus.com "How DraftKings MMA & UFC Work"
UNCERTAIN = rules Will should confirm on DK's own rules page.
"""

NFL_CLASSIC = {
    # Offense [K]
    "pass_td": 4.0,
    "pass_yd": 0.04,            # +1 per 25 yards
    "pass_300_bonus": 3.0,      # 300+ passing yards
    "pass_int": -1.0,
    "rush_td": 6.0,
    "rush_yd": 0.1,
    "rush_100_bonus": 3.0,
    "rec_td": 6.0,
    "rec_yd": 0.1,
    "rec_100_bonus": 3.0,
    "reception": 1.0,           # full PPR
    "return_td": 6.0,           # punt / kick / FG-return TD
    "fumble_lost": -1.0,
    "two_pt": 2.0,              # pass, rush, or catch
    "off_fumble_recovery_td": 6.0,
    # DST [K]
    "dst_sack": 1.0,
    "dst_int": 2.0,
    "dst_fumble_recovery": 2.0,
    "dst_return_td": 6.0,       # punt/kick return TD
    "dst_int_return_td": 6.0,
    "dst_fumble_return_td": 6.0,
    "dst_blocked_kick_return_td": 6.0,
    "dst_safety": 2.0,
    "dst_blocked_kick": 2.0,
    "dst_2pt_or_xp_return": 2.0,
    # Points-allowed tiers: (max_points_allowed_inclusive, fantasy_points) [K]
    "dst_pa_tiers": [(0, 10.0), (6, 7.0), (13, 4.0), (20, 1.0), (27, 0.0), (34, -1.0), (10**9, -4.0)],
}

UNCERTAIN_NFL = [
    "DST points-allowed definition: assumed to EXCLUDE points the opponent scored on defensive/return TDs "
    "(i.e. only offensive points + kicks count). nflverse-based DST here approximates PA from schedule "
    "final score minus opponent non-offensive TDs where identifiable -> confirm on DK.",
    "DST 'blocked kick' and '2pt/XP return' values (+2 each) from memory.",
    "Offensive fumble-recovery TD (+6) value from memory.",
]

UFC_CLASSIC = {
    # [P6][RW][DFF] all agree on these values
    "strike": 0.2,              # every landed strike (UFCStats 'TOTAL STR.' landed)
    "sig_strike": 0.2,          # additional, so a significant strike = 0.4 total
    "control_per_sec": 0.03,    # replaced 'Advances' in DK's 2021 change
    "takedown": 5.0,
    "reversal": 5.0,
    "knockdown": 10.0,
    "win_round": {1: 90.0, 2: 70.0, 3: 45.0, 4: 40.0, 5: 40.0},
    "win_decision": 30.0,
    "quick_win_bonus": 25.0,
    "quick_win_seconds": 60,
}

UNCERTAIN_UFC = [
    "Quick-win bonus assumed to STACK with the +90 R1 win bonus (115 total) -> confirm.",
    "DQ win / technical decision: DQ treated as a win in the round it ended; technical decision treated "
    "as a decision win (+30). Draw / No Contest: no win bonus. -> confirm.",
    "UFCStats 'TOTAL STR.' is assumed to equal DK's 'Strikes' and UFCStats 'CTRL' DK's 'Control Time'; DK "
    "uses its own third-party stat provider, so small differences are expected.",
    "Values are from DK Pick6 page + RotoWire/DFF secondary sources, not DK Classic rules page directly.",
]
