"""Public UFC.com event pages: cards, moneylines, and news links.

Polite client: descriptive User-Agent, a delay between requests, and an in-run
cache. This module never calls ufcstats.com and never calls DraftKings.
UFC.com's CDN rejects a plain HTTP client (Varnish 403). A headless browser is
used only to read the same public HTML a visitor gets. It does not solve
challenges or hit undocumented JSON APIs.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

UA = "dfs-intel-research/0.1 (personal non-commercial sports research; polite crawler, 1 req/2.5s, caches pages)"
PT = ZoneInfo("America/Los_Angeles")
EVENTS_URL = "https://www.ufc.com/events"
NEWS_URL = "https://www.ufc.com/news"
OVERROUND_INVALID = 0.15

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
_WEIGHT_RE = re.compile(
    r"(?P<label>(?:Main Event|Co-Main Event)\s*-\s*)?(?P<cls>[A-Za-z][^:\n]{0,80}?Bout):\s*"
    r"(?P<a>.+?)\s*\((?P<aw>[\d.]+)\)(?P<astar>\*?)\s+vs\.?\s+"
    r"(?P<b>.+?)\s*\((?P<bw>[\d.]+)\)(?P<bstar>\*?)",
    re.I,
)
_CHANGE_RE = re.compile(
    r"replac|injur|out of the|pulled|scratch|medical|short notice|withdrew|removed|new opponent|"
    r"not competing|forced out|late notice|off the card|missed weight|weighed in above|forfeit",
    re.I,
)


def abs_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return "https://www.ufc.com" + (href if href.startswith("/") else "/" + href)


def _text(node) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _opt_int(value) -> int | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_american(text: str) -> int | None:
    text = (text or "").strip().replace("−", "-").replace("–", "-").replace("+", "+")
    if not re.fullmatch(r"[+-]\d{2,5}", text):
        return None
    return int(text)


def parse_events_list(html: str) -> list[dict]:
    """Upcoming events from the public events page. Past cards are ignored."""
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("#events-list-upcoming") or soup
    seen = set()
    out = []
    for art in root.select("article.c-card-event--result"):
        link = art.select_one("h3.c-card-event--result__headline a")
        if not link or not link.get("href"):
            continue
        href = link["href"].split("#")[0]
        slug = href.rstrip("/").split("/")[-1]
        if slug in seen:
            continue
        seen.add(slug)
        date = art.select_one(".c-card-event--result__date")
        loc = art.select_one(".c-card-event--result__location")
        out.append({
            "slug": slug,
            "path": href if href.startswith("/") else "/" + href,
            "url": abs_url(href),
            "headline": _text(link),
            "main_card_text": (date.get("data-main-card") or "").strip() if date else "",
            "main_ts": _opt_int(date.get("data-main-card-timestamp") if date else None),
            "prelims_text": (date.get("data-prelims-card") or "").strip() if date else "",
            "prelims_ts": _opt_int(date.get("data-prelims-card-timestamp") if date else None),
            "early_text": (date.get("data-early-card") or "").strip() if date else "",
            "early_ts": _opt_int(date.get("data-early-card-timestamp") if date else None),
            "location": _text(loc),
        })
    return out


def _corner(node, color: str) -> dict:
    box = node.select_one(f".c-listing-fight__names-row .c-listing-fight__corner-name--{color}")
    if box is None:
        box = node.select_one(f".c-listing-fight__corner-name--{color}")
    given = _text(box.select_one(".c-listing-fight__corner-given-name")) if box else ""
    family = _text(box.select_one(".c-listing-fight__corner-family-name")) if box else ""
    name = f"{given} {family}".strip() or (_text(box) if box else "")
    href = ""
    if box and box.select_one("a"):
        href = box.select_one("a").get("href") or ""
    country = ""
    ctry = node.select_one(f".c-listing-fight__country--{color} .c-listing-fight__country-text")
    if ctry:
        country = _text(ctry)
    return {"name": name, "given": given, "family": family, "profile_url": abs_url(href) if href else "", "country": country}


def _parse_fight(li, card: str) -> dict | None:
    node = li.select_one(".c-listing-fight")
    if node is None:
        return None
    red, blue = _corner(node, "red"), _corner(node, "blue")
    if not red["name"] and not blue["name"]:
        return None
    klass = node.select_one(".c-listing-fight__class--desktop .c-listing-fight__class-text")
    if klass is None:
        klass = node.select_one(".c-listing-fight__class-text")
    amounts = node.select(".c-listing-fight__odds-row .c-listing-fight__odds-amount")
    prices = [parse_american(_text(a)) for a in amounts[:2]]
    while len(prices) < 2:
        prices.append(None)
    rounds = None
    blob = _text(node)
    m = re.search(r"\b([1-5])\s*Rounds?\b", blob, re.I)
    if m:
        rounds = int(m.group(1))
    order = _opt_int(li.get("data-order"))
    return {
        "order": order,
        "card": card,
        "weight_class": _text(klass),
        "rounds_on_page": rounds,
        "fmid": node.get("data-fmid") or "",
        "red": red,
        "blue": blue,
        "ml_red": prices[0],
        "ml_blue": prices[1],
    }


def parse_event_page(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    prefix = _text(soup.select_one(".c-hero__headline-prefix"))
    top = _text(soup.select_one(".e-divider__top"))
    bottom = _text(soup.select_one(".e-divider__bottom"))
    venue = _text(soup.select_one(".c-hero__text"))
    suffix = soup.select_one(".c-hero__headline-suffix")
    cards = (("main-card", "Main card"), ("prelims-card", "Prelims"), ("early-prelims", "Early prelims"))
    fights = []
    sections = []
    for sid, label in cards:
        sec = soup.select_one(f"#{sid}")
        if sec is None:
            continue
        clock = sec.select_one(".c-event-fight-card-broadcaster__time")
        broad = sec.select_one(".c-event-fight-card-broadcaster__link a, a.broadcaster-cta")
        sections.append({
            "id": sid,
            "label": label,
            "timestamp": _opt_int(clock.get("data-timestamp") if clock else None),
            "time_text": _text(clock),
            "broadcaster": _text(broad),
        })
        for li in sec.select("li.l-listing__item"):
            fight = _parse_fight(li, label)
            if fight:
                fights.append(fight)
    news = []
    seen = set()
    for a in soup.select("a[href*='/news/']"):
        href = (a.get("href") or "").split("#")[0]
        if "/news/" not in href or href in seen:
            continue
        seen.add(href)
        news.append({"url": abs_url(href), "text": _text(a)})
    title = prefix
    if top or bottom:
        title = f"{prefix}: {top} vs {bottom}".strip(": ")
    return {
        "url": url,
        "name": title or prefix,
        "prefix": prefix,
        "headline_names": f"{top} vs {bottom}".strip() if top or bottom else "",
        "venue": venue,
        "main_ts": _opt_int(suffix.get("data-timestamp") if suffix else None),
        "sections": sections,
        "fights": fights,
        "news_links": news,
    }


def parse_news_index(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    out = []
    for a in soup.select("a[href*='/news/']"):
        href = (a.get("href") or "").split("#")[0]
        if not href or href.rstrip("/").endswith("/news") or "newsletter" in href:
            continue
        if href in seen:
            continue
        # Skip nav items that only say "News".
        text = _text(a)
        if not text or text.lower() in {"news", "all news", "see all"}:
            continue
        if not re.search(r"/news/.+", href):
            continue
        seen.add(href)
        out.append({"url": abs_url(href), "href": href, "text": text})
    return out


def parse_article(html: str, url: str) -> dict:
    """Pull weigh-in lines, a rounds statement, and short late-change sentences.

    The full article is not stored.
    """
    soup = BeautifulSoup(html, "html.parser")
    title = _text(soup.select_one("h1"))
    credit = _text(soup.select_one(".c-hero__article-credit"))
    parts = []
    for el in soup.select(".e-p--initial, .field--name-body-structured .field--name-text"):
        parts.append(el.get_text("\n", strip=True))
    text = "\n".join(parts)
    text = text.replace("\xa0", " ")
    weights = []
    for m in _WEIGHT_RE.finditer(text):
        weights.append({
            "weight_class": re.sub(r"\s+", " ", m.group("cls")).strip(),
            "a": re.sub(r"\s+", " ", m.group("a")).strip(" -"),
            "a_lb": float(m.group("aw")),
            "a_mark": bool(m.group("astar")),
            "b": re.sub(r"\s+", " ", m.group("b")).strip(" -"),
            "b_lb": float(m.group("bw")),
            "b_mark": bool(m.group("bstar")),
        })
    rounds = {}
    main = re.search(r"main event scheduled for (one|two|three|four|five|\d+) rounds", text, re.I)
    other = re.search(r"all other bouts scheduled for (one|two|three|four|five|\d+) rounds", text, re.I)

    def _num(raw: str) -> int | None:
        raw = raw.lower()
        if raw in _WORDS:
            return _WORDS[raw]
        return int(raw) if raw.isdigit() else None

    if main:
        rounds["main_event"] = _num(main.group(1))
        rounds["main_event_quote"] = main.group(0)
    if other:
        rounds["other_bouts"] = _num(other.group(1))
        rounds["other_bouts_quote"] = other.group(0)
    changes = []
    for raw_line in text.splitlines():
        raw_line = re.sub(r"\s+", " ", raw_line).strip()
        if not raw_line:
            continue
        pieces = re.split(r"(?<=[.!?])\s+", raw_line)
        for sent in pieces:
            sent = sent.strip(" -")
            if not sent or len(sent) > 280 or not _CHANGE_RE.search(sent):
                continue
            if sent not in changes:
                changes.append(sent)
            if len(changes) >= 8:
                break
        if len(changes) >= 8:
            break
    kind = "news"
    blob = f"{title} {url}".lower()
    if "weigh" in blob:
        kind = "weigh-in"
    elif "update" in blob:
        kind = "update"
    return {
        "url": url,
        "title": title,
        "credit": credit,
        "kind": kind,
        "weights": weights,
        "rounds": rounds,
        "change_sentences": changes,
        "status": "ok",
    }


def name_tokens(headline: str) -> list[str]:
    parts = re.split(r"\s+vs\.?\s+", headline or "", flags=re.I)
    tokens = []
    for part in parts:
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'’\-]+", part)]
        if not words:
            continue
        last = words[-1].lower().replace("’", "'")
        if len(last) >= 4 and last not in {"tbd"}:
            tokens.append(last)
        if len(words) >= 2:
            pair = f"{words[-2]} {words[-1]}".lower()
            if "tbd" not in pair:
                tokens.append(pair)
    return tokens


def event_local_dates(event: dict) -> set:
    dates = set()
    for key in ("early_ts", "prelims_ts", "main_ts"):
        ts = event.get(key)
        if not ts:
            continue
        utc = datetime.fromtimestamp(int(ts), timezone.utc)
        dates.add(utc.date())
        dates.add(utc.astimezone(PT).date())
    return dates


def _date_phrases(day) -> list[str]:
    month = day.strftime("%B")
    mon = day.strftime("%b")
    n = day.day
    return [f"{month} {n}", f"{mon} {n}", f"{mon}. {n}"]


def article_matches_event(event: dict, link: dict, peers: list[dict]) -> bool:
    blob = f"{link.get('text', '')} {link.get('href', '')} {link.get('url', '')}".lower()
    tokens = name_tokens(event.get("headline") or "")
    tokens += name_tokens(event.get("headline_names") or "")
    named = any(tok in blob for tok in tokens)
    if any(bad in blob for bad in ("zuffa boxing", "ufc bjj")) and not named:
        return False
    if named:
        return True
    phrases = []
    for day in event_local_dates(event):
        phrases.extend(p.lower() for p in _date_phrases(day))
    if not any(p in blob for p in phrases):
        return False
    if "ufc" not in blob and "fight night" not in blob:
        return False
    same_day = []
    mine = event_local_dates(event)
    for other in peers:
        if event_local_dates(other) & mine:
            same_day.append(other)
    return len(same_day) <= 1


def rank_article(link: dict) -> tuple:
    blob = f"{link.get('href', '')} {link.get('text', '')}".lower()
    if "weigh" in blob:
        bucket = 0
    elif "update" in blob:
        bucket = 1
    elif "official" in blob:
        bucket = 2
    else:
        bucket = 3
    return (bucket, blob)


class PageFetcher:
    """Fetch public UFC.com HTML. One browser for the whole run."""

    def __init__(self, delay: float = 2.5):
        self.delay = delay
        self._last = 0.0
        self.cache: dict[str, str] = {}
        self._blocked = False
        self._pw = None
        self._browser = None
        self._page = None

    def close(self):
        try:
            if self._browser:
                self._browser.close()
        finally:
            self._browser = None
            self._page = None
            if self._pw:
                self._pw.stop()
                self._pw = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _wait(self):
        gap = self.delay - (time.time() - self._last)
        if self._last and gap > 0:
            time.sleep(gap)
        self._last = time.time()

    def _requests(self, url: str) -> tuple[int, str]:
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "text/html"}, timeout=30)
        return r.status_code, r.text

    def _ensure_browser(self):
        if self._page is not None:
            return
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        errors = []
        for kwargs in (
            {"channel": "chrome", "headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]},
            {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]},
        ):
            try:
                self._browser = self._pw.chromium.launch(**kwargs)
                break
            except Exception as exc:
                errors.append(str(exc))
                self._browser = None
        if self._browser is None:
            raise RuntimeError("headless browser unavailable: " + "; ".join(errors))
        self._page = self._browser.new_page(user_agent=UA)

        def _route(route):
            if route.request.resource_type in {"image", "media", "font"}:
                return route.abort()
            return route.continue_()

        self._page.route("**/*", _route)

    def _selector(self, url: str) -> str:
        path = url.split("?")[0].rstrip("/")
        if path.endswith("/events"):
            return "#events-list-upcoming"
        if "/event/" in path:
            return ".c-hero, .c-listing-fight"
        if path.endswith("/news"):
            return "a[href*='/news/']"
        return "h1, .field--name-text, article"

    def _browser_get(self, url: str) -> str:
        self._ensure_browser()
        self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            self._page.wait_for_selector(self._selector(url), timeout=20000)
        except Exception:
            # Still return whatever HTML arrived; the parser records empty/missing.
            pass
        html = self._page.content()
        if not html or "403 Forbidden" in html[:500]:
            raise RuntimeError(f"UFC.com returned a block page for {url}")
        return html

    def get(self, url: str) -> str:
        if url in self.cache:
            return self.cache[url]
        self._wait()
        if not self._blocked:
            try:
                status, html = self._requests(url)
            except Exception:
                status, html = 0, ""
            if status == 200 and html and "403 Forbidden" not in html[:600]:
                self.cache[url] = html
                return html
            self._blocked = True
        html = self._browser_get(url)
        self.cache[url] = html
        return html
