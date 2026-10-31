# dfs-intel — DraftKings DFS research (NFL + UFC)

Research and entertainment only. Nothing in this repo places a bet, and nothing contacts
draftkings.com, NFL.com, or Pro-Football-Reference. DraftKings salary files, when you have
them, are downloaded by hand and dropped in `data/inbox/`.

The public site is a static research desk for every upcoming UFC event and every regular-season
week of the current NFL season. Each number is labeled observed, market, derived, or model, and
carries a source and an America/Los_Angeles as-of time. A failed source is shown as
**unavailable**. The page does not invent a replacement.

## Site

GitHub Pages serves the build produced by `.github/workflows/pages.yml`.

Expected URL, after the workflow has deployed from `main`:

<https://luckygoats33.github.io/dfs-intel/>

The workflow rebuilds the site on every push to `main`, on demand (`workflow_dispatch`), every
six hours, and every two hours on Friday through Monday (UFC weigh-in and fight window, NFL
weekend). Pull requests build the site and upload it as an artifact; they do not deploy.

If the deploy job fails because Pages is not enabled, open the repo on GitHub and click
**Settings → Pages → Build and deployment → Source → GitHub Actions**, then re-run
**Research site**. The workflow’s `GITHUB_TOKEN` cannot flip that setting by itself.

## What each page shows

- **Home** — upcoming UFC events from the public UFC.com events list, and every regular-season
  NFL week in the nflverse schedule.
- **UFC event** — full card (main, prelims, early prelims), UFC.com moneylines, no-vig implied
  probabilities, overround, weigh-in weights and missed-weight lines when a UFC.com article is
  linked from the news index, and scheduled rounds only when UFC.com states them. Elo ratings
  are `elo-baseline-v0` (the walk-forward check on this mirror barely beats 50/50 when that is
  what the numbers say). Timing base rates — first 60s of round 1, first 60s of any round, last
  10s of any round — are historical frequencies by weight class and 3-round vs 5-round, with
  fair American odds and per-fighter counts.
- **NFL week** — games, nflverse moneylines (the book is not named in that file), and top
  trailing-average DraftKings Classic projections by position. The projection is
  `trailing-average-v0`: the mean of up to the last 8 regular-season games before that week,
  scored with the rules in `dfs_intel/dk_scoring_config.py`. DST and kickers are unavailable
  because this refresh does not download play-by-play.
- **Parlay builder** (every page) — pick legs, stake defaults to $1, combined American and
  decimal odds, implied chance under independence (correlation is called out), payout and profit.
  A filter keeps presets that pay $50 or more on a $1 stake (decimal odds ≥ 50). Preset 3-, 5-,
  and 7-leg favorite and longshot parlays are built from the valid moneylines. Quotes with an
  overround above 15% stay visible and are left out of the builder.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m playwright install --with-deps chromium
```

On a machine that already has Google Chrome, the fetcher uses that and you can skip the
Playwright browser download. UFC.com’s CDN rejects a plain HTTP client; the fetcher reads the
public HTML in a headless browser with a descriptive User-Agent and a 2.5s delay. It does not
call ufcstats.com.

## Refresh the site locally

```bash
python -m dfs_intel.site_build --out site
```

Then open `site/index.html`. The command exits non-zero if it could not parse any UFC fight or
if NFL week 9 is missing from the schedule, so a bad build is not treated as a success.

Other flags: `--no-refresh-nfl` reuses the on-disk nflverse cache, `--refresh-history` re-downloads
the UFC mirror CSVs, `--delay 2.5` is the pause between UFC.com requests.

`data/` and `site/` are gitignored. The pipelines rebuild them.

## Pipelines

| Path | What |
|---|---|
| `dfs_intel/storage.py` | Append-only revisioned fact store |
| `dfs_intel/nfl_pipeline.py` | nflverse schedules, weekly player stats, rosters, snap counts, play-by-play |
| `dfs_intel/nfl_board.py` | Week pages: schedule, moneylines, trailing DK averages |
| `dfs_intel/ufc_pipeline.py` | `mirror` loads Greco1899/scrape_ufc_stats. `scrape` is the polite UFCStats crawler and stays stopped when robots or the site blocks it |
| `dfs_intel/ufc_history.py` | Timing rates and Elo from the mirror only |
| `dfs_intel/ufc_public.py` | UFC.com events, cards, moneylines, weigh-in articles |
| `dfs_intel/ufc_timing.py` | Fight-end flags and fair odds |
| `dfs_intel/site_build.py` | Writes the static site |
| `dfs_intel/dk_scoring_config.py` | DK rule values and the `UNCERTAIN_*` lists. DK’s site is not fetched |
| `scripts/ufc_refresh_odds_news.py` | Earlier one-card refresh. The site build replaces it for ongoing use |

```bash
python -m dfs_intel.nfl_pipeline --seasons 2021-2026
python -m dfs_intel.ufc_pipeline mirror --since 2022-01-01
python -m dfs_intel.nfl_dk
python -m dfs_intel.evaluate
pytest -q
```

## Sources the site will not touch

DraftKings, NFL.com, Pro-Football-Reference, Sports Reference, paid APIs, and undocumented
endpoints. UFCStats.com blocks automated clients; this project does not try to get around that.
UFC history is tagged `ufcstats_via_github:Greco1899/scrape_ufc_stats`.

## Leakage semantics

`effective_at <= as_of` always. Historical backfill was observed in 2026, so `mode="backtest"`
ignores `observed_at` but uses the first-observed revision; `mode="strict"` also requires
`observed_at <= as_of`. NFL trailing averages on the site use only regular-season games before
the target week. UFC Elo and timing counts use the mirror window, which ends at the mirror’s
last event, not at the upcoming card.
