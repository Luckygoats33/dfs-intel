"""Static HTML for the research desk. Every number carries a kind, source, and as-of time."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")

DISCLAIMER = (
    "Research and entertainment only. This site does not place bets, does not connect to DraftKings, "
    "and is not betting advice. Nothing here is a recommendation. Observed facts, market odds, model "
    "estimates, and inferences are labeled separately. If a source fails, the number is shown as "
    "unavailable rather than filled in."
)

LEGEND = (
    ("observed", "Observed"),
    ("market", "Market"),
    ("derived", "Derived"),
    ("model", "Model"),
    ("inference", "Inference"),
    ("missing", "Missing"),
)


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def fmt_pt(value) -> str:
    if value is None or value == "":
        return "unavailable"
    if isinstance(value, (int, float)):
        moment = datetime.fromtimestamp(value, timezone.utc)
    elif isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    else:
        text = str(value).replace("Z", "+00:00")
        moment = datetime.fromisoformat(text)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(PT)
    clock = local.strftime("%I:%M %p").lstrip("0")
    return f"{local.strftime('%a %b')} {local.day}, {local.year}, {clock} PT"


def pct(value) -> str:
    if value is None:
        return "unavailable"
    return f"{value * 100:.1f}%"


def chip(kind: str) -> str:
    label = dict(LEGEND).get(kind, kind)
    return f'<span class="chip chip-{esc(kind)}">{esc(label)}</span>'


def fig(display, kind: str, source: str, asof, title: str | None = None) -> str:
    shown = "unavailable" if display is None or display == "" else display
    miss = shown == "unavailable"
    kind = "missing" if miss else kind
    body = f'<b class="miss">unavailable</b>' if miss else f"<b>{esc(shown)}</b>"
    note = f'{esc(kind)} · {esc(source)} · {esc(fmt_pt(asof))}'
    extra = f' title="{esc(title)}"' if title else ""
    return f'<span class="fig"{extra}>{body}<i class="src">{note}</i></span>'


def legend() -> str:
    return '<div class="legend" aria-label="How numbers are labeled">' + "".join(chip(k) for k, _name in LEGEND) + "</div>"


def shell(title: str, depth: int, body: str, built_at, parlay: dict | None) -> str:
    root = "../" * depth
    data = ""
    script = ""
    if parlay is not None:
        raw = json.dumps(parlay, ensure_ascii=False).replace("<", "\\u003c")
        data = f'<script type="application/json" id="parlay-data">{raw}</script>'
        script = f'<script src="{root}assets/parlay.js"></script>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · dfs-intel</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@560;700&family=Barlow:wght@400;560;700&family=IBM+Plex+Mono:wght@400;560&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{root}assets/site.css">
</head>
<body>
<a class="skip" href="#builder-title">Skip to parlay builder</a>
<header class="mast">
  <a class="brand" href="{root}index.html">dfs-intel<small>Research desk · not a sportsbook</small></a>
  <div class="asof">Built {esc(fmt_pt(built_at))}<br>Times shown in America/Los_Angeles.</div>
</header>
<p class="disclaimer"><strong>Disclaimer.</strong> {esc(DISCLAIMER)}</p>
<main class="wrap">
{body}
</main>
<footer class="site">
<p>{esc(DISCLAIMER)}</p>
<p>Sources are named next to each number. UFC history is the GitHub mirror Greco1899/scrape_ufc_stats, not a live UFCStats pull. NFL numbers are nflverse via nflreadpy. DraftKings, NFL.com, and Sports Reference are not fetched.</p>
</footer>
{data}
{script}
</body>
</html>
"""


