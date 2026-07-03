#!/usr/bin/env python3
"""
Secret_DE_EPG - Sports Event XMLTV builder

This starter builder creates a valid XMLTV feed and EPGImport source/channel templates
for fixed event-channel IDs. Real scrapers can be added later provider by provider.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone, timedelta
import html
import lzma
import os

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
EPGIMPORT = PUBLIC / "epgimport"
PUBLIC.mkdir(parents=True, exist_ok=True)
EPGIMPORT.mkdir(parents=True, exist_ok=True)


def repo_pages_url() -> str:
    """Return the GitHub Pages base URL, e.g. https://user.github.io/repo."""
    explicit = os.environ.get("PAGES_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}"

    # Fallback for local tests / this repository.
    return "https://byteghosthunter.github.io/Secret_DE_EPG"


CHANNEL_GROUPS: list[tuple[str, str, int, int]] = [
    # RTL+
    ("rtlplus.sport", "RTL+ SPORT", 1, 20),

    # DAZN generic and Bundesliga
    ("dazn.event", "DAZN Event", 1, 10),
    ("dazn.bundesliga", "DAZN Bundesliga", 1, 10),

    # DAZN requested sports/leagues
    ("dazn.laliga", "DAZN LaLiga", 1, 10),
    ("dazn.ufc", "DAZN UFC", 1, 10),
    ("dazn.nba", "DAZN NBA", 1, 10),
    ("dazn.nfl", "DAZN NFL", 1, 10),
    ("dazn.ligue1", "DAZN Ligue 1", 1, 10),
    ("dazn.seriea", "DAZN Serie A", 1, 10),

    # DYN
    ("dyn.sport", "DYN Sport", 1, 25),

    # Amazon Prime Video live event placeholders
    ("amazon.live", "Amazon Live Event", 1, 8),

    # Discovery / Eurosport / Sporteurope
    ("discovery.extra", "Discovery Extra", 1, 16),
    ("eurosport.extra", "Eurosport Extra", 1, 16),
    ("sporteurope.tv", "SportDeutschland.TV", 1, 20),
]

EXTRA_CHANNELS: list[tuple[str, str]] = [
    ("sporteurope.del2", "Sport.DE DEL 2"),
]


def build_channels() -> list[tuple[str, str]]:
    channels: list[tuple[str, str]] = []
    for prefix, label, start, end in CHANNEL_GROUPS:
        for number in range(start, end + 1):
            channels.append((f"{prefix}.{number:02d}", f"{label} {number} FHD"))
    channels.extend(EXTRA_CHANNELS)
    return channels


def xml_time(dt: datetime) -> str:
    # EPGImport/XMLTV accepts explicit timezone offsets. Germany uses +0200 in summer.
    return dt.astimezone(timezone(timedelta(hours=2))).strftime("%Y%m%d%H%M%S +0200")


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def build_demo_programmes(channels: list[tuple[str, str]]) -> list[str]:
    """Create one rolling demo programme per channel so mapping can be tested in EPGImport."""
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    stop = start + timedelta(hours=2)

    lines: list[str] = []
    for channel_id, name in channels:
        category = "Sport"
        if ".ufc." in channel_id:
            category = "MMA"
        elif ".nba." in channel_id:
            category = "Basketball"
        elif ".nfl." in channel_id:
            category = "American Football"
        elif any(token in channel_id for token in ["laliga", "ligue1", "seriea", "bundesliga"]):
            category = "Fußball"

        lines.append(f'  <programme start="{xml_time(start)}" stop="{xml_time(stop)}" channel="{esc(channel_id)}">')
        lines.append(f'    <title lang="de">{esc(name)} - EPG Test</title>')
        lines.append(f'    <desc lang="de">Demo-Eintrag. Wenn du das im EPG siehst, funktioniert die ID und dein Service-Reference-Mapping.</desc>')
        lines.append(f'    <category lang="de">{esc(category)}</category>')
        lines.append("  </programme>")
    return lines


def write_xmltv(channels: list[tuple[str, str]]) -> None:
    lines: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<tv generator-info-name="Secret_DE_EPG" generator-info-url="https://github.com/Byteghosthunter/Secret_DE_EPG">')

    for channel_id, name in channels:
        lines.append(f'  <channel id="{esc(channel_id)}">')
        lines.append(f'    <display-name>{esc(name)}</display-name>')
        lines.append("  </channel>")

    lines.extend(build_demo_programmes(channels))
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


def write_index(channels: list[tuple[str, str]]) -> None:
    groups = []
    for prefix, label, start, end in CHANNEL_GROUPS:
        groups.append(f"<li><code>{esc(prefix)}.01</code> bis <code>{esc(prefix)}.{end:02d}</code> — {esc(label)} 1-{end}</li>")
    for channel_id, name in EXTRA_CHANNELS:
        groups.append(f"<li><code>{esc(channel_id)}</code> — {esc(name)}</li>")

    html_doc = f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Secret DE EPG</title>
</head>
<body>
  <h1>Secret DE EPG</h1>
  <p>XMLTV Feed: <a href="sports-events.xml.xz">sports-events.xml.xz</a></p>
  <p>EPGImport Source: <a href="epgimport/sports-events.sources.xml">sports-events.sources.xml</a></p>
  <p>EPGImport Channels: <a href="epgimport/sports-events.channels.xml">sports-events.channels.xml</a></p>
  <h2>Channel-ID-Gruppen</h2>
  <ul>
    {''.join(groups)}
  </ul>
  <p>Channels insgesamt: {len(channels)}</p>
</body>
</html>
'''
    (PUBLIC / "index.html").write_text(html_doc, encoding="utf-8")


def main() -> None:
    channels = build_channels()
    write_xmltv(channels)
    write_epgimport_files(channels)
    write_index(channels)
    print(f"Generated {len(channels)} channels")
    print(f"Feed: {PUBLIC / 'sports-events.xml.xz'}")
    print(f"EPGImport source: {EPGIMPORT / 'sports-events.sources.xml'}")
    print(f"EPGImport channels: {EPGIMPORT / 'sports-events.channels.xml'}")


if __name__ == "__main__":
    main()
