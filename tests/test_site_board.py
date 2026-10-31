import pandas as pd

from dfs_intel.nfl_board import trailing_averages
from dfs_intel.odds_math import combine_parlay, implied_prob, no_vig, preset_parlays, to_decimal
from dfs_intel.site_render import DISCLAIMER, render_ufc
from dfs_intel.ufc_public import parse_american, parse_article, parse_event_page, parse_events_list


def test_no_vig_matches_oct31_chalk():
    # Szabova -750 / Lisboa +525 -> about 84.7% / 15.3% in the Oct 31 note.
    pa, pb, over = no_vig(-750, 525)
    assert round(pa, 3) == 0.847
    assert round(pb, 3) == 0.153
    assert 0.03 < over < 0.06
    both_minus = no_vig(-105, -115)
    assert both_minus[2] < 0.15


def test_parlay_product_and_fifty_dollar_filter():
    legs = [
        {"decimal": to_decimal(500), "novig": implied_prob(500)},
        {"decimal": to_decimal(800), "novig": implied_prob(800)},
    ]
    # +500 is 6.0 decimal, +800 is 9.0, product 54. Pays $54 on $1.
    priced = combine_parlay(legs, stake=1)
    assert priced["decimal"] == 54
    assert priced["pays_50_on_1"] is True
    assert priced["payout"] == 54
    assert priced["profit"] == 53
    short = combine_parlay([{"decimal": 3, "novig": 0.3}, {"decimal": 3, "novig": 0.3}], 1)
    assert short["pays_50_on_1"] is False
    assert abs(priced["implied"] - implied_prob(500) * implied_prob(800)) < 1e-12


def test_presets_skip_short_cards_and_pick_extremes():
    def side(leg_id, novig, american):
        return {"id": leg_id, "label": leg_id, "novig": novig, "american": american, "decimal": to_decimal(american)}

    groups = []
    for i, (fav_p, fav_a, dog_a) in enumerate([(0.8, -400, 300), (0.7, -230, 190), (0.6, -150, 130)]):
        groups.append({
            "id": f"g{i}",
            "legs": [side(f"g{i}a", fav_p, fav_a), side(f"g{i}b", 1 - fav_p, dog_a)],
        })
    presets = preset_parlays(groups)
    assert [p["id"] for p in presets] == ["favorite-3", "longshot-3"]
    assert presets[0]["leg_ids"] == ["g0a", "g1a", "g2a"]
    # Lowest no-vig (longest price) first.
    assert presets[1]["leg_ids"] == ["g0b", "g1b", "g2b"]


def test_parse_event_list_and_fight_card():
    html = """
    <div id="events-list-upcoming">
      <article class="c-card-event--result">
        <h3 class="c-card-event--result__headline"><a href="/event/ufc-fight-night-october-31-2026">Moicano vs Nolan</a></h3>
        <div class="c-card-event--result__date" data-main-card="Sun, Nov 1 / 12:00 AM UTC" data-main-card-timestamp="1793491200"
             data-prelims-card="Sat, Oct 31 / 9:00 PM UTC" data-prelims-card-timestamp="1793480400" data-early-card="" data-early-card-timestamp=""></div>
        <div class="c-card-event--result__location"><span class="locality">Las Vegas</span></div>
      </article>
      <article class="c-card-event--result">
        <h3 class="c-card-event--result__headline"><a href="/event/ufc-fight-night-october-31-2026">duplicate</a></h3>
      </article>
    </div>
    <div id="events-list-past">
      <article class="c-card-event--result">
        <h3 class="c-card-event--result__headline"><a href="/event/ufc-333">Volkanovski vs Evloev</a></h3>
      </article>
    </div>
    """
    events = parse_events_list(html)
    assert [e["slug"] for e in events] == ["ufc-fight-night-october-31-2026"]
    assert events[0]["main_ts"] == 1793491200
    assert "Las Vegas" in events[0]["location"]

    card = """
    <h1 class="c-hero__headline-prefix">UFC Fight Night</h1>
    <span class="e-divider__top">Moicano</span><span class="e-divider__bottom">Nolan</span>
    <div class="c-hero__text">Meta APEX, Las Vegas</div>
    <div id="main-card">
      <ul><li class="l-listing__item" data-order="1">
        <div class="c-listing-fight" data-fmid="13133">
          <div class="c-listing-fight__class--desktop"><div class="c-listing-fight__class-text">Lightweight Bout</div></div>
          <div class="c-listing-fight__corner-name--red"><span class="c-listing-fight__corner-given-name">Renato</span><span class="c-listing-fight__corner-family-name">Moicano</span></div>
          <div class="c-listing-fight__corner-name--blue"><span class="c-listing-fight__corner-given-name">Tom</span><span class="c-listing-fight__corner-family-name">Nolan</span></div>
          <div class="c-listing-fight__odds-row">
            <span class="c-listing-fight__odds-amount">-125</span>
            <span class="c-listing-fight__odds-amount">+105</span>
          </div>
          <div class="c-listing-fight__country--red"><div class="c-listing-fight__country-text">Brazil</div></div>
        </div>
      </li></ul>
    </div>
    """
    page = parse_event_page(card, "https://www.ufc.com/event/ufc-fight-night-october-31-2026")
    assert page["fights"][0]["ml_red"] == -125
    assert page["fights"][0]["ml_blue"] == 105
    assert page["fights"][0]["red"]["name"] == "Renato Moicano"
    assert page["fights"][0]["weight_class"] == "Lightweight Bout"
    assert parse_american("−270") == -270


