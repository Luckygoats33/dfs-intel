"""Consensus UFC method prices from the public GAPOdds props page.

https://www.gapodds.com/ufc/player-props is allowed by that site's robots.txt.
/api/ is disallowed and is not requested. Projections behind the GAP Report are not used.
"""
from __future__ import annotations

import re
import time

import requests
from bs4 import BeautifulSoup

from dfs_intel.odds_math import format_american
from dfs_intel.ufc_pipeline import norm_name
from dfs_intel.ufc_public import parse_american

PROPS_URL = "https://www.gapodds.com/ufc/player-props"
UA = "dfs-intel-research/0.1 (personal non-commercial sports research; polite crawler, respects crawl-delay)"
SOURCE = "GAPOdds consensus method props (public page; book not named)"


def parse_props(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    updated = ""
    text = soup.get_text(" ", strip=True)
    stamp = re.search(r"Updated\s+([A-Z][a-z]{2},?\s+[A-Z][a-z]{2}\s+\d{1,2},\s+\d{1,2}:\d{2}\s*[AP]M\s+ET)", text)
    if stamp:
        updated = stamp.group(1)
    else:
        loose = re.search(r"Lines\s+updated\s+(.{0,40}?)\s+Next update", text)
        if loose:
            updated = loose.group(1).strip()
    fighters = {}
    for game in soup.select("section.pp-game"):
        for row in game.select(":scope > ul > li"):
            link = row.select_one("a[href*='/ufc/fighters/']")
            if link is None:
                continue
            name = link.get_text(" ", strip=True)
            prices = {}
            for bit in row.select(".pp-lines span"):
                label = bit.get_text(" ", strip=True)
                bold = bit.select_one("b")
                if bold is None:
                    continue
                price = parse_american(bold.get_text(strip=True))
                if price is None:
                    continue
                low = label.lower()
                if "ko/tko" in low:
                    prices["ko"] = price
                elif "submission" in low:
                    prices["sub"] = price
                elif "decision" in low:
                    prices["dec"] = price
            if prices:
                fighters[norm_name(name)] = {"name": name, **prices}
    return {"status": "ok" if fighters else "empty", "url": PROPS_URL, "updated_text": updated, "fighters": fighters, "source": SOURCE}


def fetch_props(delay: float = 2.0) -> dict:
    if delay:
        time.sleep(delay)
    try:
        response = requests.get(PROPS_URL, headers={"User-Agent": UA, "Accept": "text/html"}, timeout=30)
    except Exception as exc:
        return {"status": "unavailable", "url": PROPS_URL, "error": str(exc), "fighters": {}, "source": SOURCE}
    if response.status_code != 200 or "Every prop line" not in response.text and "pp-game" not in response.text:
        return {"status": "unavailable", "url": PROPS_URL, "error": f"HTTP {response.status_code}", "fighters": {}, "source": SOURCE}
    parsed = parse_props(response.text)
    parsed["status"] = "ok" if parsed["fighters"] else "unavailable"
    if not parsed["fighters"]:
        parsed["error"] = "Public page did not include consensus method prices."
    return parsed


def lookup(table: dict | None, name: str) -> dict:
    if not table or table.get("status") not in {"ok", "empty"}:
        return {}
    return (table.get("fighters") or {}).get(norm_name(name)) or {}


def describe(price: int | None) -> str:
    return format_american(price)
