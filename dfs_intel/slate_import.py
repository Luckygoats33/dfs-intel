"""Manual DK file import. Will downloads files from DK himself and drops them in data/inbox/.
This module only reads local files; it never contacts DraftKings."""
from __future__ import annotations
import argparse, re, unicodedata
from pathlib import Path
import pandas as pd
from .storage import DATA, refresh_views, append_facts, utcnow

INBOX = DATA / "inbox"
SALARY_COLS = ["Position", "Name + ID", "Name", "ID", "Roster Position", "Salary", "Game Info", "TeamAbbrev", "AvgPointsPerGame"]
DK_TO_NFLVERSE_TEAM = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS", "LVR": "LV", "OAK": "LV"}
SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def norm_name(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.\-'’]", " ", s); s = SUFFIX.sub("", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", "", s)).strip()


def read_salary_csv(path) -> pd.DataFrame:
    """Parse a DK salary CSV. DK's export sometimes has instruction rows/cols before the table;
    we locate the header row containing 'Name + ID'."""
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    hdr = next(i for i, l in enumerate(lines) if "Name + ID" in l)
    df = pd.read_csv(path, skiprows=hdr, encoding="utf-8-sig", dtype=str)
    start = list(df.columns).index("Position") if "Position" in df.columns else 0
    df = df.iloc[:, start:start + len(SALARY_COLS)]
    missing = set(SALARY_COLS) - set(df.columns)
    if missing: raise ValueError(f"missing columns {missing}")
    df = df.dropna(subset=["ID"]).copy()
    df["Salary"] = df["Salary"].astype(int); df["AvgPointsPerGame"] = pd.to_numeric(df["AvgPointsPerGame"], errors="coerce")
    gi = df["Game Info"].fillna("")
    df["game_start_et"] = pd.to_datetime(gi.str.extract(r"(\d{2}/\d{2}/\d{4} \d{1,2}:\d{2}[AP]M)")[0], format="%m/%d/%Y %I:%M%p", errors="coerce")
    df["game_start_utc"] = df["game_start_et"].dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    return df


def detect_sport(df) -> str:
    pos = set(df["Position"].str.upper())
    return "UFC" if pos <= {"F", "CPT", "MVP"} else "NFL"


def match_nfl(df, con=None):
    con = con or refresh_views()
    ro = con.execute("""SELECT gsis_id, full_name, team, season, week FROM nfl_rosters_weekly
                        WHERE gsis_id IS NOT NULL QUALIFY row_number() OVER (PARTITION BY gsis_id ORDER BY season DESC, week DESC)=1""").df()
    ro["nn"] = ro.full_name.map(norm_name)
    out = df.copy(); out["team_nv"] = out.TeamAbbrev.replace(DK_TO_NFLVERSE_TEAM); out["nn"] = out.Name.map(norm_name)
    m = out.merge(ro[["nn", "team", "gsis_id"]], left_on=["nn", "team_nv"], right_on=["nn", "team"], how="left")
    # fallback: unique name across league
    uniq = ro.groupby("nn").gsis_id.agg(lambda s: s.iloc[0] if s.nunique() == 1 else None)
    m["gsis_id"] = m["gsis_id"].fillna(m["nn"].map(uniq))
    m["match_id"] = m["gsis_id"].where(m.Position != "DST", "DST_" + m["team_nv"])
    m["match_method"] = m["match_id"].notna().map({True: "name+team/unique-name", False: "UNMATCHED"})
    return m.drop(columns=["team", "gsis_id"])


def match_ufc(df, con=None):
    con = con or refresh_views()
    f = con.execute("SELECT fighter_id, first, last FROM ufc_fighters").df()
    f["nn"] = (f["first"].fillna("") + " " + f["last"].fillna("")).map(norm_name)
    uniq = f.groupby("nn").fighter_id.agg(lambda s: s.iloc[0] if s.nunique() == 1 else None)
    out = df.copy(); out["nn"] = out.Name.map(norm_name); out["match_id"] = out["nn"].map(uniq)
    out["match_method"] = out["match_id"].notna().map({True: "unique-name", False: "UNMATCHED"})
    return out


def import_salary(path, slate_id=None, store=True):
    df = read_salary_csv(path); sport = detect_sport(df)
    m = match_nfl(df) if sport == "NFL" else match_ufc(df)
    slate_id = slate_id or Path(path).stem
    m["slate_id"] = slate_id; m["sport"] = sport
    un = m[m.match_id.isna()][["Name", "ID", "Position", "TeamAbbrev"]]
    rep = DATA / "results" / f"unmatched_{slate_id}.csv"; un.to_csv(rep, index=False)
    if store:
        # Salary is effective from when the file was observed (DK posts salaries days before lock).
        obs = utcnow(); m["source_file"] = str(Path(path).name)
        append_facts("dk_salaries", m.drop(columns=["game_start_et"]), ["slate_id", "ID"], "manual:dk_salary_csv", "slate_id",
                     pd.Series(obs, index=m.index), obs)
    return {"sport": sport, "rows": len(m), "matched": int(m.match_id.notna().sum()), "unmatched": len(un), "unmatched_report": str(rep)}


def read_contest_standings(path) -> dict:
    """STUB: DK post-lock contest-standings export. Typical layout: left block
    Rank, EntryId, EntryName, TimeRemaining, Points, Lineup; right block Player, Roster Position, %Drafted, FPTS.
    Returns {'entries': df, 'ownership': df(Player, Roster Position, own_pct, FPTS)}. Not validated on a real file yet."""
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    entries = df[[c for c in ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup"] if c in df]].dropna(how="all")
    own = df[[c for c in ["Player", "Roster Position", "%Drafted", "FPTS"] if c in df]].dropna(subset=["Player"]) if "Player" in df else pd.DataFrame()
    if len(own):
        own = own.assign(own_pct=own["%Drafted"].str.rstrip("%").astype(float))
    return {"entries": entries, "ownership": own}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("path"); ap.add_argument("--slate-id"); ap.add_argument("--no-store", action="store_true")
    a = ap.parse_args(); print(import_salary(a.path, a.slate_id, not a.no_store))
