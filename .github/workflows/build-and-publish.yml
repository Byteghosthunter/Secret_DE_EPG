#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone, timedelta
import html
import json
import lzma
import os
import urllib.request
from typing import Any

ROOT = Path(os.environ.get("GITHUB_WORKSPACE", Path(__file__).resolve().parent)).resolve()
PUBLIC = ROOT / "public"
EPGIMPORT = PUBLIC / "epgimport"
DATA = ROOT / "data"
MANUAL_EVENTS_FILE = DATA / "manual_events.json"
SCRAPER_CONFIG_FILE = DATA / "scraper_config.json"

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
    ("dazn.ucl", "DAZN UEFA Champions League", 1, 20, "FHD"),
    ("dyn.sport", "DYN Sport", 1, 25, ""),
    ("amazon.live", "Amazon Live Event", 1, 8, ""),
    ("prime.event", "Amazon Prime Event", 1, 9, ""),
    ("discovery.extra", "Discovery Extra", 1, 16, ""),
    ("eurosport.extra", "Eurosport Extra", 1, 16, ""),
    ("sporteurope.tv", "SportDeutschland.TV", 1, 20, ""),
    ("ufcfightpass.event", "UFC Fight Pass Event", 1, 5, ""),
]

EXTRA_CHANNELS: list[tuple[str, str]] = [
    ("sporteurope.del2", "Sport.DE DEL 2"),
    ("ufcfightpass.24x7", "UFC Fight Pass 24/7"),
]

DEFAULT_SCRAPER_CONFIG: dict[str, Any] = {
    "scrapers_enabled": True,
    "providers": {
        "dazn_epgpw": {
            "enabled": True,
            "url": "https://epg.pw/api/epg.json?channel_id=76632",
            "timeout_seconds": 12,
        }
    },
}


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
    if channel_id.startswith("ufcfightpass."):
        return "MMA"
    if channel_id.startswith("dazn.ucl."):
        return "Fußball"
    if ".ufc." in channel_id:
        return "MMA"
    if ".nba." in channel_id:
        return "Basketball"
    if ".nfl." in channel_id:
        return "American Football"
    if any(token in channel_id for token in ("laliga", "ligue1", "seriea", "bundesliga")):
        return "Fußball"
    return "Sport"


def load_json_file(path: Path, fallback: Any) -> tuple[Any, list[str]]:
    if not path.exists():
        return fallback, [f"{path.relative_to(ROOT)} not found"]
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except Exception as exc:
        return fallback, [f"{path.relative_to(ROOT)} parse error: {type(exc).__name__}: {exc}"]


def load_scraper_config() -> tuple[dict[str, Any], list[str]]:
    raw, errors = load_json_file(SCRAPER_CONFIG_FILE, DEFAULT_SCRAPER_CONFIG)
    if not isinstance(raw, dict):
        return DEFAULT_SCRAPER_CONFIG, errors + ["data/scraper_config.json must be an object"]
    config = DEFAULT_SCRAPER_CONFIG.copy()
    config.update(raw)
    if not isinstance(config.get("providers"), dict):
        config["providers"] = DEFAULT_SCRAPER_CONFIG["providers"]
    return config, errors


