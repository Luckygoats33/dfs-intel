"""UFC historical pipeline.

Two ingest paths, both producing the same tables:
 1) `scrape`  - direct, polite UFCStats.com crawler: descriptive User-Agent, robots.txt honored
    (an unreachable/5xx robots.txt is treated as DISALLOW ALL, per RFC 9309), >= 2 s between requests,
    every raw HTML page cached in data/raw_cache/ufcstats/ (never fetched twice), resumable.
    NOTE 2026-10-30: from this box ufcstats.com returns HTTP 500 (Cloudflare/Pingora, empty body) to
    every request incl. robots.txt, so this path is built but could NOT be run or validated on live HTML.
 2) `mirror`  - loads the public CSVs of github.com/Greco1899/scrape_ufc_stats (a community scrape OF
    UFCStats, updated through UFC 333 / 2026-10-24 at time of writing). Rows tagged
    source='ufcstats_via_github:Greco1899/scrape_ufc_stats' so they are distinguishable from direct pulls.
"""
from __future__ import annotations
import argparse, hashlib, re, time, urllib.robotparser
import pandas as pd, requests
from bs4 import BeautifulSoup
from .storage import RAW, append_facts, utcnow

UA = "dfs-intel-research/0.1 (personal non-commercial sports research; polite crawler, 1 req/2s, caches pages)"
CACHE = RAW / "ufcstats"
MIRROR = RAW / "ufc_mirror"
MIRROR_BASE = "https://raw.githubusercontent.com/Greco1899/scrape_ufc_stats/main/"
MIRROR_SRC = "ufcstats_via_github:Greco1899/scrape_ufc_stats"
DELAY = 2.5

# ---------------- shared parsing helpers ----------------

def id_from_url(u: str) -> str:
    return str(u).rstrip("/").split("/")[-1].strip()


def of_pair(s):
    m = re.match(r"\s*(\d+)\s+of\s+(\d+)", str(s))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def mmss(s):
    m = re.match(r"\s*(\d+):(\d+)", str(s))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def norm_name(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower().replace("-", " ")).strip().replace("  ", " ")

# ---------------- path 1: polite direct scraper ----------------

class PoliteClient:
    def __init__(self, delay=DELAY):
        self.s = requests.Session(); self.s.headers["User-Agent"] = UA
        self.delay, self.last, self.rp = delay, 0.0, None

    def _robots(self):
        if self.rp is None:
            self.rp = urllib.robotparser.RobotFileParser()
            r = self._raw("http://ufcstats.com/robots.txt", check=False)
            if r.status_code == 200:
                self.rp.parse(r.text.splitlines())
            elif 400 <= r.status_code < 500:
                self.rp.parse([])  # no robots.txt -> allowed
            else:
                raise RuntimeError(f"robots.txt unreachable (HTTP {r.status_code}); treating as disallow-all, stopping")
        return self.rp

    def _raw(self, url, check=True):
        if check and not self._robots().can_fetch(UA, url):
            raise PermissionError(f"robots.txt disallows {url}")
        wait = self.delay - (time.time() - self.last)
        if wait > 0: time.sleep(wait)
        r = self.s.get(url, timeout=30); self.last = time.time()
        return r

    def get(self, url) -> str:
        CACHE.mkdir(parents=True, exist_ok=True)
        f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html")
        if f.exists():
            return f.read_text()
        r = self._raw(url); r.raise_for_status()
        f.write_text(r.text)
        return r.text


def parse_events_list(html):
    soup = BeautifulSoup(html, "html.parser"); out = []
    for tr in soup.select("tr.b-statistics__table-row"):
        a = tr.select_one("a.b-link"); d = tr.select_one("span.b-statistics__date")
        tds = tr.find_all("td")
        if a and d:
            out.append({"event_id": id_from_url(a["href"]), "url": a["href"].strip(), "name": a.text.strip(),
                        "date": d.text.strip(), "location": tds[-1].text.strip() if len(tds) > 1 else None})
    return out


def parse_event_fights(html):
    soup = BeautifulSoup(html, "html.parser")
    return [tr.get("data-link").strip() for tr in soup.select("tr.b-fight-details__table-row[data-link]")]


