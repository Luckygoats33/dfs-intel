"""Walk-forward parlay backtest. Only information from before the event or week is used.

UFC win probabilities are elo-baseline-v0. The mirror has no historical moneylines, so UFC
tickets are graded at fair model prices, not at a market fill. NFL moneylines use the
nflverse schedule price. NFL props have no market line, so they use the trailing-game rate.
"""
from __future__ import annotations

import hashlib

from dfs_intel.method_split import build_split_table, fight_model, method_bucket
from dfs_intel.nfl_props import MARKETS, build_game_props
from dfs_intel.odds_math import to_decimal
from dfs_intel.parlay_search import sample_parlays
from dfs_intel.slip_data import nfl_history
from dfs_intel.tiers import tiers
from dfs_intel.ufc_pipeline import norm_name

THIN_LEG = 30
THIN_FIGHTER = 8
THIN_TEAM = 12
BINS = ((0, 0.02), (0.02, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.40), (0.40, 1.01))


def _elo_before(fights) -> dict:
    ordered = fights.sort_values(["event_date", "fight_id"])
    elo: dict[str, float] = {}
    before: dict[str, dict] = {}
    seen = set()
    for row in ordered.itertuples(index=False):
        event_id = getattr(row, "event_id", None)
        if event_id not in seen:
            before[event_id] = dict(elo)
            seen.add(event_id)
        winner = getattr(row, "winner", None)
        a, b = getattr(row, "fighter_a", None), getattr(row, "fighter_b", None)
        if not isinstance(a, str) or not isinstance(b, str) or not isinstance(winner, str):
            continue
        if winner not in (a, b):
            continue
        ra, rb = elo.get(a, 1500.0), elo.get(b, 1500.0)
        pa = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        score = 1.0 if winner == a else 0.0
        elo[a] = ra + 32.0 * (score - pa)
        elo[b] = rb + 32.0 * ((1.0 - score) - (1.0 - pa))
    return before


def _probs(ra: float, rb: float) -> tuple[float, float]:
    pa = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
    return pa, 1.0 - pa


def _actual(row) -> dict:
    winner = getattr(row, "winner", None)
    winner = winner if isinstance(winner, str) else None
    rnd = getattr(row, "rnd", None)
    try:
        rnd = int(rnd)
    except (TypeError, ValueError):
        rnd = None
    return {
        "winner": winner,
        "bucket": method_bucket(getattr(row, "method", None)),
        "round": rnd,
        "r1_le60": bool(getattr(row, "finish_r1_le60", False)),
        "any_le60": bool(getattr(row, "finish_any_rnd_le60", False)),
        "last10": bool(getattr(row, "finish_last10", False)),
    }


def _status(hit: bool | None) -> str:
    if hit is None:
        return "void"
    return "won" if hit else "lost"


def _legs_for_fight(model: dict, actual: dict, name_a: str, name_b: str, when: str) -> list[dict]:
    if actual["winner"] is None:
        return []
    legs = []

    def add(leg_id, label, leg_type, prob, hit, who=None):
        if prob is None or not 0 < prob < 1:
            return
        legs.append({
            "id": leg_id, "label": label, "type": leg_type, "p": prob, "decimal": 1.0 / prob,
            "edge": None, "hit": hit, "who": who, "team": None, "when": when, "kind": "model",
        })

    for side, name in (("a", name_a), ("b", name_b)):
        prob = sum(atom["p"] for atom in model["atoms"] if atom["side"] == side)
        add(f"{side}-ml", f"{name} wins", "moneyline", prob, actual["winner"] == name, name)
        for method, word in (("ko", "KO/TKO"), ("sub", "submission"), ("dec", "decision")):
            p_m = sum(atom["p"] for atom in model["atoms"] if atom["side"] == side and atom["method"] == method)
            hit = actual["winner"] == name and actual["bucket"] == method
            add(f"{side}-{method}", f"{name} by {word}", "method", p_m, hit, name)
            if not model.get("rounds"):
                continue
            for rnd in range(1, int(model["rounds"]) + 1):
                if method == "dec":
                    continue
                p_r = sum(atom["p"] for atom in model["atoms"] if atom["side"] == side and atom["method"] == method and atom["round"] == rnd)
                hit_r = hit and actual["round"] == rnd
                add(f"{side}-{method}-r{rnd}", f"{name} by {word} R{rnd}", "method-round", p_r, hit_r, name)
    p_yes = sum(atom["p"] for atom in model["atoms"] if atom["method"] == "dec")
    add("dist-yes", "Goes the distance", "distance", p_yes, actual["bucket"] == "dec")
    add("dist-no", "Does not go the distance", "distance", 1 - p_yes if 0 < p_yes < 1 else None, actual["bucket"] in ("ko", "sub"))
    if model.get("rounds"):
        for rnd in range(1, int(model["rounds"]) + 1):
            p_end = sum(atom["p"] for atom in model["atoms"] if atom["method"] in ("ko", "sub") and atom["round"] == rnd)
            add(f"end-{rnd}", f"Fight ends in round {rnd}", "round", p_end, actual["bucket"] in ("ko", "sub") and actual["round"] == rnd)
    timing_flags = {"r1_le60": actual["r1_le60"], "any_le60": actual["any_le60"], "last10": actual["last10"]}
    for kind, happened in timing_flags.items():
        block = (model.get("timing") or {}).get(kind) or {}
        add(f"t-{kind}", kind, "timing", block.get("p"), happened)
    return legs