def builder_mount() -> str:
    return """
<section class="builder" aria-label="Parlay builder">
  <div class="board">
    <div class="board-head">
      <h2 id="builder-title">Parlay builder</h2>
      <p class="fine" data-market-note></p>
    </div>
    <div class="mode" role="tablist" aria-label="Builder mode">
      <button type="button" role="tab" id="mode-results" aria-selected="true">Results</button>
      <button type="button" role="tab" id="mode-manual" aria-selected="false">Build your own</button>
    </div>
    <div data-results-panel>
      <div class="filters" aria-label="Parlay filters">
        <div class="filter-row">
          <label>Min payout on $1 <input data-min-pay type="number" min="1" step="1" value="50"></label>
          <label>Max payout on $1 <input data-max-pay type="number" min="1" step="1" placeholder="No max"></label>
          <label>Legs <input data-min-legs type="number" min="2" max="8" value="2">–<input data-max-legs type="number" min="2" max="8" value="5"></label>
          <label>Min leg chance <input data-min-p type="range" min="0" max="40" value="2"><output data-min-p-out>2%</output></label>
          <label>Min edge <input data-min-edge type="range" min="0" max="20" value="0"><output data-min-edge-out>0</output></label>
        </div>
        <div class="chips" role="group" aria-label="Style">
          <button type="button" data-style="any" aria-pressed="true">Any price</button>
          <button type="button" data-style="fav" aria-pressed="false">Favorites</button>
          <button type="button" data-style="dog" aria-pressed="false">Underdogs</button>
          <button type="button" data-style="mixed" aria-pressed="false">Mixed</button>
        </div>
        <div class="chips" data-type-chips role="group" aria-label="Leg types"></div>
        <div class="chips" data-event-chips role="group" aria-label="Fights and games"></div>
        <div class="filter-row">
          <label>Include <input data-include type="search" placeholder="Names, comma separated"></label>
          <label>Exclude <input data-exclude type="search" placeholder="Leave these out"></label>
          <button type="button" class="switch" role="switch" aria-checked="false" data-market-only><span class="switch-ui" aria-hidden="true"></span>Market price only</button>
          <button type="button" class="switch" role="switch" aria-checked="false" data-same><span class="switch-ui" aria-hidden="true"></span>Allow same fight or game</button>
          <label>Sort
            <select data-sort>
              <option value="chance">Highest chance</option>
              <option value="payout">Highest payout</option>
              <option value="edge">Best edge</option>
              <option value="legs">Fewest legs</option>
            </select>
          </label>
        </div>
      </div>
      <div class="random-box">
        <button type="button" class="random-go" data-random>Random pick</button>
        <p class="fine">A fresh ticket at +5000 or longer, from the legs these filters allow. Sampling leans toward higher model probability and a positive edge.</p>
        <div data-random-card></div>
        <div class="history-row" data-random-history aria-label="Last five random picks"></div>
      </div>
      <p class="fine" data-result-count></p>
      <div class="result-list" data-results></div>
    </div>
    <div data-manual-panel hidden>
      <div class="tabs" role="tablist" aria-label="Prop type" data-tabs></div>
      <div class="board-tools">
        <label class="search">Search
          <input type="search" data-search placeholder="Fighter, player, or bet" autocomplete="off">
        </label>
      </div>
      <div class="leg-list" data-board></div>
    </div>
    <p class="empty" data-empty hidden>No parlays match these filters.</p>
  </div>
  <aside class="slip" id="slip" aria-label="Bet slip">
    <button type="button" class="slip-peek" data-peek aria-expanded="false" aria-controls="slip-body">
      <span data-peek-count>Slip · 0 legs</span>
      <span data-peek-pay>Add a leg</span>
    </button>
    <div id="slip-body" class="slip-body">
      <header class="slip-head">
        <h2>Slip</h2>
        <button type="button" class="textish" data-clear>Clear</button>
      </header>
      <div class="slip-stake">
        <label>Stake
          <span class="stake-wrap"><span aria-hidden="true">$</span><input data-stake type="number" min="0" step="1" value="1" inputmode="decimal"></span>
        </label>
        <div class="chips" role="group" aria-label="Quick stake">
          <button type="button" data-chip="1" aria-pressed="true">$1</button>
          <button type="button" data-chip="5" aria-pressed="false">$5</button>
          <button type="button" data-chip="10" aria-pressed="false">$10</button>
        </div>
      </div>
      <ul class="slip-legs" data-slip-legs></ul>
      <p class="warn" data-slip-warn hidden></p>
      <dl class="slip-nums" data-slip-nums></dl>
      <p class="fine" data-slip-note></p>
      <button type="button" class="share" data-share>Copy slip link</button>
      <p class="copied" data-copied hidden>Link copied.</p>
      <p class="sr-only" aria-live="polite" data-live></p>
    </div>
  </aside>
</section>
"""


