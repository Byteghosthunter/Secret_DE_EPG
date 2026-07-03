#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
import html
import json
import lzma
import os
import re
import urllib.request
import urllib.error

try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:
    BERLIN = timezone(timedelta(hours=2))

HERE = Path(__file__).resolve()
if HERE.parent.name == "builder":
    ROOT = HERE.parents[1]
else:
    ROOT = HERE.parent

PUBLIC = ROOT / "public"
EPGIMPORT = PUBLIC / "epgimport"
PUBLIC.mkdir(parents=True, exist_ok=True)
EPGIMPORT.mkdir(parents=True, exist_ok=True)

DAZN_EPG_PW_CHANNEL_ID = "76632"
DAZN_EPG_PW_BASE = "https://epg.pw/api/epg.json"

CHANNEL_GROUPS: list[tuple[str, str, int, int, str]] = [
    ("rtlplus.sport", "RTL+ SPORT", 1, 20, "FHD"),

    ("dazn.event", "DAZN Event", 1, 10, "FHD"),
    ("dazn.bundesliga", "DAZN Bundesliga", 1, 10, "FHD"),
    ("dazn.laliga", "DAZN LaLiga", 1, 10, "FHD"),
    ("dazn.ufc", "DAZN UFC", 1, 10, "FHD"),
    ("dazn.nba", "DAZN NBA", 1, 10, "FHD"),
    ("dazn.nfl", "DAZN NFL", 1, 10, "FHD"),
    ("dazn.ligue1", "DAZN Ligue 1", 1, 10, "FHD"),
    ("dazn.seriea", "DAZN Serie A", 1, 10, "FHD"),

    ("dyn.sport", "DYN Sport", 1, 25, ""),
    ("amazon.live", "Amazon Live Event", 1, 8, ""),
    ("prime.event", "Amazon Prime Event", 1, 9, ""),
    ("discovery.extra", "Discovery Extra", 1, 16, ""),
    ("eurosport.extra", "Eurosport Extra", 1, 16, ""),
    ("sporteurope.tv", "SportDeutschland.TV", 1, 20, ""),
]

EXTRA_CHANNELS: list[tuple[str, str]] = [
    ("sporteurope.del2", "Sport.DE DEL 2"),
]