def test_article_extracts_weights_rounds_and_miss_without_copying_the_essay():
    html = """
    <h1>Official Weigh-In Results | UFC Fight Night: Moicano vs Nolan</h1>
    <div class="c-hero__article-credit">By UFC Staff Report • Oct. 30, 2026</div>
    <div class="field--name-body-structured"><div class="field--name-text">
      <p>Main event scheduled for five rounds. All other bouts scheduled for three rounds.</p>
      <h4>Main Event - Lightweight Bout: Renato Moicano (156) vs Tom Nolan (155.5)</h4>
      <h4>Featherweight Bout: Francis Marshall (148)* vs Dakota Hope (145.5)</h4>
      <p>Marshall weighed in above the featherweight limit of 146 pounds. He forfeits 20% of his purse to his opponent.</p>
      <p>Fight fans are in for a treat on Halloween night as the card closes a long month of events in Las Vegas with a five-round main event and a crowded undercard.</p>
    </div></div>
    """
    art = parse_article(html, "https://www.ufc.com/news/official-weigh-results-ufc-fight-night-moicano-vs-nolan")
    assert art["kind"] == "weigh-in"
    assert art["rounds"]["main_event"] == 5
    assert art["rounds"]["other_bouts"] == 3
    assert art["weights"][0]["a_lb"] == 156
    assert art["weights"][1]["a_mark"] is True
    assert any("weighed in above" in s for s in art["change_sentences"])
    assert not any("Fight fans are in for a treat" in s for s in art["change_sentences"])


def test_trailing_average_excludes_the_target_week():
    stats = pd.DataFrame({
        "player_id": ["p1", "p1", "p1"],
        "player_display_name": ["A", "A", "A"],
        "position": ["QB", "QB", "QB"],
        "season": [2026, 2026, 2026],
        "week": [7, 8, 9],
        "season_type": ["REG", "REG", "REG"],
        "dk_points": [10.0, 20.0, 100.0],
    })
    out = trailing_averages(stats, 2026, 9, n=8)
    assert len(out) == 1
    assert out.iloc[0]["games"] == 2
    assert out.iloc[0]["dk_avg"] == 15.0
    assert out.iloc[0]["through_week"] == 8


def test_assembled_card_renders_odds_and_skips_inference():
    from dfs_intel.site_build import assemble_event
    from dfs_intel.ufc_public import parse_event_page

    listing = {"slug": "sample", "headline": "Moicano vs Nolan", "url": "https://www.ufc.com/event/sample", "main_ts": 1793491200}
    page = parse_event_page("""
    <span class="e-divider__top">Moicano</span><span class="e-divider__bottom">Nolan</span>
    <div id="main-card"><ul><li class="l-listing__item" data-order="1"><div class="c-listing-fight">
      <div class="c-listing-fight__class--desktop"><div class="c-listing-fight__class-text">Lightweight Bout</div></div>
      <div class="c-listing-fight__names-row">
        <div class="c-listing-fight__corner-name--red"><a>Renato Moicano</a></div>
        <div class="c-listing-fight__corner-name--blue"><a>Tom Nolan</a></div>
      </div>
      <div class="c-listing-fight__odds-row">
        <span class="c-listing-fight__odds-amount">-125</span>
        <span class="c-listing-fight__odds-amount">+105</span>
      </div>
    </div></li></ul></div>
    """, "https://www.ufc.com/event/sample")
    articles = [{
        "status": "ok", "kind": "weigh-in", "url": "https://www.ufc.com/news/weigh",
        "title": "Weigh-in", "credit": "UFC", "change_sentences": ["Moicano weighed in on the limit."],
        "weights": [{"weight_class": "Lightweight Bout", "a": "Renato Moicano", "a_lb": 156, "a_mark": False, "b": "Tom Nolan", "b_lb": 155.5, "b_mark": False}],
        "rounds": {"main_event": 5, "other_bouts": 3, "main_event_quote": "Main event scheduled for five rounds"},
    }]
    event = assemble_event(listing, page, articles, {"status": "unavailable", "error": "mirror down"}, "2026-10-30T23:00:00+00:00")
    assert event["fights"][0]["rounds"]["value"] == 5
    assert event["fights"][0]["red"]["weight"]["lb"] == 156
    assert event["fights"][0]["odds_valid"] is True
    assert event["fights"][0]["red"]["elo"]["status"] == "unavailable"
    html = render_ufc(event, {"status": "unavailable", "error": "mirror down"}, "2026-10-30T23:00:00+00:00", [])
    assert DISCLAIMER in html
    assert "Renato Moicano" in html
    assert "-125" in html
    assert "inference" in html.lower()


def test_unavailable_event_page_still_carries_the_disclaimer():
    html = render_ufc({"status": "unavailable", "slug": "x", "headline": "Missing", "error": "boom"}, {}, "2026-10-30T20:00:00+00:00", [])
    assert DISCLAIMER in html
    assert "unavailable" in html
    assert "boom" in html