def _grade_tickets(groups: list[dict], when: str, limit: int = 8) -> tuple[list[dict], list[dict]]:
    tickets = []
    offered = []
    seen = set()
    for tier in tiers():
        drawn = sample_parlays(
            groups, min_decimal=tier["min_decimal"], max_decimal=tier["max_decimal"],
            min_legs=2, max_legs=10, limit=limit, seed=int(hashlib.md5(f"{when}:{tier['id']}".encode()).hexdigest()[:8], 16),
        )
        for ticket in drawn:
            legs = ticket["legs"]
            for leg in legs:
                if leg["id"] in seen:
                    continue
                seen.add(leg["id"])
                offered.append(leg)
            if any(leg.get("hit") is None for leg in legs):
                result = "void"
            elif all(leg.get("hit") for leg in legs):
                result = "won"
            else:
                result = "lost"
            tickets.append({
                "tier": tier["id"], "when": when, "result": result, "decimal": ticket["decimal"],
                "p": ticket["p"], "n": ticket["n"],
            })
    return tickets, offered


def run_ufc(fights, since: str = "2024-01-01", limit_per_tier: int = 6, max_events: int | None = None) -> tuple[list[dict], list[dict]]:
    if fights is None or len(fights) == 0:
        return [], []
    frame = fights[fights["event_date"] >= since].copy() if "event_date" in fights else fights
    if frame.empty:
        return [], []
    before = _elo_before(fights)
    tickets, offered = [], []
    events = frame.sort_values("event_date").drop_duplicates("event_id")
    ready = []
    for event in events.itertuples(index=False):
        card = frame[frame["event_id"] == event.event_id]
        if len(card) < 4:
            continue
        prior = fights[fights["event_date"] < card["event_date"].min()]
        if len(prior) < 40:
            continue
        winners = 0
        for row in card.itertuples(index=False):
            if isinstance(getattr(row, "winner", None), str) and isinstance(getattr(row, "fighter_a", None), str):
                winners += 1
        if winners >= 2:
            ready.append(event)
    if max_events is not None:
        ready = ready[-max_events:]
    for event in ready:
        event_id = event.event_id
        when = str(getattr(event, "event_date", ""))[:10]
        card = frame[frame["event_id"] == event_id]
        if len(card) < 4:
            continue
        prior = fights[fights["event_date"] < card["event_date"].min()]
        if len(prior) < 40:
            continue
        table = build_split_table(prior)
        ratings = before.get(event_id) or {}
        groups = []
        for index, row in enumerate(card.itertuples(index=False)):
            a, b = row.fighter_a, row.fighter_b
            if not isinstance(a, str) or not isinstance(b, str):
                continue
            actual = _actual(row)
            if actual["winner"] is None:
                continue
            rounds = 5 if getattr(row, "format", None) == "5-round" else 3
            pa, pb = _probs(ratings.get(a, 1500.0), ratings.get(b, 1500.0))
            model = fight_model(table, prior, a, b, pa, pb, getattr(row, "weight_class", "") or "", rounds)
            legs = _legs_for_fight(model, actual, a, b, when)
            if len(legs) < 2:
                continue
            groups.append({
                "id": f"{event_id}-{index}", "label": f"{a} vs {b}", "sport": "ufc",
                "atoms": model.get("atoms") or [], "timing_p": {}, "legs": legs,
            })
        if len(groups) < 2:
            continue
        got, legs = _grade_tickets(groups, when, limit_per_tier)
        tickets.extend(got)
        offered.extend(legs)
    return tickets, offered