def parlay_payload(slates: list[dict], default: str) -> dict:
    return {"slates": slates, "default": default}


def render_timing(timing: dict | None, history: dict) -> str:
    if not history or history.get("status") != "ok" or not timing or not timing.get("overall"):
        err = (history or {}).get("error") or "mirror unavailable"
        return f"<h2>Fight-end timing</h2><p class='miss'>unavailable</p><p class='fine'>{esc(err)}</p>"
    src = history["source"]
    asof = history["observed_at"]
    window = f"{history.get('date_min')} to {history.get('date_max')}"
    overall = timing["overall"]

    def cells(block):
        out = []
        for key, label in timing["labels"].items():
            item = block[key]
            rate = None if item["rate"] is None else f"{item['rate'] * 100:.2f}%"
            count = f"{item['count']}/{item['n']}"
            out.append(
                "<tr>"
                f"<td>{esc(label)}</td>"
                f"<td>{fig(count, 'observed', src, asof)}</td>"
                f"<td>{fig(rate, 'observed', src, asof)}</td>"
                f"<td>{fig(item['fair_american'], 'derived', 'no-vig price of the observed rate', asof, timing['definition'])}</td>"
                "</tr>"
            )
        return "".join(out)

    def split_table(rows, key):
        body = []
        for row in rows:
            bits = []
            for flag in timing["labels"]:
                item = row[flag]
                bits.append(f"{item['count']}/{item['n']} ({item['rate'] * 100:.2f}%)" if item["rate"] is not None else "unavailable")
            body.append(
                "<tr>"
                f"<td>{esc(row.get(key) or 'unknown')}</td>"
                f"<td>{fig(row['n_fights'], 'observed', src, asof)}</td>"
                f"<td>{fig(bits[0], 'observed', src, asof)}</td>"
                f"<td>{fig(bits[1], 'observed', src, asof)}</td>"
                f"<td>{fig(bits[2], 'observed', src, asof)}</td>"
                "</tr>"
            )
        return (
            "<div class='scroll'><table><thead><tr><th></th><th>Fights</th><th>R1 ≤60s</th><th>Any round ≤60s</th><th>Last 10s</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>"
        )

    small = [r for r in timing["by_weight_class"] if r["n_fights"] < 10]
    main = [r for r in timing["by_weight_class"] if r["n_fights"] >= 10]
    metrics = history.get("elo_metrics") or {}
    elo_box = ""
    if metrics.get("n_fights"):
        from dfs_intel.ufc_history import elo_label
        gap = metrics["coin_log_loss"] - metrics["elo_log_loss"]
        verdict = "beats a coin flip on this slice" if metrics.get("beats_coin") else "does not beat a coin flip on this slice"
        barely = " The edge is small." if metrics.get("beats_coin") and gap < 0.02 else ""
        label = elo_label(metrics)
        elo_box = (
            f"<h3>{esc(label)}</h3>"
            f"<p>{fig(f'{metrics["elo_log_loss"]:.4f}', 'model', 'walk-forward Elo on the mirror', asof)} "
            f"log loss vs {fig(f'{metrics["coin_log_loss"]:.4f}', 'model', '50/50', asof)} for a coin flip. "
            f"Brier {fig(f'{metrics["elo_brier"]:.4f}', 'model', 'walk-forward Elo on the mirror', asof)} vs "
            f"{fig(f'{metrics["coin_brier"]:.4f}', 'model', '50/50', asof)}. "
            f"Scored fights: {fig(metrics['n_fights'], 'observed', src, asof)}. The model {esc(verdict)}.{esc(barely)} "
            f"{esc(metrics.get('note') or '')}</p>"
        )
    return f"""
<h2>Fight-end timing</h2>
<p class="fine">Observed historical frequencies, not predictions. Window {esc(window)}, {fig(history['n_fights'], 'observed', src, asof)} fights. {esc(timing['definition'])}</p>
<div class="scroll"><table>
<thead><tr><th>Event</th><th>Count</th><th>Rate</th><th>Fair American</th></tr></thead>
<tbody>{cells(overall)}</tbody>
</table></div>
<h3>3 rounds vs 5 rounds</h3>
{split_table(timing['by_format'], 'format')}
<h3>By weight class</h3>
<p class="fine">Classes with at least 10 fights in the window. Smaller classes are listed under the fold because the rates are mostly noise.</p>
{split_table(main, 'weight_class')}
<details><summary>{len(small)} weight classes with fewer than 10 fights</summary>
{split_table(small, 'weight_class') if small else '<p>None.</p>'}
</details>
{elo_box}
"""


