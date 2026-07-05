#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RTL+ scraper test for Secret_DE_EPG.

This is a safe standalone test:
- It does NOT modify public/sports-events.xml.xz.
- It does NOT deploy GitHub Pages.
- It only creates rtlplus-results/rtlplus-events.json and .txt as an Actions artifact.

Goal:
Extract upcoming RTL+ live sport events from public RTL+ pages and map them to
rtlplus.sport.01, rtlplus.sport.02, ...

After this test is verified, the logic can be integrated into build_sports_events.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
import json
import re
import urllib.error
import urllib.request


OUT_DIR = Path("rtlplus-results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

BERLIN = timezone(timedelta(hours=2))

URLS = [
    "https://plus.rtl.de/live-events",
    "https://plus.rtl.de/rtlplus-root/sport-main-root-service-f_6",
]

SPORT_WORDS = [
    "MMA",
    "Motorsport",
    "Fußball",
    "Fussball",
    "Sport",
    "NFL",
    "American Football",
    "Show",
]

# Handles examples from the probe:
# OKTAGON 91 MMA • Ab 18 • Sa., 11.07.26, 17:15 Uhr
# 6 Stunden von São Paulo 2026 Motorsport • So., 12.07.26, 16:30 Uhr
EVENT_RE = re.compile(
    r"(?P<title>.{3,140}?)\s+"
    r"(?P<sport>MMA|Motorsport|Fußball|Fussball|Sport|NFL|American Football|Show)"
    r"\s+•\s+"
    r"(?:Ab\s+\d+\s+•\s+)?"
    r"(?P<weekday>Mo|Di|Mi|Do|Fr|Sa|So)\.,\s+"
    r"(?P<day>[0-3]\d)\.(?P<month>[01]\d)\.(?P<year>\d{2}),\s+"
    r"(?P<hour>[0-2]\d):(?P<minute>[0-5]\d)\s+Uhr",
    flags=re.IGNORECASE,
)


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Secret_DE_EPG RTLPlus Scraper Test",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json,*/*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read(1_500_000)
    return raw.decode("utf-8", errors="replace")


def html_to_text(html: str) -> str:
    # Keep scripts because RTL+ often stores useful text in rendered or embedded data.
    text = re.sub(r"(?is)<style\b.*?</style>", " ", html)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    text = text.replace("\\u0026", "&")
    text = text.replace("\\u003c", "<").replace("\\u003e", ">")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip(" -–—|•\t\r\n")
    # Remove obvious navigation leftovers that can appear before the first title.
    cut_markers = [
        "Sport im Livestream",
        "Die nächsten Live-Events",
        "Start Alles Serien Filme Shows Themenwelten Live-TV Sport Audio Suche Paket wählen Profil und Einstellungen",
    ]
    for marker in cut_markers:
        if marker in title:
            title = title.split(marker, 1)[-1].strip()
    # Take the last reasonable chunk if still too long.
    if len(title) > 90:
        chunks = re.split(r"\s{2,}| Mehr Details | Alles zur | Sport im Überblick ", title)
        chunks = [c.strip() for c in chunks if c.strip()]
        if chunks:
            title = chunks[-1]
    return title[:120].strip()


def parse_dt(day: str, month: str, year: str, hour: str, minute: str) -> datetime:
    full_year = 2000 + int(year)
    return datetime(
        full_year,
        int(month),
        int(day),
        int(hour),
        int(minute),
        tzinfo=BERLIN,
    )


def default_duration(title: str, sport: str) -> timedelta:
    text = f"{title} {sport}".casefold()
    if "oktagon" in text or "mma" in text:
        return timedelta(hours=5)
    if "motorsport" in text or "stunden von" in text or "le mans" in text:
        return timedelta(hours=4)
    if "football" in text or "nfl" in text:
        return timedelta(hours=3, minutes=30)
    if "fußball" in text or "fussball" in text:
        return timedelta(hours=2, minutes=30)
    return timedelta(hours=2)


def assign_channels(events: list[dict]) -> list[dict]:
    """
    Assign rtlplus.sport.01 ... rtlplus.sport.20.
    If events overlap, use the next free channel. If not, reuse 01.
    """
    active: dict[int, datetime] = {}

    for event in sorted(events, key=lambda e: (e["start_dt"], e["title"])):
        chosen = None
        for number in range(1, 21):
            if number not in active or active[number] <= event["start_dt"]:
                chosen = number
                break
        if chosen is None:
            chosen = 20

        event["channel"] = f"rtlplus.sport.{chosen:02d}"
        active[chosen] = event["stop_dt"]

    return events


def scrape_rtlplus() -> tuple[list[dict], list[dict]]:
    debug_pages = []
    raw_events = []

    for url in URLS:
        page_info = {
            "url": url,
            "ok": False,
            "error": "",
            "bytes": 0,
            "matches": 0,
        }

        try:
            html = fetch(url)
            page_info["ok"] = True
            page_info["bytes"] = len(html.encode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            page_info["error"] = f"HTTPError {exc.code}: {exc.reason}"
            debug_pages.append(page_info)
            continue
        except Exception as exc:
            page_info["error"] = f"{type(exc).__name__}: {exc}"
            debug_pages.append(page_info)
            continue

        text = html_to_text(html)
        seen_on_page = set()

        for match in EVENT_RE.finditer(text):
            title = clean_title(match.group("title"))
            sport = match.group("sport").strip()

            if not title or len(title) < 3:
                continue

            start_dt = parse_dt(
                match.group("day"),
                match.group("month"),
                match.group("year"),
                match.group("hour"),
                match.group("minute"),
            )
            stop_dt = start_dt + default_duration(title, sport)

            key = (title.casefold(), start_dt.isoformat())
            if key in seen_on_page:
                continue
            seen_on_page.add(key)

            raw_events.append({
                "source": "rtlplus",
                "source_url": url,
                "title": title,
                "category": sport,
                "start_dt": start_dt,
                "stop_dt": stop_dt,
                "desc": f"RTL+ Live-Event: {title} ({sport})",
            })

        page_info["matches"] = len(seen_on_page)
        debug_pages.append(page_info)

    # Global de-duplication across both RTL+ pages.
    deduped = []
    seen_global = set()
    for event in sorted(raw_events, key=lambda e: (e["start_dt"], e["title"])):
        key = (event["title"].casefold(), event["start_dt"].isoformat())
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
        "desc": event["desc"],
    }


def main() -> int:
    events, pages = scrape_rtlplus()
    serializable = [serializable_event(e) for e in events]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "rtlplus",
        "event_count": len(serializable),
        "pages": pages,
        "events": serializable,
    }

    (OUT_DIR / "rtlplus-events.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = []
    lines.append(f"RTL+ scraper test generated at {payload['generated_at']}")
    lines.append(f"event_count: {len(serializable)}")
    lines.append("")
    lines.append("Pages:")
    for page in pages:
        lines.append(f"- {page['url']}")
        lines.append(f"  ok={page['ok']} bytes={page['bytes']} matches={page['matches']} error={page['error']}")
    lines.append("")
    lines.append("Events:")
    for event in serializable:
        lines.append(f"- {event['channel']} | {event['start']} - {event['stop']} | {event['title']} | {event['category']}")
        lines.append(f"  {event['source_url']}")

    (OUT_DIR / "rtlplus-events.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"RTL+ events found: {len(serializable)}")
    print(f"Wrote {OUT_DIR / 'rtlplus-events.json'}")
    print(f"Wrote {OUT_DIR / 'rtlplus-events.txt'}")

    # Always succeed. This is a test scraper.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
