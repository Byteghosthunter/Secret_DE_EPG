#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DYN Sport scraper test for Secret_DE_EPG.

Safe standalone test:
- Does NOT modify public/sports-events.xml.xz.
- Does NOT deploy GitHub Pages.
- Creates dyn-results/dyn-events.json and .txt as an Actions artifact.

Goal:
1. Check which DYN pages contain real dates/times.
2. Extract possible upcoming event candidates.
3. Map candidates to dyn.sport.01, dyn.sport.02, ...

This is intentionally conservative. If DYN only exposes category pages and not
real fixtures in static HTML, this test will show that clearly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
import json
import re
import urllib.error
import urllib.request


OUT_DIR = Path("dyn-results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

BERLIN = timezone(timedelta(hours=2))

SEED_URLS = [
    "https://www.dyn.sport/deinsender/programm/",
    "https://www.dyn.sport/deinsender/handball-spielplaene/",
    "https://www.dyn.sport/deinsender/basketball-spielplane/",
    "https://www.dyn.sport/deinsender/volleyball-spielplaene/",
    "https://www.dyn.sport/deinsender/tischtennis-spielplaene/",
]

SPORT_HINTS = {
    "handball": "Handball",
    "hbl": "Handball",
    "dhb": "Handball",
    "ehf": "Handball",
    "basketball": "Basketball",
    "bbl": "Basketball",
    "volleyball": "Volleyball",
    "tischtennis": "Tischtennis",
    "ttbl": "Tischtennis",
    "hockey": "Hockey",
}

DATE_TIME_RE = re.compile(
    r"(?:(?P<weekday>Mo|Di|Mi|Do|Fr|Sa|So)\.,?\s*)?"
    r"(?P<day>[0-3]?\d)\.(?P<month>[01]?\d)\.(?P<year>\d{2,4})"
    r"(?:,|\s)+"
    r"(?P<hour>[0-2]?\d):(?P<minute>[0-5]\d)"
    r"(?:\s*Uhr)?",
    flags=re.IGNORECASE,
)

DATE_ONLY_RE = re.compile(
    r"(?:(?:Mo|Di|Mi|Do|Fr|Sa|So)\.,?\s*)?"
    r"[0-3]?\d\.[01]?\d\.(?:\d{2,4})",
    flags=re.IGNORECASE,
)


def fetch(url: str) -> tuple[str, dict]:
    info = {
        "url": url,
        "ok": False,
        "error": "",
        "bytes": 0,
        "final_url": url,
        "content_type": "",
    }

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Secret_DE_EPG DYN Scraper Test",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json,*/*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read(1_500_000)
            info["ok"] = True
            info["bytes"] = len(raw)
            info["final_url"] = resp.geturl()
            info["content_type"] = resp.headers.get("content-type", "")
            return raw.decode("utf-8", errors="replace"), info
    except urllib.error.HTTPError as exc:
        info["error"] = f"HTTPError {exc.code}: {exc.reason}"
        return "", info
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        return "", info


def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<script\b.*?</script>", " ", html)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_links(html: str, base_url: str) -> list[str]:
    links = []
    for href in re.findall(r"(?i)<a\b[^>]+href=[\"']([^\"']+)[\"']", html):
        href = unescape(href).strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        url = urljoin(base_url, href)
        if "dyn.sport" not in url:
            continue
        if any(token in url.casefold() for token in [
            "spielplan", "spielplaene", "programm", "handball", "basketball",
            "volleyball", "tischtennis", "hockey", "live"
        ]):
            links.append(url.split("#", 1)[0])
    return sorted(set(links))


def infer_sport(url: str, text: str) -> str:
    blob = f"{url} {text[:1000]}".casefold()
    for key, value in SPORT_HINTS.items():
        if key in blob:
            return value
    return "Sport"


def clean_title(raw: str) -> str:
    raw = re.sub(r"\s+", " ", raw)
    raw = raw.strip(" -–—|•\t\r\n")
    fragments = [
        "HANDBALL ÜBERSICHT",
        "BASKETBALL ÜBERSICHT",
        "VOLLEYBALL ÜBERSICHT",
        "TISCHTENNIS ÜBERSICHT",
        "HOCKEY ÜBERSICHT",
        "NEWSLETTER",
        "Dyn MOVE YOUR SPORT",
        "Seite wählen",
        "Aktuelle Spielpläne",
        "Spielpläne",
        "Spielplan",
    ]
    for frag in fragments:
        if frag in raw:
            raw = raw.split(frag)[-1].strip(" -–—|")
    if len(raw) > 120:
        raw = raw[-120:].strip(" -–—|")
    return raw[:120].strip()


def parse_dt(day: str, month: str, year: str, hour: str, minute: str) -> datetime:
    y = int(year)
    if y < 100:
        y += 2000
    return datetime(y, int(month), int(day), int(hour), int(minute), tzinfo=BERLIN)


def event_duration(sport: str, title: str) -> timedelta:
    text = f"{sport} {title}".casefold()
    if "handball" in text:
        return timedelta(hours=2)
    if "basketball" in text:
        return timedelta(hours=2, minutes=15)
    if "volleyball" in text:
        return timedelta(hours=2, minutes=30)
    if "tischtennis" in text:
        return timedelta(hours=2)
    if "hockey" in text:
        return timedelta(hours=2)
    return timedelta(hours=2)


def extract_event_candidates(url: str, text: str) -> list[dict]:
    events = []
    sport = infer_sport(url, text)
    now = datetime.now(timezone.utc).astimezone(BERLIN)

    for match in DATE_TIME_RE.finditer(text):
        start = parse_dt(
            match.group("day"),
            match.group("month"),
            match.group("year"),
            match.group("hour"),
            match.group("minute"),
        )
        stop = start + event_duration(sport, "")

        if stop < now - timedelta(hours=2):
            continue

        prefix = text[max(0, match.start() - 180):match.start()]
        suffix = text[match.end():match.end() + 120]
        title = clean_title(prefix)

        if len(title) < 5 or title.casefold() in {"programm", "spielplan", "spielpläne"}:
            title = clean_title(suffix)

        if not title:
            title = f"DYN {sport} Event"

        events.append({
            "source": "dyn_test",
            "source_url": url,
            "title": title,
            "category": sport,
            "start_dt": start,
            "stop_dt": stop,
            "desc": f"DYN Sport candidate: {title} ({sport})",
            "raw_context": text[max(0, match.start() - 220):match.end() + 220],
        })

    return events


def assign_channels(events: list[dict]) -> list[dict]:
    active: dict[int, datetime] = {}
    for event in sorted(events, key=lambda e: (e["start_dt"], e["title"])):
        chosen = None
        for number in range(1, 26):
            if number not in active or active[number] <= event["start_dt"]:
                chosen = number
                break
        if chosen is None:
            chosen = 25
        event["channel"] = f"dyn.sport.{chosen:02d}"
        active[chosen] = event["stop_dt"]
    return events


def serialize_event(event: dict) -> dict:
    return {
        "source": event["source"],
        "source_url": event["source_url"],
        "channel": event.get("channel", ""),
        "start": event["start_dt"].isoformat(),
        "stop": event["stop_dt"].isoformat(),
        "title": event["title"],
        "category": event["category"],
        "desc": event["desc"],
        "raw_context": event["raw_context"],
    }


def main() -> int:
    pages = []
    all_links = set()
    raw_candidates = []

    for url in SEED_URLS:
        html, info = fetch(url)
        text = html_to_text(html)
        info["text_length"] = len(text)
        info["date_time_matches"] = len(DATE_TIME_RE.findall(text))
        info["date_only_matches"] = len(DATE_ONLY_RE.findall(text))
        links = extract_links(html, url)
        info["candidate_links"] = links[:60]
        info["candidate_link_count"] = len(links)
        info["snippet"] = text[:1600]
        pages.append(info)
        all_links.update(links)
        raw_candidates.extend(extract_event_candidates(url, text))

    followed = []
    for url in sorted(all_links)[:40]:
        if url in SEED_URLS:
            continue
        html, info = fetch(url)
        text = html_to_text(html)
        info["text_length"] = len(text)
        info["date_time_matches"] = len(DATE_TIME_RE.findall(text))
        info["date_only_matches"] = len(DATE_ONLY_RE.findall(text))
        info["snippet"] = text[:1000]
        followed.append(info)
        raw_candidates.extend(extract_event_candidates(url, text))

    deduped = []
    seen = set()
    for event in sorted(raw_candidates, key=lambda e: (e["start_dt"], e["title"])):
        key = (event["title"].casefold(), event["start_dt"].isoformat(), event["source_url"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)

    deduped = assign_channels(deduped)
    serializable = [serialize_event(e) for e in deduped]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "dyn",
        "event_count": len(serializable),
        "seed_pages": pages,
        "followed_pages": followed,
        "events": serializable,
    }

    (OUT_DIR / "dyn-events.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = []
    lines.append(f"DYN scraper test generated at {payload['generated_at']}")
    lines.append(f"event_count: {len(serializable)}")
    lines.append("")
    lines.append("Seed pages:")
    for page in pages:
        lines.append(f"- {page['url']}")
        lines.append(
            f"  ok={page['ok']} bytes={page['bytes']} date_time={page['date_time_matches']} "
            f"date_only={page['date_only_matches']} links={page['candidate_link_count']} error={page['error']}"
        )
    lines.append("")
    lines.append("Followed pages:")
    for page in followed:
        lines.append(f"- {page['url']}")
        lines.append(
            f"  ok={page['ok']} bytes={page['bytes']} date_time={page['date_time_matches']} "
            f"date_only={page['date_only_matches']} error={page['error']}"
        )
    lines.append("")
    lines.append("Events:")
    for event in serializable:
        lines.append(
            f"- {event['channel']} | {event['start']} - {event['stop']} | "
            f"{event['title']} | {event['category']}"
        )
        lines.append(f"  {event['source_url']}")
        lines.append(f"  context: {event['raw_context'][:260]}")

    (OUT_DIR / "dyn-events.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"DYN candidates found: {len(serializable)}")
    print(f"Wrote {OUT_DIR / 'dyn-events.json'}")
    print(f"Wrote {OUT_DIR / 'dyn-events.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