def parse_fight_page(html, fight_id):
    """Returns (fight_row, round_rows). Structure per UFCStats fight-details layout (unvalidated live)."""
    soup = BeautifulSoup(html, "html.parser")
    persons = soup.select("div.b-fight-details__person")
    names, ids, res = [], [], []
    for p in persons:
        a = p.select_one("a"); names.append(a.text.strip()); ids.append(id_from_url(a["href"]))
        res.append(p.select_one("i.b-fight-details__person-status").text.strip())
    info = {}
    for i in soup.select("i.b-fight-details__text-item, i.b-fight-details__text-item_first"):
        lab = i.select_one("i.b-fight-details__label")
        if lab:
            k = lab.text.strip().rstrip(":").lower(); info[k] = i.text.replace(lab.text, "").strip()
    fight = {"fight_id": fight_id, "fighter_a": names[0], "fighter_b": names[1], "fighter_a_id": ids[0],
             "fighter_b_id": ids[1], "outcome": f"{res[0]}/{res[1]}", "method": info.get("method"),
             "round": int(info.get("round", 0) or 0), "time": info.get("time"), "time_format": info.get("time format"),
             "referee": info.get("referee"),
             "weightclass": soup.select_one("i.b-fight-details__fight-title").text.strip() if soup.select_one("i.b-fight-details__fight-title") else None}
    rounds = []
    tables = soup.select("section.b-fight-details__section table")
    # per-round totals table: thead rows "Round N", two fighters per cell
    tot = [t for t in tables if t.select("thead.b-fight-details__table-row_type_head")]
    if tot:
        for head in tot[0].select("thead.b-fight-details__table-row_type_head"):
            rn = int(re.search(r"\d+", head.text).group())
            tr = head.find_next_sibling("tr")
            cols = [[p.text.strip() for p in td.select("p")] for td in tr.find_all("td")]
            for j in range(2):
                g = lambda c: cols[c][j]
                rounds.append({"fight_id": fight_id, "fighter_id": ids[j], "fighter_name": names[j], "round": rn,
                               "kd": g(1), "sig_str": g(2), "total_str": g(4), "td": g(5), "sub_att": g(7),
                               "rev": g(8), "ctrl": g(9)})
    return fight, rounds


def scrape(since="2022-01-01", max_events=None):
    """Resumable: cached pages are re-parsed for free; only uncached pages hit the network."""
    c = PoliteClient()
    events = [e for e in parse_events_list(c.get("http://ufcstats.com/statistics/events/completed?page=all"))
              if pd.to_datetime(e["date"]) >= pd.Timestamp(since)]
    events.sort(key=lambda e: pd.to_datetime(e["date"]), reverse=True)
    fights, rounds = [], []
    for e in events[:max_events]:
        for fu in parse_event_fights(c.get(e["url"])):
            f, r = parse_fight_page(c.get(fu), id_from_url(fu)); f["event_id"] = e["event_id"]
            fights.append(f); rounds += r
    _load(pd.DataFrame(events), pd.DataFrame(fights), _clean_rounds(pd.DataFrame(rounds)), None, "ufcstats.com", utcnow())

# ---------------- path 2: GitHub mirror of UFCStats ----------------

def _mirror_csv(name, refresh=False):
    MIRROR.mkdir(parents=True, exist_ok=True)
    f = MIRROR / f"{name}.csv"
    if refresh or not f.exists():
        r = requests.get(MIRROR_BASE + f"{name}.csv", headers={"User-Agent": UA}, timeout=60); r.raise_for_status()
        f.write_bytes(r.content)
    return pd.read_csv(f, dtype=str, keep_default_na=False).apply(lambda s: s.str.strip())


def _clean_rounds(r):
    if r.empty: return r
    for c, (l, a) in {"sig_str": ("sig_landed", "sig_att"), "total_str": ("total_landed", "total_att"), "td": ("td_landed", "td_att")}.items():
        p = r[c].map(of_pair); r[l] = p.map(lambda x: x[0]); r[a] = p.map(lambda x: x[1])
    for c in ["head", "body", "leg", "distance", "clinch", "ground"]:
        if c in r:
            p = r[c].map(of_pair); r[c + "_landed"] = p.map(lambda x: x[0]); r[c + "_att"] = p.map(lambda x: x[1])
    r["ctrl_sec"] = r["ctrl"].map(mmss)
    for c in ["kd", "sub_att", "rev"]:
        r[c] = pd.to_numeric(r[c], errors="coerce")
    r["round"] = pd.to_numeric(r["round"], errors="coerce").astype("Int64")
    return r.drop(columns=[c for c in ["sig_str", "total_str", "td", "ctrl", "head", "body", "leg", "distance", "clinch", "ground"] if c in r])


