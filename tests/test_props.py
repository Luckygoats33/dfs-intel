import pandas as pd

from dfs_intel.gapodds import parse_props
from dfs_intel.method_split import (
    K,
    build_split_table,
    catalog,
    fight_model,
    joint_probability,
    shrink,
    slate_probability,
)
from dfs_intel.nfl_props import default_line, side_probs
from dfs_intel.odds_math import preset_parlays, to_decimal


def _fights():
    rows = []
    for i in range(40):
        rows.append({
            "winner": "Ace", "fighter_a": "Ace", "fighter_b": "Other",
            "method": "KO/TKO" if i < 20 else ("Submission" if i < 30 else "Decision - Unanimous"),
            "rnd": 1 if i < 20 else (2 if i < 30 else 3),
            "format": "3-round", "weight_class": "Lightweight",
            "finish_r1_le60": i < 2, "finish_any_rnd_le60": i < 4, "finish_last10": i == 39,
        })
    rows.append({
        "winner": "Ace", "fighter_a": "Ace", "fighter_b": "Other",
        "method": "Decision - Unanimous", "rnd": 3, "format": "3-round", "weight_class": "Lightweight",
        "finish_r1_le60": False, "finish_any_rnd_le60": False, "finish_last10": False,
    })
    return pd.DataFrame(rows)


def test_shrink_pulls_a_short_sample_toward_the_class():
    assert shrink(0, 0, 0.25, K) == 0.25
    assert shrink(4, 4, 0.25, K) == (4 + K * 0.25) / (4 + K)


def test_method_split_scales_the_win_probability_and_flags_a_short_record():
    table = build_split_table(_fights())
    model = fight_model(table, _fights(), "Ace", "Rookie", 0.6, 0.4, "Lightweight", 3)
    ko = [atom for atom in model["atoms"] if atom["name"] == "Ace" and atom["method"] == "ko"]
    assert abs(sum(atom["p"] for atom in ko) - 0.6 * shrink(20, 41, 20 / 41, K)) < 1e-9
    assert model["thin"] is True  # Rookie has no wins
    legs = catalog(model, "bout", {"rookie": {}}, "2026-10-30T00:00:00+00:00", None, {"a": -150, "b": 130})
    labels = {leg["label"]: leg for leg in legs}
    assert "Ace by KO/TKO" in labels
    assert labels["Ace wins"]["price_kind"] == "market"
    assert labels["Finish in the first 60s of round 1"]["kind"] == "observed"
    assert any(leg["type"] == "method-round" and "R1" in leg["label"] for leg in legs)


def test_same_fight_joint_is_not_a_product():
    atoms = [
        {"id": "a:ko:1", "side": "a", "method": "ko", "round": 1, "p": 0.10},
        {"id": "a:dec:dec", "side": "a", "method": "dec", "round": None, "p": 0.40},
        {"id": "b:ko:1", "side": "b", "method": "ko", "round": 1, "p": 0.20},
        {"id": "b:dec:dec", "side": "b", "method": "dec", "round": None, "p": 0.30},
    ]
    win = {"atoms": ["a:ko:1", "a:dec:dec"], "timing": None, "model_p": 0.5}
    ko = {"atoms": ["a:ko:1"], "timing": None, "model_p": 0.10}
    both = joint_probability(atoms, [win, {"atoms": ["b:ko:1", "b:dec:dec"], "timing": None}])
    assert both["status"] == "contradictory" and both["p"] == 0
    nested = joint_probability(atoms, [win, ko])
    assert nested["status"] == "ok" and abs(nested["p"] - 0.10) < 1e-12
    assert abs(nested["p"] - (0.5 * 0.10)) > 1e-6
    decision = {"atoms": ["a:dec:dec"], "timing": None}
    assert joint_probability(atoms, [ko, decision])["status"] == "contradictory"
    distance = {"atoms": ["a:dec:dec", "b:dec:dec"], "timing": None, "model_p": 0.7}
    assert joint_probability(atoms, [distance, ko])["status"] == "contradictory"
    timing = {"atoms": None, "timing": "r1_le60", "model_p": 0.03}
    alone = joint_probability(atoms, [timing], {"r1_le60": 0.03})
    assert alone["status"] == "ok" and abs(alone["p"] - 0.03) < 1e-12
    ends = {"atoms": ["a:ko:1", "b:ko:1"], "timing": None, "model_p": 0.30}
    tighter = joint_probability(atoms, [ends, timing], {"r1_le60": 0.03})
    assert tighter["status"] == "ok" and abs(tighter["p"] - 0.03) < 1e-12
    cut = joint_probability(atoms, [ko, timing], {"r1_le60": 0.03})
    assert cut["status"] == "unidentified" and cut["p"] is None


def test_gapodds_public_method_prices_parse():
    html = """
    <p>Updated Fri, Oct 30, 12:15 PM ET</p>
    <section class="pp-game" aria-label="Renato Moicano vs. Tom Nolan">
      <ul>
        <li><span class="pp-pl"><a href="/ufc/fighters/renato-moicano">Renato Moicano</a></span>
          <span class="pp-lines">
            <span>To win <b>-125</b></span>
            <span>Wins by KO/TKO <b>+750</b></span>
            <span>Wins by submission <b>+200</b></span>
            <span>Wins by decision <b>+550</b></span>
          </span>
        </li>
      </ul>
    </section>
    """
    parsed = parse_props(html)
    row = parsed["fighters"]["renato moicano"]
    assert row["ko"] == 750 and row["sub"] == 200 and row["dec"] == 550
    assert "Oct" in parsed["updated_text"]


def test_nfl_line_probs_leave_pushes_out_of_both_sides():
    samples = [10, 20, 20, 40]
    assert default_line(samples, "rushing") == 22.5
    probs = side_probs(samples, 20)
    assert probs["over"] == 0.25 and probs["under"] == 0.25 and probs["push"] == 0.5
    assert side_probs([], 10.5)["over"] is None


def test_moneyline_presets_still_build_and_long_prices_clear_plus_5000():
    groups = []
    for i in range(3):
        groups.append({"id": f"g{i}", "legs": [
            {"id": f"g{i}a", "label": "fav", "novig": 0.7, "american": -230, "decimal": to_decimal(-230)},
            {"id": f"g{i}b", "label": "dog", "novig": 0.3, "american": 230, "decimal": to_decimal(230)},
        ]})
    assert any(item["kind"] == "longshot" for item in preset_parlays(groups))
    from dfs_intel.odds_math import presets_plus_5000
    long_groups = []
    for i in range(4):
        long_groups.append({"id": f"f{i}", "legs": [{
            "id": f"f{i}-t", "label": f"timing {i}", "type": "timing", "model_p": 0.03, "novig": 0.03,
            "decimal": 1 / 0.03, "thin": False, "fair_american": "+3233",
        }]})
    preset = presets_plus_5000(long_groups)
    assert preset is not None
    assert preset["american"] >= 5000
    assert preset["pays_50_on_1"] is True
