"""Build the static research site: UFC.com cards, mirror history, nflverse weeks.

Usage:
    python -m dfs_intel.site_build --out site
"""
from __future__ import annotations

import argparse
import json
import shutil
import traceback
from datetime import datetime, timezone
from pathlib import Path

from dfs_intel import ROOT
from dfs_intel.odds_math import format_american, no_vig, preset_parlays, to_decimal
from dfs_intel.site_render import render_home, render_nfl, render_ufc
from dfs_intel.ufc_pipeline import norm_name
from dfs_intel.ufc_public import (
    EVENTS_URL,
    NEWS_URL,
    PageFetcher,
    article_matches_event,
    parse_article,
    parse_event_page,
    parse_events_list,
    parse_news_index,
    rank_article,
)

STATIC = ROOT / "web"
OVERROUND_INVALID = 0.15


def _now():
    return datetime.now(timezone.utc)


def _groups_from_fights(fights: list[dict]) -> list[dict]:
    groups = []
    for fight in fights:
        if not fight.get("odds_valid"):
            continue
        red, blue = fight["red"], fight["blue"]
        groups.append({
            "id": fight["id"],
            "label": f"{red['name']} vs {blue['name']}",
            "legs": [
                _leg(fight["id"] + "-red", red),
                _leg(fight["id"] + "-blue", blue),
            ],
        })
    return groups


def _leg(leg_id: str, side: dict) -> dict:
    return {
        "id": leg_id,
        "label": side["name"],
        "american": side["ml"],
        "american_fmt": side.get("american_fmt"),
        "decimal": side["decimal"],
        "novig": side["novig"],
    }


def _with_presets(slate_id: str, title: str, groups: list[dict]) -> dict:
    presets = preset_parlays(groups)
    for preset in presets:
        preset["american_fmt"] = format_american(preset.get("american"))
    return {"id": slate_id, "title": title, "groups": groups, "presets": presets}


def _elo_label(history: dict) -> str:
    from dfs_intel.ufc_history import elo_label
    return elo_label((history or {}).get("elo_metrics"))


def _elo_side(history: dict, name: str) -> dict:
    if not history or history.get("status") != "ok":
        return {"status": "unavailable"}
    from dfs_intel.ufc_history import lookup_fighter
    found = lookup_fighter(history, name)
    if found.get("status") == "ambiguous":
        names = ", ".join(row["fighter"] for row in found.get("matches") or [])
        return {"status": "ambiguous", "note": f"More than one mirror fighter matches: {names}."}
    if found.get("status") != "matched":
        return {
            "status": "prior",
            "note": "No fight under this normalized name in the mirror window. 1500 is the cold-start prior, not a measurement.",
        }
    if found.get("elo") is None:
        return {
            "status": "prior",
            "note": "The name is in the mirror, but no decisive result moved a rating. 1500 remains the cold-start prior.",
        }
    return {
        "status": "number",
        "rating": float(found["elo"]),
        "note": "elo-baseline-v0 after every decisive fight in the mirror window. Not a market price.",
    }


def _timing_side(history: dict, name: str) -> dict:
    if not history or history.get("status") != "ok":
        return {"status": "unavailable"}
    from dfs_intel.ufc_history import lookup_fighter
    return lookup_fighter(history, name)


def _bio_side(history: dict, name: str) -> dict:
    if not history or history.get("status") != "ok":
        return {"status": "unavailable"}
    from dfs_intel.ufc_history import lookup_bio
    return lookup_bio(history, name)


def _weights(articles: list[dict], observed_at: str) -> dict:
    idx = {}
    for art in articles:
        if art.get("status") != "ok" or art.get("kind") != "weigh-in":
            continue
        for row in art.get("weights") or []:
            for side, lb_key, mark_key in (("a", "a_lb", "a_mark"), ("b", "b_lb", "b_mark")):
                idx[norm_name(row[side])] = {
                    "lb": row[lb_key],
                    "mark": row[mark_key],
                    "source": art["url"],
                    "asof": observed_at,
                }
    return idx


