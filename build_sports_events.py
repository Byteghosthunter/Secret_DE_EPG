#!/usr/bin/env python3
"""
Secret_DE_EPG builder
- Creates XMLTV + EPGImport files for GitHub Pages
- Includes fixed channel IDs for RTL+, DAZN, DYN, Amazon, Discovery, Eurosport, Sporteurope
- First DAZN prototype: pulls public DAZN schedule page and maps visible events into DAZN groups.

No external Python packages required.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape as xesc, unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import json
import lzma
import os
import re
import sys
import urllib.error
import urllib.request

# --- Paths -----------------------------------------------------------------
HERE = Path(__file__).resolve()
if HERE.parent.name == "builder":
    ROOT = HERE.parents[1]
else:
    ROOT = HERE.parent

PUBLIC = ROOT / "public"
EPGIMPORT = PUBLIC / "epgimport"
PUBLIC.mkdir(parents=True, exist_ok=True)
EPGIMPORT.mkdir(parents=True, exist_ok=True)

GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "byteghosthunter")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Secret_DE_EPG")
BASE_URL = f"https://{GITHUB_OWNER.lower()}.github.io/{GITHUB_REPO}"

BERLIN = timezone(timedelta(hours=2))  # Simple fixed offset for now; good for summer. Later: zoneinfo Europe/Berlin.

# --- Channel definitions ----------------------------------------------------
channels: List[Tuple[str, str]] = []
seen_channels = set()


def add_channel(channel_id: str, name: str) -> None:
    if channel_id not in seen_channels:
        channels.append((channel_id, name))
        seen_channels.add(channel_id)


def add_range(prefix: str, label: str, start: int, end: int, suffix: str = "") -> None:
    for i in range(start, end + 1):
        name = f"{label} {i}"
        if suffix:
            name = f"{name} {suffix}"
        add_channel(f"{prefix}.{i:02d}", name)


# RTL+
add_range("rtlplus.sport", "RTL+ SPORT", 1, 20, "FHD")

# DAZN general + categories
add_range("dazn.event", "DAZN Event", 1, 10, "FHD")
add_range("dazn.bundesliga", "DAZN Bundesliga", 1, 10, "FHD")
add_range("dazn.laliga", "DAZN LaLiga", 1, 10, "FHD")
add_range("dazn.ufc", "DAZN UFC", 1, 10, "FHD")
add_range("dazn.nba", "DAZN NBA", 1, 10, "FHD")
add_range("dazn.nfl", "DAZN NFL", 1, 10, "FHD")
add_range("dazn.ligue1", "DAZN Ligue 1", 1, 10, "FHD")
add_range("dazn.seriea", "DAZN Serie A", 1, 10, "FHD")

# DYN
add_range("dyn.sport", "DYN Sport", 1, 25)

# Amazon / Prime
add_range("amazon.live", "Amazon Live Event", 1, 8)
add_range("prime.event", "Amazon Prime Event", 1, 9)

# Discovery / Eurosport
add_range("discovery.extra", "Discovery Extra", 1, 16)
add_range("eurosport.extra", "Eurosport Extra", 1, 16)

# SportDeutschland / Sporteurope
add_range("sporteurope.tv", "SportDeutschland.TV", 1, 20)
add_channel("sporteurope.del2", "Sport.DE DEL 2")

# --- Event model ------------------------------------------------------------
@dataclass
class Event:
    channel: str
    start: datetime
    stop: datetime
    title: str
    category: str = "Sport"
    desc: str = ""
    source: str = ""


def xml_time(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # XMLTV time in +0200 for now. Later we can switch to zoneinfo Europe/Berlin.
    return dt.astimezone(BERLIN).strftime("%Y%m%d%H%M%S +0200")


# --- HTTP helpers -----------------------------------------------------------
def fetch_url(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Secret_DE_EPG/0.2",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return data.decode("utf-8", errors="replace")


# --- DAZN parsing -----------------------------------------------------------
DAZN_SCHEDULE_URLS = [
    "https://www.dazn.com/de-DE/schedule",
    "https://www.dazn.com/en-DE/schedule",
]

DATE_RE = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\b", re.I)
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_a = False
        self.current_href = ""
        self.current_text: List[str] = []
        self.anchors: List[Tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "a":
            self.in_a = True
            self.current_text = []
            attrs_d = dict(attrs)
            self.current_href = attrs_d.get("href") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self.in_a:
            text = re.sub(r"\s+", " ", unescape("".join(self.current_text))).strip()
            if text:
                self.anchors.append((text, self.current_href))
            self.in_a = False
            self.current_href = ""
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.in_a:
            self.current_text.append(data)


def strip_tags(html_text: str) -> str:
    html_text = re.sub(r"(?is)<script.*?</script>", " ", html_text)
    html_text = re.sub(r"(?is)<style.*?</style>", " ", html_text)
    text = re.sub(r"(?s)<[^>]+>", " ", html_text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_iso_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # DAZN/JSON APIs sometimes use epoch milliseconds.
        if value > 10_000_000_000:
            value = value / 1000
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except Exception:
            return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # ISO formats
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    # epoch in string
    if re.fullmatch(r"\d{10,13}", s):
        try:
            v = int(s)
            if v > 10_000_000_000:
                v = v / 1000
            return datetime.fromtimestamp(v, tz=timezone.utc)
        except Exception:
            return None
    return None


def walk_json(obj: Any) -> Iterable[Any]:
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk_json(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_json(v)


def extract_dazn_json_events(html_text: str) -> List[Dict[str, Any]]:
    """Try to extract events from embedded JSON structures, if DAZN exposes them."""
    events: List[Dict[str, Any]] = []
    candidates: List[str] = []

    # Common Next.js data block.
    for m in re.finditer(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html_text, re.S | re.I):
        candidates.append(unescape(m.group(1)))

    # Other script application/json blobs.
    for m in re.finditer(r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>', html_text, re.S | re.I):
        blob = unescape(m.group(1)).strip()
        if blob.startswith("{") or blob.startswith("["):
            candidates.append(blob)

    for blob in candidates:
        try:
            data = json.loads(blob)
        except Exception:
            continue
        for item in walk_json(data):
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("name") or item.get("assetTitle") or item.get("eventTitle")
            start = None
            for key in ("startDate", "startTime", "start", "airingStartTime", "scheduledStartTime", "begin", "startAt"):
                start = parse_iso_datetime(item.get(key))
                if start:
                    break
            if title and start:
                sport = item.get("sport") or item.get("sportName") or item.get("category") or ""
                comp = item.get("competition") or item.get("competitionName") or item.get("league") or ""
                duration = item.get("duration") or item.get("durationSeconds") or item.get("durationInSeconds")
                stop = None
                for key in ("endDate", "endTime", "end", "airingEndTime", "scheduledEndTime", "endAt"):
                    stop = parse_iso_datetime(item.get(key))
                    if stop:
                        break
                if not stop:
                    minutes = 180
                    try:
                        if duration:
                            d = int(duration)
                            minutes = d // 60 if d > 1000 else d
                    except Exception:
                        pass
                    stop = start + timedelta(minutes=max(30, min(minutes, 360)))
                events.append({
                    "title": str(title),
                    "sport": str(sport),
                    "competition": str(comp),
                    "start": start,
                    "stop": stop,
                    "source": "DAZN JSON",
                })
    return dedupe_raw_events(events)


def dedupe_raw_events(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for e in items:
        key = (re.sub(r"\s+", " ", e.get("title", "")).strip().lower(), e.get("start"))
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def extract_dazn_anchor_events(html_text: str) -> List[Dict[str, Any]]:
    """Fallback: parse visible DAZN schedule anchors. Static page often exposes titles but not exact times."""
    parser = AnchorParser()
    try:
        parser.feed(html_text)
    except Exception:
        pass

    visible_text = strip_tags(html_text)
    year = datetime.now(BERLIN).year

    # Determine dates visible in the page. If no date can be attached to a title, use today.
    date_matches = [(m.start(), MONTHS[m.group(1).lower()], int(m.group(2))) for m in DATE_RE.finditer(visible_text)]
    default_date = datetime.now(BERLIN).date()

    events: List[Dict[str, Any]] = []
    slot_counter: Dict[Tuple[int, int], int] = {}

    ignored = {
        "start", "alle sportarten", "kalender", "news & stories", "willkommen", "hilfe", "impressum",
        "datenschutzerklärung und cookie-hinweis", "nutzungsbedingungen", "jetzt anmelden", "einloggen",
        "dazn group", "news", "einlösen", "ueber-uns", "mehr erfahren", "image",
    }

    for title, href in parser.anchors:
        t = re.sub(r"\s+", " ", title).strip()
        tl = t.lower()
        if not t or tl in ignored or len(t) < 5:
            continue
        if any(x in tl for x in ["datenschutz", "impressum", "anmelden", "einloggen", "hilfe"]):
            continue
        # Keep likely event titles: sport terms, separators, vs, race, match/card etc.
        likely = any(x in tl for x in [
            " vs. ", " vs ", " - ", " | ", "ufc", "nfl", "nba", "bundesliga", "laliga", "liga", "serie a",
            "ligue 1", "premier league", "fight", "boxing", "mma", "rennen", "qualifikation", "etappe", "world cup",
            "fifa", "basketball", "american football", "game pass",
        ])
        if not likely:
            continue

        # Try to infer date from occurrence in visible text.
        pos = visible_text.find(t)
        month = default_date.month
        day = default_date.day
        if pos >= 0 and date_matches:
            prev = [d for d in date_matches if d[0] <= pos]
            if prev:
                _, month, day = prev[-1]
        # Handle year rollover roughly.
        dt_date = datetime(year, month, day, 8, 0, tzinfo=BERLIN)
        if dt_date.date() < (datetime.now(BERLIN).date() - timedelta(days=2)):
            dt_date = dt_date.replace(year=year + 1)

        key = (dt_date.month, dt_date.day)
        idx = slot_counter.get(key, 0)
        slot_counter[key] = idx + 1
        # Fallback time slots if exact time is not exposed in static HTML.
        start_local = dt_date.replace(hour=8, minute=0) + timedelta(minutes=90 * idx)
        stop_local = start_local + timedelta(minutes=120)

        events.append({
            "title": t,
            "sport": "",
            "competition": "",
            "start": start_local.astimezone(timezone.utc),
            "stop": stop_local.astimezone(timezone.utc),
            "source": "DAZN visible schedule fallback",
        })
    return dedupe_raw_events(events)


def classify_dazn_event(title: str, sport: str = "", competition: str = "") -> Tuple[str, str, int]:
    text = f"{title} {sport} {competition}".lower()

    if "ufc" in text:
        return "dazn.ufc", "MMA / UFC", 10
    if "nfl" in text or "american football" in text or "game pass" in text:
        return "dazn.nfl", "American Football", 10
    if "nba" in text:
        return "dazn.nba", "Basketball / NBA", 10
    if "bundesliga" in text and "u19" not in text:
        return "dazn.bundesliga", "Fußball / Bundesliga", 10
    if "laliga" in text or "la liga" in text:
        return "dazn.laliga", "Fußball / LaLiga", 10
    if "ligue 1" in text or "ligue1" in text:
        return "dazn.ligue1", "Fußball / Ligue 1", 10
    # Avoid matching random "Serie" words; require Serie A specifically.
    if re.search(r"\bserie\s*a\b", text):
        return "dazn.seriea", "Fußball / Serie A", 10
    return "dazn.event", "Sport", 10


def build_dazn_events() -> Tuple[List[Event], Dict[str, Any]]:
    all_raw: List[Dict[str, Any]] = []
    errors: List[str] = []
    used_url = ""

    for url in DAZN_SCHEDULE_URLS:
        try:
            html_text = fetch_url(url)
            used_url = url
            raw = extract_dazn_json_events(html_text)
            if not raw:
                raw = extract_dazn_anchor_events(html_text)
            if raw:
                all_raw.extend(raw)
                break
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")

    all_raw = dedupe_raw_events(all_raw)
    all_raw.sort(key=lambda e: e.get("start") or datetime.now(timezone.utc))

    # Map into groups, distributing same-day events across .01-.10.
    group_day_counter: Dict[Tuple[str, str], int] = {}
    events: List[Event] = []
    now_utc = datetime.now(timezone.utc) - timedelta(hours=6)

    for raw in all_raw[:250]:
        title = raw.get("title", "").strip()
        if not title:
            continue
        start = raw.get("start")
        stop = raw.get("stop")
        if not isinstance(start, datetime):
            continue
        if not isinstance(stop, datetime) or stop <= start:
            stop = start + timedelta(hours=2)
        if stop < now_utc:
            continue

        prefix, category, max_n = classify_dazn_event(title, raw.get("sport", ""), raw.get("competition", ""))
        day_key = start.astimezone(BERLIN).strftime("%Y-%m-%d")
        counter_key = (prefix, day_key)
        n = group_day_counter.get(counter_key, 0) + 1
        group_day_counter[counter_key] = n
        channel_num = ((n - 1) % max_n) + 1
        channel = f"{prefix}.{channel_num:02d}"

        desc_parts = ["Quelle: DAZN Schedule"]
        if raw.get("competition"):
            desc_parts.append(f"Wettbewerb: {raw['competition']}")
        if raw.get("sport"):
            desc_parts.append(f"Sportart: {raw['sport']}")
        if raw.get("source") and "fallback" in raw.get("source", "").lower():
            desc_parts.append("Hinweis: Uhrzeit aus statischem Seiten-Fallback geschätzt; exakte Zeiten werden verfeinert, sobald JSON-Zeiten sichtbar sind.")

        events.append(Event(
            channel=channel,
            start=start,
            stop=stop,
            title=title,
            category=category,
            desc=" | ".join(desc_parts),
            source=raw.get("source", "DAZN"),
        ))

    meta = {
        "source": "DAZN",
        "url": used_url,
        "raw_events": len(all_raw),
        "mapped_events": len(events),
        "errors": errors,
    }
    return events, meta


# --- Manual/fallback events -------------------------------------------------
def fallback_events() -> List[Event]:
    """Keep the feed valid even if all websites fail."""
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    stop = start + timedelta(hours=2)
    return [
        Event(
            channel="dazn.event.01",
            start=start,
            stop=stop,
            title="DAZN EPG Builder aktiv",
            category="System",
            desc="Fallback-Eintrag. Wenn du das siehst, läuft GitHub Pages + EPGImport; echte DAZN-Daten wurden in diesem Lauf nicht gefunden.",
            source="fallback",
        )
    ]


# --- Output -----------------------------------------------------------------
def write_xmltv(events: List[Event]) -> str:
    lines: List[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<tv generator-info-name="Secret_DE_EPG">')

    for channel_id, name in channels:
        lines.append(f'  <channel id="{xesc(channel_id)}">')
        lines.append(f'    <display-name>{xesc(name)}</display-name>')
        lines.append('  </channel>')

    for ev in sorted(events, key=lambda e: (e.start, e.channel, e.title)):
        lines.append(f'  <programme start="{xml_time(ev.start)}" stop="{xml_time(ev.stop)}" channel="{xesc(ev.channel)}">')
        lines.append(f'    <title lang="de">{xesc(ev.title)}</title>')
        if ev.desc:
            lines.append(f'    <desc lang="de">{xesc(ev.desc)}</desc>')
        if ev.category:
            lines.append(f'    <category lang="de">{xesc(ev.category)}</category>')
        lines.append('  </programme>')

    lines.append('</tv>')
    return "\n".join(lines) + "\n"


def write_epgimport_files() -> None:
    source_xml = f'''<?xml version="1.0" encoding="utf-8"?>
<sources>
  <sourcecat sourcecatname="Secret DE Sports Event EPG">
    <source type="gen_xmltv" nocheck="1" channels="/etc/epgimport/sports-events.channels.xml">
      <description>Secret DE Sports Event EPG</description>
      <url>{BASE_URL}/sports-events.xml.xz</url>
    </source>
  </sourcecat>
</sources>
'''
    (EPGIMPORT / "sports-events.sources.xml").write_text(source_xml, encoding="utf-8")

    ch_lines = ['<?xml version="1.0" encoding="utf-8"?>', '<channels>']
    for channel_id, name in channels:
        placeholder = channel_id.upper().replace(".", "_").replace("-", "_")
        ch_lines.append(f'  <channel id="{channel_id}">DEINE_SERVICE_REFERENCE_FUER_{placeholder}</channel>')
    ch_lines.append('</channels>')
    (EPGIMPORT / "sports-events.channels.xml").write_text("\n".join(ch_lines) + "\n", encoding="utf-8")


def write_index(meta: Dict[str, Any], events: List[Event]) -> None:
    dazn = meta.get("dazn", {})
    index = f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Secret DE EPG</title>
</head>
<body>
  <h1>Secret DE EPG</h1>
  <p>XMLTV Feed: <a href="sports-events.xml.xz">sports-events.xml.xz</a></p>
  <p>Unkomprimiert: <a href="sports-events.xml">sports-events.xml</a></p>
  <p>EPGImport Source: <a href="epgimport/sports-events.sources.xml">sports-events.sources.xml</a></p>
  <p>EPGImport Channels: <a href="epgimport/sports-events.channels.xml">sports-events.channels.xml</a></p>
  <p>Status: <a href="status.json">status.json</a></p>
  <h2>Status</h2>
  <p>Generiert: {xesc(meta.get('generated_at', ''))}</p>
  <p>Kanäle: {len(channels)} | Events: {len(events)}</p>
  <p>DAZN Quelle: {xesc(dazn.get('url', ''))}</p>
  <p>DAZN raw: {dazn.get('raw_events', 0)} | mapped: {dazn.get('mapped_events', 0)}</p>
</body>
</html>
'''
    (PUBLIC / "index.html").write_text(index, encoding="utf-8")


def main() -> int:
    all_events: List[Event] = []
    meta: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE_URL,
    }

    dazn_events, dazn_meta = build_dazn_events()
    meta["dazn"] = dazn_meta
    all_events.extend(dazn_events)

    if not all_events:
        all_events.extend(fallback_events())
        meta["fallback_used"] = True
    else:
        meta["fallback_used"] = False

    xml_text = write_xmltv(all_events)
    xml_path = PUBLIC / "sports-events.xml"
    xz_path = PUBLIC / "sports-events.xml.xz"
    xml_path.write_text(xml_text, encoding="utf-8")
    with lzma.open(xz_path, "wb", preset=6) as f:
        f.write(xml_text.encode("utf-8"))

    write_epgimport_files()
    status = {
        **meta,
        "channel_count": len(channels),
        "event_count": len(all_events),
        "events_by_channel": {},
    }
    for ev in all_events:
        status["events_by_channel"][ev.channel] = status["events_by_channel"].get(ev.channel, 0) + 1
    (PUBLIC / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_index(status, all_events)

    print(f"Wrote {xml_path}")
    print(f"Wrote {xz_path}")
    print(f"Channels: {len(channels)}")
    print(f"Events: {len(all_events)}")
    print(f"DAZN: raw={dazn_meta.get('raw_events')} mapped={dazn_meta.get('mapped_events')} url={dazn_meta.get('url')}")
    if dazn_meta.get("errors"):
        print("DAZN errors:")
        for err in dazn_meta["errors"]:
            print(f" - {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

