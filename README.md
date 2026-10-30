# dfs-intel — DraftKings DFS research (NFL + UFC), milestone 1

Research / entertainment decision support only. **Nothing here contacts draftkings.com**; DK files are
downloaded by Will by hand and dropped in `data/inbox/`.

## Setup
    python3 -m venv .venv && . .venv/bin/activate
    pip install duckdb pandas pyarrow nflreadpy polars requests beautifulsoup4 pytest

## Layout
| Path | What |
|---|---|
| `dfs_intel/storage.py` | Append-only revisioned fact store: `data/parquet/<table>/batch_*.parquet` + DuckDB views in `data/dfs.duckdb`. Provenance cols: `source, source_event_id, observed_at, effective_at, revision, row_hash`. `facts_as_of(table, as_of, mode=backtest|strict)` |
| `dfs_intel/nfl_pipeline.py` | nflverse schedules, weekly player stats, weekly rosters, snap counts, pbp. Raw cache `data/raw_cache/nflverse/` |
| `dfs_intel/ufc_pipeline.py` | `scrape` = polite direct UFCStats crawler (cached, resumable, robots-aware); `mirror` = UFCStats data via public GitHub CSVs |
| `dfs_intel/dk_scoring_config.py` | **every** DK rule value + source comments + `UNCERTAIN_*` lists |
| `dfs_intel/scoring.py` | pure scoring functions |
| `dfs_intel/nfl_dk.py` | DK points table (`nfl_dk_points`, offense + DST from pbp) and validation vs nflverse PPR |
| `dfs_intel/slate_import.py` | DK salary CSV parser + ID matching + unmatched report; contest-standings stub |
| `dfs_intel/evaluate.py` | walk-forward baselines + metrics (pinball, CRPS, log loss, Brier, calibration) |
| `data/results/` | `nfl_scoring_validation.json`, `walkforward_baselines.json`, `unmatched_<slate>.csv` |
| `examples/` | **SYNTHETIC** example salary CSVs (invented, for tests) |

## Commands
    python -m dfs_intel.nfl_pipeline --seasons 2021-2026     # re-run is idempotent; --refresh re-pulls -> revisions
    python -m dfs_intel.ufc_pipeline mirror --since 2022-01-01   # --since 1994-01-01 to backfill all
    python -m dfs_intel.ufc_pipeline scrape --since 2022-01-01   # direct; currently blocked from this box (HTTP 500)
    python -m dfs_intel.nfl_dk
    python -m dfs_intel.slate_import data/inbox/DKSalaries.csv --slate-id 2026wk9_main
    python -m dfs_intel.evaluate
    pytest -q

## Leakage semantics
`effective_at <= as_of` always. Historical backfill was observed in 2026, so `mode="backtest"` ignores
`observed_at` but uses the **first-observed revision**; `mode="strict"` (for live use) also requires
`observed_at <= as_of` and uses the latest revision observed by then. NFL effective_at = kickoff (UTC);
UFC effective_at = event date + 36h (conservative "result known by"); UFC fighter bios = fetch time.
