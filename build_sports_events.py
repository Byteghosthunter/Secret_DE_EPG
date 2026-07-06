#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ByteGH / Secret_DE_EPG - Sports Events XMLTV Builder

Stable GitHub Actions version.

Fixes included:
- Adds Magenta Sport channel IDs:
  magenta.sport.01 - magenta.sport.18
- EPGImport source points to the local E-Channelizer mapping file:
  /etc/epgimport/echannelizer.channels/bytegh.sport-feeds.xml
- A compatibility sports-events.channels.xml is still generated because the
  GitHub Action checks that this file exists. It is NOT used as active mapping.
- status.json, events-debug.json and events-debug.txt are generated so the
  GitHub Action file checks do not fail.
- Output files are written with clean UTF-8 / LF line endings.
- XMLTV is compressed to .xz for GitHub Pages.

Expected output:
  public/
    index.html
    sports-events.xml
    sports-events.xml.xz
    status.json
    events-debug.json
    events-debug.txt
    epgimport/
      sports-events.sources.xml
      sports-events.channels.xml

Optional input:
  data/sports-events.json
  data/manual_events.json

JSON event format examples:
[
  {
    "channel_id": "magenta.sport.01",
    "title": "3. Liga - Live",
    "start": "2026-07-07T10:00:00+02:00",
    "stop": "2026-07-07T12:00:00+02:00",
    "description": "Live event",
    "category": "Fußball"
  },
  {
    "channel": "magenta.sport.01",
    "title": "TEST - MAGENTA SPORT 1 FHD",
    "start": "2026-07-07T10:00:00+02:00",
    "duration_minutes": 720,
    "desc": "Wenn du das siehst, funktioniert das Mapping.",
    "category": "Fußball"
  }
]
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from html import escape as esc
from pathlib import Path
from typing import Any, Iterable
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
COMPAT_CHANNELS_FILE = EPGIMPORT / "sports-events.channels.xml"

STATUS_FILE = PUBLIC / "status.json"
EVENTS_DEBUG_JSON = PUBLIC / "events-debug.json"
EVENTS_DEBUG_TXT = PUBLIC / "events-debug.txt"

# Important:
# The active EPGImport source must point to the local E-Channelizer mapping.
# The generated sports-events.channels.xml is only a compatibility/debug file.
ECHANNELIZER_CHANNELS_PATH = "/etc/epgimport/echannelizer.channels/bytegh.sport-feeds.xml"

SOURCECAT_NAME = "ByteGH - Sport Feed"
SOURCE_DESCRIPTION = "ByteGH - Sport Feed"

DEFAULT_BASE_URL = "https://byteghosthunter.github.io/Secret_DE_EPG"


# ---------------------------------------------------------------------------
# Channel IDs shown on the website and written into XMLTV
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

    # Magenta Sport / 3. Liga and other Magenta event slots.
    # These IDs match the Dreambox mapping we will use:
    # magenta.sport.01 - magenta.sport.18
    "Magenta Sport": [f"magenta.sport.{i:02d}" for i in range(1, 19)],

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
    source: str = "manual"


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


def iso(dt: datetime) -> str:
    return dt.isoformat()


def all_channel_ids() -> list[str]:
    ids: list[str] = []
    for group_ids in CHANNEL_GROUPS.values():
        ids.extend(group_ids)
    return ids


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def event_to_debug_dict(event: SportsEvent) -> dict[str, Any]:
    data = asdict(event)
    data["start"] = iso(event.start)
    data["stop"] = iso(event.stop)
    return data


def input_paths() -> list[Path]:
    """
    EVENTS_JSON can point to one file.
    Without override we load both:
      data/sports-events.json
      data/manual_events.json
    """
    override = os.environ.get("EVENTS_JSON", "").strip()
    if override:
        return [Path(override)]

    return [
        ROOT / "data" / "sports-events.json",
        ROOT / "data" / "manual_events.json",
    ]


def normalize_raw_events(raw: Any) -> list[dict[str, Any]]:
    """
    Accepts either:
      [ {...}, {...} ]
    or:
      { "events": [ {...}, {...} ] }
    """
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]

    if isinstance(raw, dict):
        events = raw.get("events", [])
        if isinstance(events, list):
            return [item for item in events if isinstance(item, dict)]

    return []