def _rounds_for(fight: dict, statement: dict | None, source: str | None, observed_at: str) -> dict:
    if fight.get("rounds_on_page"):
        return {
            "value": fight["rounds_on_page"],
            "kind": "observed",
            "source": "UFC.com event page",
            "asof": observed_at,
            "note": "Printed on the fight listing.",
        }
    main = fight.get("card") == "Main card" and fight.get("order") == 1
    if statement and main and statement.get("main_event"):
        return {
            "value": statement["main_event"],
            "kind": "observed",
            "source": source,
            "asof": observed_at,
            "note": statement.get("main_event_quote") or "",
        }
    if statement and not main and statement.get("other_bouts"):
        return {
            "value": statement["other_bouts"],
            "kind": "observed",
            "source": source,
            "asof": observed_at,
            "note": statement.get("other_bouts_quote") or "",
        }
    return {
        "value": None,
        "kind": "missing",
        "source": "UFC.com event page",
        "asof": observed_at,
        "note": "Scheduled rounds are not printed on the event page, and no matched UFC.com article stated them.",
    }


def _statement(articles: list[dict]) -> tuple[dict | None, str | None]:
    for art in articles:
        rounds = (art or {}).get("rounds") or {}
        if rounds.get("main_event") or rounds.get("other_bouts"):
            return rounds, art.get("url")
    return None, None


def _side(name: str, country: str, ml, novig, decimal, history, weights, observed_at: str) -> dict:
    return {
        "name": name,
        "country": country,
        "ml": ml,
        "american_fmt": format_american(ml) if ml is not None else None,
        "novig": novig,
        "decimal": decimal,
        "weight": weights.get(norm_name(name)),
        "elo": _elo_side(history, name),
        "timing": _timing_side(history, name),
        "bio": _bio_side(history, name),
    }


def assemble_event(listing: dict, page: dict, articles: list[dict], history: dict, observed_at: str) -> dict:
    statement, statement_src = _statement(articles)
    weights = _weights(articles, observed_at)
    fights = []
    for index, raw in enumerate(page.get("fights") or [], start=1):
        ml_a, ml_b = raw.get("ml_red"), raw.get("ml_blue")
        novig_a = novig_b = dec_a = dec_b = over = None
        valid = False
        if ml_a is not None and ml_b is not None:
            novig_a, novig_b, over = no_vig(ml_a, ml_b)
            dec_a, dec_b = to_decimal(ml_a), to_decimal(ml_b)
            valid = over < OVERROUND_INVALID
        note = (
            "Overround above 15%. The quote is shown and excluded from parlays."
            if ml_a is not None and ml_b is not None and not valid
            else ("Moneyline missing on the event page." if ml_a is None or ml_b is None else "No-vig renormalizes the two implied probabilities.")
        )
        fight = {
            "id": f"{listing['slug']}-{index}",
            "order": raw.get("order") or index,
            "card": raw.get("card"),
            "weight_class": raw.get("weight_class"),
            "rounds_on_page": raw.get("rounds_on_page"),
            "ml_red": ml_a,
            "ml_blue": ml_b,
            "overround": over,
            "odds_valid": valid,
            "odds_note": note,
        }
        fight["rounds"] = _rounds_for(fight, statement, statement_src, observed_at)
        fight["red"] = _side(raw["red"]["name"], raw["red"].get("country"), ml_a, novig_a, dec_a, history, weights, observed_at)
        fight["blue"] = _side(raw["blue"]["name"], raw["blue"].get("country"), ml_b, novig_b, dec_b, history, weights, observed_at)
        fights.append(fight)
    times = {}
    for key, label, list_ts, list_text in (
        ("early", "Early prelims", listing.get("early_ts"), listing.get("early_text")),
        ("prelims", "Prelims", listing.get("prelims_ts"), listing.get("prelims_text")),
        ("main", "Main card", listing.get("main_ts") or page.get("main_ts"), listing.get("main_card_text")),
    ):
        ts, text = list_ts, list_text
        for sec in page.get("sections") or []:
            if sec.get("label") == label and sec.get("timestamp"):
                ts, text = sec["timestamp"], sec.get("time_text") or text
        times[key] = {"ts": ts, "text": text}
    broadcasters = []
    for sec in page.get("sections") or []:
        if sec.get("broadcaster") and sec["broadcaster"] not in broadcasters:
            broadcasters.append(sec["broadcaster"])
    slate = _with_presets(listing["slug"], page.get("name") or listing.get("headline") or listing["slug"], _groups_from_fights(fights))
    return {
        "status": "ok",
        "slug": listing["slug"],
        "url": page.get("url") or listing.get("url"),
        "name": page.get("name") or listing.get("headline"),
        "headline": listing.get("headline"),
        "location": listing.get("location"),
        "venue": page.get("venue") or listing.get("location"),
        "observed_at": observed_at,
        "times": times,
        "broadcaster": "; ".join(broadcasters),
        "fights": fights,
        "articles": articles,
        "elo_label": _elo_label(history),
        "parlay_slates": [slate],
    }