def _stat_value(row, market: str):
    spec = {item[0]: item for item in MARKETS}[market]
    column = spec[3]
    if market == "anytime-td":
        total = 0.0
        for name in ("rushing_tds", "receiving_tds", "special_teams_tds", "pt_return_tds"):
            if name in row.index:
                value = row[name]
                total += 0.0 if value != value else float(value or 0)
        return 1.0 if total > 0 else 0.0
    if column not in row.index:
        return None
    value = row[column]
    if value != value:
        return None
    return float(value)


def run_nfl(stats, weeks: list[dict], limit_per_tier: int = 6) -> tuple[list[dict], list[dict]]:
    if stats is None or not weeks:
        return [], []
    tickets, offered = [], []
    for week in weeks:
        season, wk = int(week["season"]), int(week["week"])
        finals = [game for game in week.get("games") or [] if game.get("score_status") == "final"]
        if len(finals) < 4:
            continue
        history = nfl_history(stats, season, wk)
        if history is None or history.empty:
            continue
        actual = stats[(stats["season"] == season) & (stats["week"] == wk) & (stats["season_type"] == "REG")]
        when = f"{season}-W{wk:02d}"
        groups = []
        for game in finals:
            legs = []
            priced = game.get("priced") or {}
            if priced.get("valid"):
                home = game["home_score"]
                away = game["away_score"]
                for side, team in (("away", game["away"]), ("home", game["home"])):
                    won = (away > home) if side == "away" else (home > away)
                    if home == away:
                        continue
                    prob = priced[f"novig_{side}"]
                    ml = game.get(f"{side}_moneyline")
                    if not prob or not ml:
                        continue
                    implied = to_decimal(int(ml))
                    market_p = (1 / implied) if implied else None
                    legs.append({
                        "id": f"{game['game_id']}-{side}", "label": f"{team} wins", "type": "moneyline",
                        "p": prob, "decimal": implied, "edge": None if market_p is None else prob - market_p,
                        "hit": won, "who": None, "team": team, "when": when, "kind": "market",
                    })
            props = build_game_props(history, game, week.get("stats_observed_at") or "")
            for prop in props:
                if not prop.get("model_p") or not prop.get("decimal"):
                    continue
                rows = actual[actual["player_id"].astype(str) == str(prop["player_id"])]
                if rows.empty:
                    continue
                value = _stat_value(rows.iloc[-1], prop["type"])
                if value is None or value == prop["line"]:
                    continue
                hit = value > prop["line"] if prop["side"] == "over" else value < prop["line"]
                legs.append({
                    "id": prop["id"], "label": prop["label"], "type": prop["type"], "p": prop["model_p"],
                    "decimal": prop["decimal"], "edge": None, "hit": hit, "who": prop.get("player"),
                    "team": _team_of(history, prop["player_id"], game), "when": when, "kind": "model",
                })
            if len(legs) >= 2:
                groups.append({"id": game["game_id"], "label": f"{game['away']} at {game['home']}", "sport": "nfl", "atoms": [], "legs": legs})
        if len(groups) < 2:
            continue
        got, legs = _grade_tickets(groups, when, limit_per_tier)
        tickets.extend(got)
        offered.extend(legs)
    return tickets, offered


def _team_of(history, player_id: str, game: dict) -> str | None:
    rows = history[history["player_id"].astype(str) == str(player_id)].sort_values(["season", "week"])
    if rows.empty or "team" not in rows:
        return None
    team = str(rows.iloc[-1]["team"])
    if team in (game.get("home"), game.get("away")):
        return team
    return None


def _bin_label(lo: float, hi: float) -> str:
    if hi > 1:
        return f"{lo * 100:.0f}%+"
    return f"{lo * 100:.0f}–{hi * 100:.0f}%"