def _fighter_side(side: dict, source_odds: str, odds_asof, history_source: str, history_asof) -> str:
    timing = side.get("timing") or {}
    if timing.get("status") == "matched" and timing.get("matches"):
        row = timing["matches"][0]
        bits = []
        for key, short in (("finish_r1_le60", "R1≤60"), ("finish_any_rnd_le60", "any≤60"), ("finish_last10", "last10")):
            bits.append(f"{short} {row[key]} ({row[key + '_won']} won)")
        timing_fig = fig("; ".join(bits) + f" in {row['n_fights']} fights", "observed", history_source, history_asof)
    elif timing.get("status") == "ambiguous":
        names = ", ".join(m["fighter"] for m in timing.get("matches") or [])
        timing_fig = fig(None, "missing", history_source, history_asof, f"ambiguous mirror names: {names}")
    elif timing.get("status") == "none":
        timing_fig = fig("none in mirror", "observed", history_source, history_asof, "No 2022+ mirror fight under this normalized name.")
    else:
        timing_fig = fig(None, "missing", history_source or "mirror", history_asof)
    elo = side.get("elo")
    if elo and elo.get("status") == "number":
        elo_fig = fig(f"{elo['rating']:.0f}", "model", "elo-baseline-v0", history_asof, elo.get("note"))
    elif elo and elo.get("status") == "prior":
        elo_fig = fig("1500 prior", "model", "elo-baseline-v0 cold start", history_asof, elo.get("note"))
    elif elo and elo.get("status") == "ambiguous":
        elo_fig = fig(None, "missing", "elo-baseline-v0", history_asof, elo.get("note"))
    else:
        elo_fig = fig(None, "missing", "elo-baseline-v0", history_asof)
    weight = side.get("weight")
    if weight and weight.get("lb") is not None:
        mark = "*" if weight.get("mark") else ""
        weight_fig = fig(f"{weight['lb']:g} lb{mark}", "observed", weight.get("source") or "UFC.com weigh-in", weight.get("asof") or odds_asof)
    else:
        weight_fig = fig(None, "missing", "UFC.com weigh-in", odds_asof)
    bio = side.get("bio") or {}
    if bio.get("status") == "matched":
        b = bio["bio"]
        bio_bits = ", ".join(x for x in [b.get("height"), b.get("reach") and f"reach {b['reach']}", b.get("stance"), b.get("dob") and f"DOB {b['dob']}"] if x)
        bio_fig = fig(bio_bits or "record present, fields blank", "observed", history_source, history_asof)
    elif bio.get("status") == "ambiguous":
        bio_fig = fig(None, "missing", history_source, history_asof, "more than one mirror bio")
    elif bio.get("status") == "none":
        bio_fig = fig("none in mirror", "observed", history_source, history_asof)
    else:
        bio_fig = fig(None, "missing", history_source or "mirror", history_asof)
    return (
        f"<td>{esc(side.get('name'))}<br><span class='fine'>{esc(side.get('country') or '')}</span></td>"
        f"<td>{fig(side.get('american_fmt'), 'market', source_odds, odds_asof)}</td>"
        f"<td>{fig(pct(side.get('novig')) if side.get('novig') is not None else None, 'derived', 'no-vig from the two moneylines', odds_asof)}</td>"
        f"<td>{weight_fig}</td><td>{elo_fig}</td><td>{timing_fig}</td><td>{bio_fig}</td>"
    )


