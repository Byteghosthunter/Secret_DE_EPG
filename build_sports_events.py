#!/usr/bin/env python3
"""
Sports Event EPG starter builder.

This first version creates a valid XMLTV feed and EPGImport helper files.
Later, provider scrapers can be added here for DAZN, DYN, Prime, Eurosport,
Discovery, Sporteurope/SportDeutschland, RTL+ SPORT, etc.
"""

from __future__ import annotations

import datetime as dt
import html
import lzma
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
EPGIMPORT = PUBLIC / "epgimport"

OWNER = os.environ.get("GITHUB_OWNER", "DEIN-GITHUB-NAME")
REPO = os.environ.get("GITHUB_REPO", "sports-event-epg")
PAGES_BASE_URL = f"https://{OWNER}.github.io/{REPO}"


def xml_escape(value: str) -> str:
    return html.escape(value or "", quote=True)


def xmltv_time(value: dt.datetime) -> str:
    # XMLTV erwartet z.B. 20260711201500 +0200.
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone(dt.timedelta(hours=2)))
    return value.strftime("%Y%m%d%H%M%S %z")


def channel_ids() -> list[tuple[str, str]]:
    channels: list[tuple[str, str]] = []

    def add_range(prefix: str, label: str, start: int, end: int) -> None:
        for i in range(start, end + 1):
            channels.append((f"{prefix}.{i:02d}", f"{label} {i}"))

    add_range("rtlplus.sport", "RTL+ SPORT", 1, 20)
    add_range("dazn.event", "DAZN Event", 1, 10)
    add_range("dazn.bundesliga", "DAZN Bundesliga", 1, 10)
    add_range("dazn.ufc", "DAZN UFC", 1, 10)
    add_range("dazn.nba", "DAZN NBA", 1, 10)
    add_range("dazn.nfl", "DAZN NFL", 1, 10)
    add_range("dazn.laliga", "DAZN LaLiga", 1, 10)
    add_range("dazn.ligue1", "DAZN Ligue 1", 1, 10)
    add_range("dazn.seriea", "DAZN Serie A", 1, 10)
    add_range("dyn.sport", "DYN Sport", 1, 25)
    add_range("prime.event", "Amazon Prime Event", 1, 9)
    add_range("discovery.extra", "Discovery Extra", 1, 16)
    add_range("eurosport.extra", "Eurosport Extra", 1, 16)
    add_range("sporteurope.tv", "Sporteurope.TV", 1, 20)
    channels.append(("sporteurope.del2", "Sporteurope.TV DEL2"))
    channels.append(("sportdeutschland.del2", "SportDeutschland.TV DEL2"))
    return channels


def demo_events(now: dt.datetime) -> list[dict[str, str | int | dt.datetime]]:
    # Dummy-Events nur zum technischen Test. Später durch echte Providerdaten ersetzen.
    base = now.replace(hour=20, minute=15, second=0, microsecond=0)
    if base < now:
        base += dt.timedelta(days=1)
    return [
        {
            "channel": "rtlplus.sport.01",
            "start": base,
            "duration": 180,
            "title": "Demo: RTL+ SPORT Event",
            "category": "Sport",
            "desc": "Technischer Testeintrag. Wird später durch echte RTL+ Daten ersetzt.",
        },
        {
            "channel": "dazn.bundesliga.01",
            "start": base + dt.timedelta(hours=1),
            "duration": 150,
            "title": "Demo: DAZN Bundesliga Event",
            "category": "Fußball",
            "desc": "Technischer Testeintrag. Wird später durch echte DAZN Daten ersetzt.",
        },
        {
            "channel": "dyn.sport.01",
            "start": base + dt.timedelta(hours=2),
            "duration": 120,
            "title": "Demo: DYN Sport Event",
            "category": "Sport",
            "desc": "Technischer Testeintrag. Wird später durch echte DYN Daten ersetzt.",
        },
    ]


def write_xmltv() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    EPGIMPORT.mkdir(parents=True, exist_ok=True)

    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=2)))
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<tv generator-info-name="sports-event-epg" generator-info-url="https://github.com/">',
    ]

    for channel_id, display_name in channel_ids():
        lines.extend([
            f'  <channel id="{xml_escape(channel_id)}">',
            f'    <display-name>{xml_escape(display_name)}</display-name>',
            '  </channel>',
        ])

    for event in demo_events(now):
        start = event["start"]
        stop = start + dt.timedelta(minutes=int(event["duration"]))
        lines.extend([
            f'  <programme start="{xmltv_time(start)}" stop="{xmltv_time(stop)}" channel="{xml_escape(str(event["channel"]))}">',
            f'    <title lang="de">{xml_escape(str(event["title"]))}</title>',
            f'    <category lang="de">{xml_escape(str(event["category"]))}</category>',
            f'    <desc lang="de">{xml_escape(str(event["desc"]))}</desc>',
            '  </programme>',
        ])

    lines.append('</tv>')
    xml_data = "\n".join(lines) + "\n"
    (PUBLIC / "sports-events.xml").write_text(xml_data, encoding="utf-8")
    with lzma.open(PUBLIC / "sports-events.xml.xz", "wt", encoding="utf-8", preset=9) as f:
        f.write(xml_data)


def write_sources_xml() -> None:
    source = f'''<?xml version="1.0" encoding="utf-8"?>
<sources>
    <sourcecat sourcecatname="Sports Event EPG">
        <source type="gen_xmltv" nocheck="1" channels="/etc/epgimport/sports-events.channels.xml">
            <description>Sports Event EPG - DAZN / DYN / Prime / Discovery / Eurosport / Sporteurope</description>
            <url>{PAGES_BASE_URL}/sports-events.xml.xz</url>
        </source>
    </sourcecat>
</sources>
'''
    (EPGIMPORT / "sports-events.sources.xml").write_text(source, encoding="utf-8")


def write_channels_xml() -> None:
    lines = ['<?xml version="1.0" encoding="utf-8"?>', '<channels>']
    for channel_id, display_name in channel_ids():
        # Platzhalter: Nutzer ersetzen das in e-channelizer oder manuell durch eigene Service Reference.
        placeholder = f"DEINE_SERVICE_REFERENCE_{display_name.upper().replace(' ', '_').replace('+', 'PLUS').replace('.', '').replace('-', '_')}"
        lines.append(f'    <channel id="{xml_escape(channel_id)}">{xml_escape(placeholder)}</channel>')
    lines.append('</channels>')
    (EPGIMPORT / "sports-events.channels.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_index() -> None:
    html_page = f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Sports Event EPG</title>
</head>
<body>
  <h1>Sports Event EPG</h1>
  <p>XMLTV Feed: <a href="sports-events.xml.xz">sports-events.xml.xz</a></p>
  <p>EPGImport Source: <a href="epgimport/sports-events.sources.xml">sports-events.sources.xml</a></p>
  <p>EPGImport Channels Template: <a href="epgimport/sports-events.channels.xml">sports-events.channels.xml</a></p>
</body>
</html>
'''
    (PUBLIC / "index.html").write_text(html_page, encoding="utf-8")


def main() -> None:
    write_xmltv()
    write_sources_xml()
    write_channels_xml()
    write_index()
    print(f"Built {PUBLIC / 'sports-events.xml.xz'}")
    print(f"Pages base URL: {PAGES_BASE_URL}")


if __name__ == "__main__":
    main()
