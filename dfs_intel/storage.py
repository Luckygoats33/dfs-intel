"""Append-only, revisioned fact store: Parquet batches per table + DuckDB views.

Each table lives in data/parquet/<table>/batch_*.parquet. Every row carries
source, source_event_id, observed_at (UTC fetch time), effective_at (UTC time the fact
was true), revision (1 = first observed; corrections get revision+1, old rows kept),
and row_hash (content hash of the non-provenance columns).
"""
from __future__ import annotations
import datetime as dt, json, uuid
import duckdb, pandas as pd
from pandas.util import hash_pandas_object
from . import DATA

PARQ = DATA / "parquet"
DB = DATA / "dfs.duckdb"
RAW = DATA / "raw_cache"
PROV = ["source", "source_event_id", "observed_at", "effective_at", "revision", "row_hash"]
META = PARQ / "_tables.json"


def utcnow():
    return pd.Timestamp(dt.datetime.now(dt.timezone.utc)).tz_convert("UTC")


def _meta():
    return json.loads(META.read_text()) if META.exists() else {}


def _connect():
    PARQ.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DB))


def refresh_views(con=None):
    con = con or _connect()
    for t in _meta():
        if list((PARQ / t).glob("*.parquet")):
            con.execute(f"CREATE OR REPLACE VIEW {t} AS SELECT * FROM read_parquet('{PARQ / t}/*.parquet', union_by_name=true)")
    return con


def append_facts(table: str, df: pd.DataFrame, key_cols: list[str], source: str,
                 source_event_id_col: str, effective_at: pd.Series, observed_at=None) -> dict:
    """Insert new rows (rev 1), changed rows (rev = prev max + 1); skip identical rows."""
    observed_at = observed_at or utcnow()
    df = df.copy()
    for c in df.columns:  # normalize object columns so parquet is happy
        if df[c].dtype == object:
            df[c] = df[c].astype("string")
    content = [c for c in df.columns if c not in PROV]
    df["row_hash"] = hash_pandas_object(df[content], index=False).astype("int64")
    df["source"] = source
    df["source_event_id"] = df[source_event_id_col].astype("string")
    df["observed_at"] = observed_at
    df["effective_at"] = pd.to_datetime(effective_at, utc=True).values
    df["effective_at"] = pd.to_datetime(df["effective_at"], utc=True)
    df = df.drop_duplicates(subset=key_cols, keep="last")
    meta = _meta(); meta[table] = {"key_cols": key_cols}
    (PARQ / table).mkdir(parents=True, exist_ok=True)
    con = _connect()
    existing = list((PARQ / table).glob("*.parquet"))
    if existing:
        keys = ", ".join(key_cols)
        prev = con.execute(f"""SELECT {keys}, arg_max(row_hash, revision) AS prev_hash, max(revision) AS prev_rev
            FROM read_parquet('{PARQ / table}/*.parquet', union_by_name=true) GROUP BY {keys}""").df()
        for k in key_cols:  # align dtypes for merge
            prev[k] = prev[k].astype(df[k].dtype) if str(df[k].dtype) != "string" else prev[k].astype("string")
        df = df.merge(prev, on=key_cols, how="left")
        new = df["prev_rev"].isna(); changed = (~new) & (df["prev_hash"] != df["row_hash"])
        df["revision"] = 1
        df.loc[changed, "revision"] = df.loc[changed, "prev_rev"].astype(int) + 1
        df = df[new | changed].drop(columns=["prev_hash", "prev_rev"])
        stats = {"new": int(new.sum()), "revised": int(changed.sum())}
    else:
        df["revision"] = 1
        stats = {"new": len(df), "revised": 0}
    df["revision"] = df["revision"].astype("int32")
    if len(df):
        df.to_parquet(PARQ / table / f"batch_{observed_at:%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}.parquet", index=False)
    META.write_text(json.dumps(meta, indent=1))
    refresh_views(con); con.close()
    return stats


def facts_as_of(table: str, as_of, where: str = "", mode: str = "backtest", con=None) -> pd.DataFrame:
    """Return one row per key as knowable at `as_of` (UTC). No leakage:
    - always: effective_at <= as_of
    - mode='strict': also observed_at <= as_of, latest revision observed by then (use for live use).
    - mode='backtest': for history backfilled after the fact (observed_at is later than the games),
      ignore observed_at but use the FIRST-observed revision (revision=min) so later corrections
      don't leak in. Documented limitation: first-observed in our store is still post-hoc.
    """
    as_of = pd.Timestamp(as_of, tz="UTC") if pd.Timestamp(as_of).tzinfo is None else pd.Timestamp(as_of).tz_convert("UTC")
    keys = ", ".join(_meta()[table]["key_cols"])
    own = con is None
    con = con or refresh_views()
    cond = "effective_at <= ?" + (" AND observed_at <= ?" if mode == "strict" else "")
    params = [as_of] + ([as_of] if mode == "strict" else [])
    order = "revision DESC" if mode == "strict" else "revision ASC"
    extra = f"AND ({where})" if where else ""
    q = f"""SELECT * EXCLUDE (_rn) FROM (SELECT *, row_number() OVER (PARTITION BY {keys} ORDER BY {order}) _rn
            FROM {table} WHERE {cond} {extra}) WHERE _rn = 1"""
    out = con.execute(q, params).df()
    if own: con.close()
    return out