def render_ufc(event: dict, history: dict, built_at, siblings: list[dict]) -> str:
    if event.get("status") != "ok":
        body = f"<h1>{esc(event.get('headline') or event.get('slug'))}</h1><p class='miss'>unavailable</p><p>{esc(event.get('error') or 'UFC.com event page failed')}</p>"
        return shell(event.get("headline") or "UFC", 1, body, built_at, None)
    odds_asof = event["observed_at"]
    src = event["url"]
    hist_src = (history or {}).get("source") or "mirror"
    hist_asof = (history or {}).get("observed_at")
    rows = []
    detail_rows = []
    for fight in event["fights"]:
        klass = "invalid" if fight.get("odds_valid") is False and fight.get("ml_red") is not None else ""
        rounds = fight.get("rounds") or {}
        rfig = fig(rounds.get("value"), rounds.get("kind") or "missing", rounds.get("source") or "UFC.com event page", rounds.get("asof") or odds_asof, rounds.get("note"))
        over = pct(fight["overround"]) if fight.get("overround") is not None else None
        rows.append(
            f"<tr class='{klass}'><td>{esc(fight.get('card'))} {esc(fight.get('order') or '')}</td>"
            f"<td>{esc(fight['red']['name'])} vs {esc(fight['blue']['name'])}</td>"
            f"<td>{fig(fight.get('weight_class') or None, 'observed', src, odds_asof)}</td>"
            f"<td>{rfig}</td>"
            f"<td>{fig(over, 'derived', 'sum of vigged implied probabilities minus 1', odds_asof, fight.get('odds_note') or '')}</td>"
            "</tr>"
        )
        detail_rows.append("<tr class='%s'>%s</tr>" % (klass, _fighter_side(fight["red"], src, odds_asof, hist_src, hist_asof)))
        detail_rows.append("<tr class='%s'>%s</tr>" % (klass, _fighter_side(fight["blue"], src, odds_asof, hist_src, hist_asof)))
    news = []
    for art in event.get("articles") or []:
        if art.get("status") != "ok":
            news.append(f"<li><a href='{esc(art.get('url'))}'>{esc(art.get('url'))}</a> — <span class='miss'>unavailable</span> {esc(art.get('error') or '')}</li>")
            continue
        bits = [f"<li><a href='{esc(art['url'])}'>{esc(art.get('title') or art['url'])}</a> <span class='fine'>{esc(art.get('credit') or '')}</span>"]
        if art.get("kind") == "weigh-in" and not art.get("weights"):
            bits.append("<br><span class='miss'>Weigh-in numbers unavailable in the article body.</span>")
        for sent in art.get("change_sentences") or []:
            bits.append(f"<br>{fig(sent, 'observed', art['url'], odds_asof)}")
        if art.get("rounds"):
            quote = ". ".join(x for x in [art["rounds"].get("main_event_quote"), art["rounds"].get("other_bouts_quote")] if x)
            if quote:
                bits.append(f"<br>{fig(quote, 'observed', art['url'], odds_asof)}")
        if not art.get("change_sentences") and not art.get("rounds") and art.get("kind") != "weigh-in":
            bits.append("<br><span class='fine'>No late-change sentence matched. The link is the source; the article is not copied here.</span>")
        bits.append("</li>")
        news.append("".join(bits))
    if not news:
        news.append("<li>No weigh-in or late-change article on the UFC.com news index matched this event at build time. That is an absence on the index, not a claim that nothing changed.</li>")
    times = []
    for label, key in (("Early prelims", "early"), ("Prelims", "prelims"), ("Main card", "main")):
        block = (event.get("times") or {}).get(key) or {}
        if block.get("ts"):
            shown, note = fmt_pt(block["ts"]), "Card start published on the event page."
        elif block.get("text"):
            shown, note = block["text"], "Card start text published on the event page."
        else:
            shown, note = "not listed", "UFC.com did not publish this card time."
        times.append(f"<li>{esc(label)}: {fig(shown, 'observed', src, odds_asof, note)}</li>")
    links = " · ".join(f'<a href="{esc(s["slug"])}.html">{esc(s["headline"])}</a>' for s in siblings if s["slug"] != event["slug"])
    body = f"""
<p class="kicker ufc">UFC · public event page</p>
<h1>{esc(event.get('name') or event.get('headline'))}</h1>
<p class="lede">{fig(event.get('venue') or event.get('location'), 'observed', src, odds_asof)}</p>
{legend()}
{builder_mount()}
<p class="fine">This page does not add handwritten fight leans. {chip('inference')} is unused here on purpose. Invalid moneylines (overround above 15%) stay visible and are left out of the parlay builder. Same-fight props use the joint from method-split-v0. A clock-time leg cut by a narrower method is left unidentified instead of multiplied.</p>
<ul>{''.join(times)}</ul>
<p class="fine">Broadcaster text on the page: {esc(event.get('broadcaster') or 'not stated')}.</p>
<h2>News, weigh-ins, late changes</h2>
<ul>{''.join(news)}</ul>
<h2>Fight table</h2>
<div class="scroll"><table>
<thead><tr><th>Card</th><th>Bout</th><th>Class</th><th>Rounds</th><th>Overround</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="5">UFC.com did not list any fights on this event page at the as-of time.</td></tr>'}</tbody>
</table></div>
<h2>Odds, Elo, timing counts</h2>
<p class="fine">Elo is {esc(event.get('elo_label') or 'elo-baseline-v0')}. A 1500 prior is the cold start for someone with no decisive fight in the mirror window, not a measured rating. Timing cells are that fighter’s own counts in the mirror window: total finishes (finishes they won).</p>
<div class="scroll"><table>
<thead><tr><th>Fighter</th><th>Moneyline</th><th>No-vig</th><th>Weigh-in</th><th>Elo</th><th>Own timing counts</th><th>Mirror bio</th></tr></thead>
<tbody>{''.join(detail_rows)}</tbody>
</table></div>
{render_timing((history or {}).get('timing'), history)}
<p class="navrow"><a href="../index.html">All events</a><span>{links}</span></p>
"""
    slate = event.get("slate")
    payload = parlay_payload([slate] if slate else [], event.get("slug") or "")
    return shell(event.get("name") or "UFC", 1, body, built_at, payload)


