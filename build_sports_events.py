#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ByteGH / Secret_DE_EPG - Sports Events XMLTV Builder

Fixes included:
- EPGImport source points to the local E-Channelizer mapping file:
  /etc/epgimport/echannelizer.channels/bytegh.sport-feeds.xml
- No misleading sports-events.channels.xml is advertised as the active mapping.
- Output files are written with clean UTF-8 / LF line endings.
- XMLTV is compressed to .xz for GitHub Pages.
- Index page clearly explains that channel mapping comes from E-Channelizer.

Expected output:
  public/
    index.html
    sports-events.xml
    sports-events.xml.xz
    epgimport/
      sports-events.sources.xml

Optional input:
  data/sports-events.json

JSON event format example:
[
  {
    "channel_id": "dazn.ufc.01",
    "title": "UFC Fight Night",
    "start": "2026-07-05T20:00:00+02:00",
    "stop": "2026-07-05T23:00:00+02:00",
    "description": "Live event"
  }
]

If your existing scraper already creates events, connect it inside collect_events().
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from html import escape as esc
from pathlib import Path
from typing import Iterable, Any
import json
import lzma
import os
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# Paths / config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
EPGIMPORT = PUBLIC / "epgimport"

XMLTV_FILE = PUBLIC / "sports-events.xml"
XMLTV_XZ_FILE = PUBLIC / "sports-events.xml.xz"
SOURCE_FILE = EPGIMPORT / "sports-events.sources.xml"

# Important fix:
# Do NOT point to /etc/epgimport/sports-events.channels.xml.
# E-Channelizer owns the real local mapping file.
ECHANNELIZER_CHANNELS_PATH = "/etc/epgimport/echannelizer.channels/bytegh.sport-feeds.xml"

SOURCECAT_NAME = "ByteGH - Sport Feed"
SOURCE_DESCRIPTION = "ByteGH - Sport Feed"

DEFAULT_BASE_URL = "https://byteghosthunter.github.io/Secret_DE_EPG"


# ---------------------------------------------------------------------------
# Channel IDs shown on the website
# ---------------------------------------------------------------------------

