#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFC.com scraper test for Secret_DE_EPG.

Safe standalone test:
- Does NOT modify public/sports-events.xml.xz.
- Does NOT deploy GitHub Pages.
- Creates ufc-results/ufc-events.json and .txt as an Actions artifact.

Goal:
Extract upcoming UFC events from UFC.com and map them to ufcfightpass.event.01,
ufcfightpass.event.02, ...

After this test is verified, the logic can be integrated into build_sports_events.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import re
import urllib.error
import urllib.request


OUT_DIR = Path("ufc-results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

BERLIN = ZoneInfo("Europe/Berlin")
EASTERN = ZoneInfo("America/New_York")
PACIFIC = ZoneInfo("America/Los_Angeles")

URLS = [
    "https://www.ufc.com/events",
]

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

TZ_MAP = {
    "EDT": EASTERN,
    "EST": EASTERN,
    "ET": EASTERN,
    "PDT": PACIFIC,
    "PST": PACIFIC,
    "PT": PACIFIC,
}

# Typical UFC.com text:
# McGregor vs Holloway 2 Sat, Jul 11 / 9:00 PM EDT / Main Card
# Du Plessis vs Usman Sat, Jul 18 / 8:00 PM EDT / Main Card
EVENT_RE = re.compile(
    r"(?P<title>.{3,120}?)\s+"
    r"(?P<weekday>Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+"
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+"
    r"(?P<day>[0-3]?\d)\s*/\s*"
    r"(?P<hour>[0-1]?\d):(?P<minute>[0-5]\d)\s*"
    r"(?P<ampm>AM|PM)\s*"
    r"(?P<tz>EDT|EST|ET|PDT|PST|PT)?\s*/\s*"
    r"(?P<card>Early Prelims|Prelims|Main Card)",
    flags=re.IGNORECASE,
)


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Secret_DE_EPG UFC Scraper Test",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json,*/*",
            "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read(2_000_000)
    return raw.decode("utf-8", errors="replace")


def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<style\b.*?</style>", " ", html)
    text = re.sub(r"(?is)<script\b.*?</script>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip(" -–—|•\t\r\n")

    # UFC.com navigation/card labels sometimes stick to the title.
    cut_markers = [
        "View Event Details",
        "How to Watch",
        "Tickets",
        "Watch On-the-Go",
        "Download the UFC Mobile App",
        "Find a bar",
        "Watch Live in Bar",
        "Start Times",
        "Upcoming",
        "Showing this event live on pay-per-view",
        "What'S Trending Now Sponsored By",
        "What's Trending Now Sponsored By",
        "Events 1 UFC 329",
    ]
    for marker in cut_markers:
        if marker in title:
            title = title.split(marker, 1)[-1].strip()

    # Keep final compact chunk if title still contains too much.
    if len(title) > 80:
        parts = re.split(r"\b(?:View Fight Card|Watch On|See these athletes|Sponsored By|Upcoming|Filters)\b", title)
        parts = [p.strip(" -–—|") for p in parts if p.strip(" -–—|")]
        if parts:
            title = parts[-1]

    title = title.strip(" -–—|")
    title = re.sub(r"^(?:Event Details\s*)+", "", title, flags=re.I)
    return title[:100].strip()


def parse_ufc_datetime(month: str, day: str, hour: str, minute: str, ampm: str, tz_text: str | None) -> datetime:
    now = datetime.now(timezone.utc).astimezone(BERLIN)
    year = now.year
    month_num = MONTHS[month.casefold()]
    h = int(hour)
    m = int(minute)

    if ampm.upper() == "PM" and h != 12:
        h += 12
    if ampm.upper() == "AM" and h == 12:
        h = 0

    zone = TZ_MAP.get((tz_text or "ET").upper(), EASTERN)
    dt = datetime(year, month_num, int(day), h, m, tzinfo=zone)

    # If the date is already far in the past, assume next year.
    if dt.astimezone(BERLIN) < now - timedelta(days=14):
        dt = datetime(year + 1, month_num, int(day), h, m, tzinfo=zone)

    return dt.astimezone(BERLIN)


def duration_for_card(card: str) -> timedelta:
    card_l = card.casefold()
    if "early" in card_l:
        return timedelta(hours=2)
    if "prelims" in card_l:
        return timedelta(hours=2)
    return timedelta(hours=3)


def assign_channels(events: list[dict]) -> list[dict]:
    active: dict[int, datetime] = {}

    for event in sorted(events, key=lambda e: (e["start_dt"], e["title"], e["card"])):
        chosen = None
        for number in range(1, 6):
            if number not in active or active[number] <= event["start_dt"]:
                chosen = number
                break
        if chosen is None:
            chosen = 5

        event["channel"] = f"ufcfightpass.event.{chosen:02d}"
        active[chosen] = event["stop_dt"]

    return events


def scrape_ufc() -> tuple[list[dict], list[dict]]:
    debug_pages = []
    raw_events = []

    for url in URLS:
        page = {
            "url": url,
            "ok": False,
            "error": "",
            "bytes": 0,
            "matches": 0,
        }

        try:
            html = fetch(url)
            page["ok"] = True
            page["bytes"] = len(html.encode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            page["error"] = f"HTTPError {exc.code}: {exc.reason}"
            debug_pages.append(page)
            continue
        except Exception as exc:
            page["error"] = f"{type(exc).__name__}: {exc}"
            debug_pages.append(page)
            continue

        text = html_to_text(html)
        seen_on_page = set()

        for match in EVENT_RE.finditer(text):
            title = clean_title(match.group("title"))
            card = match.group("card").strip()

            # We keep all card entries, but title must be meaningful.
            if not title or len(title) < 3:
                continue
            if title.casefold() in {"early prelims", "prelims", "main card"}:
                continue

            start_dt = parse_ufc_datetime(
                match.group("month"),
                match.group("day"),
                match.group("hour"),
                match.group("minute"),
                match.group("ampm"),
                match.group("tz"),
            )
            stop_dt = start_dt + duration_for_card(card)

            key = (title.casefold(), start_dt.isoformat(), card.casefold())
            if key in seen_on_page:
                continue
            seen_on_page.add(key)

            raw_events.append({
                "source": "ufc_com",
                "source_url": url,
                "title": title,
                "category": "MMA",
                "card": card,
                "start_dt": start_dt,
                "stop_dt": stop_dt,
                "desc": f"UFC.com Event: {title} ({card})",
            })

        page["matches"] = len(seen_on_page)
        debug_pages.append(page)

    # Global de-duplication.
    deduped = []
    seen_global = set()
    for event in sorted(raw_events, key=lambda e: (e["start_dt"], e["title"], e["card"])):
        key = (event["title"].casefold(), event["start_dt"].isoformat(), event["card"].casefold())
        if key in seen_global:
            continue
        seen_global.add(key)
        deduped.append(event)

    deduped = assign_channels(deduped)
    return deduped, debug_pages


def serializable_event(event: dict) -> dict:
    return {
        "source": event["source"],
        "source_url": event["source_url"],
        "channel": event["channel"],
        "start": event["start_dt"].isoformat(),
        "stop": event["stop_dt"].isoformat(),
        "title": event["title"],
        "category": event["category"],
        "card": event["card"],
        "desc": event["desc"],
    }


def main() -> int:
    events, pages = scrape_ufc()
    serializable = [serializable_event(e) for e in events]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "ufc_com",
        "event_count": len(serializable),
        "pages": pages,
        "events": serializable,
    }

    (OUT_DIR / "ufc-events.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = []
    lines.append(f"UFC scraper test generated at {payload['generated_at']}")
    lines.append(f"event_count: {len(serializable)}")
    lines.append("")
    lines.append("Pages:")
    for page in pages:
        lines.append(f"- {page['url']}")
        lines.append(f"  ok={page['ok']} bytes={page['bytes']} matches={page['matches']} error={page['error']}")
    lines.append("")
    lines.append("Events:")
    for event in serializable:
        lines.append(
            f"- {event['channel']} | {event['start']} - {event['stop']} | "
            f"{event['title']} | {event['card']} | {event['category']}"
        )
        lines.append(f"  {event['source_url']}")

    (OUT_DIR / "ufc-events.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"UFC events found: {len(serializable)}")
    print(f"Wrote {OUT_DIR / 'ufc-events.json'}")
    print(f"Wrote {OUT_DIR / 'ufc-events.txt'}")

    # Always succeed. This is a test scraper.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
