#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone, timedelta
import html
import json
import lzma
import os

ROOT = Path(os.environ.get("GITHUB_WORKSPACE", Path(__file__).resolve().parent)).resolve()
PUBLIC = ROOT / "public"
EPGIMPORT = PUBLIC / "epgimport"

PUBLIC.mkdir(parents=True, exist_ok=True)
EPGIMPORT.mkdir(parents=True, exist_ok=True)

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


def build_demo_programmes(channels: list[tuple[str, str]]) -> list[str]:
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    stop = start + timedelta(hours=2)

    lines: list[str] = []

    for channel_id, name in channels:
        category = category_for_channel(channel_id)
        lines.append(
            f'  <programme start="{xml_time(start)}" stop="{xml_time(stop)}" channel="{esc(channel_id)}">'
        )
        lines.append(f'    <title lang="de">{esc(name)} - EPG Test</title>')
        lines.append(
            '    <desc lang="de">Demo-Eintrag. Wenn du das im EPG siehst, funktioniert GitHub Pages + EPGImport.</desc>'
        )
        lines.append(f'    <category lang="de">{esc(category)}</category>')
        lines.append("  </programme>")

    return lines


def write_xmltv(channels: list[tuple[str, str]]) -> int:
    lines: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<tv generator-info-name="Secret_DE_EPG">')

    for channel_id, name in channels:
        lines.append(f'  <channel id="{esc(channel_id)}">')
        lines.append(f'    <display-name>{esc(name)}</display-name>')
        lines.append("  </channel>")

    programme_lines = build_demo_programmes(channels)
    lines.extend(programme_lines)
    lines.append("</tv>")

    xml_text = "\n".join(lines) + "\n"

    xml_path = PUBLIC / "sports-events.xml"
    xz_path = PUBLIC / "sports-events.xml.xz"

    xml_path.write_text(xml_text, encoding="utf-8", newline="\n")

    with lzma.open(xz_path, "wb", preset=6) as handle:
        handle.write(xml_text.encode("utf-8"))

    return len(channels)


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


def write_index(channels: list[tuple[str, str]]) -> None:
    rows = []
    for prefix, label, _start, end, suffix in CHANNEL_GROUPS:
        suffix_text = f" {suffix}" if suffix else ""
        rows.append(
            f"<li><code>{esc(prefix)}.01</code> bis <code>{esc(prefix)}.{end:02d}</code> — "
            f"{esc(label)} 1-{end}{esc(suffix_text)}</li>"
        )
    for channel_id, name in EXTRA_CHANNELS:
        rows.append(f"<li><code>{esc(channel_id)}</code> — {esc(name)}</li>")

    html_doc = f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Secret DE EPG</title>
</head>
<body>
  <h1>Secret DE EPG</h1>
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


def write_status(channels: list[tuple[str, str]], programme_count: int) -> None:
    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": repo_pages_url(),
        "channel_count": len(channels),
        "event_count": programme_count,
        "fallback_used": True,
        "note": "Stable demo feed. Real provider scrapers can be added after the GitHub Pages pipeline is stable.",
        "groups": [group[0] for group in CHANNEL_GROUPS],
    }
    (PUBLIC / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    channels = build_channels()
    programme_count = write_xmltv(channels)
    write_epgimport_files(channels)
    write_index(channels)
    write_status(channels, programme_count)

    print(f"Generated {len(channels)} channels")
    print(f"Generated {programme_count} demo programmes")
    print(f"Public folder: {PUBLIC}")
    print(f"Feed: {PUBLIC / 'sports-events.xml.xz'}")
    print(f"Status: {PUBLIC / 'status.json'}")


if __name__ == "__main__":
    main()