def parse_event(item: dict[str, Any], source_name: str) -> SportsEvent | None:
    channel_id = clean_text(item.get("channel_id") or item.get("channel"))
    title = clean_text(item.get("title") or item.get("name"))

    if not channel_id or not title:
        return None

    try:
        start = parse_dt(clean_text(item.get("start")))
    except Exception as exc:
        print(f"[WARN] Skip event without valid start: {title!r} ({exc})")
        return None

    stop_raw = clean_text(item.get("stop") or item.get("end"))

    try:
        if stop_raw:
            stop = parse_dt(stop_raw)
        else:
            minutes_raw = item.get("duration_minutes")
            hours_raw = item.get("duration_hours")

            if minutes_raw not in (None, ""):
                stop = start + timedelta(minutes=int(minutes_raw))
            elif hours_raw not in (None, ""):
                stop = start + timedelta(hours=float(hours_raw))
            else:
                # Safe fallback.
                stop = start + timedelta(hours=2)
    except Exception as exc:
        print(f"[WARN] Invalid stop/duration for {title!r}: {exc}; using 2 hours")
        stop = start + timedelta(hours=2)

    if stop <= start:
        print(f"[WARN] Stop is not after start for {title!r}; using 2 hours")
        stop = start + timedelta(hours=2)

    description = clean_text(item.get("description") or item.get("desc"))
    category = clean_text(item.get("category") or category_for_channel(channel_id))
    source = clean_text(item.get("source") or source_name)

    return SportsEvent(
        channel_id=channel_id,
        title=title,
        start=start,
        stop=stop,
        description=description,
        category=category,
        source=source,
    )


def category_for_channel(channel_id: str) -> str:
    if ".ufc." in channel_id or channel_id.startswith("ufcfightpass."):
        return "MMA"
    if ".nba." in channel_id:
        return "Basketball"
    if ".nfl." in channel_id:
        return "American Football"
    if (
        channel_id.startswith("magenta.sport.")
        or ".ucl." in channel_id
        or ".laliga." in channel_id
        or ".ligue1." in channel_id
        or ".seriea." in channel_id
        or ".bundesliga." in channel_id
    ):
        return "Fußball"
    return "Sports"


# ---------------------------------------------------------------------------
# Event loading hook
# ---------------------------------------------------------------------------

def collect_events() -> list[SportsEvent]:
    """
    Loads event data from:
      data/sports-events.json
      data/manual_events.json

    Override path:
      EVENTS_JSON=/path/to/events.json python3 build_sports_events.py
    """
    events: list[SportsEvent] = []

    for path in input_paths():
        if not path.exists():
            print(f"[INFO] Optional events JSON not found: {path}")
            continue

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[WARN] Could not read JSON {path}: {exc}")
            continue

        for item in normalize_raw_events(raw):
            event = parse_event(item, source_name=path.name)
            if event is not None:
                events.append(event)

    # Stable order and light duplicate protection.
    unique: dict[tuple[str, str, datetime, datetime], SportsEvent] = {}
    for event in events:
        key = (event.channel_id, event.title, event.start, event.stop)
        unique[key] = event

    result = sorted(unique.values(), key=lambda e: (e.start, e.channel_id, e.title))
    print(f"[OK] Events loaded: {len(result)}")
    return result


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
    Writes the active EPGImport source file.

    Important:
    channels= points to the local E-Channelizer mapping.
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


def write_compat_channels_file() -> None:
    """
    Compatibility/debug file only.

    GitHub Actions checks that this file exists, but Dreambox EPGImport uses:
      /etc/epgimport/echannelizer.channels/bytegh.sport-feeds.xml
    """
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<channels>",
        "  <!-- Compatibility/debug only. Active mapping is local E-Channelizer. -->",
        f"  <!-- Active mapping: {esc(ECHANNELIZER_CHANNELS_PATH)} -->",
    ]

    for channel_id in sorted(all_channel_ids()):
        placeholder = "DEINE_SERVICE_REFERENCE_FUER_" + channel_id.upper().replace(".", "_").replace("-", "_")
        lines.append(f'  <channel id="{esc(channel_id)}">{esc(placeholder)}</channel>')

    lines.append("</channels>")
    COMPAT_CHANNELS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"[OK] Compatibility channels written: {COMPAT_CHANNELS_FILE}")


def write_index(events: list[SportsEvent]) -> None:
    rows: list[str] = []
    event_counts: dict[str, int] = {}
    for event in events:
        event_counts[event.channel_id] = event_counts.get(event.channel_id, 0) + 1

    for group_name, ids in CHANNEL_GROUPS.items():
        items = []
        for channel_id in ids:
            count = event_counts.get(channel_id, 0)
            if count:
                items.append(f"<li><code>{esc(channel_id)}</code> <strong>({count} Events)</strong></li>")
            else:
                items.append(f"<li><code>{esc(channel_id)}</code></li>")

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
    <p><strong>Kompatibilitäts-Datei:</strong> <a href="epgimport/sports-events.channels.xml">sports-events.channels.xml</a></p>
    <p><strong>Aktives EPGImport Channel-Mapping:</strong> lokal über <code>{esc(ECHANNELIZER_CHANNELS_PATH)}</code></p>
    <p><strong>Aktuelle Programme im XMLTV:</strong> {total_events}</p>
    <p><strong>Channel IDs insgesamt:</strong> {len(all_channel_ids())}</p>
  </div>

  <h2>Hinweis für EPGImport</h2>
  <p>
    Die aktive Source verwendet E-Channelizer:
    <code>{esc(ECHANNELIZER_CHANNELS_PATH)}</code>.
    Die Datei <code>sports-events.channels.xml</code> wird nur erzeugt, damit
    GitHub Actions und Browser-Checks nicht fehlschlagen.
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

