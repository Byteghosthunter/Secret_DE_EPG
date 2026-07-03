#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone, timedelta
import html
import json
import lzma
import os
from typing import Any

ROOT = Path(os.environ.get("GITHUB_WORKSPACE", Path(__file__).resolve().parent)).resolve()
PUBLIC = ROOT / "public"
EPGIMPORT = PUBLIC / "epgimport"
DATA = ROOT / "data"
MANUAL_EVENTS_FILE = DATA / "manual_events.json"

PUBLIC.mkdir(parents=True, exist_ok=True)
EPGIMPORT.mkdir(parents=True, exist_ok=True)
DATA.mkdir(parents=True, exist_ok=True)

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


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


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
                name += f" {suffix}"
            channels.append((f"{prefix}.{number:02d}", name))

    channels.extend(EXTRA_CHANNELS)
    return channels


def xml_time(dt: datetime) -> str:
    return dt.astimezone(timezone(timedelta(hours=2))).strftime("%Y%m%d%H%M%S +0200")


def parse_datetime(value: str) -> datetime:
    text = str(value).strip()
    if not text:
        raise ValueError("empty datetime")

    # Allows "2026-07-05T20:15:00+02:00" and "2026-07-05 20:15".
    if "T" not in text and len(text) == 16:
        text = text.replace(" ", "T") + ":00+02:00"
    elif "T" not in text and len(text) == 19:
        text = text.replace(" ", "T") + "+02:00"

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=2)))
    return dt


def category_for_channel(channel_id: str) -> str:
    if ".ufc." in channel_id:
        return "MMA"
    if ".nba." in channel_id:
        return "Basketball"
    if ".nfl." in channel_id:
        return "American Football"
    if any(token in channel_id for token in ("laliga", "ligue1", "seriea", "bundesliga")):
        return "Fußball"
    return "Sport"