def load_manual_events(valid_channel_ids: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    raw, errors = load_json_file(MANUAL_EVENTS_FILE, [])
    events: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return [], errors + ["manual_events.json must be a JSON array"]
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            errors.append(f"manual event #{index}: must be an object")
            continue
        channel = str(item.get("channel", "")).strip()
        title = str(item.get("title", "")).strip()
        desc = str(item.get("desc", "")).strip()
        category = str(item.get("category", "")).strip()
        start_raw = item.get("start")
        stop_raw = item.get("stop")
        duration_raw = item.get("duration_minutes", item.get("duration", 120))
        if not channel:
            errors.append(f"manual event #{index}: missing channel")
            continue
        if channel not in valid_channel_ids:
            errors.append(f"manual event #{index}: unknown channel {channel}")
            continue
        if not title:
            errors.append(f"manual event #{index}: missing title")
            continue
        if not start_raw:
            errors.append(f"manual event #{index}: missing start")
            continue
        try:
            start = parse_datetime(str(start_raw))
        except Exception as exc:
            errors.append(f"manual event #{index}: invalid start: {exc}")
            continue
        if stop_raw:
            try:
                stop = parse_datetime(str(stop_raw))
            except Exception as exc:
                errors.append(f"manual event #{index}: invalid stop: {exc}")
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
            errors.append(f"manual event #{index}: stop must be after start")
            continue
        if not category:
            category = category_for_channel(channel)
        events.append({
            "source": "manual",
            "channel": channel,
            "title": title,
            "desc": desc,
            "category": category,
            "start": start,
            "stop": stop,
        })
    events.sort(key=lambda event: (event["start"], event["channel"], event["title"]))
    return events, errors


def http_json(url: str, timeout_seconds: int) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Secret_DE_EPG/1.0 (+https://github.com/Byteghosthunter/Secret_DE_EPG)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8", errors="replace"))


def map_dazn_title_to_channel(title: str, desc: str) -> tuple[str, str]:
    text = f"{title} {desc}".casefold()

    # Specific DAZN group channels first.
    if any(word in text for word in ("ufc", "mixed martial arts", "mma", "extreme fighting championship", "oktagon", "octagon")):
        return "dazn.ufc.01", "MMA"

    if any(word in text for word in ("nba", "basketball")):
        return "dazn.nba.01", "Basketball"

    if any(word in text for word in ("nfl", "american football")):
        return "dazn.nfl.01", "American Football"

    if "bundesliga" in text:
        return "dazn.bundesliga.01", "Fußball"

    if any(word in text for word in ("laliga", "la liga")):
        return "dazn.laliga.01", "Fußball"

    if "ligue 1" in text:
        return "dazn.ligue1.01", "Fußball"

    if any(word in text for word in ("serie a", "serie-a")):
        return "dazn.seriea.01", "Fußball"

    if any(word in text for word in ("champions league", "uefa champions league", "ucl")):
        return "dazn.ucl.01", "Fußball"

    # General DAZN event channel distribution.
    # This keeps mixed sports away from dazn.ufc.01 and avoids putting everything on dazn.event.01.
    if any(word in text for word in ("boxen", "boxing")):
        return "dazn.event.02", "Boxen"

    if any(word in text for word in ("fußball", "fussball", "dfb.tv", "u19-em", "champions league", "europa league", "conference league")):
        return "dazn.event.03", "Fußball"

    if any(word in text for word in ("rad:", "radsport", "tour de france", "giro", "vuelta", "cycling")):
        return "dazn.event.04", "Radsport"

    if any(word in text for word in ("traillauf", "utmb", "marathon", "laufen", "running")):
        return "dazn.event.05", "Laufen"

    if any(word in text for word in ("springreiten", "reiten", "equestrian", "global champions tour")):
        return "dazn.event.06", "Reiten"

    if any(word in text for word in ("rallye", "wrc", "motorsport", "formel", "formula")):
        return "dazn.event.07", "Motorsport"

    if any(word in text for word in ("tennis", "wta", "atp")):
        return "dazn.event.08", "Tennis"

    if any(word in text for word in ("handball", "ehf")):
        return "dazn.event.09", "Handball"

    return "dazn.event.01", "Sport"

def scrape_dazn_epgpw(config: dict[str, Any], valid_channel_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider_status: dict[str, Any] = {
        "source": "epg.pw",
        "channel_id": "76632",
        "url": "",
        "raw_events": 0,
        "mapped_events": 0,
        "kept_events": 0,
        "dropped_past_events": 0,
        "dropped_future_events": 0,
        "errors": [],
        "filter": "v9: keep events with stop > now - 2h and start < now + 10d",
    }

    provider_cfg = config.get("providers", {}).get("dazn_epgpw", {})
    if not provider_cfg.get("enabled", True):
        provider_status["errors"].append("provider disabled")
        return [], provider_status

    url = str(provider_cfg.get("url", DEFAULT_SCRAPER_CONFIG["providers"]["dazn_epgpw"]["url"]))
    timeout_seconds = int(provider_cfg.get("timeout_seconds", 12))
    provider_status["url"] = url

    try:
        payload = http_json(url, timeout_seconds)
    except Exception as exc:
        provider_status["errors"].append(f"fetch failed: {type(exc).__name__}: {exc}")
        return [], provider_status

    epg_list = payload.get("epg_list", []) if isinstance(payload, dict) else []
    if not isinstance(epg_list, list):
        provider_status["errors"].append("epg_list missing or not a list")
        return [], provider_status

    provider_status["raw_events"] = len(epg_list)

    parsed_items: list[dict[str, Any]] = []
    for index, item in enumerate(epg_list, start=1):
        if not isinstance(item, dict):
            continue

        title = str(item.get("title") or "").strip()
        desc = str(item.get("desc") or "").strip()
        start_raw = item.get("start_date") or item.get("start")

        if not title or not start_raw:
            continue

        try:
            start = parse_datetime(str(start_raw))
        except Exception as exc:
            provider_status["errors"].append(f"event #{index}: invalid start: {exc}")
            continue

        channel, category = map_dazn_title_to_channel(title, desc)
        if channel not in valid_channel_ids:
            channel = "dazn.event.01"

        parsed_items.append({
            "source": "dazn_epgpw",
            "channel": channel,
            "title": title,
            "desc": desc,
            "category": category,
            "start": start,
            "stop": start + timedelta(hours=2),
        })

    parsed_items.sort(key=lambda event: event["start"])

    # epg.pw returns one linear schedule. End time is inferred from the next item.
    for idx, event in enumerate(parsed_items):
        if idx + 1 < len(parsed_items):
            next_start = parsed_items[idx + 1]["start"]
            if next_start > event["start"]:
                event["stop"] = next_start
        if event["stop"] <= event["start"]:
            event["stop"] = event["start"] + timedelta(hours=2)

    provider_status["mapped_events"] = len(parsed_items)

    now_utc = datetime.now(timezone.utc)
    keep_after = now_utc - timedelta(hours=2)
    keep_before = now_utc + timedelta(days=10)

    filtered_items: list[dict[str, Any]] = []
    for event in parsed_items:
        start_utc = event["start"].astimezone(timezone.utc)
        stop_utc = event["stop"].astimezone(timezone.utc)

        if stop_utc <= keep_after:
            provider_status["dropped_past_events"] += 1
            continue
        if start_utc >= keep_before:
            provider_status["dropped_future_events"] += 1
            continue

        filtered_items.append(event)

    provider_status["kept_events"] = len(filtered_items)
    return filtered_items, provider_status

def build_demo_programmes(channels: list[tuple[str, str]]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    stop = start + timedelta(hours=24)
    events: list[dict[str, Any]] = []
    for channel_id, name in channels:
        events.append({
            "source": "demo",
            "channel": channel_id,
            "title": f"{name} - EPG Test",
            "desc": "Demo-Eintrag. Wenn du das im EPG siehst, funktioniert GitHub Pages + EPGImport.",
            "category": category_for_channel(channel_id),
            "start": start,
            "stop": stop,
        })
    return events


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda item: (item["start"], item["channel"], item["title"])):
        key = (str(event["channel"]), event["start"].isoformat(), str(event["title"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    return result


def write_xmltv(channels: list[tuple[str, str]], events: list[dict[str, Any]]) -> None:
    lines: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<tv generator-info-name="Secret_DE_EPG">')
    for channel_id, name in channels:
        lines.append(f'  <channel id="{esc(channel_id)}">')
        lines.append(f'    <display-name>{esc(name)}</display-name>')
        lines.append("  </channel>")
    for event in events:
        lines.append(f'  <programme start="{xml_time(event["start"])}" stop="{xml_time(event["stop"])}" channel="{esc(event["channel"])}">')
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



def write_events_debug(events: list[dict[str, Any]]) -> None:
    debug_events: list[dict[str, Any]] = []

    for event in sorted(events, key=lambda item: (item["start"], item["channel"], item["title"])):
        debug_events.append({
            "source": str(event.get("source", "unknown")),
            "channel": str(event.get("channel", "")),
            "start": event["start"].isoformat(),
            "stop": event["stop"].isoformat(),
            "title": str(event.get("title", "")),
            "category": str(event.get("category", "")),
            "desc": str(event.get("desc", "")),
        })

    (PUBLIC / "events-debug.json").write_text(
        json.dumps(debug_events, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = ["Secret_DE_EPG events debug", ""]
    for item in debug_events:
        lines.append(f'{item["start"]} - {item["stop"]}')
        lines.append(f'  source:   {item["source"]}')
        lines.append(f'  channel:  {item["channel"]}')
        lines.append(f'  title:    {item["title"]}')
        lines.append(f'  category: {item["category"]}')
        if item["desc"]:
            desc = item["desc"].replace("\\n", " ").strip()
            if len(desc) > 240:
                desc = desc[:237] + "..."
            lines.append(f'  desc:     {desc}')
        lines.append("")

    (PUBLIC / "events-debug.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

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
    (EPGIMPORT / "sports-events.channels.xml").write_text("\n".join(channel_lines) + "\n", encoding="utf-8", newline="\n")


def write_index(channels: list[tuple[str, str]], manual_count: int, scraped_count: int, fallback_used: bool) -> None:
    rows = []
    for prefix, label, start, end, suffix in CHANNEL_GROUPS:
        suffix_text = f" {suffix}" if suffix else ""
        rows.append(f"<li><code>{esc(prefix)}.01</code> bis <code>{esc(prefix)}.{end:02d}</code> — {esc(label)} 1-{end}{esc(suffix_text)}</li>")
    for channel_id, name in EXTRA_CHANNELS:
        rows.append(f"<li><code>{esc(channel_id)}</code> — {esc(name)}</li>")
    mode = "Demo-Fallback" if fallback_used else "Manuell/Scraper aktiv"
    html_doc = f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Secret DE EPG</title>
</head>
<body>
  <h1>Secret DE EPG</h1>
  <p>Modus: <strong>{esc(mode)}</strong></p>
  <p>Manuelle Events: {manual_count}</p>
  <p>Scraper Events: {scraped_count}</p>
  <p>XMLTV Feed: <a href="sports-events.xml.xz">sports-events.xml.xz</a></p>
  <p>Unkomprimierte XML: <a href="sports-events.xml">sports-events.xml</a></p>
  <p>Status: <a href="status.json">status.json</a></p>
  <p>Events Debug JSON: <a href="events-debug.json">events-debug.json</a></p>
  <p>Events Debug TXT: <a href="events-debug.txt">events-debug.txt</a></p>
  <p>EPGImport Source: <a href="epgimport/sports-events.sources.xml">sports-events.sources.xml</a></p>
  <p>EPGImport Channels: <a href="epgimport/sports-events.channels.xml">sports-events.channels.xml</a></p>
  <h2>Channel-ID-Gruppen</h2>
  <ul>{''.join(rows)}</ul>
  <p>Channels insgesamt: {len(channels)}</p>
</body>
</html>
'''
    (PUBLIC / "index.html").write_text(html_doc, encoding="utf-8", newline="\n")


def write_status(channels: list[tuple[str, str]], events: list[dict[str, Any]], manual_count: int, scraped_count: int, fallback_used: bool, manual_errors: list[str], config_errors: list[str], provider_status: dict[str, Any]) -> None:
    events_by_channel: dict[str, int] = {}
    events_by_source: dict[str, int] = {}
    for event in events:
        channel = str(event["channel"])
        source = str(event.get("source", "unknown"))
        events_by_channel[channel] = events_by_channel.get(channel, 0) + 1
        events_by_source[source] = events_by_source.get(source, 0) + 1
    status = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": repo_pages_url(),
        "channel_count": len(channels),
        "event_count": len(events),
        "manual_event_count": manual_count,
        "scraped_event_count": scraped_count,
        "fallback_used": fallback_used,
        "manual_events_file": str(MANUAL_EVENTS_FILE.relative_to(ROOT)) if MANUAL_EVENTS_FILE.exists() else "data/manual_events.json missing",
        "scraper_config_file": str(SCRAPER_CONFIG_FILE.relative_to(ROOT)) if SCRAPER_CONFIG_FILE.exists() else "data/scraper_config.json missing - defaults used",
        "errors": manual_errors + config_errors,
        "providers": {"dazn_epgpw": provider_status},
        "events_by_source": events_by_source,
        "events_by_channel": events_by_channel,
        "channel_extension_version": "v11-ufcfightpass-corrected",
        "new_channel_groups": ["dazn.ucl.01-20", "ufcfightpass.24x7", "ufcfightpass.event.01-05"],
        "dazn_mapping_version": "v8-distributed-events",
        "dazn_filter_version": "v9-drop-stale-events",
        "dazn_mapping_note": "Boxen -> dazn.event.02, Fußball -> dazn.event.03, Radsport -> dazn.event.04, Traillauf -> dazn.event.05, Reiten -> dazn.event.06, Motorsport -> dazn.event.07. UFC/MMA bleibt dazn.ufc.01. v9 filtert alte DAZN-Scraper-Einträge heraus.",
        "groups": [group[0] for group in CHANNEL_GROUPS],
    }
    (PUBLIC / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    channels = build_channels()
    valid_channel_ids = {channel_id for channel_id, _name in channels}
    config, config_errors = load_scraper_config()
    manual_events, manual_errors = load_manual_events(valid_channel_ids)
    provider_status: dict[str, Any] = {
        "source": "epg.pw",
        "channel_id": "76632",
        "url": "",
        "raw_events": 0,
        "mapped_events": 0,
        "errors": ["scrapers disabled"],
    }
    scraped_events: list[dict[str, Any]] = []
    if bool(config.get("scrapers_enabled", True)):
        scraped_events, provider_status = scrape_dazn_epgpw(config, valid_channel_ids)
    combined_events = dedupe_events(manual_events + scraped_events)
    if combined_events:
        events = combined_events
        fallback_used = False
    else:
        events = build_demo_programmes(channels)
        fallback_used = True
    write_xmltv(channels, events)
    write_events_debug(events)
    write_epgimport_files(channels)
    write_index(channels, len(manual_events), len(scraped_events), fallback_used)
    write_status(channels, events, len(manual_events), len(scraped_events), fallback_used, manual_errors, config_errors, provider_status)
    print(f"Generated {len(channels)} channels")
    print(f"Generated {len(events)} programmes")
    print(f"Manual events: {len(manual_events)}")
    print(f"Scraped events: {len(scraped_events)}")
    print(f"Fallback used: {fallback_used}")
    print(f"Public folder: {PUBLIC}")


if __name__ == "__main__":
    main()