The active source points to the local E-Channelizer channel mapping:

{ECHANNELIZER_CHANNELS_PATH}

The generated sports-events.channels.xml is compatibility/debug only.
'''

    (EPGIMPORT / "README.txt").write_text(readme, encoding="utf-8", newline="\n")
    print(f"[OK] README written: {EPGIMPORT / 'README.txt'}")


def write_status_files(events: list[SportsEvent]) -> None:
    event_counts: dict[str, int] = {}
    for event in events:
        event_counts[event.channel_id] = event_counts.get(event.channel_id, 0) + 1

    status = {
        "ok": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url(),
        "channel_count": len(all_channel_ids()),
        "group_count": len(CHANNEL_GROUPS),
        "event_count": len(events),
        "events_by_channel": dict(sorted(event_counts.items())),
        "magenta_sport_enabled": True,
        "magenta_sport_channels": [f"magenta.sport.{i:02d}" for i in range(1, 19)],
        "prime_event_range": "prime.event.01-08",
        "epgimport_source": "public/epgimport/sports-events.sources.xml",
        "epgimport_source_mapping": ECHANNELIZER_CHANNELS_PATH,
        "compatibility_channels_file": "public/epgimport/sports-events.channels.xml",
        "source_fix": "sports-events.sources.xml points to E-Channelizer mapping; sports-events.channels.xml is compatibility only",
        "xmltv": "public/sports-events.xml",
        "xmltv_xz": "public/sports-events.xml.xz",
        "input_files": [str(p) for p in input_paths()],
    }

    STATUS_FILE.write_text(
        json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    debug = [event_to_debug_dict(event) for event in events]
    EVENTS_DEBUG_JSON.write_text(
        json.dumps(debug, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    txt_lines = [
        "ByteGH Sport Feed events debug",
        f"Generated UTC: {status['generated_at_utc']}",
        f"Events: {len(events)}",
        f"Channels: {len(all_channel_ids())}",
        f"Active mapping: {ECHANNELIZER_CHANNELS_PATH}",
        "",
    ]

    if not events:
        txt_lines.append("No events loaded. XMLTV still contains channel IDs for mapping visibility.")
    else:
        for event in events:
            txt_lines.append(
                f"{event.start.isoformat()} -> {event.stop.isoformat()} | "
                f"{event.channel_id} | {event.title} | {event.category} | {event.source}"
            )

    EVENTS_DEBUG_TXT.write_text("\n".join(txt_lines) + "\n", encoding="utf-8", newline="\n")

    print(f"[OK] Status written: {STATUS_FILE}")
    print(f"[OK] Debug JSON written: {EVENTS_DEBUG_JSON}")
    print(f"[OK] Debug TXT written: {EVENTS_DEBUG_TXT}")


def validate_output() -> None:
    """
    Basic sanity checks.
    """
    ET.parse(XMLTV_FILE)
    ET.parse(SOURCE_FILE)
    ET.parse(COMPAT_CHANNELS_FILE)

    source_text = SOURCE_FILE.read_text(encoding="utf-8")
    xmltv_text = XMLTV_FILE.read_text(encoding="utf-8")
    compat_text = COMPAT_CHANNELS_FILE.read_text(encoding="utf-8")

    if "sports-events.channels.xml" in source_text:
        raise RuntimeError("Wrong active mapping path found in source: sports-events.channels.xml")

    if ECHANNELIZER_CHANNELS_PATH not in source_text:
        raise RuntimeError("Missing E-Channelizer mapping path in source XML")

    if "magenta.sport.01" not in xmltv_text or "magenta.sport.18" not in xmltv_text:
        raise RuntimeError("Magenta Sport IDs missing in XMLTV")

    if "prime.event.09" in xmltv_text or "prime.event.09" in compat_text:
        raise RuntimeError("prime.event.09 must not be generated")

    required = [
        PUBLIC / "index.html",
        XMLTV_FILE,
        XMLTV_XZ_FILE,
        STATUS_FILE,
        EVENTS_DEBUG_JSON,
        EVENTS_DEBUG_TXT,
        SOURCE_FILE,
        COMPAT_CHANNELS_FILE,
    ]

    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("Missing required output files: " + ", ".join(missing))

    print("[OK] XML validation passed")
    print("[OK] Required output files exist")
    print("[OK] Magenta Sport IDs present")
    print("[OK] Prime range remains 01-08")


def main() -> int:
    ensure_dirs()

    events = collect_events()

    write_xmltv(events)
    write_epgimport_source()
    write_compat_channels_file()
    write_index(events)
    write_readme()
    write_status_files(events)
    validate_output()

    print("")
    print("[DONE] Build complete")
    print(f"[INFO] Events: {len(events)}")
    print(f"[INFO] Channels: {len(all_channel_ids())}")
    print(f"[INFO] Source URL: {base_url()}/epgimport/sports-events.sources.xml")
    print(f"[INFO] XMLTV URL:  {base_url()}/sports-events.xml.xz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