def summarize(tickets: list[dict], offered: list[dict]) -> dict:
    def pack_tier(rows: list[dict]) -> dict:
        settled = [row for row in rows if row["result"] in ("won", "lost")]
        n = len(settled)
        hits = sum(1 for row in settled if row["result"] == "won")
        profits = [(row["decimal"] - 1.0) if row["result"] == "won" else -1.0 for row in settled]
        drought = longest = 0
        for row in settled:
            if row["result"] == "lost":
                drought += 1
                longest = max(longest, drought)
            else:
                drought = 0
        hit_decimals = [row["decimal"] for row in settled if row["result"] == "won"]
        return {
            "n": n,
            "hits": hits,
            "hit_rate": (hits / n) if n else None,
            "avg_payout_on_hit": (sum(hit_decimals) / len(hit_decimals)) if hit_decimals else None,
            "roi": (sum(profits) / n) if n else None,
            "longest_drought": longest if n else None,
            "thin": n < THIN_LEG,
            "mean_predicted": (sum(row["p"] for row in settled) / n) if n else None,
        }

    by_tier = {tier["id"]: [] for tier in tiers()}
    for ticket in tickets:
        if ticket["result"] == "void":
            continue
        by_tier.setdefault(ticket["tier"], []).append(ticket)
    # Droughts follow the order tickets were appended (chronological).
    tier_stats = {key: pack_tier(rows) for key, rows in by_tier.items()}

    settled_legs = [leg for leg in offered if leg.get("hit") is not None and leg.get("p")]
    types: dict[str, list] = {}
    fighters: dict[tuple, list] = {}
    teams: dict[tuple, list] = {}
    for leg in settled_legs:
        types.setdefault(leg["type"], []).append(leg)
        if leg.get("who") and leg["type"] in ("moneyline", "method", "method-round", "anytime-td", "passing", "rushing", "receiving", "receptions"):
            fighters.setdefault((leg["who"], leg["type"]), []).append(leg)
        if leg.get("team") and leg["type"] != "moneyline":
            teams.setdefault((leg["team"], leg["type"]), []).append(leg)

    def rate_row(rows: list[dict], thin_at: int) -> dict:
        n = len(rows)
        hits = sum(1 for row in rows if row["hit"])
        return {
            "n": n,
            "hits": hits,
            "hit_rate": (hits / n) if n else None,
            "avg_predicted": (sum(row["p"] for row in rows) / n) if n else None,
            "thin": n < thin_at,
        }

    calibration = []
    for lo, hi in BINS:
        bucket = [row for row in tickets if row["result"] in ("won", "lost") and lo <= row["p"] < hi]
        item = rate_row([{"hit": row["result"] == "won", "p": row["p"]} for row in bucket], THIN_LEG)
        item["label"] = _bin_label(lo, hi)
        calibration.append(item)

    def listed(rows_by_key, thin_at: int, name_key: str) -> tuple[list[dict], int]:
        shown = []
        hidden = 0
        for key, rows in rows_by_key.items():
            packed = rate_row(rows, thin_at)
            if packed["thin"]:
                hidden += 1
                continue
            shown.append({name_key: key[0], "type": key[1], **packed})
        shown.sort(key=lambda row: (-row["n"], row[name_key], row["type"]))
        return shown, hidden

    ufc_types = {"moneyline", "method", "method-round", "distance", "round", "timing"}
    prop_types = {"passing", "rushing", "receiving", "receptions", "anytime-td"}
    fighter_src = {key: rows for key, rows in fighters.items() if key[1] in ufc_types}
    player_src = {key: rows for key, rows in fighters.items() if key[1] in prop_types}
    fighter_rows, thin_fighters = listed(fighter_src, THIN_FIGHTER, "name")
    player_rows, thin_players = listed(player_src, THIN_FIGHTER, "name")
    team_rows, thin_teams = listed(teams, THIN_TEAM, "team")

    return {
        "kind": "backtest",
        "ufc_price_note": "UFC tickets are settled at fair model prices. The mirror does not include historical moneylines, so this is not a market-fill ROI. Win probabilities are elo-baseline-v0 from fights before the event.",
        "nfl_price_note": "NFL moneylines use the nflverse schedule price. Player props use trail-quantile-v0 at the pre-week trailing mean. A player with no stat line, or a line that pushes, is left out of the sample. It is not counted as a loss. Leg, fighter, and team rows count a leg once per card or week, and only when that leg was inside a sampled ticket. Both sides of one result are not listed just because they exist.",
        "tiers": tier_stats,
        "calibration": calibration,
        "leg_types": {key: rate_row(rows, THIN_LEG) for key, rows in sorted(types.items())},
        "fighters": fighter_rows[:24],
        "players": player_rows[:24],
        "teams": team_rows[:24],
        "thin_fighters": thin_fighters,
        "thin_players": thin_players,
        "thin_teams": thin_teams,
        "offered_legs": len(settled_legs),
        "tickets": len([row for row in tickets if row["result"] in ("won", "lost")]),
    }