def mirror(since="2022-01-01", refresh=False):
    obs = utcnow()
    ev = _mirror_csv("ufc_event_details", refresh)
    ev = ev.rename(columns={"EVENT": "name", "URL": "url", "DATE": "date", "LOCATION": "location"})
    ev["event_id"] = ev["url"].map(id_from_url); ev["event_date"] = pd.to_datetime(ev["date"])
    ev = ev[ev.event_date >= pd.Timestamp(since)]
    res = _mirror_csv("ufc_fight_results", refresh)
    res = res.rename(columns=str.lower).rename(columns={"time format": "time_format", "url": "fight_url", "event": "event_name"})
    res["fight_id"] = res["fight_url"].map(id_from_url)
    res = res.merge(ev[["name", "event_id", "event_date"]], left_on="event_name", right_on="name", how="inner").drop(columns="name")
    ab = res["bout"].str.split(r"\s+vs\.\s+", n=1, expand=True); res["fighter_a"], res["fighter_b"] = ab[0], ab[1]
    fd = _mirror_csv("ufc_fighter_details", refresh); tott = _mirror_csv("ufc_fighter_tott", refresh)
    fd["fighter_id"] = fd["URL"].map(id_from_url); tott["fighter_id"] = tott["URL"].map(id_from_url)
    fighters = fd.merge(tott.drop(columns=["URL"]), on="fighter_id", how="left")
    fighters.columns = [c.lower() for c in fighters.columns]
    fighters["name_norm"] = (fighters["first"] + " " + fighters["last"]).map(norm_name)
    dup = fighters["name_norm"].duplicated(keep=False)
    name2id = fighters[~dup].set_index("name_norm")["fighter_id"]
    res["fighter_a_id"] = res["fighter_a"].map(norm_name).map(name2id)
    res["fighter_b_id"] = res["fighter_b"].map(norm_name).map(name2id)
    o = res["outcome"].str.split("/", expand=True)
    res["winner"] = res["fighter_a"].where(o[0] == "W", res["fighter_b"].where(o[1] == "W", None))
    st = _mirror_csv("ufc_fight_stats", refresh).rename(columns={"EVENT": "event_name", "BOUT": "bout", "ROUND": "round", "FIGHTER": "fighter_name",
        "KD": "kd", "SIG.STR.": "sig_str", "TOTAL STR.": "total_str", "TD": "td", "SUB.ATT": "sub_att", "REV.": "rev", "CTRL": "ctrl",
        "HEAD": "head", "BODY": "body", "LEG": "leg", "DISTANCE": "distance", "CLINCH": "clinch", "GROUND": "ground"})
    st = st.drop(columns=["SIG.STR. %", "TD %"])
    st["round"] = st["round"].str.extract(r"(\d+)")[0]
    st = st[st["round"].notna()]  # some old rows lack round data
    st = st.merge(res[["event_name", "bout", "fight_id"]], on=["event_name", "bout"], how="inner")
    st["fighter_id"] = st["fighter_name"].map(norm_name).map(name2id)
    rounds = _clean_rounds(st.drop(columns=["event_name", "bout"]))
    _load(ev, res, rounds, fighters, MIRROR_SRC, obs)
    return {"events": len(ev), "fights": len(res), "round_rows": len(rounds), "ambiguous_fighter_names": int(dup.sum())}


def _load(ev, fights, rounds, fighters, src, obs):
    if "event_date" not in ev: ev["event_date"] = pd.to_datetime(ev["date"])
    ev_date = ev.set_index("event_id")["event_date"]
    # Event date is local calendar date; effective_at = end of that day UTC+? -> use date+1d 12:00 UTC
    # as a conservative "result known by" time (cards can end after midnight UTC).
    known = lambda d: pd.to_datetime(d).dt.tz_localize("UTC") + pd.Timedelta(hours=36)
    print("events", append_facts("ufc_events", ev.drop(columns=["date"], errors="ignore"), ["event_id"], src, "event_id", known(ev["event_date"]), obs))
    if "event_date" not in fights: fights["event_date"] = fights["event_id"].map(ev_date)
    print("fights", append_facts("ufc_fights", fights, ["fight_id"], src, "fight_id", known(fights["event_date"]), obs))
    if not rounds.empty:
        rounds = rounds.merge(fights[["fight_id", "event_date"]], on="fight_id", how="left")
        print("rounds", append_facts("ufc_fight_rounds", rounds, ["fight_id", "fighter_name", "round"], src, "fight_id", known(rounds["event_date"]), obs))
    if fighters is not None:
        # Bio attributes are as-of fetch time (no history on UFCStats) -> effective_at = observed_at.
        print("fighters", append_facts("ufc_fighters", fighters, ["fighter_id"], src, "fighter_id", pd.Series(obs, index=fighters.index), obs))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("mode", choices=["scrape", "mirror"])
    ap.add_argument("--since", default="2022-01-01"); ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--max-events", type=int)
    a = ap.parse_args()
    print(scrape(a.since, a.max_events) if a.mode == "scrape" else mirror(a.since, a.refresh))