def _match_articles(event: dict, page: dict, news_links: list[dict], peers: list[dict]) -> list[dict]:
    found = []
    seen = set()
    pool = list(news_links) + list(page.get("news_links") or [])
    enriched = dict(event)
    enriched["headline_names"] = page.get("headline_names") or ""
    for link in pool:
        url = link.get("url")
        if not url or url in seen:
            continue
        if not article_matches_event(enriched, link, peers):
            continue
        seen.add(url)
        found.append(link)
    found.sort(key=rank_article)
    return found[:3]


def build_ufc(client: PageFetcher, history: dict) -> tuple[list[dict], str | None]:
    try:
        events = parse_events_list(client.get(EVENTS_URL))
    except Exception as exc:
        return [], f"UFC.com events page unavailable: {exc}"
    try:
        news_links = parse_news_index(client.get(NEWS_URL))
    except Exception as exc:
        news_links = []
        news_error = str(exc)
    else:
        news_error = None
    built = []
    parsed_articles: dict[str, dict] = {}
    for listing in events:
        try:
            page = parse_event_page(client.get(listing["url"]), listing["url"])
            observed = datetime.now(timezone.utc).isoformat()
            articles = []
            if news_error and not page.get("news_links"):
                articles.append({"url": NEWS_URL, "status": "unavailable", "error": news_error})
            for link in _match_articles(listing, page, news_links, events):
                url = link["url"]
                if url not in parsed_articles:
                    try:
                        parsed_articles[url] = parse_article(client.get(url), url)
                    except Exception as exc:
                        parsed_articles[url] = {"url": url, "status": "unavailable", "error": str(exc)}
                articles.append(parsed_articles[url])
            event = assemble_event(listing, page, articles, history, observed)
            built.append(event)
        except Exception as exc:
            built.append({
                "status": "unavailable",
                "slug": listing.get("slug"),
                "url": listing.get("url"),
                "headline": listing.get("headline"),
                "name": listing.get("headline"),
                "error": str(exc),
                "fights": [],
                "parlay_slates": [],
            })
    return built, None


def build_nfl(refresh: bool) -> dict:
    from dfs_intel.nfl_board import load_nfl
    from dfs_intel.slip_data import nfl_slate
    board = load_nfl(refresh=refresh)
    if board.get("status") != "ok":
        return board
    stats = board.pop("stats_frame", None)
    for week in board["weeks"]:
        slate = nfl_slate(week, stats)
        week["slate"] = slate
        week["parlay_slates"] = [slate]
    board["week_links"] = [{"slug": w["slug"], "week": w["week"]} for w in board["weeks"]]
    return board


def _history_blurb(history: dict) -> str:
    if not history or history.get("status") != "ok":
        return "UFC history mirror: unavailable. Timing rates and Elo are not filled in."
    metrics = history.get("elo_metrics") or {}
    label = _elo_label(history)
    if not metrics.get("n_fights"):
        return f"UFC history: {history['source']}, {history['n_fights']} fights, {history['date_min']} to {history['date_max']}."
    return (
        f"UFC history: {history['source']}, {history['n_fights']} fights, {history['date_min']} to {history['date_max']}. "
        f"{label}. Walk-forward log loss {metrics['elo_log_loss']:.4f} vs coin flip {metrics['coin_log_loss']:.4f} "
        f"on {metrics['n_fights']} scored fights."
    )