@dataclass
class Event:
    channel_id: str
    start: datetime
    stop: datetime
    title: str
    desc: str = ""
    category: str = "Sport"


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def repo_pages_url() -> str:
    explicit = os.environ.get("PAGES_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}"

    return "https://byteghosthunter.github.io/Secret_DE_EPG"


def build_channels() -> list[tuple[str, str]]:
    channels: list[tuple[str, str]] = []
    for prefix, label, start, end, suffix in CHANNEL_GROUPS:
        for number in range(start, end + 1):
            name = f"{label} {number}"
            if suffix:
                name = f"{name} {suffix}"
            channels.append((f"{prefix}.{number:02d}", name))
    channels.extend(EXTRA_CHANNELS)
    return channels


def xml_time(dt: datetime) -> str:
    local = dt.astimezone(BERLIN)
    return local.strftime("%Y%m%d%H%M%S %z")


def parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def http_json(url: str, timeout: int = 25) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Secret_DE_EPG/1.0 (+https://byteghosthunter.github.io/Secret_DE_EPG)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8", errors="replace"))


def normalize_text(value: str) -> str:
    value = value.lower()
    value = value.replace("é", "e").replace("è", "e").replace("á", "a").replace("à", "a")
    value = value.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def classify_dazn(title: str, desc: str) -> tuple[str, str]:
    text = normalize_text(f"{title} {desc}")

    if any(k in text for k in ["bundesliga", "2. bundesliga", "relegation"]):
        return "dazn.bundesliga", "Fußball"
    if any(k in text for k in ["laliga", "la liga", "spanische liga", "spanien:"]):
        return "dazn.laliga", "Fußball"
    if any(k in text for k in ["ufc", "mma", "mixed martial", "fighting championship", "cage warriors", "pfl", "oktagon"]):
        return "dazn.ufc", "MMA"
    if any(k in text for k in ["nba", "basketball"]):
        return "dazn.nba", "Basketball"
    if any(k in text for k in ["nfl", "american football", "game pass", "super bowl", "redzone"]):
        return "dazn.nfl", "American Football"
    if any(k in text for k in ["ligue 1", "ligue1", "franzoesische liga", "frankreich:"]):
        return "dazn.ligue1", "Fußball"
    if any(k in text for k in ["serie a", "italienische liga", "italien:"]):
        return "dazn.seriea", "Fußball"

    if any(k in text for k in ["fussball", "fußball", "soccer", "champions league", "conference league", "europa league"]):
        return "dazn.event", "Fußball"
    if any(k in text for k in ["boxen", "boxing", "fight"]):
        return "dazn.event", "Kampfsport"
    if any(k in text for k in ["radsport", "rad:", "tour de france", "cycling"]):
        return "dazn.event", "Radsport"

    return "dazn.event", "Sport"


def channel_slot(prefix: str, index: int) -> str:
    # 1..10 slots, overflow rotates back to 01
    slot = (index % 10) + 1
    return f"{prefix}.{slot:02d}"


def fetch_dazn_epg_pw(days: int = 7) -> tuple[list[Event], dict]:
    status = {
        "source": "epg.pw",
        "channel_id": DAZN_EPG_PW_CHANNEL_ID,
        "raw_events": 0,
        "mapped_events": 0,
        "errors": [],
        "fallback_used": False,
    }

    raw_items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    today = datetime.now(timezone.utc).date()

    for offset in range(0, days):
        day = today + timedelta(days=offset)
        date_str = day.strftime("%Y%m%d")
        url = f"{DAZN_EPG_PW_BASE}?channel_id={DAZN_EPG_PW_CHANNEL_ID}&date={date_str}&timezone=UTC"
        try:
            data = http_json(url)
            items = data.get("epg_list") or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = (str(item.get("start_date", "")), str(item.get("title", "")))
                if key in seen:
                    continue
                seen.add(key)
                raw_items.append(item)
        except Exception as exc:
            status["errors"].append(f"{date_str}: {type(exc).__name__}: {exc}")

    parsed: list[tuple[datetime, str, str]] = []
    for item in raw_items:
        title = str(item.get("title") or "").strip()
        desc = str(item.get("desc") or "").strip()
        start = parse_dt(str(item.get("start_date") or ""))
        if not title or not start:
            continue
        # Keep only events not older than 12 hours, so a same-day build still has useful current entries.
        if start < datetime.now(timezone.utc) - timedelta(hours=12):
            continue
        parsed.append((start, title, desc))

    parsed.sort(key=lambda x: x[0])
    status["raw_events"] = len(parsed)

    prefix_counts: dict[str, int] = {}
    events: list[Event] = []
    for idx, (start, title, desc) in enumerate(parsed):
        if idx + 1 < len(parsed):
            next_start = parsed[idx + 1][0]
            stop = next_start if next_start > start else start + timedelta(hours=2)
        else:
            stop = start + timedelta(hours=2)

        # Prevent broken or extremely long EPG blocks.
        if stop - start > timedelta(hours=6):
            stop = start + timedelta(hours=2)
        if stop <= start:
            stop = start + timedelta(hours=2)

        prefix, category = classify_dazn(title, desc)
        count = prefix_counts.get(prefix, 0)
        prefix_counts[prefix] = count + 1
        cid = channel_slot(prefix, count)
        events.append(Event(channel_id=cid, start=start, stop=stop, title=title, desc=desc, category=category))

    status["mapped_events"] = len(events)
    status["events_by_channel"] = {}
    for event in events:
        status["events_by_channel"][event.channel_id] = status["events_by_channel"].get(event.channel_id, 0) + 1

    return events, status


def fallback_events() -> list[Event]:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [
        Event(
            channel_id="dazn.event.01",
            start=now,
            stop=now + timedelta(hours=2),
            title="DAZN EPG Fallback / Test",
            desc="Fallback-Eintrag. Der Builder lief, aber es wurden keine echten DAZN-Events geladen.",
            category="Sport",
        )
    ]


def write_xmltv(channels: list[tuple[str, str]], events: list[Event]) -> None:
    lines: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<tv generator-info-name="Secret_DE_EPG" generator-info-url="https://github.com/Byteghosthunter/Secret_DE_EPG">')

    for channel_id, name in channels:
        lines.append(f'  <channel id="{esc(channel_id)}">')
        lines.append(f'    <display-name>{esc(name)}</display-name>')
        lines.append("  </channel>")

    for event in events:
        lines.append(f'  <programme start="{xml_time(event.start)}" stop="{xml_time(event.stop)}" channel="{esc(event.channel_id)}">')
        lines.append(f'    <title lang="de">{esc(event.title)}</title>')
        if event.desc:
            lines.append(f'    <desc lang="de">{esc(event.desc)}</desc>')
        lines.append(f'    <category lang="de">{esc(event.category)}</category>')
        lines.append("  </programme>")

    lines.append("</tv>")
    xml_text = "\n".join(lines) + "\n"

    xml_path = PUBLIC / "sports-events.xml"
    xz_path = PUBLIC / "sports-events.xml.xz"
    xml_path.write_text(xml_text, encoding="utf-8")
    with lzma.open(xz_path, "wb", preset=6) as f:
        f.write(xml_text.encode("utf-8"))


def write_epgimport_files(channels: list[tuple[str, str]]) -> None:
    base_url = repo_pages_url()
    source_xml = f'''<?xml version="1.0" encoding="utf-8"?>
<sources>
  <sourcecat sourcecatname="Secret DE Sports Event EPG">
    <source type="gen_xmltv" nocheck="1" channels="/etc/epgimport/sports-events.channels.xml">
      <description>Secret DE Sports Event EPG</description>
      <url>{esc(base_url)}/sports-events.xml.xz</url>
    </source>
  </sourcecat>
</sources>
'''
    (EPGIMPORT / "sports-events.sources.xml").write_text(source_xml, encoding="utf-8")

    channel_lines = ['<?xml version="1.0" encoding="utf-8"?>', '<channels>']
    for channel_id, _name in channels:
        placeholder = "DEINE_SERVICE_REFERENCE_FUER_" + channel_id.upper().replace(".", "_").replace("-", "_")
        channel_lines.append(f'  <channel id="{esc(channel_id)}">{esc(placeholder)}</channel>')
    channel_lines.append("</channels>")
    (EPGIMPORT / "sports-events.channels.xml").write_text("\n".join(channel_lines) + "\n", encoding="utf-8")


def write_index(channels: list[tuple[str, str]], status: dict) -> None:
    group_lines = []
    for prefix, label, start, end, suffix in CHANNEL_GROUPS:
        group_lines.append(f"<li><code>{esc(prefix)}.01</code> bis <code>{esc(prefix)}.{end:02d}</code> — {esc(label)} 1-{end}</li>")
    for channel_id, name in EXTRA_CHANNELS:
        group_lines.append(f"<li><code>{esc(channel_id)}</code> — {esc(name)}</li>")

    html_doc = f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Secret DE EPG</title>
</head>
<body>
  <h1>Secret DE EPG</h1>
  <p>XMLTV Feed: <a href="sports-events.xml.xz">sports-events.xml.xz</a></p>
  <p>XMLTV unkomprimiert: <a href="sports-events.xml">sports-events.xml</a></p>
  <p>Status: <a href="status.json">status.json</a></p>
  <p>EPGImport Source: <a href="epgimport/sports-events.sources.xml">sports-events.sources.xml</a></p>
  <p>EPGImport Channels: <a href="epgimport/sports-events.channels.xml">sports-events.channels.xml</a></p>
  <h2>Channel-ID-Gruppen</h2>
  <ul>
    {''.join(group_lines)}
  </ul>
  <p>Channels insgesamt: {len(channels)}</p>
  <p>DAZN raw events: {esc(status.get('dazn', {}).get('raw_events', 0))}</p>
  <p>DAZN mapped events: {esc(status.get('dazn', {}).get('mapped_events', 0))}</p>
</body>
</html>
'''
    (PUBLIC / "index.html").write_text(html_doc, encoding="utf-8")


def write_status(status: dict) -> None:
    (PUBLIC / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    channels = build_channels()
    dazn_events, dazn_status = fetch_dazn_epg_pw(days=7)

    events = dazn_events
    if not events:
        dazn_status["fallback_used"] = True
        events = fallback_events()

    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": repo_pages_url(),
        "dazn": dazn_status,
        "channel_count": len(channels),
        "event_count": len(events),
    }

    write_xmltv(channels, events)
    write_epgimport_files(channels)
    write_status(status)
    write_index(channels, status)

    print(f"Generated {len(channels)} channels")
    print(f"Generated {len(events)} programmes")
    print(f"DAZN raw events: {dazn_status.get('raw_events', 0)}")
    print(f"DAZN mapped events: {dazn_status.get('mapped_events', 0)}")
    print(f"Fallback used: {dazn_status.get('fallback_used', False)}")
    print(f"Feed: {PUBLIC / 'sports-events.xml.xz'}")


if __name__ == "__main__":
    main()
