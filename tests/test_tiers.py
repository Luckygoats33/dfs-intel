from datetime import datetime, timezone

from dfs_intel.backtest import summarize
from dfs_intel.parlay_pools import parlays_by_tier
from dfs_intel.parlay_search import sample_parlays
from dfs_intel.site_render import render_stats_page, render_tier_page
from dfs_intel.tiers import decimal_of, tier_for_decimal, tiers


def test_tier_bands_do_not_overlap():
    assert decimal_of(5000) == 51
    assert tier_for_decimal(51) == "5000"
    assert tier_for_decimal(100.9) == "5000"
    assert tier_for_decimal(101) == "10000"
    assert tier_for_decimal(5001) == "500000"
    assert tier_for_decimal(40) is None
    assert [tier["id"] for tier in tiers()] == ["5000", "10000", "25000", "50000", "100000", "500000"]


def test_sampler_stays_inside_the_band_and_one_group_once():
    groups = []
    for index in range(6):
        groups.append({
            "id": f"g{index}",
            "label": f"Fight {index}",
            "sport": "ufc",
            "atoms": [],
            "legs": [
                {"id": f"g{index}-short", "p": 0.4, "decimal": 2.4, "edge": 0.02, "label": "short", "type": "moneyline"},
                {"id": f"g{index}-long", "p": 0.08, "decimal": 12.0, "edge": 0.01, "label": "long", "type": "method"},
            ],
        })
    drawn = sample_parlays(groups, min_decimal=51, max_decimal=101, min_legs=2, max_legs=4, limit=8, seed=3)
    assert drawn
    for ticket in drawn:
        assert 51 <= ticket["decimal"] < 101
        assert ticket["n"] == len({leg["id"].split("-")[0] for leg in ticket["legs"]})
        assert 2 <= ticket["n"] <= 4


def test_backtest_summary_marks_a_thin_tier_and_counts_drought():
    tickets = [
        {"tier": "5000", "result": "lost", "decimal": 60, "p": 0.02, "when": "a"},
        {"tier": "5000", "result": "lost", "decimal": 60, "p": 0.02, "when": "b"},
        {"tier": "5000", "result": "won", "decimal": 51, "p": 0.03, "when": "c"},
    ]
    legs = [
        {"type": "method", "p": 0.2, "hit": True, "who": "Ace", "team": None},
        {"type": "method", "p": 0.2, "hit": False, "who": "Ace", "team": None},
    ]
    stats = summarize(tickets, legs)
    tier = stats["tiers"]["5000"]
    assert tier["n"] == 3 and tier["hits"] == 1 and tier["thin"] is True
    assert tier["longest_drought"] == 2
    assert abs(tier["roi"] - ((50 + -1 + -1) / 3)) < 1e-9
    assert stats["leg_types"]["method"]["thin"] is True
    assert stats["thin_fighters"] == 1
    assert stats["fighters"] == []


def test_precomputed_tickets_stay_in_band_and_keep_leg_filters():
    groups = []
    for index in range(8):
        groups.append({
            "id": f"g{index}",
            "label": f"Fight {index}",
            "sport": "ufc",
            "atoms": [],
            "legs": [
                {
                    "id": f"g{index}-ml", "label": f"Fighter {index} wins", "type": "moneyline",
                    "model_p": 0.42, "decimal": 2.2, "market_american": "-130", "fair_american": "-120",
                    "kind": "market", "thin": False,
                },
                {
                    "id": f"g{index}-ko", "label": f"Fighter {index} by KO/TKO", "type": "method",
                    "model_p": 0.08, "decimal": 12.0, "fair_american": "+1100",
                    "kind": "model", "thin": False,
                },
            ],
        })
    drawn = parlays_by_tier({"id": "card", "sport": "ufc", "groups": groups}, limit=6)
    band = {tier["id"]: tier for tier in tiers()}
    for tier_id, tickets in drawn.items():
        assert tickets
        for ticket in tickets:
            assert band[tier_id]["min_decimal"] <= ticket["decimal"] < (band[tier_id]["max_decimal"] or 10**12)
            assert 2 <= ticket["n"] <= 10
            assert ticket["min_p"] == min(leg["p"] for leg in ticket["legs"])
            assert "market" in ticket["legs"][0]


def test_stats_page_withholds_a_thin_rate():
    stats = summarize(
        [{"tier": "5000", "result": "lost", "decimal": 60, "p": 0.02, "when": "a"}],
        [],
    )
    html = render_stats_page(stats, datetime(2026, 10, 31, tzinfo=timezone.utc))
    assert "Backtest" in html
    assert "too thin (n=1)" in html
    assert "Parlay stats" in html


def test_tier_page_has_filters_random_and_slip():
    tier = tiers()[0]
    html = render_tier_page(tier, [{
        "id": "ufc-1", "sport": "ufc", "title": "Test card", "href": "../ufc/test.html",
        "parlays": [{
            "key": "a|b", "n": 2, "p": 0.01, "decimal": 60.0, "american": "+5900",
            "edge": 0.01, "same": False, "nfl_same": False, "min_p": 0.05,
            "legs": [
                {"id": "a", "label": "A wins", "type": "moneyline", "price": "-150", "why": "No-vig 60.0%.", "kind": "market", "thin": False, "p": 0.6, "decimal": 1.6, "edge": 0.01, "market": True},
                {"id": "b", "label": "B by KO", "type": "method", "price": "+800", "why": "Model 8.0%.", "kind": "model", "thin": False, "p": 0.08, "decimal": 9.0, "edge": None, "market": False},
            ],
        }],
    }], datetime(2026, 10, 31, tzinfo=timezone.utc))
    assert "Random pick" in html
    assert "Save filter preset" in html
    assert "Save to My slips" in html
    assert "data-market-only" in html
    assert "+5000 (50 to 1)" in html
