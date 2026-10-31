"""Turn a UFC card or an NFL week into one parlay slate."""
from __future__ import annotations

from dfs_intel.method_split import catalog, clean_weight_class, fight_model
from dfs_intel.nfl_props import build_game_props
from dfs_intel.odds_math import format_american, preset_parlays, presets_plus_5000
from dfs_intel.ufc_pipeline import norm_name


def _moneyline_groups(groups: list[dict]) -> list[dict]:
    out = []
    for group in groups:
        legs = [leg for leg in group["legs"] if leg["type"] == "moneyline"]
        if len(legs) >= 2:
            out.append({"id": group["id"], "label": group["label"], "legs": legs})
    return out


def _presets(groups: list[dict]) -> list[dict]:
    presets = preset_parlays(_moneyline_groups(groups))
    for preset in presets:
        preset["american_fmt"] = format_american(preset.get("american"))
    longshot = presets_plus_5000(groups)
    if longshot:
        presets.append(longshot)
    timing_groups = []
    for group in groups:
        legs = [leg for leg in group["legs"] if leg["type"] == "timing" and not leg.get("thin")]
        if legs:
            timing_groups.append({"id": group["id"], "legs": legs})
    timing = presets_plus_5000(timing_groups)
    if timing:
        timing["id"] = "timing-plus5000"
        timing["name"] = f"{timing['n']}-leg timing +5000"
        presets.append(timing)
    return presets


def ufc_slate(event: dict, table: dict | None, fights, gap: dict | None) -> dict:
    fighters = (gap or {}).get("fighters") or {}
    source = (gap or {}).get("source")
    observed = event.get("observed_at")
    groups = []
    for fight in event.get("fights") or []:
        red, blue = fight.get("red") or {}, fight.get("blue") or {}
        if not red.get("name") and not blue.get("name"):
            continue
        rounds = (fight.get("rounds") or {}).get("value")
        rounds = rounds if rounds in (3, 5) else None
        priced = bool(fight.get("odds_valid"))
        model = fight_model(
            table, fights, red.get("name") or "", blue.get("name") or "",
            red.get("novig") if priced else None, blue.get("novig") if priced else None,
            clean_weight_class(fight.get("weight_class")), rounds,
        )
        moneylines = {"a": fight.get("ml_red"), "b": fight.get("ml_blue")} if priced else {}
        legs = catalog(model, fight["id"], fighters, observed, source, moneylines)
        groups.append({
            "id": fight["id"],
            "label": f"{red.get('name') or 'Red'} vs {blue.get('name') or 'Blue'}",
            "sport": "ufc",
            "atoms": model.get("atoms") or [],
            "timing_p": {kind: block.get("p") for kind, block in (model.get("timing") or {}).items() if block.get("p")},
            "legs": legs,
        })
    return {
        "id": event["slug"],
        "title": event.get("name") or event.get("headline") or event["slug"],
        "sport": "ufc",
        "groups": groups,
        "presets": _presets(groups),
        "market_status": (gap or {}).get("status") or "unavailable",
        "market_source": source,
        "market_updated": (gap or {}).get("updated_text") or "",
        "market_url": (gap or {}).get("url"),
        "market_error": (gap or {}).get("error"),
    }


def nfl_history(stats, season: int, week: int):
    if stats is None or stats.empty:
        return stats
    return stats[(stats["season_type"] == "REG") & (
        (stats["season"] < season) | ((stats["season"] == season) & (stats["week"] < week))
    )].copy()


def nfl_slate(week: dict, stats) -> dict:
    observed = week.get("stats_observed_at") or week.get("schedule_observed_at")
    history = nfl_history(stats, week["season"], week["week"])
    groups = []
    for game in week.get("games") or []:
        legs = []
        priced = game.get("priced") or {}
        if priced.get("valid"):
            for side, team, ml_key, novig_key, dec_key in (
                ("away", game["away"], "away_moneyline", "novig_away", "decimal_away"),
                ("home", game["home"], "home_moneyline", "novig_home", "decimal_home"),
            ):
                legs.append({
                    "id": f"{game['game_id']}-{side}",
                    "type": "moneyline",
                    "label": f"{team} wins",
                    "kind": "market",
                    "model_p": priced[novig_key],
                    "novig": priced[novig_key],
                    "fair_american": None,
                    "decimal": priced[dec_key],
                    "price_kind": "market",
                    "market_american": game.get(f"{side}_moneyline_american"),
                    "source": "nflverse:schedules moneyline, book not named",
                    "asof": week.get("schedule_observed_at"),
                    "thin": False,
                    "thin_note": "",
                    "atoms": None,
                    "timing": None,
                })
        if history is not None and not history.empty:
            legs.extend(build_game_props(history, game, observed))
        groups.append({
            "id": game["game_id"],
            "label": f"{game['away']} at {game['home']}",
            "sport": "nfl",
            "atoms": None,
            "timing_p": {},
            "legs": legs,
        })
    return {
        "id": week["slug"],
        "title": f"NFL {week['season']} week {week['week']}",
        "sport": "nfl",
        "groups": groups,
        "presets": _presets(groups),
        "market_status": "user-line",
        "market_source": None,
        "market_updated": "",
        "market_error": "No free prop-line feed is wired in. Yardage and reception lines start at the trailing mean and you can change them.",
    }