CHANNEL_GROUPS: dict[str, list[str]] = {
    "DAZN Event": [f"dazn.event.{i:02d}" for i in range(1, 31)],
    "DAZN UFC": [f"dazn.ufc.{i:02d}" for i in range(1, 11)],
    "UFC Fight Pass": ["ufcfightpass.24x7"] + [f"ufcfightpass.event.{i:02d}" for i in range(1, 6)],
    "DAZN UCL": [f"dazn.ucl.{i:02d}" for i in range(1, 21)],
    "DAZN NBA": [f"dazn.nba.{i:02d}" for i in range(1, 11)],
    "DAZN NFL": [f"dazn.nfl.{i:02d}" for i in range(1, 11)],
    "DAZN LaLiga": [f"dazn.laliga.{i:02d}" for i in range(1, 11)],
    "DAZN Serie A": [f"dazn.seriea.{i:02d}" for i in range(1, 11)],
    "DAZN Ligue 1": [f"dazn.ligue1.{i:02d}" for i in range(1, 11)],
    "RTL+ Sport": [f"rtlplus.sport.{i:02d}" for i in range(1, 21)],
    "Discovery Extra": [f"discovery.extra.{i:02d}" for i in range(1, 17)],
    "Eurosport Extra": [f"eurosport.extra.{i:02d}" for i in range(1, 17)],
    "Prime Event": [f"prime.event.{i:02d}" for i in range(1, 9)],
    "Dyn Sport": [f"dyn.sport.{i:02d}" for i in range(1, 26)],
    "Sport Europe": ["sporteurope.del2"],
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SportsEvent:
    channel_id: str
    title: str
    start: datetime
    stop: datetime
    description: str = ""
    category: str = "Sports"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_dirs() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    EPGIMPORT.mkdir(parents=True, exist_ok=True)


def base_url() -> str:
    """
    Allows override in GitHub Actions:
      BASE_URL=https://byteghosthunter.github.io/Secret_DE_EPG
    """
    value = os.environ.get("BASE_URL", DEFAULT_BASE_URL).strip()
    return value.rstrip("/")


def parse_dt(value: str) -> datetime:
    """
    Parses ISO timestamps. Naive datetimes are treated as UTC.
    """
    if not value:
        raise ValueError("empty datetime")

    value = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def xmltv_time(dt: datetime) -> str:
    """
    XMLTV timestamp format: YYYYmmddHHMMSS +0000
    """
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%d%H%M%S +0000")


def all_channel_ids() -> list[str]:
    ids: list[str] = []
    for group_ids in CHANNEL_GROUPS.values():
        ids.extend(group_ids)
    return ids


def clean_text(value: Any) -> str:
    return str(value or "").strip()


# ---------------------------------------------------------------------------
# Event loading hook
# ---------------------------------------------------------------------------

def collect_events() -> list[SportsEvent]:
    """
    Replace or extend this function with your real scraper.

    By default it loads:
      data/sports-events.json

    Override path:
      EVENTS_JSON=/path/to/events.json python3 build_sports_events.py
    """
    path = Path(os.environ.get("EVENTS_JSON", str(ROOT / "data" / "sports-events.json")))

    if not path.exists():
        print(f"[WARN] No events JSON found: {path}")
        print("[WARN] Building an empty XMLTV file. Connect your scraper in collect_events().")
        return []

    raw = json.loads(path.read_text(encoding="utf-8"))
    events: list[SportsEvent] = []

    for item in raw:
        channel_id = clean_text(item.get("channel_id") or item.get("channel"))
        title = clean_text(item.get("title") or item.get("name"))
        start = parse_dt(clean_text(item.get("start")))
        stop_raw = clean_text(item.get("stop") or item.get("end"))

        if stop_raw:
            stop = parse_dt(stop_raw)
        else:
            # Safe fallback: 2 hours.
            stop = start + timedelta(hours=2)

        description = clean_text(item.get("description") or item.get("desc"))
        category = clean_text(item.get("category") or "Sports")

        if not channel_id or not title:
            continue

        events.append(
            SportsEvent(
                channel_id=channel_id,
                title=title,
                start=start,
                stop=stop,
                description=description,
                category=category,
            )
        )

    return sorted(events, key=lambda e: (e.start, e.channel_id, e.title))


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_xmltv(events: Iterable[SportsEvent]) -> None:
    """
    Writes public/sports-events.xml and public/sports-events.xml.xz.
    """
    event_list = list(events)

    tv = ET.Element("tv", {
        "generator-info-name": "ByteGH Secret_DE_EPG",
        "generator-info-url": base_url(),
    })

    used_channels = sorted({event.channel_id for event in event_list} | set(all_channel_ids()))

    for channel_id in used_channels:
        channel = ET.SubElement(tv, "channel", {"id": channel_id})
        display = ET.SubElement(channel, "display-name", {"lang": "de"})
        display.text = channel_id

    for event in event_list:
        programme = ET.SubElement(tv, "programme", {
            "start": xmltv_time(event.start),
            "stop": xmltv_time(event.stop),
            "channel": event.channel_id,
        })

        title = ET.SubElement(programme, "title", {"lang": "de"})
        title.text = event.title

        if event.description:
            desc = ET.SubElement(programme, "desc", {"lang": "de"})
            desc.text = event.description

        if event.category:
            cat = ET.SubElement(programme, "category", {"lang": "de"})
            cat.text = event.category

    tree = ET.ElementTree(tv)
    ET.indent(tree, space="  ", level=0)
    tree.write(XMLTV_FILE, encoding="utf-8", xml_declaration=True, short_empty_elements=True)

    data = XMLTV_FILE.read_bytes()
    XMLTV_XZ_FILE.write_bytes(lzma.compress(data, preset=9))

    print(f"[OK] XMLTV written: {XMLTV_FILE}")
    print(f"[OK] XMLTV compressed: {XMLTV_XZ_FILE}")


def write_epgimport_source() -> None:
    """
    Writes only the EPGImport source file.

    Important:
    channels= points to the local E-Channelizer mapping.
    We intentionally do NOT generate or advertise sports-events.channels.xml
    as the active mapping file.
    """
    url = f"{base_url()}/sports-events.xml.xz"

    source_xml = f'''<?xml version="1.0" encoding="utf-8"?>
<sources>
  <sourcecat sourcecatname="{esc(SOURCECAT_NAME)}">
    <source type="gen_xmltv" nocheck="1" channels="{ECHANNELIZER_CHANNELS_PATH}">
      <description>{esc(SOURCE_DESCRIPTION)}</description>
      <url><![CDATA[{url}]]></url>
    </source>
  </sourcecat>
</sources>
'''

    SOURCE_FILE.write_text(source_xml, encoding="utf-8", newline="\n")
    print(f"[OK] EPGImport source written: {SOURCE_FILE}")


def write_index(events: list[SportsEvent]) -> None:
    rows: list[str] = []
    event_counts: dict[str, int] = {}
    for event in events:
        event_counts[event.channel_id] = event_counts.get(event.channel_id, 0) + 1

    for group_name, ids in CHANNEL_GROUPS.items():
        items = []
        for channel_id in ids:
            count = event_counts.get(channel_id, 0)
            label = channel_id
            if count:
                items.append(f"<li><code>{esc(label)}</code> <strong>({count} Events)</strong></li>")
            else:
                items.append(f"<li><code>{esc(label)}</code></li>")

        rows.append(
            f"<li><strong>{esc(group_name)}</strong><ul>{''.join(items)}</ul></li>"
        )

    total_events = len(events)

    html = f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>ByteGH - Sport Feed EPG</title>
  <style>
    body {{ font-family: Arial, sans-serif; max-width: 1100px; margin: 30px auto; padding: 0 18px; line-height: 1.45; }}
    code {{ background: #f3f3f3; padding: 2px 5px; border-radius: 4px; }}
    .box {{ background: #f8f8f8; border: 1px solid #ddd; padding: 12px 15px; border-radius: 8px; }}
  </style>
</head>
<body>
  <h1>ByteGH - Sport Feed EPG</h1>

  <div class="box">
    <p><strong>XMLTV:</strong> <a href="sports-events.xml.xz">sports-events.xml.xz</a></p>
    <p><strong>EPGImport Source:</strong> <a href="epgimport/sports-events.sources.xml">sports-events.sources.xml</a></p>
    <p><strong>EPGImport Channel-Mapping:</strong> lokal über <code>{esc(ECHANNELIZER_CHANNELS_PATH)}</code></p>
    <p><strong>Aktuelle Programme im XMLTV:</strong> {total_events}</p>
  </div>

  <h2>Hinweis für EPGImport</h2>
  <p>
    Diese Source verwendet absichtlich keine veröffentlichte
    <code>sports-events.channels.xml</code> als aktive Mapping-Datei.
    Die ServiceRefs kommen aus E-Channelizer:
    <code>{esc(ECHANNELIZER_CHANNELS_PATH)}</code>.
  </p>

  <h2>Channel-ID-Gruppen</h2>
  <ul>{''.join(rows)}</ul>
</body>
</html>
'''

    (PUBLIC / "index.html").write_text(html, encoding="utf-8", newline="\n")
    print(f"[OK] Index written: {PUBLIC / 'index.html'}")


def write_readme() -> None:
    readme = f'''ByteGH Sport Feed EPGImport

Use this source on Enigma2/Dreambox:

{base_url()}/epgimport/sports-events.sources.xml

The source points to the local E-Channelizer channel mapping:

{ECHANNELIZER_CHANNELS_PATH}

Do not use sports-events.channels.xml as the active mapping for this setup.
'''

    (EPGIMPORT / "README.txt").write_text(readme, encoding="utf-8", newline="\n")


def validate_output() -> None:
    """
    Basic sanity checks.
    """
    ET.parse(XMLTV_FILE)
    ET.parse(SOURCE_FILE)

    source_text = SOURCE_FILE.read_text(encoding="utf-8")
    if "sports-events.channels.xml" in source_text:
        raise RuntimeError("Wrong mapping path found: sports-events.channels.xml")

    if ECHANNELIZER_CHANNELS_PATH not in source_text:
        raise RuntimeError("Missing E-Channelizer mapping path in source XML")

    print("[OK] XML validation passed")


def main() -> int:
    ensure_dirs()

    events = collect_events()

    write_xmltv(events)
    write_epgimport_source()
    write_index(events)
    write_readme()
    validate_output()

    print("")
    print("[DONE] Build complete")
    print(f"[INFO] Events: {len(events)}")
    print(f"[INFO] Source URL: {base_url()}/epgimport/sports-events.sources.xml")
    print(f"[INFO] XMLTV URL:  {base_url()}/sports-events.xml.xz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
