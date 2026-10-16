"""Conservative weekly conference discovery, with permanent link retention.

Search results are NOT treated as confirmed conferences until we can find:
(1) evidence it is a conference, workshop or research meeting (not necessarily in the title),
(2) a requested topic or person on the event page,
(3) an explicit event date that has not finished.

Pages without parseable event dates are skipped, not guessed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "conferences" / "events.json"
TAVILY_ENDPOINT = "https://api.tavily.com/search"

KEYWORDS = {
    "Microlocal analysis": ["microlocal analysis"],
    "Poincaré–Einstein manifolds": ["poincare einstein", "poincare-einstein"],
    "Conformally compact manifolds": ["conformally compact manifold", "conformally compact manifolds"],
    "Asymptotically hyperbolic manifolds": ["asymptotically hyperbolic manifold", "asymptotically hyperbolic manifolds"],
    "Hyperbolic manifolds": ["hyperbolic manifold", "hyperbolic manifolds"],
    "Convex-cocompact hyperbolic manifolds": [
        "convex cocompact hyperbolic manifold", "convex co compact hyperbolic manifold",
        "convex-cocompact hyperbolic manifolds", "convex cocompact hyperbolic manifolds",
        "convex co compact hyperbolic manifolds",
    ],
}
PEOPLE = {
    "Colin Guillarmou": ["colin guillarmou"],
    "Rafe Mazzeo": ["rafe mazzeo"],
    "Polyxeni Spilioti": ["polyxeni spilioti"],
    "Werner Müller": ["warner muller", "werner muller", "werner müller"],
    "Ksenia Fedosova": ["ksenia fedosova"],
    "Martin Bridgeman": ["martin bridgeman"],
    "Franco Vargas Pallete": ["franco vargas pallete", "franco e vargas pallete"],
    "Jeffrey Brock": ["jeffery brock", "jeffrey brock", "jeffrey f brock", "jeff brock"],
    "Yair Minsky": ["yair minsky"],
}
EVENT_CONTEXT = re.compile(
    r"\b(conference|workshop|symposi(?:um|a)|research meeting|the meeting|this meeting|"
    r"event information|conference information|conference contacts|"
    r"organizers?|organisers?|participants?|programme|program|research school|"
    r"summer school|winter school|conference date)\b", re.I
)
EVENT_WORD = re.compile(
    r"\b(conference|workshop|symposi(?:um|a)|mini\s?school|summer school|"
    r"winter school|research school|scientific meeting|annual meeting|"
    r"colloquium|colloque|tagung|congress)\b", re.IGNORECASE
)
BLOCKED_HOSTS = (
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "researchgate.net", "wikipedia.org", "arxiv.org",
    "conferencealerts.com", "10times.com", "allconferencealert.com",
)
SEARCH_TERMS = [
    "microlocal analysis",
    "Poincare Einstein manifolds",
    "conformally compact manifolds",
    "asymptotically hyperbolic manifolds",
    "hyperbolic manifolds",
    "convex cocompact hyperbolic manifolds",
    "Colin Guillarmou", "Rafe Mazzeo", "Polyxeni Spilioti",
    "Werner Müller", "Ksenia Fedosova", "Martin Bridgeman",
    "Franco Vargas Pallete", "Jeffrey Brock", "Yair Minsky",
]
MONTH_WORDS = (
    "January February March April May June July August September October November December "
    "Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec"
).split()
MONTH_RE = "(?:" + "|".join(MONTH_WORDS) + ")\\.?"
DAY_RE = r"\d{1,2}(?:st|nd|rd|th)?"
SEP_RE = r"(?:\s*[-–—]\s*|\s+to\s+|\s+through\s+)"
ISO_RE = re.compile(r"(?<!\d)20\d{2}-\d{1,2}-\d{1,2}(?!\d)")
MONTH_DATE_RE = re.compile(rf"\b({MONTH_RE})\s+({DAY_RE}),?\s+(20\d{{2}})\b", re.I)
MONTH_RANGE_RE = re.compile(
    rf"\b({MONTH_RE})\s+({DAY_RE}){SEP_RE}({DAY_RE}),?\s+(20\d{{2}})\b", re.I
)
DAY_RANGE_RE = re.compile(
    rf"\b({DAY_RE}){SEP_RE}({DAY_RE})\s+({MONTH_RE})\s+(20\d{{2}})\b", re.I
)
CROSS_MONTH_RE = re.compile(
    rf"\b({MONTH_RE})\s+({DAY_RE}){SEP_RE}({MONTH_RE})\s+({DAY_RE}),?\s+(20\d{{2}})\b", re.I
)
DAY_MONTH_RE = re.compile(rf"\b({DAY_RE})\s+({MONTH_RE})\s+(20\d{{2}})\b", re.I)
EVENT_DATE_HINT_RE = re.compile(
    r"\b(conference dates?|workshop dates?|event dates?|meeting dates?|"
    r"takes place|starts?|begins?|from|date(?:s)?|held|when)\b", re.I
)
DEADLINE_RE = re.compile(
    r"\b(registration|submission|application|abstract|notification|"
    r"deadline|early bird|paper submission|camera ready)\b", re.I
)


def normalize(text: object) -> str:
    base = unicodedata.normalize("NFKD", str(text or ""))
    base = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", base.lower()))


def matches(haystack: str, dictionary: dict[str, list[str]]) -> list[str]:
    text = " " + normalize(haystack) + " "
    return [label for label, aliases in dictionary.items()
            if any(" " + normalize(alias) + " " in text for alias in aliases)]


def canonical_url(value: str) -> str | None:
    try:
        parts = urlsplit(value.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        hostname = parts.hostname.lower()
        if any(hostname == b or hostname.endswith("." + b) for b in BLOCKED_HOSTS):
            return None
        if parts.path.lower().endswith((".pdf", ".jpg", ".zip", ".docx")):
            return None
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query)
                           if not k.lower().startswith("utm_") and k.lower() not in
                           ("fbclid", "gclid", "mc_cid", "mc_eid")])
        return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/") or "/", query, ""))
    except (ValueError, AttributeError):
        return None


def to_day(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    m = re.match(r"^(20\d{2})-(\d{1,2})-(\d{1,2})(?:$|[T\s])", value.strip())
    if not m:
        return None
    try:
        return date(*map(int, m.groups()))
    except ValueError:
        return None


def month_num(value: str) -> int:
    import calendar
    prefix = value.replace(".", "").lower()[:3]
    return next(i for i in range(1, 13) if calendar.month_name[i].lower().startswith(prefix))


def numeric_day(value: str) -> int:
    return int(re.match(r"\d+", value).group())


def event_dates_from_text(text: str, today: date) -> tuple[date, date] | None:
    """Accept explicit dates/ranges only, never infer a year or a duration."""
    candidates: list[tuple[int, date, date]] = []

    def save(index: int, start: date, end: date) -> None:
        if start > end or (end - start).days > 45 or end < today:
            return
        if (start - today).days > 730:
            return
        # Prefer explicit conference dates, especially date ranges.
        # Registration/submission deadlines are not event dates.
        before = text[max(0, index - 100): index]
        nearby = text[max(0, index - 100): index + 90]
        penalty = 7 if DEADLINE_RE.search(before[-75:]) else 0
        event_bonus = -2 if EVENT_DATE_HINT_RE.search(before[-65:]) else 0
        range_bonus = -1 if end > start else 0
        priority = max(0, 3 + penalty + event_bonus + range_bonus)
        candidates.append((priority * 1000000 + index, start, end))

    for m in CROSS_MONTH_RE.finditer(text):
        try:
            a_month, a_day, b_month, b_day, year = m.groups()
            end = date(int(year), month_num(b_month), numeric_day(b_day))
            start_year = int(year) - (month_num(a_month) > month_num(b_month))
            save(m.start(), date(start_year, month_num(a_month), numeric_day(a_day)), end)
        except ValueError:
            continue
    for m in MONTH_RANGE_RE.finditer(text):
        try:
            month, first, last, year = m.groups()
            save(m.start(), date(int(year), month_num(month), numeric_day(first)),
                 date(int(year), month_num(month), numeric_day(last)))
        except ValueError:
            continue
    for m in DAY_RANGE_RE.finditer(text):
        try:
            first, last, month, year = m.groups()
            save(m.start(), date(int(year), month_num(month), numeric_day(first)),
                 date(int(year), month_num(month), numeric_day(last)))
        except ValueError:
            continue
    # A pair of nearby ISO dates is interpreted as a date range.
    iso_hits = [(m.start(), to_day(m.group())) for m in ISO_RE.finditer(text)]
    for i, (index, first) in enumerate(iso_hits):
        if not first:
            continue
        second = None
        if i + 1 < len(iso_hits) and iso_hits[i + 1][0] - index < 95:
            second = iso_hits[i + 1][1]
        save(index, first, second if second and second >= first else first)
    for m in MONTH_DATE_RE.finditer(text):
        try:
            month, day, year = m.groups()
            one = date(int(year), month_num(month), numeric_day(day))
            save(m.start(), one, one)
        except ValueError:
            continue
    day_month_hits = list(DAY_MONTH_RE.finditer(text))
    # Indico-style events often have separate "Starts" and "Ends" lines.
    for a, b in zip(day_month_hits, day_month_hits[1:]):
        lead = text[max(0, a.start() - 28):a.start()]
        between = text[a.end():b.start()]
        if (b.start() - a.end() < 95
                and re.search(r"\bstarts?\s*$", lead, re.I)
                and re.search(r"\bends?\s+[^\d]*$", between, re.I)):
            try:
                aa = a.groups(); bb = b.groups()
                start = date(int(aa[2]), month_num(aa[1]), numeric_day(aa[0]))
                end = date(int(bb[2]), month_num(bb[1]), numeric_day(bb[0]))
                save(a.start(), start, end)
            except ValueError:
                pass
    for m in day_month_hits:
        try:
            day, month, year = m.groups()
            one = date(int(year), month_num(month), numeric_day(day))
            save(m.start(), one, one)
        except ValueError:
            continue
    if not candidates:
        return None
    _, start, end = min(candidates)
    return start, end


def schema_events(soup: BeautifulSoup) -> list[dict]:
    items: list[dict] = []

    def visit(node: object) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            kinds = node.get("@type", [])
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if any(isinstance(kind, str) and kind.lower().endswith("event") for kind in kinds):
                items.append(node)
            for key in ("@graph", "mainEntity", "itemListElement", "event"):
                if key in node:
                    visit(node[key])

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            visit(json.loads(tag.string or tag.get_text()))
        except (ValueError, TypeError):
            pass
    return items


def place_text(location: object) -> str:
    if isinstance(location, str):
        return location[:160]
    if isinstance(location, list):
        return ", ".join(filter(None, (place_text(x) for x in location)))[:160]
    if isinstance(location, dict):
        address = location.get("address", {})
        if isinstance(address, dict):
            parts = [str(address.get(k, "")) for k in ("addressLocality", "addressRegion", "addressCountry")]
            return ", ".join(p for p in parts if p)[:160]
        return str(location.get("name", ""))[:160]
    return ""


def page_record(result: dict, today: date, session: requests.Session,
                rejected: Counter | None = None) -> dict | None:
    def skip(reason: str) -> None:
        if rejected is not None:
            rejected[reason] += 1
        return None

    url = canonical_url(str(result.get("url", "")))
    if not url:
        return skip("invalid or excluded URL")
    search_title = str(result.get("title", ""))
    excerpt = str(result.get("content", ""))
    raw = str(result.get("raw_content") or "")[:100000]
    soup = BeautifulSoup("", "html.parser")
    original_html = b""
    try:
        response = session.get(url, timeout=16, headers={"User-Agent": "ConferenceTracker/1.0 (+public academic index)"})
        response.raise_for_status()
        if "html" in response.headers.get("Content-Type", "").lower():
            # requests decodes according to the page's declared charset.
            # Passing bytes directly to BeautifulSoup sometimes produces
            # "REPLACEMENT CHARACTER" warnings from charset detection.
            if not response.encoding or response.encoding.lower() in ("iso-8859-1", "ascii"):
                response.encoding = response.apparent_encoding or "utf-8"
            original_html = response.text[:1200000]
            soup = BeautifulSoup(original_html, "html.parser")
    except requests.RequestException:
        pass  # Some academic sites block bots; Tavily text may still be available.

    heading = soup.find("h1")
    heading_title = (heading.get_text(" ", strip=True) if heading else "")
    # Many legitimate research conferences have subject-only names, e.g.
    # "Microlocal Analysis and Curved Spacetimes".
    title = heading_title if heading_title and len(heading_title) >= 9 else search_title
    if not title:
        return skip("missing title")
    for tag in soup(["style", "script", "nav", "footer", "header"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    page_text = main.get_text(" ", strip=True)[:100000]
    # Require evidence that the page is about an event, but not necessarily
    # that the event title literally contains "conference" or "workshop".
    # Avoid interpreting a single seminar/lecture or an academic paper as a conference.
    evidence = (page_text[:18000] or raw[:12000] or excerpt)
    structured_events = schema_events(BeautifulSoup(original_html, "html.parser"))
    if not (EVENT_WORD.search(title + " " + search_title)
            or structured_events or EVENT_CONTEXT.search(evidence)):
        return skip("no conference or meeting evidence")
    # Do not count the user's search query as confirmation of topic relevance.
    confirmed_content = " ".join((page_text[:30000], raw[:12000], excerpt))
    combined = " ".join((title, confirmed_content))
    matched_keywords = matches(combined, KEYWORDS)
    matched_people = matches(combined, PEOPLE)
    if not (matched_keywords or matched_people):
        return skip("no requested topic or researcher on page")

    start_end = None
    location = ""
    # JSON-LD Event dates are the highest-confidence source.
    for event in structured_events:
        start = to_day(event.get("startDate"))
        end = to_day(event.get("endDate")) or start
        if (start and end and start <= end and end >= today
                and (start - today).days <= 730 and (end - start).days <= 45):
            start_end = start, end
            location = place_text(event.get("location"))
            if isinstance(event.get("name"), str) and EVENT_WORD.search(event["name"]):
                title = event["name"][:240]
            break

    if not start_end:
        # Only parse dates in the conference body (and indexed content), not page metadata.
        start_end = event_dates_from_text(page_text[:25000] + " " + raw[:12000] + " " + excerpt, today)
    if not start_end:
        return skip("missing or unparseable future event dates")
    start, end = start_end
    return {
        "title": title[:240], "url": url,
        "start": start.isoformat(), "end": end.isoformat(),
        "location": location,
        "matched_keywords": matched_keywords,
        "matched_people": matched_people,
        "added_on": today.isoformat(),
    }


def tavily_search(api_key: str, query: str, session: requests.Session) -> list[dict]:
    payload = {"query": query, "search_depth": "basic", "max_results": 10,
               "include_raw_content": "markdown", "topic": "general"}
    response = session.post(
        TAVILY_ENDPOINT, json=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=35,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data.get("results"), list):
        raise ValueError("Unexpected Tavily response; missing results array")
    return data["results"]


def run() -> None:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("TAVILY_API_KEY is missing. Add it in GitHub repository Actions secrets.")
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    if DATABASE.exists():
        saved = json.loads(DATABASE.read_text(encoding="utf-8"))
    else:
        saved = {"last_checked": None, "events": []}
    records = {canonical_url(e["url"]): e for e in saved.get("events", [])
               if isinstance(e, dict) and e.get("url") and canonical_url(e["url"])}
    # Independently verified event pages: merged, not overwriting archived entries.
    # This guarantees that a confirmed event isn't lost due to search ranking.
    curated_file = ROOT / "conferences" / "verified_events.json"
    if curated_file.exists():
        curated = json.loads(curated_file.read_text(encoding="utf-8"))
        for event in curated.get("events", []):
            url = canonical_url(event.get("url", ""))
            if (url and to_day(event.get("start")) and to_day(event.get("end"))
                    and to_day(event["start"]) <= to_day(event["end"])):
                records.setdefault(url, {**event, "url": url, "added_on": today.isoformat()})
    known_links = set(records)
    session = requests.Session()
    successes = 0
    seen = set()
    discovered = 0
    rejected = Counter()
    search_hits = 0
    distinct_pages = 0
    # Separate year-scoped searches work better than requiring 3 years in one query.
    for term in SEARCH_TERMS:
        for year in range(today.year, today.year + 3):
            query = f'"{term}" {year} conference workshop mathematics'
            try:
                results = tavily_search(key, query, session)
                successes += 1
                search_hits += len(results)
                print(f"QUERY {term!r} {year}: {len(results)} results", flush=True)
            except (requests.RequestException, ValueError) as error:
                print(f"SEARCH FAILED for {term} {year}: {error}", file=sys.stderr)
                continue
            for item in results:
                url = canonical_url(str(item.get("url", "")))
                if not url or url in known_links or url in seen:
                    continue
                seen.add(url)
                distinct_pages += 1
                try:
                    event = page_record(item, today, session, rejected)
                except (ValueError, TypeError, OverflowError) as error:
                    rejected["malformed page"] += 1
                    print(f"Skipped malformed page: {url}: {error}", file=sys.stderr)
                    continue
                if event:
                    fingerprint = (normalize(event["title"]), event["start"])
                    existing = {(normalize(v["title"]), v["start"]) for v in records.values()
                                if v.get("title") and v.get("start")}
                    if fingerprint in existing:
                        rejected["duplicate conference"] += 1
                        continue
                    records[url] = event
                    discovered += 1
                    print(f"NEW: {event['start']} {event['title']} -> {url}")
            time.sleep(0.15)
    if successes == 0:
        raise RuntimeError("All search queries failed; existing archive was left untouched.")
    print(f"Successful searches: {successes}/{len(SEARCH_TERMS) * 3}; "
          f"search hits: {search_hits}; distinct pages checked: {distinct_pages}; "
          f"new entries: {discovered}; total archived: {len(records)}")
    print("Reasons for excluded pages:", dict(rejected), flush=True)
    # Never delete archived links or reset an organizer's original dates.
    output = {
        "last_checked": today.isoformat(),
        "events": sorted(records.values(), key=lambda e: (e.get("start", ""), e.get("title", "").lower())),
    }
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    DATABASE.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