def _score_fig(game: dict, source: str, asof) -> str:
    status = game.get("score_status")
    if status == "final":
        return fig(f"{game['away_score']}-{game['home_score']}", "observed", source, asof, "final")
    if status == "not_played":
        return fig("not played", "observed", source, asof, "nflverse has no score yet")
    return fig(None, "missing", source, asof, status or "score missing")


def render_nfl(week: dict, built_at, board: dict) -> str:
    src_sched = board.get("source_schedule") or "nflverse:schedules"
    src_stats = board.get("source_stats") or "nflverse:player_stats"
    sched_asof = week.get("schedule_observed_at")
    stats_asof = week.get("stats_observed_at")
    games = []
    for game in week["games"]:
        priced = game.get("priced") or {}
        games.append(
            "<tr>"
            f"<td>{fig(fmt_pt(game.get('kickoff_pt')) if game.get('kickoff_pt') else None, 'observed', src_sched + ' kickoff (gametime treated as America/New_York)', sched_asof)}</td>"
            f"<td>{esc(game['away'])} at {esc(game['home'])}</td>"
            f"<td>{_score_fig(game, src_sched, sched_asof)}</td>"
            f"<td>{fig(game.get('away_moneyline_american'), 'market', src_sched + ' away_moneyline (book not named)', sched_asof)}</td>"
            f"<td>{fig(game.get('home_moneyline_american'), 'market', src_sched + ' home_moneyline (book not named)', sched_asof)}</td>"
            f"<td>{fig(pct(priced.get('novig_away')) if priced.get('novig_away') is not None else None, 'derived', 'no-vig from the two moneylines', sched_asof)} / {fig(pct(priced.get('novig_home')) if priced.get('novig_home') is not None else None, 'derived', 'no-vig from the two moneylines', sched_asof)}</td>"
            f"<td>{fig(None if game.get('spread_line') is None else f'{game["spread_line"]:+.1f} home', 'market', src_sched + ' spread_line (book not named)', sched_asof)}</td>"
            f"<td>{fig(None if game.get('total_line') is None else f'{game["total_line"]:.1f}', 'market', src_sched + ' total_line (book not named)', sched_asof)}</td>"
            "</tr>"
        )
    pos_blocks = []
    if week.get("projections_status") != "ok":
        pos_blocks.append("<p class='miss'>Projections unavailable.</p>")
    else:
        for pos, rows in (week.get("top") or {}).items():
            body_rows = []
            for row in rows:
                window = f"{row['from_season']} W{row['from_week']}–{row['through_season']} W{row['through_week']}"
                body_rows.append(
                    "<tr>"
                    f"<td>{esc(row['player'])}</td><td>{esc(row['team'])}</td><td>{esc(row.get('opponent') or '')}</td>"
                    f"<td>{fig(f'{row["dk_avg"]:.2f}', 'model', board.get('model') or 'trailing-average-v0', stats_asof, 'DK Classic offense rules in dfs_intel, applied to nflverse weekly stats. Not a DraftKings projection.')}</td>"
                    f"<td>{fig(row['games'], 'observed', src_stats, stats_asof, window)}</td>"
                    "</tr>"
                )
            pos_blocks.append(
                f"<h3>{esc(pos)}</h3><div class='scroll'><table><thead><tr><th>Player</th><th>Team</th><th>Opp</th><th>Trailing DK avg</th><th>Games in avg</th></tr></thead>"
                f"<tbody>{''.join(body_rows) or '<tr><td colspan=5>None.</td></tr>'}</tbody></table></div>"
            )
    others = board.get("week_links") or []
    nav = " · ".join(f'<a href="{esc(item["slug"])}.html">W{item["week"]}</a>' for item in others)
    body = f"""
<p class="kicker nfl">NFL · {esc(week['season'])} week {esc(week['week'])} · {esc(week['state'])}</p>
<h1>Week {esc(week['week'])}</h1>
<p class="lede">First kickoff {fig(fmt_pt(week.get('first_kickoff_pt')) if week.get('first_kickoff_pt') else None, 'observed', src_sched, sched_asof)}. Last kickoff {fig(fmt_pt(week.get('last_kickoff_pt')) if week.get('last_kickoff_pt') else None, 'observed', src_sched, sched_asof)}.</p>
{legend()}
{builder_mount()}
<p class="fine">This page does not add handwritten leans. {chip('inference')} is unused. Moneylines are whatever nflverse publishes in the schedule file; the book is not named there. Player props are {esc('trail-quantile-v0')}: the share of that player's previous regular-season games over or under a line you set. The line starts at the trailing mean, rounded to a half-point. There is no licensed prop feed, so a blank market price means the line is yours. Same-game props are correlated; the slip says so and still multiplies them. Trailing DK averages are {esc(week.get('model'))}, last {esc(week.get('trail_games'))} regular-season games before this week. {esc(week.get('roster_note') or '')} Players on the active roster with no prior line in the stat window: {fig(week.get('missing_history'), 'observed', board.get('source_rosters') or 'nflverse:rosters_weekly', week.get('roster_observed_at'))}. {esc(week.get('dst_note') or '')}</p>
<h2>Games</h2>
<div class="scroll"><table>
<thead><tr><th>Kickoff</th><th>Game</th><th>Score</th><th>Away ML</th><th>Home ML</th><th>No-vig away/home</th><th>Home spread</th><th>Total</th></tr></thead>
<tbody>{''.join(games)}</tbody>
</table></div>
<h2>Top trailing-average projections by position</h2>
<p class="fine">Baseline only. Salaries are not loaded, so this is not a lineup. Listed QB on the schedule, when nflverse has one: see the game feed in the source file; it is not repeated as a projection.</p>
{''.join(pos_blocks)}
<p class="navrow"><a href="../index.html">All weeks</a><span>{nav}</span></p>
"""
    slate = week.get("slate")
    return shell(f"NFL {week['season']} week {week['week']}", 1, body, built_at, parlay_payload([slate] if slate else [], week["slug"]))


