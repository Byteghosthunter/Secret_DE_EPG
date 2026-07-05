#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFC.com scraper test V2 for Secret_DE_EPG.

Safe standalone test:
- Does NOT modify public/sports-events.xml.xz.
- Does NOT deploy GitHub Pages.
- Creates ufc-results/ufc-events.json and .txt as an Actions artifact.

V2 fixes:
- Ignore Past / Watch Replay blocks.
- Keep only upcoming events.
- Avoid bogus next-year conversion for past/replay events.
- Clean titles more aggressively.
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

URL = "https://www.ufc.com/events"

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

EVENT_RE = re.compile(
    r"(?P<title>.{3,140}?)\s+"
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
            "User-Agent": "Mozilla/5.0 Secret_DE_EPG UFC Scraper Test V2",
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


def upcoming_only(text: str) -> str:
    """
    UFC.com often contains Upcoming and Past blocks on the same page.
    We only want the upcoming block.
    """
    # Start close to "Upcoming ... Events". If not found, use whole text.
    m = re.search(r"\bUpcoming\b.*?\bEvents\b", text, flags=re.I)
    if m:
        text = text[m.start():]

    # Cut before obvious past/replay area.
    cut_patterns = [
        r"\bPast\b\s+\d+\s+Filters\b",
        r"\bLoad More Past\b",
        r"\bWatch Replay\b",
        r"\bPast Events\b",
    ]
    cuts = []
    for pat in cut_patterns:
        mm = re.search(pat, text, flags=re.I)
        if mm:
            cuts.append(mm.start())
    if cuts:
        text = text[:min(cuts)]

    return text


def clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip(" -–—|•\t\r\n")

    # Remove sticky navigation/marketing fragments.
    fragments = [
        "Upcoming",
        "Filters",
        "How to Watch",
        "Start Times",
        "Early Prelims",
        "Prelims",
        "Main Card",
        "Watch On",
        "Watch on UFC Fight Pass",
        "Watch Live in Bar",
        "Find a bar",
        "View Event Details",
        "Tickets",
        "Fight Card",
        "View Fight Card",
        "See these athletes in action at",
        "Watch On-the-Go",
        "Download the UFC Mobile App",
        "What'S Trending Now Sponsored By",
        "What's Trending Now Sponsored By",
        "Sponsored By",
        "Showing this event live on pay-per-view",
    ]

    # Keep the text after the last known fragment.
    for fragment in fragments:
        if fragment in title:
            title = title.split(fragment)[-1].strip(" -–—|")

    # Remove leading "number UFC xxx" fragments.
    title = re.sub(r"^\d+\s+UFC\s+\d+\s+", "", title, flags=re.I).strip()
    title = re.sub(r"^UFC\s+\d+\s+", "", title, flags=re.I).strip()

    # If title is still too long, take the final likely fight-name chunk.
    if len(title) > 80:
        parts = re.split(r"\b(?:Tickets|How to Watch|View Event Details|Watch On|Fight Card|United States|Azerbaijan|Las Vegas|Oklahoma City|T-Mobile Arena|Paycom Center)\b", title)
        parts = [p.strip(" -–—|,") for p in parts if p.strip(" -–—|,")]
        if parts:
            title = parts[-1]

    title = title.strip(" -–—|,")
    return title[:100].strip()


def is_bad_title(title: str) -> bool:
    bad = [
        "Load More Past",
        "Watch Replay",
        "Fight Card Watch Replay",
        "Past",
        "Filters",
        "Events",
        "View Event Details",
        "How to Watch",
    ]
    title_l = title.casefold()
    return any(b.casefold() in title_l for b in bad) or len(title) < 3


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
    dt = datetime(year, month_num, int(day), h, m, tzinfo=zone).astimezone(BERLIN)

    # For UFC page: keep only real upcoming dates. If it's already more than
    # two hours old, discard later instead of converting to next year.
    return dt


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


def scrape_ufc() -> tuple[list[dict], dict]:
    page = {
        "url": URL,
        "ok": False,
        "error": "",
        "bytes": 0,
        "matches_raw": 0,
        "matches_kept": 0,
        "dropped_past": 0,
        "dropped_bad_title": 0,
        "dropped_duplicate": 0,
    }

    raw_events = []
    now = datetime.now(timezone.utc).astimezone(BERLIN)

    try:
        html = fetch(URL)
        page["ok"] = True
        page["bytes"] = len(html.encode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        page["error"] = f"HTTPError {exc.code}: {exc.reason}"
        return [], page
    except Exception as exc:
        page["error"] = f"{type(exc).__name__}: {exc}"
        return [], page

    text = upcoming_only(html_to_text(html))
    seen = set()

    for match in EVENT_RE.finditer(text):
        page["matches_raw"] += 1

        title = clean_title(match.group("title"))
        card = match.group("card").strip()

        if is_bad_title(title):
            page["dropped_bad_title"] += 1
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

        if stop_dt < now - timedelta(hours=2):
            page["dropped_past"] += 1
            continue

        key = (title.casefold(), start_dt.isoformat(), card.casefold())
        if key in seen:
            page["dropped_duplicate"] += 1
            continue
        seen.add(key)

        raw_events.append({
            "source": "ufc_com",
            "source_url": URL,
            "title": title,
            "category": "MMA",
            "card": card,
            "start_dt": start_dt,
            "stop_dt": stop_dt,
            "desc": f"UFC.com Event: {title} ({card})",
        })

    raw_events = assign_channels(raw_events)
    page["matches_kept"] = len(raw_events)
    return raw_events, page


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
    events, page = scrape_ufc()
    serializable = [serializable_event(e) for e in events]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "ufc_com",
        "event_count": len(serializable),
        "page": page,
        "events": serializable,
    }

    (OUT_DIR / "ufc-events.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = []
    lines.append(f"UFC scraper test V2 generated at {payload['generated_at']}")
    lines.append(f"event_count: {len(serializable)}")
    lines.append("")
    lines.append("Page:")
    lines.append(f"- {page['url']}")
    for key in ["ok", "bytes", "matches_raw", "matches_kept", "dropped_past", "dropped_bad_title", "dropped_duplicate", "error"]:
        lines.append(f"  {key}: {page.get(key)}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