def write_site(out: Path, events: list[dict], board: dict, history: dict, built_at: datetime) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    (out / "ufc").mkdir()
    (out / "nfl").mkdir()
    shutil.copy(STATIC / "site.css", out / "assets" / "site.css")
    shutil.copy(STATIC / "parlay.js", out / "assets" / "parlay.js")
    slates = []
    for event in events:
        slate = event.get("slate")
        if slate and slate.get("groups"):
            slates.append(slate)
            break
    default = slates[0]["id"] if slates else ""
    board = dict(board)
    board["history_blurb"] = _history_blurb(history)
    (out / "index.html").write_text(render_home(events, board, built_at, slates, default), encoding="utf-8")
    siblings = [{"slug": e["slug"], "headline": e.get("headline") or e.get("name")} for e in events if e.get("slug")]
    for event in events:
        if not event.get("slug"):
            continue
        html = render_ufc(event, history, built_at, siblings)
        (out / "ufc" / f"{event['slug']}.html").write_text(html, encoding="utf-8")
    if board.get("status") == "ok":
        for week in board["weeks"]:
            html = render_nfl(week, built_at, board)
            (out / "nfl" / f"{week['slug']}.html").write_text(html, encoding="utf-8")
    summary = {
        "built_at": built_at.isoformat(),
        "ufc_events": [
            {"slug": e.get("slug"), "status": e.get("status"), "fights": len(e.get("fights") or []), "error": e.get("error")}
            for e in events
        ],
        "nfl_status": board.get("status"),
        "nfl_weeks": [w["week"] for w in board.get("weeks") or []],
        "history_status": (history or {}).get("status"),
        "history_error": (history or {}).get("error"),
    }
    (out / "assets" / "build.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


def build(out: Path, delay: float = 2.5, refresh_nfl: bool = True, refresh_history: bool = False) -> dict:
    try:
        from dfs_intel.ufc_history import load_mirror
        history = load_mirror(refresh=refresh_history)
    except Exception as exc:
        history = {"status": "unavailable", "error": str(exc), "timing": None}
    from dfs_intel.gapodds import fetch_props
    from dfs_intel.method_split import build_split_table
    from dfs_intel.slip_data import ufc_slate
    gap = fetch_props(delay=2.0)
    with PageFetcher(delay=delay) as client:
        events, ufc_error = build_ufc(client, history)
    fights = history.get("fights") if history and history.get("status") == "ok" else None
    table = build_split_table(fights) if fights is not None else None
    for event in events:
        if event.get("status") == "ok" and event.get("slug"):
            slate = ufc_slate(event, table, fights, gap)
            event["slate"] = slate
            event["parlay_slates"] = [slate]
    if ufc_error and not events:
        events = [{"status": "unavailable", "slug": None, "headline": "UFC events", "error": ufc_error, "fights": [], "parlay_slates": []}]
    try:
        board = build_nfl(refresh=refresh_nfl)
    except Exception as exc:
        board = {"status": "unavailable", "error": str(exc), "weeks": []}
    built_at = _now()
    write_site(out, events, board, history, built_at)
    fights = sum(len(e.get("fights") or []) for e in events if e.get("status") == "ok")
    weeks = [w["week"] for w in board.get("weeks") or []]
    return {
        "ufc_events": len([e for e in events if e.get("status") == "ok"]),
        "ufc_fights": fights,
        "nfl_weeks": weeks,
        "history": history.get("status"),
        "out": str(out),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the dfs-intel research site")
    ap.add_argument("--out", default="site")
    ap.add_argument("--delay", type=float, default=2.5)
    ap.add_argument("--refresh-nfl", action="store_true", default=True)
    ap.add_argument("--no-refresh-nfl", action="store_false", dest="refresh_nfl")
    ap.add_argument("--refresh-history", action="store_true")
    args = ap.parse_args(argv)
    try:
        summary = build(Path(args.out), delay=args.delay, refresh_nfl=args.refresh_nfl, refresh_history=args.refresh_history)
    except Exception:
        traceback.print_exc()
        return 1
    print(json.dumps(summary, indent=1))
    if summary["ufc_fights"] < 1:
        print("no UFC fights were parsed", flush=True)
        return 1
    if 9 not in summary["nfl_weeks"]:
        print("NFL week 9 missing", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