def render_home(events: list[dict], board: dict, built_at, parlay_slates: list[dict], default_slate: str) -> str:
    ufc_cards = []
    for event in events:
        if event.get("status") != "ok":
            ufc_cards.append(
                f"<article class='card'><p class='kicker ufc'>UFC</p><h3>{esc(event.get('headline') or event.get('slug'))}</h3>"
                f"<p class='miss'>unavailable</p><p class='fine'>{esc(event.get('error') or '')}</p></article>"
            )
            continue
        n = len(event.get("fights") or [])
        priced = sum(1 for f in event["fights"] if f.get("odds_valid"))
        when = (event.get("times") or {}).get("main") or {}
        ufc_cards.append(
            "<article class='card'><a class='block' href='ufc/{slug}.html'><p class='kicker ufc'>UFC</p>"
            "<p class='when'>{when}</p><h3>{name}</h3>"
            "<p>{where}</p><p class='fine'>{n} fights on the page · {priced} with valid moneylines · odds as of {asof}</p>"
            "</a></article>".format(
                slug=esc(event["slug"]),
                when=esc(fmt_pt(when.get("ts")) if when.get("ts") else "time unavailable"),
                name=esc(event.get("name") or event.get("headline")),
                where=esc(event.get("venue") or event.get("location") or ""),
                n=n,
                priced=priced,
                asof=esc(fmt_pt(event.get("observed_at"))),
            )
        )
    weeks = []
    if board.get("status") != "ok":
        weeks.append(f"<article class='card'><p class='miss'>NFL unavailable</p><p>{esc(board.get('error') or '')}</p></article>")
    else:
        order = {"in_progress": 0, "upcoming": 1, "final": 2}
        for week in sorted(board["weeks"], key=lambda w: (order.get(w["state"], 9), w["week"])):
            weeks.append(
                "<article class='card'><a class='block' href='nfl/{slug}.html'><p class='kicker nfl'>{season} week {week} · {state}</p>"
                "<p class='when'>{when}</p><p class='fine'>{games} games</p></a></article>".format(
                    slug=esc(week["slug"]),
                    season=esc(week["season"]),
                    week=esc(week["week"]),
                    state=esc(week["state"]),
                    when=esc(fmt_pt(week.get("first_kickoff_pt")) if week.get("first_kickoff_pt") else "kickoff unavailable"),
                    games=len(week["games"]),
                )
            )
    elo = ""
    hist = board.get("history_blurb")
    if hist:
        elo = f"<p class='fine'>{esc(hist)}</p>"
    body = f"""
<h1>Build a slip</h1>
<p class="lede">The next UFC card is loaded in the builder. Other cards and every NFL week are one tap away. Research only. It never places a bet.</p>
{legend()}
{elo}
{builder_mount()}
<div class="grid">
<section><h2>UFC</h2><div class="stack">{''.join(ufc_cards) or '<p>No upcoming events.</p>'}</div></section>
<section><h2>NFL</h2><div class="stack">{''.join(weeks) or '<p>No weeks.</p>'}</div></section>
</div>
"""
    return shell("Research desk", 0, body, built_at, parlay_payload(parlay_slates, default_slate))
