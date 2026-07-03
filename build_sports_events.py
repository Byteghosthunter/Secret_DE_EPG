#!/usr/bin/env python3
"""
Secret_DE_EPG - Sports Event XMLTV builder

DAZN v2:
- Builds fixed channel IDs for EPGImport/e-channelizer mapping.
- Fetches DAZN EPG data from epg.pw JSON API as a practical XMLTV source.
- Categorises DAZN programmes into DAZN Bundesliga / LaLiga / UFC-MMA / NBA / NFL / Ligue 1 / Serie A / Event placeholders.
- Keeps a fallback event so the feed is never empty.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
import html
import json
import lzma
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve()
if HERE.parent.name == "builder":
    ROOT = HERE.parents[1]
else:
    ROOT = HERE.parent

PUBLIC = ROOT / "public"
EPGIMPORT = PUBLIC / "epgimport"
PUBLIC.mkdir(parents=True, exist_ok=True)
EPGIMPORT.mkdir(parents=True, exist_ok=True)

DAZN_EPGPW_CHANNEL_ID = os.environ.get("DAZN_EPGPW_CHANNEL_ID", "76632")
DAZN_EPG_DAYS = max(1, min(21, int(os.environ.get("DAZN_EPG_DAYS", "10"))))
DAZN_EPG_URL = "https://epg.pw/api/epg.json"


def repo_pages_url() -> str:
    explicit = os.environ.get("PAGES_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}"

    return "https://byteghosthunter.github.io/Secret_DE_EPG"


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
    ("discovery.extra", "Discovery Extra", 1, 16, ""),
    ("eurosport.extra", "Eurosport Extra", 1, 16, ""),
    ("sporteurope.tv", "SportDeutschland.TV", 1, 20, ""),
]

EXTRA_CHANNELS: list[tuple[str, str]] = [
    ("sporteurope.del2", "Sport.DE DEL 2"),
]


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


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def xml_time(dt: datetime) -> str:
    # Europe/Berlin summer offset in July is +0200. This feed is intended for German users.
    return dt.astimezone(timezone(timedelta(hours=2))).strftime("%Y%m%d%H%M%S +0200")


def norm_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = value.replace("ß", "ss")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_iso_dt(value: str) -> datetime | None:
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
            "User-Agent": "Secret_DE_EPG/0.2 (+https://github.com/Byteghosthunter/Secret_DE_EPG)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8", errors="replace"))


def epgpw_url_for_date(date_yyyymmdd: str) -> str:
    query = urllib.parse.urlencode({
        "channel_id": DAZN_EPGPW_CHANNEL_ID,
        "date": date_yyyymmdd,
        "timezone": "UTC",
    })
    return f"{DAZN_EPG_URL}?{query}"


def fetch_dazn_epgpw(days: int = DAZN_EPG_DAYS) -> tuple[list[dict], dict]:
    status = {
        "source": "epg.pw DAZN JSON",
        "channel_id": DAZN_EPGPW_CHANNEL_ID,
        "url_template": f"{DAZN_EPG_URL}?channel_id={DAZN_EPGPW_CHANNEL_ID}&date=YYYYMMDD&timezone=UTC",
        "days_requested": days,
        "raw_events": 0,
        "errors": [],
        "dates": [],
    }
    events_by_key: dict[tuple[str, str], dict] = {}
    today_utc = datetime.now(timezone.utc).date()

    for offset in range(days):
        day = today_utc + timedelta(days=offset)
        date_key = day.strftime("%Y%m%d")
        url = epgpw_url_for_date(date_key)
        try:
            data = http_json(url)
            epg_list = data.get("epg_list") or []
            status["dates"].append({"date": date_key, "events": len(epg_list), "error_code": data.get("error_code")})
            for item in epg_list:
                title = str(item.get("title") or "").strip()
                desc = str(item.get("desc") or "").strip()
                start = parse_iso_dt(str(item.get("start_date") or ""))
                if not title or not start:
                    continue
                key = (start.isoformat(), title)
                events_by_key[key] = {
                    "source": "epg.pw DAZN",
                    "title": title,
                    "desc": desc,
                    "start": start,
                    "raw": item,
                }
            time.sleep(0.25)
        except Exception as exc:
            status["errors"].append({"date": date_key, "url": url, "error": repr(exc)})

    events = sorted(events_by_key.values(), key=lambda item: item["start"])
    status["raw_events"] = len(events)
    return events, status


def classify_dazn_event(title: str, desc: str = "") -> tuple[str, str, int]:
    """Return (group_prefix, category, default_duration_minutes)."""
    text = norm_text(f"{title} {desc}")

    # Order matters. Put precise league/sport matches before generic football.
    if any(token in text for token in ["ufc", "mma", "mixed martial arts", "fighting championship", "extreme fighting championship"]):
        return "dazn.ufc", "MMA", 240

    if any(token in text for token in ["nfl", "american football", "game pass", "redzone", "super bowl"]):
        return "dazn.nfl", "American Football", 210

    if any(token in text for token in ["nba", "basketball nba"]):
        return "dazn.nba", "Basketball", 150

    if any(token in text for token in ["laliga", "la liga", "primera division", "spanien la liga"]):
        return "dazn.laliga", "Fußball", 135

    if any(token in text for token in ["ligue 1", "ligue1", "frankreich ligue", "franzoesische liga", "franzosische liga"]):
        return "dazn.ligue1", "Fußball", 135

    if any(token in text for token in ["serie a", "seriea", "italien serie", "italienische liga"]):
        return "dazn.seriea", "Fußball", 135

    # Keep football Bundesliga separate, but avoid mapping Handball-/Basketball-Bundesliga titles to DAZN Bundesliga.
    if "bundesliga" in text and not any(token in text for token in ["handball bundesliga", "basketball bundesliga", "volleyball bundesliga"]):
        return "dazn.bundesliga", "Fußball", 135

    # Generic DAZN event bucket.
    if any(token in text for token in ["boxen", "boxing", "fussball", "fu ball", "soccer", "rallye", "radsport", "tour de france", "tennis", "darts"]):
        return "dazn.event", "Sport", 120

    return "dazn.event", "Sport", 120


def programme_stop_for(index: int, events: list[dict], default_minutes: int) -> datetime:
    start = events[index]["start"]
    # Since epg.pw represents a linear DAZN schedule, the next programme start is a good stop time.
    if index + 1 < len(events):
        next_start = events[index + 1]["start"]
        delta = next_start - start
        if timedelta(minutes=10) <= delta <= timedelta(hours=8):
            return next_start
    return start + timedelta(minutes=default_minutes)


def map_dazn_events(raw_events: list[dict]) -> tuple[list[dict], dict]:
    status = {
        "mapped_events": 0,
        "events_by_channel": {},
        "events_by_group": {},
    }
    programmes: list[dict] = []
    counters: dict[str, int] = defaultdict(int)

    for index, event in enumerate(raw_events):
        prefix, category, default_duration = classify_dazn_event(event["title"], event.get("desc", ""))
        counters[prefix] += 1
        slot = ((counters[prefix] - 1) % 10) + 1
        channel_id = f"{prefix}.{slot:02d}"
        stop = programme_stop_for(index, raw_events, default_duration)

        desc = event.get("desc") or ""
        if desc:
            desc = f"{desc}\n\nQuelle: epg.pw DAZN EPG. Automatisch einsortiert in {channel_id}."
        else:
            desc = f"Quelle: epg.pw DAZN EPG. Automatisch einsortiert in {channel_id}."

        programmes.append({
            "channel": channel_id,
            "start": event["start"],
            "stop": stop,
            "title": event["title"],
            "desc": desc,
            "category": category,
            "source": event.get("source", "epg.pw DAZN"),
        })

    by_channel = Counter(item["channel"] for item in programmes)
    by_group = Counter(item["channel"].rsplit(".", 1)[0] for item in programmes)
    status["mapped_events"] = len(programmes)
    status["events_by_channel"] = dict(sorted(by_channel.items()))
    status["events_by_group"] = dict(sorted(by_group.items()))
    return programmes, status


def fallback_programmes() -> list[dict]:
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    return [{
        "channel": "dazn.event.01",
        "start": start,
        "stop": start + timedelta(hours=2),
        "title": "DAZN EPG Fallback / Test",
        "desc": "Der Feed funktioniert, aber die DAZN-EPG-Datenquelle hat aktuell keine verwertbaren Events geliefert.",
        "category": "Sport",
        "source": "fallback",
    }]


def write_xmltv(channels: list[tuple[str, str]], programmes: list[dict]) -> None:
    lines: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<tv generator-info-name="Secret_DE_EPG" generator-info-url="https://github.com/Byteghosthunter/Secret_DE_EPG">')

    for channel_id, name in channels:
        lines.append(f'  <channel id="{esc(channel_id)}">')
        lines.append(f'    <display-name>{esc(name)}</display-name>')
        lines.append('  </channel>')

    for programme in sorted(programmes, key=lambda item: (item["start"], item["channel"], item["title"])):
        lines.append(f'  <programme start="{xml_time(programme["start"])}" stop="{xml_time(programme["stop"])}" channel="{esc(programme["channel"])}">')
        lines.append(f'    <title lang="de">{esc(programme["title"])}</title>')
        if programme.get("desc"):
            lines.append(f'    <desc lang="de">{esc(programme["desc"])}</desc>')
        if programme.get("category"):
            lines.append(f'    <category lang="de">{esc(programme["category"])}</category>')
        lines.append('  </programme>')

    lines.append('</tv>')
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
    channel_lines.append('</channels>')
    (EPGIMPORT / "sports-events.channels.xml").write_text("\n".join(channel_lines) + "\n", encoding="utf-8")


def write_index(channels: list[tuple[str, str]], programmes: list[dict], status: dict) -> None:
    groups = []
    for prefix, label, start, end, suffix in CHANNEL_GROUPS:
        groups.append(f'<li><code>{esc(prefix)}.01</code> bis <code>{esc(prefix)}.{end:02d}</code> — {esc(label)} {start}-{end}</li>')
    for channel_id, name in EXTRA_CHANNELS:
        groups.append(f'<li><code>{esc(channel_id)}</code> — {esc(name)}</li>')

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
  <h2>Status</h2>
  <p>Channels insgesamt: {len(channels)}<br>Programme aktuell: {len(programmes)}<br>DAZN raw: {esc(status.get('dazn', {}).get('raw_events', 0))}<br>DAZN mapped: {esc(status.get('dazn', {}).get('mapped_events', 0))}</p>
  <h2>Channel-ID-Gruppen</h2>
  <ul>{''.join(groups)}</ul>
</body>
</html>
'''
    (PUBLIC / "index.html").write_text(html_doc, encoding="utf-8")


def write_status(channels: list[tuple[str, str]], programmes: list[dict], dazn_fetch_status: dict, dazn_map_status: dict, fallback_used: bool) -> dict:
    by_channel = Counter(item["channel"] for item in programmes)
    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": repo_pages_url(),
        "channel_count": len(channels),
        "event_count": len(programmes),
        "fallback_used": fallback_used,
        "events_by_channel": dict(sorted(by_channel.items())),
        "dazn": {
            **dazn_fetch_status,
            **dazn_map_status,
        },
    }
    (PUBLIC / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return status


def main() -> int:
    channels = build_channels()

    raw_dazn_events, fetch_status = fetch_dazn_epgpw()
    programmes, map_status = map_dazn_events(raw_dazn_events)

    fallback_used = False
    if not programmes:
        fallback_used = True
        programmes = fallback_programmes()

    status = write_status(channels, programmes, fetch_status, map_status, fallback_used)
    write_xmltv(channels, programmes)
    write_epgimport_files(channels)
    write_index(channels, programmes, status)

    print(f"Generated {len(channels)} channels")
    print(f"Generated {len(programmes)} programmes")
    print(f"DAZN raw events: {fetch_status.get('raw_events')}")
    print(f"DAZN mapped events: {map_status.get('mapped_events')}")
    print(f"Fallback used: {fallback_used}")
    print(f"Feed: {PUBLIC / 'sports-events.xml.xz'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
