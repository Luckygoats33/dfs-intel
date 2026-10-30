"""Re-pull public UFC.com moneylines + weigh-in/news headlines for UFC FN Oct 31 2026.
Polite: descriptive UA, 2s delay. Never touches DraftKings. Output: data/raw/ufc_refresh/<ts>.json
Usage: .venv/bin/python scripts/ufc_refresh_odds_news.py"""
import re, json, time, datetime, pathlib, requests
from zoneinfo import ZoneInfo
UA = {"User-Agent": "dfs-intel personal research script (non-commercial; 2s delay)"}
URLS = {"ufc_event": "https://www.ufc.com/event/ufc-fight-night-october-31-2026",
        "ufc_weighins": "https://www.ufc.com/news/official-weigh-results-ufc-fight-night-moicano-vs-nolan",
        "ufcalendar_santos": "https://www.ufcalendar.com/fights/yana-santos-vs-luana-santos"}
def nv(a, b):
    p = lambda o: 100/(o+100) if o > 0 else -o/(-o+100)
    x, y = p(a), p(b); return round(x/(x+y), 4), round(y/(x+y), 4), round(x+y-1, 4)
out = {"observed_at": datetime.datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(), "sources": {}, "fights": []}
for k, u in URLS.items():
    time.sleep(2)
    try:
        r = requests.get(u, headers=UA, timeout=30); out["sources"][k] = {"url": u, "status": r.status_code}
        txt = re.sub(r"<[^>]+>", " ", r.text); txt = re.sub(r"\s+", " ", txt)
        if k == "ufc_event":
            for m in re.finditer(r"([A-Z][\w'\.\- ]+?) vs ([A-Z][\w'\.\- ]+?) Round.*?([+-]\d{3}) odds ([+-]\d{3})", txt):
                a, b = int(m.group(3)), int(m.group(4))
                out["fights"].append({"a": m.group(1).split("Live now")[-1].strip(), "b": m.group(2).strip(), "ml_a": a, "ml_b": b,
                    "novig_a_b_overround": nv(a, b), "source": u, "valid": nv(a, b)[2] < 0.15})
        else:
            out["sources"][k]["miss_mentions"] = re.findall(r"[^.]{0,120}(?:missed weight|above the|forfeits)[^.]{0,120}", txt)[:5]
    except Exception as e:
        out["sources"][k] = {"url": u, "error": str(e)}
d = pathlib.Path("data/raw/ufc_refresh"); d.mkdir(parents=True, exist_ok=True)
f = d / (datetime.datetime.now().strftime("%Y%m%dT%H%M%S") + ".json"); f.write_text(json.dumps(out, indent=1))
print(f); print(json.dumps(out, indent=1)[:3000])