def load_manual_events(valid_channel_ids: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    events: list[dict[str, Any]] = []

    if not MANUAL_EVENTS_FILE.exists():
        return [], [f"{MANUAL_EVENTS_FILE} not found"]

    try:
        raw = json.loads(MANUAL_EVENTS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], [f"manual_events.json parse error: {type(exc).__name__}: {exc}"]

    if not isinstance(raw, list):
        return [], ["manual_events.json must be a JSON array"]

    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            errors.append(f"event #{index}: must be an object")
            continue

        channel = str(item.get("channel", "")).strip()
        title = str(item.get("title", "")).strip()
        desc = str(item.get("desc", "")).strip()
        category = str(item.get("category", "")).strip()
        start_raw = item.get("start")
        stop_raw = item.get("stop")
        duration_raw = item.get("duration_minutes", item.get("duration", 120))

        if not channel:
            errors.append(f"event #{index}: missing channel")
            continue
        if channel not in valid_channel_ids:
            errors.append(f"event #{index}: unknown channel {channel}")
            continue
        if not title:
            errors.append(f"event #{index}: missing title")
            continue
        if not start_raw:
            errors.append(f"event #{index}: missing start")
            continue

        try:
            start = parse_datetime(str(start_raw))
        except Exception as exc:
            errors.append(f"event #{index}: invalid start: {exc}")
            continue

        if stop_raw:
            try:
                stop = parse_datetime(str(stop_raw))
            except Exception as exc:
                errors.append(f"event #{index}: invalid stop: {exc}")
                continue
        else:
            try:
                duration = int(duration_raw)
            except Exception:
                duration = 120
            if duration < 1:
                duration = 120
            stop = start + timedelta(minutes=duration)

        if stop <= start:
            errors.append(f"event #{index}: stop must be after start")
            continue

        if not category:
            category = category_for_channel(channel)

        events.append({
            "channel": channel,
            "title": title,
            "desc": desc,
            "category": category,
            "start": start,
            "stop": stop,
        })

    events.sort(key=lambda event: (event["start"], event["channel"], event["title"]))
    return events, errors


def build_demo_programmes(channels: list[tuple[str, str]]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    stop = start + timedelta(hours=2)

    events: list[dict[str, Any]] = []
    for channel_id, name in channels:
        events.append({
            "channel": channel_id,
            "title": f"{name} - EPG Test",
            "desc": "Demo-Eintrag. Wenn du das im EPG siehst, funktioniert GitHub Pages + EPGImport.",
            "category": category_for_channel(channel_id),
            "start": start,
            "stop": stop,
        })
    return events


def write_xmltv(channels: list[tuple[str, str]], events: list[dict[str, Any]]) -> None:
    lines: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<tv generator-info-name="Secret_DE_EPG">')

    for channel_id, name in channels:
        lines.append(f'  <channel id="{esc(channel_id)}">')
        lines.append(f'    <display-name>{esc(name)}</display-name>')
        lines.append("  </channel>")

    for event in events:
        lines.append(
            f'  <programme start="{xml_time(event["start"])}" stop="{xml_time(event["stop"])}" channel="{esc(event["channel"])}">'
        )
        lines.append(f'    <title lang="de">{esc(event["title"])}</title>')
        if event.get("desc"):
            lines.append(f'    <desc lang="de">{esc(event["desc"])}</desc>')
        if event.get("category"):
            lines.append(f'    <category lang="de">{esc(event["category"])}</category>')
        lines.append("  </programme>")

    lines.append("</tv>")
    xml_text = "\n".join(lines) + "\n"

    xml_path = PUBLIC / "sports-events.xml"
    xz_path = PUBLIC / "sports-events.xml.xz"

    xml_path.write_text(xml_text, encoding="utf-8", newline="\n")

    with lzma.open(xz_path, "wb", preset=6) as handle:
        handle.write(xml_text.encode("utf-8"))


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
    (EPGIMPORT / "sports-events.sources.xml").write_text(source_xml, encoding="utf-8", newline="\n")

    channel_lines = ['<?xml version="1.0" encoding="utf-8"?>', "<channels>"]
    for channel_id, _name in channels:
        placeholder = "DEINE_SERVICE_REFERENCE_FUER_" + channel_id.upper().replace(".", "_").replace("-", "_")
        channel_lines.append(f'  <channel id="{esc(channel_id)}">{esc(placeholder)}</channel>')
    channel_lines.append("</channels>")

    (EPGIMPORT / "sports-events.channels.xml").write_text(
        "\n".join(channel_lines) + "\n", encoding="utf-8", newline="\n"
    )


def write_index(channels: list[tuple[str, str]], manual_event_count: int, fallback_used: bool) -> None:
    rows = []
    for prefix, label, start, end, suffix in CHANNEL_GROUPS:
        suffix_text = f" {suffix}" if suffix else ""
        rows.append(
            f"<li><code>{esc(prefix)}.01</code> bis <code>{esc(prefix)}.{end:02d}</code> — {esc(label)} 1-{end}{esc(suffix_text)}</li>"
        )
    for channel_id, name in EXTRA_CHANNELS:
        rows.append(f"<li><code>{esc(channel_id)}</code> — {esc(name)}</li>")

    mode = "Demo-Fallback" if fallback_used else "Manuelle Events aktiv"

    html_doc = f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Secret DE EPG</title>
</head>
<body>
  <h1>Secret DE EPG</h1>
  <p>Modus: <strong>{esc(mode)}</strong></p>
  <p>Manuelle Events: {manual_event_count}</p>
  <p>XMLTV Feed: <a href="sports-events.xml.xz">sports-events.xml.xz</a></p>
  <p>Unkomprimierte XML: <a href="sports-events.xml">sports-events.xml</a></p>
  <p>Status: <a href="status.json">status.json</a></p>
  <p>EPGImport Source: <a href="epgimport/sports-events.sources.xml">sports-events.sources.xml</a></p>
  <p>EPGImport Channels: <a href="epgimport/sports-events.channels.xml">sports-events.channels.xml</a></p>
  <h2>Channel-ID-Gruppen</h2>
  <ul>
    {''.join(rows)}
  </ul>
  <p>Channels insgesamt: {len(channels)}</p>
</body>
</html>
'''
    (PUBLIC / "index.html").write_text(html_doc, encoding="utf-8", newline="\n")


def write_status(channels: list[tuple[str, str]], events: list[dict[str, Any]], manual_event_count: int, fallback_used: bool, errors: list[str]) -> None:
    events_by_channel: dict[str, int] = {}
    for event in events:
        channel = str(event["channel"])
        events_by_channel[channel] = events_by_channel.get(channel, 0) + 1

    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": repo_pages_url(),
        "channel_count": len(channels),
        "event_count": len(events),
        "manual_event_count": manual_event_count,
        "fallback_used": fallback_used,
        "manual_events_file": str(MANUAL_EVENTS_FILE.relative_to(ROOT)) if MANUAL_EVENTS_FILE.exists() else "data/manual_events.json missing",
        "errors": errors,
        "events_by_channel": events_by_channel,
        "groups": [group[0] for group in CHANNEL_GROUPS],
    }
    (PUBLIC / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    channels = build_channels()
    valid_channel_ids = {channel_id for channel_id, _name in channels}

    manual_events, manual_errors = load_manual_events(valid_channel_ids)

    if manual_events:
        events = manual_events
        fallback_used = False
    else:
        events = build_demo_programmes(channels)
        fallback_used = True

    write_xmltv(channels, events)
    write_epgimport_files(channels)
    write_index(channels, len(manual_events), fallback_used)
    write_status(channels, events, len(manual_events), fallback_used, manual_errors)

    print(f"Generated {len(channels)} channels")
    print(f"Generated {len(events)} programmes")
    print(f"Manual events: {len(manual_events)}")
    print(f"Fallback used: {fallback_used}")
    print(f"Public folder: {PUBLIC}")


if __name__ == "__main__":
    main()
