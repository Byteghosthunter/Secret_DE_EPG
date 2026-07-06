#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Secret_DE_EPG / ByteGH Sports Event Builder

Drop-in version for the existing GitHub workflow.

Fixes:
- EPGImport source uses the E-Channelizer mapping file:
  /etc/epgimport/echannelizer.channels/bytegh.sport-feeds.xml
- The old sports-events.channels.xml is still generated only as a compatibility
  file because the GitHub workflow checks that it exists.
- status.json, events-debug.json and events-debug.txt are generated again.
- Index page no longer advertises sports-events.channels.xml as the active
  mapping file.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape as esc, unescape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import json
import lzma
import os
import re
import time
import urllib.parse
import urllib.error
import urllib.request

ROOT = Path(os.environ.get("GITHUB_WORKSPACE", Path(__file__).resolve().parent)).resolve()
PUBLIC = ROOT / "public"
EPGIMPORT = PUBLIC / "epgimport"
DATA = ROOT / "data"

MANUAL_EVENTS_FILE = DATA / "manual_events.json"
SCRAPER_CONFIG_FILE = DATA / "scraper_config.json"

ECHANNELIZER_CHANNELS_PATH = "/etc/epgimport/echannelizer.channels/bytegh.sport-feeds.xml"
SOURCECAT_NAME = "ByteGH - Sport Feed"
SOURCE_DESCRIPTION = "ByteGH - Sport Feed"

PUBLIC.mkdir(parents=True, exist_ok=True)
EPGIMPORT.mkdir(parents=True, exist_ok=True)
DATA.mkdir(parents=True, exist_ok=True)

BERLIN = timezone(timedelta(hours=2))

CHANNEL_GROUPS: list[tuple[str, str, int, int, str]] = [
    ("rtlplus.sport", "RTL+ SPORT", 1, 20, "FHD"),
    ("dazn.event", "DAZN Event", 1, 30, "FHD"),
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
        },
        "dazn_discovery_epg": {
            "enabled": True,
            "base_url": "https://epg.discovery.indazn.com/eu/v1/Epg",
            "country": "de",
            "languageCode": "de",
            "days_ahead": 7,
            "timeout_seconds": 20,
            "allowed_types": ["Live", "UpComing"],
        },
        "rtlplus": {
            "enabled": True,
            "urls": [
                "https://plus.rtl.de/live-events",
                "https://plus.rtl.de/rtlplus-root/sport-main-root-service-f_6",
            ],
            "timeout_seconds": 30,
        },
        "ufc_com": {
            "enabled": True,
            "url": "https://www.ufc.com/events",
            "timeout_seconds": 30,
        },
        "dyn_contentdesk": {
            "enabled": True,
            "base_url": "https://api.contentdesk.sport/public",
            "timeout_seconds": 25,
            "days_ahead": 120,
            "limit": 50,
            "completion_states": ["scheduled", "running"],
            "stages": [1, 2, 3, 4],
            "competitions": [
                {
                    "sport": "handball",
                    "label": "Daikin Handball-Bundesliga",
                    "uuid": "Q7Zk5rLkdJxBZgaXExX7Vb",
                    "category": "Handball"
                },
                {
                    "sport": "basketball",
                    "label": "easyCredit BBL",
                    "uuid": "NCmk4W4gjZ5PcD9y7K3hiZ",
                    "category": "Basketball"
                },
                {
                    "sport": "volleyball",
                    "label": "Volleyball Bundesliga",
                    "uuid": "LpS8QMGJSs4D4XiyM3ULZo",
                    "category": "Volleyball"
                },
                {
                    "sport": "tabletennis",
                    "label": "Tischtennis Bundesliga",
                    "uuid": "8HKTtNzWTZJBZii8ZSKh5h",
                    "category": "Tischtennis"
                }
            ]
        },
        "prime_video": {
            "enabled": True,
            "urls": [
                "https://www.amazon.de/-/de/gp/video/sports",
                "https://www.amazon.de/-/en/gp/video/sports"
            ],
            "timeout_seconds": 30,
            "days_ahead": 45,
            "allowed_statuses": ["UPCOMING", "LIVE"],
            "channel": "prime.event.01",
            "title_blacklist": [
                "Vive el Mundial",
                "Todo el Mundial",
                "El Pelotazo",
                "Hoy en el Mundial",
                "Inside The Ring",
                "Season 2026"
            ],
            "prefer_languages": ["de", "en"],
            "drop_language_suffixes": [
                " em Português",
                " en Español"
            ]
        },
        "discoveryplus_eurosport": {
            "enabled": True,
            "url": "https://www.discoveryplus.com/de/de/watch-eurosport-on-discoveryplus",
            "timeout_seconds": 30,
            "days_ahead": 60,
            "channel_prefix": "discovery.extra",
            "fallback_channel_prefix": "eurosport.extra",
            "detail_pages_enabled": True,
            "detail_timeout_seconds": 25,
            "max_detail_pages": 60
        },
    },
}


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
    # Original project used fixed +0200 output. Keep this for compatibility.
    return dt.astimezone(BERLIN).strftime("%Y%m%d%H%M%S +0200")


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
        dt = dt.replace(tzinfo=BERLIN)
    return dt


def category_for_channel(channel_id: str) -> str:
    if channel_id.startswith("ufcfightpass."):
        return "MMA"
    if ".ufc." in channel_id:
        return "MMA"
    if ".nba." in channel_id:
        return "Basketball"
    if ".nfl." in channel_id:
        return "American Football"
    if ".ucl." in channel_id:
        return "Fußball"
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

    config = json.loads(json.dumps(DEFAULT_SCRAPER_CONFIG))
    config.update(raw)
    if isinstance(raw.get("providers"), dict):
        config["providers"].update(raw["providers"])
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

        channel = str(item.get("channel") or item.get("channel_id") or "").strip()
        title = str(item.get("title") or item.get("name") or "").strip()
        desc = str(item.get("desc") or item.get("description") or "").strip()
        category = str(item.get("category") or "").strip()
        start_raw = item.get("start")
        stop_raw = item.get("stop") or item.get("end")
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


def map_dazn_title_to_channel(title: str, desc: str = "") -> tuple[str, str]:
    text = f"{title} {desc}".casefold()

    if any(word in text for word in (
        "ufc", "mixed martial arts", "mma", "extreme fighting championship",
        "oktagon", "octagon", "bare knuckle", "bkfc", "muay thai",
        "beatdown mma", "rajadamnern",
    )):
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

    if any(word in text for word in ("boxen", "boxing")):
        return "dazn.event.02", "Boxen"
    if any(word in text for word in ("fußball", "fussball", "dfb.tv", "u19-em", "europa league", "conference league")):
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



RTLPLUS_EVENT_RE = re.compile(
    r"(?P<title>.{3,140}?)\s+"
    r"(?P<sport>MMA|Motorsport|Fußball|Fussball|Sport|NFL|American Football|Show)"
    r"\s+•\s+"
    r"(?:Ab\s+\d+\s+•\s+)?"
    r"(?P<weekday>Mo|Di|Mi|Do|Fr|Sa|So)\.,\s+"
    r"(?P<day>[0-3]\d)\.(?P<month>[01]\d)\.(?P<year>\d{2}),\s+"
    r"(?P<hour>[0-2]\d):(?P<minute>[0-5]\d)\s+Uhr",
    flags=re.IGNORECASE,
)


def rtlplus_html_to_text(html: str) -> str:
    # Keep script blocks: RTL+ can include useful rendered/embedded text there.
    text = re.sub(r"(?is)<style\b.*?</style>", " ", html)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    text = text.replace("\\u0026", "&")
    text = text.replace("\\u003c", "<").replace("\\u003e", ">")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_rtlplus_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip(" -–—|•\t\r\n")
    cut_markers = [
        "Sport im Livestream",
        "Die nächsten Live-Events",
        "Start Alles Serien Filme Shows Themenwelten Live-TV Sport Audio Suche Paket wählen Profil und Einstellungen",
    ]
    for marker in cut_markers:
        if marker in title:
            title = title.split(marker, 1)[-1].strip()
    if len(title) > 90:
        chunks = re.split(r"\s{2,}| Mehr Details | Alles zur | Sport im Überblick ", title)
        chunks = [chunk.strip() for chunk in chunks if chunk.strip()]
        if chunks:
            title = chunks[-1]
    return title[:120].strip()


def parse_rtlplus_dt(day: str, month: str, year: str, hour: str, minute: str) -> datetime:
    return datetime(2000 + int(year), int(month), int(day), int(hour), int(minute), tzinfo=BERLIN)


def rtlplus_duration(title: str, sport: str) -> timedelta:
    text = f"{title} {sport}".casefold()
    if "oktagon" in text or "mma" in text:
        return timedelta(hours=5)
    if "motorsport" in text or "stunden von" in text or "le mans" in text:
        return timedelta(hours=4)
    if "football" in text or "nfl" in text:
        return timedelta(hours=3, minutes=30)
    if "fußball" in text or "fussball" in text:
        return timedelta(hours=2, minutes=30)
    return timedelta(hours=2)


def assign_rtlplus_channels(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Reuse rtlplus.sport.01 when events do not overlap; use .02/.03 only for overlaps.
    active_until: dict[int, datetime] = {}
    result: list[dict[str, Any]] = []

    for event in sorted(events, key=lambda item: (item["start"], item["title"])):
        chosen = None
        for number in range(1, 21):
            if number not in active_until or active_until[number] <= event["start"]:
                chosen = number
                break
        if chosen is None:
            chosen = 20

        new_event = dict(event)
        new_event["channel"] = f"rtlplus.sport.{chosen:02d}"
        active_until[chosen] = new_event["stop"]
        result.append(new_event)

    return result


def scrape_rtlplus(config: dict[str, Any], valid_channel_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider_status: dict[str, Any] = {
        "source": "RTL+ live events",
        "urls": [],
        "raw_matches": 0,
        "deduped_events": 0,
        "kept_events": 0,
        "errors": [],
        "pages": [],
        "sample_kept_events": [],
        "mapping": "non-overlapping events reuse rtlplus.sport.01; overlapping events use next free rtlplus.sport.*",
    }

    provider_cfg = config.get("providers", {}).get("rtlplus", {})
    if not provider_cfg.get("enabled", True):
        provider_status["errors"].append("provider disabled")
        return [], provider_status

    urls = provider_cfg.get("urls") or DEFAULT_SCRAPER_CONFIG["providers"]["rtlplus"]["urls"]
    if isinstance(urls, str):
        urls = [urls]
    timeout_seconds = int(provider_cfg.get("timeout_seconds", 30))
    provider_status["urls"] = list(urls)

    now_utc = datetime.now(timezone.utc)
    keep_after = now_utc - timedelta(hours=2)
    raw_events: list[dict[str, Any]] = []

    for url in urls:
        page_status = {"url": str(url), "ok": False, "bytes": 0, "matches": 0, "error": ""}
        try:
            request = urllib.request.Request(
                str(url),
                headers={
                    "User-Agent": "Mozilla/5.0 Secret_DE_EPG RTLPlus Scraper",
                    "Accept": "text/html,application/xhtml+xml,application/xml,application/json,*/*",
                    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read(1_500_000)
            html = raw.decode("utf-8", errors="replace")
            page_status["ok"] = True
            page_status["bytes"] = len(raw)
        except urllib.error.HTTPError as exc:
            page_status["error"] = f"HTTPError {exc.code}: {exc.reason}"
            provider_status["errors"].append(f"{url}: {page_status['error']}")
            provider_status["pages"].append(page_status)
            continue
        except Exception as exc:
            page_status["error"] = f"{type(exc).__name__}: {exc}"
            provider_status["errors"].append(f"{url}: {page_status['error']}")
            provider_status["pages"].append(page_status)
            continue

        text = rtlplus_html_to_text(html)
        seen_on_page: set[tuple[str, str]] = set()

        for match in RTLPLUS_EVENT_RE.finditer(text):
            title = clean_rtlplus_title(match.group("title"))
            sport = match.group("sport").strip()
            if not title or len(title) < 3:
                continue

            start = parse_rtlplus_dt(
                match.group("day"), match.group("month"), match.group("year"),
                match.group("hour"), match.group("minute")
            )
            stop = start + rtlplus_duration(title, sport)
            if stop.astimezone(timezone.utc) <= keep_after:
                continue

            key = (title.casefold(), start.isoformat())
            if key in seen_on_page:
                continue
            seen_on_page.add(key)

            raw_events.append({
                "source": "rtlplus",
                "channel": "rtlplus.sport.01",
                "title": title,
                "desc": f"RTL+ Live-Event: {title} ({sport})",
                "category": sport,
                "start": start,
                "stop": stop,
                "source_url": str(url),
            })

        page_status["matches"] = len(seen_on_page)
        provider_status["raw_matches"] += len(seen_on_page)
        provider_status["pages"].append(page_status)

    deduped: list[dict[str, Any]] = []
    seen_global: set[tuple[str, str]] = set()
    for event in sorted(raw_events, key=lambda item: (item["start"], item["title"])):
        key = (event["title"].casefold(), event["start"].isoformat())
        if key in seen_global:
            continue
        seen_global.add(key)
        deduped.append(event)

    mapped = assign_rtlplus_channels(deduped)
    mapped = [event for event in mapped if event["channel"] in valid_channel_ids]

    provider_status["deduped_events"] = len(deduped)
    provider_status["kept_events"] = len(mapped)
    provider_status["sample_kept_events"] = [
        {
            "channel": event["channel"],
            "start": event["start"].isoformat(),
            "stop": event["stop"].isoformat(),
            "title": event["title"],
            "category": event["category"],
            "source_url": event.get("source_url", ""),
        }
        for event in mapped[:25]
    ]
    return mapped, provider_status


UFC_BERLIN_TZ = ZoneInfo("Europe/Berlin")
UFC_EASTERN_TZ = ZoneInfo("America/New_York")
UFC_PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

UFC_MONTHS: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

UFC_TZ_MAP = {
    "EDT": UFC_EASTERN_TZ,
    "EST": UFC_EASTERN_TZ,
    "ET": UFC_EASTERN_TZ,
    "PDT": UFC_PACIFIC_TZ,
    "PST": UFC_PACIFIC_TZ,
    "PT": UFC_PACIFIC_TZ,
}

UFC_EVENT_RE = re.compile(
    r"(?P<title>.{3,140}?)\s+"
    r"(?P<weekday>Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+"
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+"
    r"(?P<day>[0-3]?\d)\s*/\s*"
    r"(?P<hour>[0-1]?\d):(?P<minute>[0-5]\d)\s*"
    r"(?P<ampm>AM|PM)\s*"
    r"(?P<tz>EDT|EST|ET|PDT|PST|PT)?\s*/\s*"
    r"(?P<card>Early Prelims|Prelims|Main Card)",
    flags=re.IGNORECASE,
)


def ufc_html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<style\b.*?</style>", " ", html)
    text = re.sub(r"(?is)<script\b.*?</script>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def ufc_upcoming_only(text: str) -> str:
    match = re.search(r"\bUpcoming\b.*?\bEvents\b", text, flags=re.I)
    if match:
        text = text[match.start():]

    cut_positions: list[int] = []
    for pattern in (r"\bPast\b\s+\d+\s+Filters\b", r"\bLoad More Past\b", r"\bWatch Replay\b", r"\bPast Events\b"):
        cut = re.search(pattern, text, flags=re.I)
        if cut:
            cut_positions.append(cut.start())
    if cut_positions:
        text = text[:min(cut_positions)]
    return text


def clean_ufc_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip(" -–—|•\t\r\n")
    fragments = [
        "Upcoming",
        "Filters",
        "How to Watch",
        "Start Times",
        "Early Prelims",
        "Prelims",
        "Main Card",
        "Watch On",
        "Watch on UFC Fight Pass",
        "Watch Live in Bar",
        "Find a bar",
        "View Event Details",
        "Tickets",
        "Fight Card",
        "View Fight Card",
        "See these athletes in action at",
        "Watch On-the-Go",
        "Download the UFC Mobile App",
        "What'S Trending Now Sponsored By",
        "What's Trending Now Sponsored By",
        "Sponsored By",
        "Showing this event live on pay-per-view",
    ]
    for fragment in fragments:
        if fragment in title:
            title = title.split(fragment)[-1].strip(" -–—|")

    title = re.sub(r"^\d+\s+UFC\s+\d+\s+", "", title, flags=re.I).strip()
    title = re.sub(r"^UFC\s+\d+\s+", "", title, flags=re.I).strip()

    if len(title) > 80:
        parts = re.split(
            r"\b(?:Tickets|How to Watch|View Event Details|Watch On|Fight Card|United States|Azerbaijan|Las Vegas|Oklahoma City|T-Mobile Arena|Paycom Center)\b",
            title,
        )
        parts = [part.strip(" -–—|,") for part in parts if part.strip(" -–—|,")]
        if parts:
            title = parts[-1]

    return title.strip(" -–—|,")[:100].strip()


def is_bad_ufc_title(title: str) -> bool:
    bad_fragments = [
        "Load More Past",
        "Watch Replay",
        "Fight Card Watch Replay",
        "Past",
        "Filters",
        "Events",
        "View Event Details",
        "How to Watch",
    ]
    title_lower = title.casefold()
    return any(fragment.casefold() in title_lower for fragment in bad_fragments) or len(title) < 3


def parse_ufc_dt(month: str, day: str, hour: str, minute: str, ampm: str, tz_text: str | None) -> datetime:
    now = datetime.now(timezone.utc).astimezone(UFC_BERLIN_TZ)
    year = now.year
    month_number = UFC_MONTHS[month.casefold()]
    h = int(hour)
    m = int(minute)

    if ampm.upper() == "PM" and h != 12:
        h += 12
    if ampm.upper() == "AM" and h == 12:
        h = 0

    zone = UFC_TZ_MAP.get((tz_text or "ET").upper(), UFC_EASTERN_TZ)
    return datetime(year, month_number, int(day), h, m, tzinfo=zone).astimezone(UFC_BERLIN_TZ)


def ufc_duration(card: str) -> timedelta:
    card_lower = card.casefold()
    if "early" in card_lower:
        return timedelta(hours=2)
    if "prelims" in card_lower:
        return timedelta(hours=2)
    return timedelta(hours=3)


def assign_ufc_channels(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active_until: dict[int, datetime] = {}
    result: list[dict[str, Any]] = []

    for event in sorted(events, key=lambda item: (item["start"], item["title"], item.get("card", ""))):
        chosen = None
        for number in range(1, 6):
            if number not in active_until or active_until[number] <= event["start"]:
                chosen = number
                break
        if chosen is None:
            chosen = 5

        new_event = dict(event)
        new_event["channel"] = f"ufcfightpass.event.{chosen:02d}"
        active_until[chosen] = new_event["stop"]
        result.append(new_event)

    return result


def scrape_ufc_com(config: dict[str, Any], valid_channel_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider_status: dict[str, Any] = {
        "source": "UFC.com events",
        "url": "",
        "ok": False,
        "bytes": 0,
        "matches_raw": 0,
        "matches_kept": 0,
        "dropped_past": 0,
        "dropped_bad_title": 0,
        "dropped_duplicate": 0,
        "errors": [],
        "sample_kept_events": [],
        "mapping": "upcoming UFC.com Main Card/Prelims entries -> ufcfightpass.event.01-.05",
    }

    provider_cfg = config.get("providers", {}).get("ufc_com", {})
    if not provider_cfg.get("enabled", True):
        provider_status["errors"].append("provider disabled")
        return [], provider_status

    url = str(provider_cfg.get("url", DEFAULT_SCRAPER_CONFIG["providers"]["ufc_com"]["url"]))
    timeout_seconds = int(provider_cfg.get("timeout_seconds", 30))
    provider_status["url"] = url

    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 Secret_DE_EPG UFC Scraper",
                "Accept": "text/html,application/xhtml+xml,application/xml,application/json,*/*",
                "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(2_000_000)
        html = raw.decode("utf-8", errors="replace")
        provider_status["ok"] = True
        provider_status["bytes"] = len(raw)
    except urllib.error.HTTPError as exc:
        provider_status["errors"].append(f"HTTPError {exc.code}: {exc.reason}")
        return [], provider_status
    except Exception as exc:
        provider_status["errors"].append(f"{type(exc).__name__}: {exc}")
        return [], provider_status

    now_berlin = datetime.now(timezone.utc).astimezone(UFC_BERLIN_TZ)
    text = ufc_upcoming_only(ufc_html_to_text(html))
    raw_events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for match in UFC_EVENT_RE.finditer(text):
        provider_status["matches_raw"] += 1
        title = clean_ufc_title(match.group("title"))
        card = match.group("card").strip()

        if is_bad_ufc_title(title):
            provider_status["dropped_bad_title"] += 1
            continue

        start = parse_ufc_dt(
            match.group("month"),
            match.group("day"),
            match.group("hour"),
            match.group("minute"),
            match.group("ampm"),
            match.group("tz"),
        )
        stop = start + ufc_duration(card)

        if stop < now_berlin - timedelta(hours=2):
            provider_status["dropped_past"] += 1
            continue

        key = (title.casefold(), start.isoformat(), card.casefold())
        if key in seen:
            provider_status["dropped_duplicate"] += 1
            continue
        seen.add(key)

        raw_events.append({
            "source": "ufc_com",
            "channel": "ufcfightpass.event.01",
            "title": title,
            "desc": f"UFC.com Event: {title} ({card})",
            "category": "MMA",
            "start": start,
            "stop": stop,
            "source_url": url,
            "card": card,
        })

    mapped = assign_ufc_channels(raw_events)
    mapped = [event for event in mapped if event["channel"] in valid_channel_ids]

    provider_status["matches_kept"] = len(mapped)
    provider_status["sample_kept_events"] = [
        {
            "channel": event["channel"],
            "start": event["start"].isoformat(),
            "stop": event["stop"].isoformat(),
            "title": event["title"],
            "category": event["category"],
            "card": event.get("card", ""),
            "source_url": event.get("source_url", ""),
        }
        for event in mapped[:25]
    ]
    return mapped, provider_status


def scrape_dazn_epgpw(config: dict[str, Any], valid_channel_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider_status: dict[str, Any] = {
        "source": "epg.pw",
        "url": "",
        "raw_events": 0,
        "mapped_events": 0,
        "kept_events": 0,
        "dropped_past_events": 0,
        "dropped_future_events": 0,
        "errors": [],
        "filter": "keep events with stop > now - 2h and start < now + 10d",
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

    # epg.pw is a linear schedule; infer stop from next event.
    for idx, event in enumerate(parsed_items):
        if idx + 1 < len(parsed_items):
            next_start = parsed_items[idx + 1]["start"]
            if next_start > event["start"]:
                event["stop"] = next_start
        if event["stop"] <= event["start"]:
            event["stop"] = event["start"] + timedelta(hours=2)

    provider_status["mapped_events"] = len(parsed_items)
    return filter_event_window(parsed_items, provider_status, days_ahead=10)


def dazn_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("Title", "Name", "title", "name"):
            if value.get(key):
                return str(value.get(key)).strip()
        return ""
    return str(value).strip()


def dazn_duration_for(title: str, sport: str, competition: str, typ: str) -> timedelta:
    text = f"{title} {sport} {competition} {typ}".casefold()
    if any(word in text for word in ("box", "ufc", "mma", "fight", "bare knuckle", "bkfc", "muay thai")):
        return timedelta(hours=3)
    if any(word in text for word in ("fussball", "fußball", "soccer", "football", "fifa", "liga", "league")):
        return timedelta(hours=2, minutes=30)
    if any(word in text for word in ("radsport", "tour de france", "motorsport", "rennen", "grand prix")):
        return timedelta(hours=2)
    return timedelta(hours=2)


def parse_dazn_discovery_tile(tile: dict[str, Any], provider_status: dict[str, Any], valid_channel_ids: set[str]) -> dict[str, Any] | None:
    title = str(tile.get("Title") or tile.get("title") or "").strip()
    desc = str(tile.get("Description") or tile.get("description") or "").strip()
    typ = str(tile.get("Type") or tile.get("type") or "").strip()
    sport = dazn_text(tile.get("Sport") or tile.get("sport"))
    competition = dazn_text(tile.get("Competition") or tile.get("competition"))
    start_raw = tile.get("Start") or tile.get("StartTime") or tile.get("StartDate") or tile.get("start")
    end_raw = tile.get("End") or tile.get("EndTime") or tile.get("EndDate") or tile.get("end")

    if not title or not start_raw:
        provider_status["dropped_missing_fields"] += 1
        return None

    try:
        start = parse_datetime(str(start_raw))
    except Exception as exc:
        provider_status["errors"].append(f"invalid start for {title}: {exc}")
        return None

    if end_raw:
        try:
            stop = parse_datetime(str(end_raw))
        except Exception:
            stop = start + dazn_duration_for(title, sport, competition, typ)
    else:
        stop = start + dazn_duration_for(title, sport, competition, typ)

    if stop <= start:
        stop = start + dazn_duration_for(title, sport, competition, typ)

    mapping_text = " | ".join(part for part in (title, sport, competition, desc) if part)
    channel, category = map_dazn_title_to_channel(mapping_text, desc)
    if channel not in valid_channel_ids:
        channel = "dazn.event.01"

    full_desc = desc
    extra = []
    if sport:
        extra.append(f"Sport: {sport}")
    if competition:
        extra.append(f"Wettbewerb: {competition}")
    if typ:
        extra.append(f"DAZN-Typ: {typ}")
    if extra:
        full_desc = (full_desc + "\n" if full_desc else "") + " | ".join(extra)

    return {
        "source": "dazn_discovery_epg",
        "channel": channel,
        "title": title,
        "desc": full_desc,
        "category": category,
        "start": start,
        "stop": stop,
        "dazn_type": typ,
        "dazn_sport": sport,
        "dazn_competition": competition,
    }


def channel_group_limit(prefix: str) -> int | None:
    for group_prefix, _label, start, end, _suffix in CHANNEL_GROUPS:
        if group_prefix == prefix and start == 1:
            return end
    return None


def distribute_overlapping_numeric_channels(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assigned_by_prefix: dict[str, list[dict[str, Any]]] = {}
    result: list[dict[str, Any]] = []

    for event in sorted(events, key=lambda item: (item["start"], item["channel"], item["title"])):
        channel = str(event.get("channel", ""))
        match = re.match(r"^(.+)\.(\d{2})$", channel)
        if not match:
            result.append(event)
            continue

        prefix = match.group(1)
        preferred = int(match.group(2))
        limit = channel_group_limit(prefix)
        if not limit:
            result.append(event)
            continue

        assigned = assigned_by_prefix.setdefault(prefix, [])
        order = list(range(preferred, limit + 1)) + list(range(1, preferred))
        chosen = preferred

        for number in order:
            candidate = f"{prefix}.{number:02d}"
            conflict = False
            for other in assigned:
                if other.get("channel") != candidate:
                    continue
                if event["start"] < other["stop"] and other["start"] < event["stop"]:
                    conflict = True
                    break
            if not conflict:
                chosen = number
                break

        new_event = dict(event)
        new_event["channel"] = f"{prefix}.{chosen:02d}"
        assigned.append(new_event)
        result.append(new_event)

    return sorted(result, key=lambda item: (item["start"], item["channel"], item["title"]))


def filter_event_window(events: list[dict[str, Any]], provider_status: dict[str, Any], days_ahead: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    now_utc = datetime.now(timezone.utc)
    keep_after = now_utc - timedelta(hours=2)
    keep_before = now_utc + timedelta(days=days_ahead)
    filtered: list[dict[str, Any]] = []

    provider_status.setdefault("dropped_past_events", 0)
    provider_status.setdefault("dropped_future_events", 0)

    for event in events:
        start_utc = event["start"].astimezone(timezone.utc)
        stop_utc = event["stop"].astimezone(timezone.utc)
        if stop_utc <= keep_after:
            provider_status["dropped_past_events"] += 1
            continue
        if start_utc >= keep_before:
            provider_status["dropped_future_events"] += 1
            continue
        filtered.append(event)

    provider_status["kept_events"] = len(filtered)
    return filtered, provider_status






DISCOVERYPLUS_EUROSPORT_TZ = ZoneInfo("Europe/Berlin")
DISCOVERYPLUS_LINK_RE = re.compile(
    r"""(?is)<a\b[^>]+href=["'](?P<href>(?:https://www\.discoveryplus\.com)?/(?:de/de/)?sports/(?P<year>20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})/[0-9a-f-]+)[^"']*["'][^>]*>(?P<body>.*?)</a>"""
)
DISCOVERYPLUS_DATE_RE = re.compile(
    r"\b(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+"
    r"(?P<day>[0-3]?\d),\s+"
    r"(?P<hour>[0-1]?\d):(?P<minute>[0-5]\d)\s*(?P<ampm>am|pm)\b",
    flags=re.IGNORECASE,
)
DISCOVERYPLUS_MONTHS: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


DISCOVERYPLUS_SCRIPT_RE = re.compile(r"(?is)<script\b[^>]*>(?P<body>.*?)</script>")
DISCOVERYPLUS_APP_JSON_MARKERS = [
    '{"props"',
    '{"pageProps"',
    '{"data"',
    '{"content"',
    '{"video"',
    '{"title"',
    '{"__typename"',
    '{"initialState"',
    '{"apolloState"',
]



def discoveryplus_clean(value: Any) -> str:
    text = unescape(str(value or ""))
    text = text.replace("\\u0026", "&").replace("\\/", "/")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def discoveryplus_html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<style\b.*?</style>", " ", html)
    text = re.sub(r"(?is)<script\b.*?</script>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return discoveryplus_clean(text)


def discoveryplus_http_text(url: str, timeout_seconds: int) -> tuple[str, str, int]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
                "Gecko/20100101 Firefox/128.0 Secret_DE_EPG DiscoveryPlus Eurosport"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-GB;q=0.7,en;q=0.6",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Connection": "close",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read(2_500_000)
        final_url = response.geturl()
    return raw.decode("utf-8", errors="replace"), final_url, len(raw)


def discoveryplus_parse_datetime_from_label(label: str, href_year: int, href_month: int, href_day: int) -> datetime | None:
    match = DISCOVERYPLUS_DATE_RE.search(label)
    if not match:
        return None

    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    ampm = match.group("ampm").lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0

    # The discovery+ DE page exposes event times for the German market.
    # The URL path provides the reliable event date; the label provides the time.
    return datetime(href_year, href_month, href_day, hour, minute, tzinfo=DISCOVERYPLUS_EUROSPORT_TZ)


def discoveryplus_parse_title_parts(label: str) -> tuple[str, str, str]:
    label = discoveryplus_clean(label)
    date_match = DISCOVERYPLUS_DATE_RE.search(label)
    before_date = label[:date_match.start()].strip() if date_match else label
    before_date = re.sub(r"^(Jetzt\s+Live\s*&\s+Demnächst\s+)?", "", before_date, flags=re.IGNORECASE).strip()

    match = re.match(r"^(?P<status>Demnächst|Live)\s+(?P<category>[A-ZÄÖÜ][\wÄÖÜäöüß+.-]+)\s+(?P<title>.+)$", before_date, flags=re.IGNORECASE)
    if match:
        status = discoveryplus_clean(match.group("status")).capitalize()
        category = discoveryplus_clean(match.group("category"))
        title = discoveryplus_clean(match.group("title"))
    else:
        status = "Demnächst"
        category = "Sport"
        title = before_date

    title = re.sub(r"^(Demnächst|Live)\s+", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"\s+", " ", title)
    return status, category, title


def discoveryplus_duration(category: str, title: str) -> timedelta:
    text = f"{category} {title}".casefold()
    if "velo club" in text or "experten-talk" in text or "tour-show" in text:
        return timedelta(minutes=75)
    if "multi-screen" in text or "multiview" in text:
        return timedelta(hours=5, minutes=30)
    if "tour de france" in text or "tour of austria" in text or "giro d" in text or "vuelta" in text:
        return timedelta(hours=6)
    if "goodwood" in text or "festival of speed" in text:
        return timedelta(hours=8)
    if "radsport" in text or "cycling" in text:
        return timedelta(hours=4)
    if "tennis" in text:
        return timedelta(hours=3)
    if "snooker" in text:
        return timedelta(hours=3)
    if "motorsport" in text or "formel" in text or "f1" in text:
        return timedelta(hours=3)
    if "wintersport" in text or "biathlon" in text or "ski" in text:
        return timedelta(hours=2)
    return timedelta(hours=2)


def discoveryplus_absolute_url(href: str, base_url: str) -> str:
    href = discoveryplus_clean(href)
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urllib.parse.urljoin(base_url, href)


def discoveryplus_balanced_json_from(raw: str, start: int) -> str:
    if start < 0 or start >= len(raw) or raw[start] not in "[{":
        return ""

    opening = raw[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False

    for pos in range(start, len(raw)):
        char = raw[pos]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return raw[start:pos + 1]

    return ""


def discoveryplus_find_mapped_data(obj: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if len(found) >= 200:
            return
        if isinstance(value, dict):
            mapped = value.get("mappedData")
            if isinstance(mapped, dict):
                for item in mapped.values():
                    if isinstance(item, dict):
                        found.append(item)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for child in value[:120]:
                if isinstance(child, (dict, list)):
                    walk(child)

    walk(obj)
    return found


def discoveryplus_detail_title_from_item(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    title_obj = item.get("title")
    full = ""
    short = ""
    if isinstance(title_obj, dict):
        full = discoveryplus_clean(title_obj.get("full", ""))
        short = discoveryplus_clean(title_obj.get("short", ""))
    else:
        full = discoveryplus_clean(title_obj)

    if not full and not short:
        full = discoveryplus_clean(item.get("name", "") or item.get("displayName", ""))

    sport = discoveryplus_clean(item.get("sport", ""))
    league = discoveryplus_clean(item.get("league", "") or item.get("competition", "") or item.get("tournament", ""))

    joined = f"{full} {short}".casefold()
    if "live & upcoming" in joined or joined.strip() in {"sports", "sport"}:
        return "", "", "", "", ""

    title = ""
    if full and short:
        if short.casefold().startswith(full.casefold()) or full.casefold() in short.casefold():
            title = short
        else:
            title = f"{full} | {short}"
    else:
        title = full or short

    title = re.sub(r"\s+", " ", title).strip(" |")

    image_url = ""
    images = item.get("images")
    if isinstance(images, dict):
        for key in ("default-wide", "cover-artwork", "background", "cover", "logo-centered"):
            value = discoveryplus_clean(images.get(key, ""))
            if value.startswith("http"):
                image_url = value
                break

    return title, sport, league, full, image_url


def discoveryplus_extract_detail_metadata(html: str) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []

    for script_match in DISCOVERYPLUS_SCRIPT_RE.finditer(html):
        raw = discoveryplus_clean(script_match.group("body"))
        if not raw:
            continue

        for marker in DISCOVERYPLUS_APP_JSON_MARKERS:
            start = raw.find(marker)
            if start < 0:
                continue
            block = discoveryplus_balanced_json_from(raw, start)
            if not block:
                continue
            try:
                data = json.loads(block)
            except Exception:
                continue

            for item in discoveryplus_find_mapped_data(data):
                title, sport, league, full_title, image_url = discoveryplus_detail_title_from_item(item)
                if not title:
                    continue
                score = 0
                score += 50 if title else 0
                score += 15 if sport else 0
                score += 15 if league else 0
                score += 5 if image_url else 0
                score += 5 if "|" in title else 0
                candidates.append({
                    "score": score,
                    "title": title,
                    "sport": sport,
                    "league": league,
                    "full_title": full_title,
                    "image_url": image_url,
                })
            break

    if not candidates:
        return {}

    candidates.sort(key=lambda item: (int(item.get("score", 0)), len(str(item.get("title", "")))), reverse=True)
    best = candidates[0]
    # Remove internal score from event metadata, keep it only in status sample.
    return {
        "title": discoveryplus_clean(best.get("title", "")),
        "sport": discoveryplus_clean(best.get("sport", "")),
        "league": discoveryplus_clean(best.get("league", "")),
        "full_title": discoveryplus_clean(best.get("full_title", "")),
        "image_url": discoveryplus_clean(best.get("image_url", "")),
        "candidate_count": len(candidates),
        "score": int(best.get("score", 0)),
    }


def discoveryplus_fetch_detail_metadata(url: str, timeout_seconds: int) -> dict[str, Any]:
    html, final_url, byte_count = discoveryplus_http_text(url, timeout_seconds)
    metadata = discoveryplus_extract_detail_metadata(html)
    metadata["final_url"] = final_url
    metadata["bytes"] = byte_count
    return metadata


def scrape_discoveryplus_eurosport(config: dict[str, Any], valid_channel_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider_status: dict[str, Any] = {
        "source": "Discovery+ Eurosport public event page",
        "enabled": False,
        "url": "",
        "final_url": "",
        "bytes": 0,
        "days_ahead": 0,
        "channel_prefix": "",
        "raw_links": 0,
        "parsed_events": 0,
        "kept_events": 0,
        "dropped_no_time": 0,
        "dropped_bad_title": 0,
        "dropped_unknown_channel": 0,
        "dropped_duplicate_events": 0,
        "detail_pages_enabled": False,
        "detail_pages_checked": 0,
        "detail_pages_ok": 0,
        "detail_pages_used": 0,
        "detail_pages_errors": [],
        "sample_detail_metadata": [],
        "errors": [],
        "sample_kept_events": [],
        "mapping": "overlapping events use discovery.extra.01-16 by default; fallback can use eurosport.extra.01-16",
    }

    provider_cfg = config.get("providers", {}).get("discoveryplus_eurosport", {})
    default_cfg = DEFAULT_SCRAPER_CONFIG["providers"]["discoveryplus_eurosport"]
    if not provider_cfg.get("enabled", default_cfg["enabled"]):
        provider_status["errors"].append("disabled")
        return [], provider_status

    provider_status["enabled"] = True
    url = discoveryplus_clean(provider_cfg.get("url", default_cfg["url"])) or default_cfg["url"]
    timeout_seconds = int(provider_cfg.get("timeout_seconds", default_cfg["timeout_seconds"]))
    days_ahead = int(provider_cfg.get("days_ahead", default_cfg["days_ahead"]))
    channel_prefix = discoveryplus_clean(provider_cfg.get("channel_prefix", default_cfg["channel_prefix"])) or "discovery.extra"
    fallback_channel_prefix = discoveryplus_clean(provider_cfg.get("fallback_channel_prefix", default_cfg["fallback_channel_prefix"])) or "eurosport.extra"
    detail_pages_enabled = bool(provider_cfg.get("detail_pages_enabled", default_cfg.get("detail_pages_enabled", True)))
    detail_timeout_seconds = int(provider_cfg.get("detail_timeout_seconds", default_cfg.get("detail_timeout_seconds", timeout_seconds)))
    max_detail_pages = int(provider_cfg.get("max_detail_pages", default_cfg.get("max_detail_pages", 60)))
    provider_status["detail_pages_enabled"] = detail_pages_enabled

    # Prefer discovery.extra.* because the source is the discovery+ Eurosport page.
    # If a local mapping only contains eurosport.extra.*, fall back automatically.
    if f"{channel_prefix}.01" not in valid_channel_ids and f"{fallback_channel_prefix}.01" in valid_channel_ids:
        channel_prefix = fallback_channel_prefix

    provider_status["url"] = url
    provider_status["days_ahead"] = days_ahead
    provider_status["channel_prefix"] = channel_prefix

    if f"{channel_prefix}.01" not in valid_channel_ids:
        provider_status["errors"].append(f"missing mapping for {channel_prefix}.01")
        return [], provider_status

    try:
        html, final_url, byte_count = discoveryplus_http_text(url, timeout_seconds)
        provider_status["final_url"] = final_url
        provider_status["bytes"] = byte_count
    except urllib.error.HTTPError as exc:
        provider_status["errors"].append(f"HTTPError {exc.code}: {exc.reason}")
        return [], provider_status
    except Exception as exc:
        provider_status["errors"].append(f"{type(exc).__name__}: {exc}")
        return [], provider_status

    events: list[dict[str, Any]] = []
    seen_links: set[str] = set()

    for match in DISCOVERYPLUS_LINK_RE.finditer(html):
        href = discoveryplus_absolute_url(match.group("href"), final_url or url)
        if href in seen_links:
            continue
        seen_links.add(href)
        provider_status["raw_links"] += 1

        label = discoveryplus_html_to_text(match.group("body"))
        if not label or len(label) < 8:
            provider_status["dropped_bad_title"] += 1
            continue

        start = discoveryplus_parse_datetime_from_label(
            label,
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
        if not start:
            provider_status["dropped_no_time"] += 1
            continue

        status, category, title = discoveryplus_parse_title_parts(label)
        if not title or len(title) < 3:
            provider_status["dropped_bad_title"] += 1
            continue

        detail_metadata: dict[str, Any] = {}
        if detail_pages_enabled and provider_status["detail_pages_checked"] < max_detail_pages:
            provider_status["detail_pages_checked"] += 1
            try:
                detail_metadata = discoveryplus_fetch_detail_metadata(href, detail_timeout_seconds)
                provider_status["detail_pages_ok"] += 1
                if detail_metadata.get("title"):
                    provider_status["detail_pages_used"] += 1
                    if len(provider_status["sample_detail_metadata"]) < 20:
                        provider_status["sample_detail_metadata"].append({
                            "source_url": href,
                            "title": detail_metadata.get("title", ""),
                            "sport": detail_metadata.get("sport", ""),
                            "league": detail_metadata.get("league", ""),
                            "candidate_count": detail_metadata.get("candidate_count", 0),
                            "score": detail_metadata.get("score", 0),
                        })
            except Exception as exc:
                provider_status["detail_pages_errors"].append(f"{href}: {type(exc).__name__}: {exc}")

        detail_title = discoveryplus_clean(detail_metadata.get("title", ""))
        detail_sport = discoveryplus_clean(detail_metadata.get("sport", ""))
        detail_league = discoveryplus_clean(detail_metadata.get("league", ""))
        detail_image_url = discoveryplus_clean(detail_metadata.get("image_url", ""))

        if detail_title:
            title = detail_title
        if detail_sport:
            category = detail_sport

        stop = start + discoveryplus_duration(category, title)
        desc_parts = ["Discovery+ / Eurosport", status]
        if category:
            desc_parts.append(category)
        if detail_league and detail_league.casefold() not in title.casefold():
            desc_parts.append(detail_league)
        desc = " · ".join(part for part in desc_parts if part)

        event = {
            "source": "discoveryplus_eurosport",
            "channel": f"{channel_prefix}.01",
            "title": title,
            "desc": desc,
            "category": category or "Sport",
            "start": start,
            "stop": stop,
            "source_url": href,
            "discoveryplus_status": status,
        }
        if detail_image_url:
            event["image_url"] = detail_image_url
        events.append(event)
        provider_status["parsed_events"] += 1

    deduped: list[dict[str, Any]] = []
    seen_events: set[tuple[str, str, str]] = set()
    for event in sorted(events, key=lambda item: (item["start"], item["title"])):
        source_url = str(event.get("source_url", ""))
        event_id_match = re.search(r"/sports/\d{4}-\d{1,2}-\d{1,2}/([^/?#]+)", source_url)
        event_id = event_id_match.group(1) if event_id_match else ""
        title_key = re.sub(r"\s+", " ", str(event.get("title", "")).casefold()).strip()
        start_key = event["start"].astimezone(timezone.utc).isoformat()
        key = (event_id or title_key, start_key, title_key)
        if key in seen_events:
            provider_status["dropped_duplicate_events"] += 1
            continue
        seen_events.add(key)
        deduped.append(event)

    filtered_events, provider_status = filter_event_window(deduped, provider_status, days_ahead=days_ahead)
    filtered_events = distribute_overlapping_numeric_channels(filtered_events)

    kept: list[dict[str, Any]] = []
    for event in filtered_events:
        if event["channel"] not in valid_channel_ids:
            provider_status["dropped_unknown_channel"] += 1
            continue
        kept.append(event)

    provider_status["kept_events"] = len(kept)
    provider_status["sample_kept_events"] = [
        {
            "channel": event["channel"],
            "start": event["start"].isoformat(),
            "stop": event["stop"].isoformat(),
            "title": event["title"],
            "category": event["category"],
            "status": event.get("discoveryplus_status", ""),
            "image_url": event.get("image_url", ""),
            "source_url": event.get("source_url", ""),
        }
        for event in kept[:40]
    ]
    return kept, provider_status

PRIME_SCRIPT_RE = re.compile(r"(?is)<script\b[^>]*>(.*?)</script>")

PRIME_DE_MONTHS = {
    "jan": 1, "januar": 1,
    "feb": 2, "februar": 2,
    "mär": 3, "märz": 3, "maerz": 3, "mrz": 3,
    "apr": 4, "april": 4,
    "mai": 5,
    "jun": 6, "juni": 6,
    "jul": 7, "juli": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oktober": 10,
    "nov": 11, "november": 11,
    "dez": 12, "dezember": 12,
}

PRIME_EN_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def prime_http_text(url: str, timeout_seconds: int) -> str:
    # Amazon can return 503 to obvious scripted clients. Use normal browser-like
    # headers and retry once before giving up.
    browser_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
            "Gecko/20100101 Firefox/128.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-GB;q=0.7,en;q=0.6",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Connection": "close",
    }

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers=browser_headers)
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read(5_500_000)
            return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last_error = exc
            # 503 is often temporary/bot-gate. Retry quickly; if it persists,
            # caller records the real HTTP status in status.json.
            if exc.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(2 + attempt * 3)
        except Exception as exc:
            last_error = exc
            time.sleep(2 + attempt * 3)

    if last_error:
        raise last_error
    raise RuntimeError("Prime fetch failed without exception")


def prime_clean(value: Any) -> str:
    text = unescape(str(value)).replace("\\u0026", "&").replace("\\/", "/")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def prime_iter_dicts(obj: Any, depth: int = 0):
    if depth > 12:
        return
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            if isinstance(value, (dict, list)):
                yield from prime_iter_dicts(value, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            yield from prime_iter_dicts(item, depth + 1)


def prime_parse_json_blocks(html: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    for script in PRIME_SCRIPT_RE.findall(html):
        raw = prime_clean(script)
        if not raw:
            continue

        candidates: list[str] = []
        if raw.startswith("{"):
            candidates.append(raw[:-1] if raw.endswith("};") else raw)

        idx = raw.find('{"init"')
        if idx >= 0:
            candidates.append(raw[idx:])

        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate.startswith("{"):
                continue

            depth = 0
            end = None
            in_string = False
            escaped = False

            for index, char in enumerate(candidate):
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue

                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break

            if end is None:
                continue

            try:
                data = json.loads(candidate[:end])
            except Exception:
                continue

            if isinstance(data, dict):
                blocks.append(data)
            break

    return blocks


def prime_find_request_context(data: Any) -> dict[str, Any] | None:
    for item in prime_iter_dicts(data):
        if not isinstance(item, dict):
            continue
        if "RequestContext" in item and isinstance(item["RequestContext"], dict):
            return item["RequestContext"]
        if any(key in item for key in ("recordTerritory", "currentTerritory", "marketplaceID", "originalURI")):
            return item
    return None


def prime_walk_containers(data: Any) -> list[tuple[str, str, list[Any]]]:
    containers: list[tuple[str, str, list[Any]]] = []

    for item in prime_iter_dicts(data):
        if not isinstance(item, dict):
            continue
        raw_entities = item.get("entities")
        if not isinstance(raw_entities, list):
            continue

        container_type = prime_clean(item.get("containerType", ""))
        container_title = ""

        for key in ("title", "displayTitle", "label", "heading", "collectionTitle"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                container_title = prime_clean(value)
                break
            if isinstance(value, dict):
                for nested_value in value.values():
                    if isinstance(nested_value, str) and nested_value.strip():
                        container_title = prime_clean(nested_value)
                        break
            if container_title:
                break

        containers.append((container_type, container_title, raw_entities))

    return containers


def prime_tzinfo(name: str) -> timezone:
    tz = prime_clean(name).upper()
    if tz in ("MESZ", "CEST"):
        return timezone(timedelta(hours=2))
    if tz in ("MEZ", "CET"):
        return timezone(timedelta(hours=1))
    if tz == "EDT":
        return timezone(timedelta(hours=-4))
    if tz == "EST":
        return timezone(timedelta(hours=-5))
    if tz in ("UTC", "GMT"):
        return timezone.utc
    return BERLIN


def prime_month_number(month: str) -> int | None:
    key = prime_clean(month).replace(".", "").casefold()
    key = key.replace("ä", "ä")
    if key in PRIME_DE_MONTHS:
        return PRIME_DE_MONTHS[key]
    if key in PRIME_EN_MONTHS:
        return PRIME_EN_MONTHS[key]
    return None


def prime_fix_year(dt: datetime, now_utc: datetime, explicit_year: bool) -> datetime:
    if explicit_year:
        return dt

    # Prime badges usually omit the year. Treat dates more than 14 days in the past
    # as next year, but otherwise let filter_event_window remove old events/replays.
    if dt.astimezone(timezone.utc) < now_utc - timedelta(days=14):
        try:
            return dt.replace(year=dt.year + 1)
        except ValueError:
            return dt + timedelta(days=365)
    return dt


def prime_parse_time_badge(value: str, now_utc: datetime | None = None) -> datetime:
    text = prime_clean(value)
    if not text:
        raise ValueError("empty Prime timeBadge")

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    # Relative forms: Heute/Morgen/Live um 19:00 MESZ.
    rel_match = re.search(
        r"(?i)\b(?P<rel>heute|morgen|today|tomorrow|live)\b(?:\s+um)?\s+"
        r"(?P<hour>[0-2]?\d)[:.](?P<minute>[0-5]\d)\s*(?P<tz>MESZ|MEZ|CEST|CET|EDT|EST|UTC|GMT)?",
        text,
    )
    if rel_match:
        tz = prime_tzinfo(rel_match.group("tz") or "MESZ")
        base = now_utc.astimezone(tz)
        rel = rel_match.group("rel").casefold()
        if rel in ("morgen", "tomorrow"):
            base = base + timedelta(days=1)
        hour = int(rel_match.group("hour"))
        minute = int(rel_match.group("minute"))
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # German: Do., 9. Juli 01:55 MESZ
    de_match = re.search(
        r"(?i)(?:\b(?:mo|di|mi|do|fr|sa|so|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\.?,?\s*)?"
        r"(?P<day>[0-3]?\d)\.\s*(?P<month>[A-Za-zÄäÖöÜü]+)\.?"
        r"(?:\s*(?P<year>20[2-9]\d))?"
        r"\s+(?P<hour>[0-2]?\d)[:.](?P<minute>[0-5]\d)\s*(?P<tz>MESZ|MEZ|CEST|CET|EDT|EST|UTC|GMT)?",
        text,
    )
    if de_match:
        month = prime_month_number(de_match.group("month"))
        if not month:
            raise ValueError(f"unknown German month in {text!r}")
        tz = prime_tzinfo(de_match.group("tz") or "MESZ")
        explicit_year = bool(de_match.group("year"))
        year = int(de_match.group("year") or now_utc.astimezone(tz).year)
        dt = datetime(
            year,
            month,
            int(de_match.group("day")),
            int(de_match.group("hour")),
            int(de_match.group("minute")),
            tzinfo=tz,
        )
        return prime_fix_year(dt, now_utc, explicit_year)

    # English: Sun 12 Jul 1:55 AM CEST
    en_match = re.search(
        r"(?i)(?:\b(?:mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\.?,?\s*)?"
        r"(?P<day>[0-3]?\d)\s+(?P<month>Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\.?"
        r"(?:\s*(?P<year>20[2-9]\d))?"
        r"\s+(?P<hour>[0-2]?\d)[:.](?P<minute>[0-5]\d)\s*(?P<ampm>AM|PM)?\s*(?P<tz>MESZ|MEZ|CEST|CET|EDT|EST|UTC|GMT)?",
        text,
    )
    if en_match:
        month = prime_month_number(en_match.group("month"))
        if not month:
            raise ValueError(f"unknown English month in {text!r}")
        tz = prime_tzinfo(en_match.group("tz") or "MESZ")
        explicit_year = bool(en_match.group("year"))
        year = int(en_match.group("year") or now_utc.astimezone(tz).year)
        hour = int(en_match.group("hour"))
        ampm = (en_match.group("ampm") or "").upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        dt = datetime(
            year,
            month,
            int(en_match.group("day")),
            hour,
            int(en_match.group("minute")),
            tzinfo=tz,
        )
        return prime_fix_year(dt, now_utc, explicit_year)

    raise ValueError(f"unsupported Prime timeBadge: {text!r}")


def prime_duration(title: str, container_title: str) -> timedelta:
    text = f"{title} {container_title}".casefold()
    if any(token in text for token in ("cricket", "test -", "test match")):
        return timedelta(hours=6)
    if any(token in text for token in ("mlb", "baseball", "draft")):
        return timedelta(hours=3, minutes=30)
    if any(token in text for token in ("nfl", "football", "49ers", "chargers", "rams", "packers", "cowboys")):
        return timedelta(hours=3, minutes=30)
    if any(token in text for token in ("nba", "wnba", "basketball", "aces", "fever", "mercury")):
        return timedelta(hours=2, minutes=30)
    if any(token in text for token in ("formel", "formula", "f1", "grand prix", "indy")):
        return timedelta(hours=2, minutes=30)
    if any(token in text for token in ("aew", "ufc", "boxing", "mma", "wrestling", "kampfsport")):
        return timedelta(hours=3)
    if any(token in text for token in ("fifa", "world cup", "fußball", "fussball", "soccer", "uefa", "champions league")):
        return timedelta(hours=2, minutes=15)
    return timedelta(hours=2)


def prime_category(title: str, container_title: str) -> str:
    text = f"{title} {container_title}".casefold()
    if any(token in text for token in ("aew", "ufc", "boxing", "mma", "wrestling", "kampfsport")):
        return "Kampfsport"
    if any(token in text for token in ("nba", "wnba", "basketball", "aces", "fever", "mercury")):
        return "Basketball"
    if any(token in text for token in ("nfl", "football", "49ers", "chargers", "rams", "packers", "cowboys")):
        return "American Football"
    if any(token in text for token in ("mlb", "baseball")):
        return "Baseball"
    if any(token in text for token in ("cricket", "test -")):
        return "Cricket"
    if any(token in text for token in ("formel", "formula", "f1", "grand prix", "indy")):
        return "Motorsport"
    if any(token in text for token in ("fifa", "world cup", "fußball", "fussball", "soccer", "uefa", "champions league", " vs. ", " vs ")):
        return "Fußball"
    return "Sport"


def prime_entity_link(entity: dict[str, Any], source_url: str) -> str:
    link = entity.get("link") if isinstance(entity.get("link"), dict) else {}
    raw_url = prime_clean(link.get("url", ""))
    if not raw_url:
        return source_url
    return urllib.parse.urljoin(source_url, raw_url)



def prime_title_blacklisted(title: str, blacklist: list[str]) -> bool:
    title_cf = prime_clean(title).casefold()
    for item in blacklist:
        item_cf = prime_clean(item).casefold()
        if item_cf and item_cf in title_cf:
            return True
    return False


def prime_is_language_variant(title: str, drop_suffixes: list[str]) -> bool:
    normalized = prime_clean(title)
    normalized_cf = normalized.casefold()
    for suffix in drop_suffixes:
        suffix_cf = prime_clean(suffix).casefold()
        if suffix_cf and normalized_cf.endswith(suffix_cf):
            return True
    return False


def prime_quality_skip_reason(title: str, blacklist: list[str], drop_suffixes: list[str]) -> str:
    if prime_title_blacklisted(title, blacklist):
        return "title_blacklist"
    if prime_is_language_variant(title, drop_suffixes):
        return "language_variant"
    return ""

def prime_parse_entity(
    entity: dict[str, Any],
    source_url: str,
    container_type: str,
    container_title: str,
    provider_status: dict[str, Any],
    allowed_statuses: set[str],
    channel: str,
    valid_channel_ids: set[str],
    title_blacklist: list[str],
    drop_language_suffixes: list[str],
) -> dict[str, Any] | None:
    if not isinstance(entity, dict):
        provider_status["dropped_bad_entities"] += 1
        return None

    if prime_clean(entity.get("entityType", "")).upper() != "EVENT":
        provider_status["dropped_non_event"] += 1
        return None

    title = prime_clean(entity.get("displayTitle") or entity.get("title", {}).get("text") if isinstance(entity.get("title"), dict) else entity.get("title") or "")
    if not title:
        provider_status["dropped_no_title"] += 1
        return None

    quality_skip_reason = prime_quality_skip_reason(title, title_blacklist, drop_language_suffixes)
    if quality_skip_reason == "title_blacklist":
        provider_status["dropped_title_blacklist"] += 1
        return None
    if quality_skip_reason == "language_variant":
        provider_status["dropped_language_variant"] += 1
        return None

    live_info = entity.get("liveInfo") if isinstance(entity.get("liveInfo"), dict) else {}
    status = prime_clean(live_info.get("status", "")).upper()
    if allowed_statuses and status not in allowed_statuses:
        provider_status["dropped_status"] += 1
        return None

    time_badge = prime_clean(live_info.get("timeBadge", ""))
    if not time_badge:
        provider_status["dropped_no_time_badge"] += 1
        return None

    try:
        start = prime_parse_time_badge(time_badge)
    except Exception as exc:
        provider_status["dropped_bad_time_badge"] += 1
        provider_status.setdefault("bad_time_badge_samples", [])
        if len(provider_status["bad_time_badge_samples"]) < 20:
            provider_status["bad_time_badge_samples"].append({"title": title, "timeBadge": time_badge, "error": str(exc)})
        return None

    stop = start + prime_duration(title, container_title)

    if channel not in valid_channel_ids:
        provider_status["dropped_unknown_channel"] += 1
        return None

    title_metadata = entity.get("entitlementCues", {}).get("titleMetadataBadge", {}) if isinstance(entity.get("entitlementCues"), dict) else {}
    badge_message = prime_clean(title_metadata.get("message", "")) if isinstance(title_metadata, dict) else ""

    desc_parts = [
        "Amazon Prime Video",
        f"Status: {status}",
        f"Zeit: {time_badge}",
    ]
    if container_title:
        desc_parts.append(f"Rubrik: {container_title}")
    if badge_message:
        desc_parts.append(f"Hinweis: {badge_message}")

    venue = prime_clean(live_info.get("venue", ""))
    if venue:
        desc_parts.append(f"Ort: {venue}")

    # Keep Prime detail link internally for debug/dedupe, but do not show URLs in Dreambox EPG descriptions.
    event_url = prime_entity_link(entity, source_url)

    return {
        "source": "prime_video",
        "channel": channel,
        "title": title,
        "desc": " | ".join(desc_parts),
        "category": prime_category(title, container_title),
        "start": start,
        "stop": stop,
        "prime_status": status,
        "prime_time_badge": time_badge,
        "prime_container": container_title,
        "prime_url": event_url,
    }


def scrape_prime_video(config: dict[str, Any], valid_channel_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider_status: dict[str, Any] = {
        "source": "Amazon Prime Video Sports",
        "enabled": False,
        "urls": [],
        "days_ahead": 0,
        "raw_entities": 0,
        "parsed_events": 0,
        "kept_events": 0,
        "dropped_non_event": 0,
        "dropped_status": 0,
        "dropped_bad_entities": 0,
        "dropped_no_title": 0,
        "dropped_no_time_badge": 0,
        "dropped_bad_time_badge": 0,
        "dropped_unknown_channel": 0,
        "dropped_duplicate_events": 0,
        "dropped_title_blacklist": 0,
        "dropped_language_variant": 0,
        "fallback_skipped_after_success": [],
        "territories": [],
        "url_results": [],
        "errors": [],
    }

    provider_cfg = config.get("providers", {}).get("prime_video", {})
    if not provider_cfg.get("enabled", DEFAULT_SCRAPER_CONFIG["providers"]["prime_video"]["enabled"]):
        provider_status["errors"].append("disabled")
        return [], provider_status

    provider_status["enabled"] = True

    urls = provider_cfg.get("urls", DEFAULT_SCRAPER_CONFIG["providers"]["prime_video"]["urls"])
    if not isinstance(urls, list) or not urls:
        urls = DEFAULT_SCRAPER_CONFIG["providers"]["prime_video"]["urls"]

    timeout_seconds = int(provider_cfg.get("timeout_seconds", DEFAULT_SCRAPER_CONFIG["providers"]["prime_video"]["timeout_seconds"]))
    days_ahead = int(provider_cfg.get("days_ahead", DEFAULT_SCRAPER_CONFIG["providers"]["prime_video"]["days_ahead"]))
    channel = prime_clean(provider_cfg.get("channel", DEFAULT_SCRAPER_CONFIG["providers"]["prime_video"]["channel"])) or "prime.event.01"

    allowed_statuses_raw = provider_cfg.get("allowed_statuses", DEFAULT_SCRAPER_CONFIG["providers"]["prime_video"]["allowed_statuses"])
    if not isinstance(allowed_statuses_raw, list):
        allowed_statuses_raw = ["UPCOMING", "LIVE"]
    allowed_statuses = {prime_clean(item).upper() for item in allowed_statuses_raw if prime_clean(item)}

    title_blacklist_raw = provider_cfg.get("title_blacklist", DEFAULT_SCRAPER_CONFIG["providers"]["prime_video"].get("title_blacklist", []))
    if not isinstance(title_blacklist_raw, list):
        title_blacklist_raw = []
    title_blacklist = [prime_clean(item) for item in title_blacklist_raw if prime_clean(item)]

    drop_language_suffixes_raw = provider_cfg.get("drop_language_suffixes", DEFAULT_SCRAPER_CONFIG["providers"]["prime_video"].get("drop_language_suffixes", []))
    if not isinstance(drop_language_suffixes_raw, list):
        drop_language_suffixes_raw = []
    drop_language_suffixes = [prime_clean(item) for item in drop_language_suffixes_raw if prime_clean(item)]

    provider_status["urls"] = [prime_clean(url) for url in urls]
    provider_status["days_ahead"] = days_ahead
    provider_status["allowed_statuses"] = sorted(allowed_statuses)
    provider_status["channel"] = channel
    provider_status["title_blacklist"] = title_blacklist
    provider_status["drop_language_suffixes"] = drop_language_suffixes

    events: list[dict[str, Any]] = []

    for raw_url in urls:
        url = prime_clean(raw_url)
        if not url:
            continue

        url_status = {
            "url": url,
            "ok": False,
            "bytes": 0,
            "json_blocks": 0,
            "containers": 0,
            "raw_entities": 0,
            "parsed_events": 0,
            "recordTerritory": "",
            "currentTerritory": "",
            "marketplaceID": "",
            "error": "",
        }

        try:
            html = prime_http_text(url, timeout_seconds)
            url_status["ok"] = True
            url_status["bytes"] = len(html.encode("utf-8", errors="replace"))
        except Exception as exc:
            url_status["error"] = f"{type(exc).__name__}: {exc}"
            provider_status["errors"].append(f"{url}: {url_status['error']}")
            provider_status["url_results"].append(url_status)
            continue

        blocks = prime_parse_json_blocks(html)
        url_status["json_blocks"] = len(blocks)

        for data in blocks:
            request_context = prime_find_request_context(data)
            if request_context:
                record_territory = prime_clean(request_context.get("recordTerritory", ""))
                current_territory = prime_clean(request_context.get("currentTerritory", ""))
                marketplace_id = prime_clean(request_context.get("marketplaceID", ""))
                url_status["recordTerritory"] = record_territory
                url_status["currentTerritory"] = current_territory
                url_status["marketplaceID"] = marketplace_id
                provider_status["territories"].append({
                    "url": url,
                    "recordTerritory": record_territory,
                    "currentTerritory": current_territory,
                    "marketplaceID": marketplace_id,
                })

            # Safety: only integrate DE marketplace/territory URLs by default.
            if "amazon.de" in url.casefold() and request_context:
                if prime_clean(request_context.get("currentTerritory", "")).upper() != "DE":
                    provider_status["errors"].append(f"{url}: skipped non-DE currentTerritory={request_context.get('currentTerritory')}")
                    continue
            elif "primevideo.com" in url.casefold() and request_context:
                provider_status["errors"].append(f"{url}: skipped primevideo.com territory={request_context.get('currentTerritory')} to avoid US feed")
                continue

            containers = prime_walk_containers(data)
            url_status["containers"] += len(containers)

            for container_type, container_title, raw_entities in containers:
                # Skip obvious replay/ended carousels even before entity parsing.
                container_text = f"{container_type} {container_title}".casefold()
                if any(token in container_text for token in ("wiederholung", "replay", "highlights", "kürzlich beendet", "ended")):
                    continue

                for entity in raw_entities:
                    if not isinstance(entity, dict):
                        continue
                    provider_status["raw_entities"] += 1
                    url_status["raw_entities"] += 1
                    event = prime_parse_entity(
                        entity,
                        url,
                        container_type,
                        container_title,
                        provider_status,
                        allowed_statuses,
                        channel,
                        valid_channel_ids,
                        title_blacklist,
                        drop_language_suffixes,
                    )
                    if not event:
                        continue
                    events.append(event)
                    provider_status["parsed_events"] += 1
                    url_status["parsed_events"] += 1

        provider_status["url_results"].append(url_status)

        # Important: amazon.de DE and amazon.de EN can expose overlapping/translated
        # copies of the same live events. Use EN only as a fallback if DE returned
        # no usable events. This keeps XMLTV clean while still surviving a DE-only
        # fetch issue.
        if "/-/de/" in url.casefold() and url_status.get("parsed_events", 0) > 0:
            remaining = [prime_clean(candidate) for candidate in urls if prime_clean(candidate) and prime_clean(candidate) != url]
            provider_status["fallback_skipped_after_success"].extend(remaining)
            break

    # De-duplicate exact Prime copies by detail id/start/title before the time-window
    # and overlap-channel distribution logic runs.
    deduped_prime_events: list[dict[str, Any]] = []
    seen_prime_events: set[tuple[str, str, str]] = set()
    for event in events:
        prime_url = str(event.get("prime_url", ""))
        detail_match = re.search(r"/detail/([^/?#]+)", prime_url)
        detail_id = detail_match.group(1) if detail_match else ""
        title_key = re.sub(r"\s+", " ", str(event.get("title", "")).casefold()).strip()
        start_key = event["start"].astimezone(timezone.utc).isoformat() if isinstance(event.get("start"), datetime) else ""
        key = (detail_id or title_key, start_key, title_key)
        if key in seen_prime_events:
            provider_status["dropped_duplicate_events"] += 1
            continue
        seen_prime_events.add(key)
        deduped_prime_events.append(event)
    # Fuzzy duplicate pass: if Prime provides the same start time and near-identical
    # same-event title in different languages, keep the first DE-preferred item.
    fuzzy_deduped_events: list[dict[str, Any]] = []
    seen_fuzzy: set[tuple[str, str]] = set()
    for event in deduped_prime_events:
        title_key = re.sub(r"\b(em português|en español|english|deutsch)\b", "", str(event.get("title", "")).casefold())
        title_key = re.sub(r"[^a-z0-9äöüß]+", " ", title_key).strip()
        start_key = event["start"].astimezone(timezone.utc).strftime("%Y%m%d%H%M") if isinstance(event.get("start"), datetime) else ""
        key = (start_key, title_key)
        if key in seen_fuzzy:
            provider_status["dropped_duplicate_events"] += 1
            continue
        seen_fuzzy.add(key)
        fuzzy_deduped_events.append(event)
    events = fuzzy_deduped_events

    filtered_events, provider_status = filter_event_window(events, provider_status, days_ahead=days_ahead)
    filtered_events = distribute_overlapping_numeric_channels(filtered_events)
    provider_status["kept_events"] = len(filtered_events)
    provider_status["sample_kept_events"] = [
        {
            "channel": str(item.get("channel", "")),
            "start": item["start"].isoformat(),
            "stop": item["stop"].isoformat(),
            "title": str(item.get("title", "")),
            "status": str(item.get("prime_status", "")),
            "container": str(item.get("prime_container", "")),
            "timeBadge": str(item.get("prime_time_badge", "")),
        }
        for item in filtered_events[:30]
    ]
    return filtered_events, provider_status

def dyn_duration_for_sport(sport: str, title: str = "") -> timedelta:
    text = f"{sport} {title}".casefold()
    if "basketball" in text:
        return timedelta(hours=2, minutes=30)
    if "volleyball" in text:
        return timedelta(hours=2, minutes=30)
    if "tabletennis" in text or "tischtennis" in text:
        return timedelta(hours=3, minutes=30)
    if "handball" in text:
        return timedelta(hours=2, minutes=15)
    return timedelta(hours=2)


def dyn_parse_side_name(side: Any) -> str:
    if not isinstance(side, dict):
        return ""
    for key in ("name", "displayName", "shortName"):
        value = str(side.get(key) or "").strip()
        if value:
            return value
    return ""


def dyn_parse_match_item(
    item: dict[str, Any],
    competition: dict[str, Any],
    allowed_states: set[str],
    valid_channel_ids: set[str],
    provider_status: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        provider_status["dropped_bad_items"] += 1
        return None

    state = str(item.get("completionState") or "").strip().casefold()
    if allowed_states and state not in allowed_states:
        provider_status["dropped_state_items"] += 1
        return None

    home = dyn_parse_side_name(item.get("homeSide") or item.get("homeTeam") or item.get("home"))
    away = dyn_parse_side_name(item.get("awaySide") or item.get("awayTeam") or item.get("away"))
    if not home or not away:
        provider_status["dropped_no_teams"] += 1
        return None

    title = f"{home} - {away}"

    live_broadcast = item.get("liveBroadcast") if isinstance(item.get("liveBroadcast"), dict) else {}
    start_raw = (
        str(live_broadcast.get("scheduledStart") or "").strip()
        or str(item.get("scheduledAt") or item.get("scheduledStart") or item.get("startDate") or "").strip()
    )
    stop_raw = (
        str(live_broadcast.get("scheduledEnd") or "").strip()
        or str(item.get("scheduledEnd") or item.get("endDate") or "").strip()
    )

    if not start_raw:
        provider_status["dropped_no_start"] += 1
        return None

    try:
        start = parse_datetime(start_raw)
    except Exception:
        provider_status["dropped_bad_start"] += 1
        return None

    if stop_raw:
        try:
            stop = parse_datetime(stop_raw)
        except Exception:
            stop = start + dyn_duration_for_sport(str(competition.get("sport", "")), title)
    else:
        stop = start + dyn_duration_for_sport(str(competition.get("sport", "")), title)

    if stop <= start:
        stop = start + dyn_duration_for_sport(str(competition.get("sport", "")), title)

    channel = "dyn.sport.01"
    if channel not in valid_channel_ids:
        provider_status["dropped_unknown_channel"] += 1
        return None

    category = str(competition.get("category") or "").strip() or category_for_channel(channel)
    competition_label = str(competition.get("label") or "DYN Sport").strip()
    gameday_id = str(item.get("gamedayId") or "").strip()
    uuid = str(item.get("uuid") or "").strip()

    desc_parts = [
        f"DYN Sport: {competition_label}",
        f"Status: {state or 'unknown'}",
    ]
    if gameday_id:
        desc_parts.append(f"GamedayId: {gameday_id}")
    if uuid:
        desc_parts.append(f"MatchId: {uuid}")

    return {
        "source": "dyn_contentdesk",
        "channel": channel,
        "title": title,
        "desc": " | ".join(desc_parts),
        "category": category,
        "start": start,
        "stop": stop,
        "dyn_sport": str(competition.get("sport", "")),
        "dyn_competition": competition_label,
        "dyn_state": state,
        "dyn_uuid": uuid,
        "dyn_gameday_id": gameday_id,
    }


def scrape_dyn_contentdesk(config: dict[str, Any], valid_channel_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider_status: dict[str, Any] = {
        "source": "DYN ContentDesk API",
        "enabled": False,
        "base_url": "",
        "days_ahead": 0,
        "completion_states": [],
        "competitions": [],
        "endpoint_results": [],
        "raw_items": 0,
        "parsed_items": 0,
        "kept_events": 0,
        "dropped_state_items": 0,
        "dropped_bad_items": 0,
        "dropped_no_teams": 0,
        "dropped_no_start": 0,
        "dropped_bad_start": 0,
        "dropped_unknown_channel": 0,
        "errors": [],
    }

    provider_cfg = config.get("providers", {}).get("dyn_contentdesk", {})
    if not provider_cfg.get("enabled", DEFAULT_SCRAPER_CONFIG["providers"]["dyn_contentdesk"]["enabled"]):
        provider_status["errors"].append("disabled")
        return [], provider_status

    provider_status["enabled"] = True
    base_url = str(provider_cfg.get("base_url", DEFAULT_SCRAPER_CONFIG["providers"]["dyn_contentdesk"]["base_url"])).rstrip("/")
    timeout_seconds = int(provider_cfg.get("timeout_seconds", DEFAULT_SCRAPER_CONFIG["providers"]["dyn_contentdesk"]["timeout_seconds"]))
    days_ahead = int(provider_cfg.get("days_ahead", DEFAULT_SCRAPER_CONFIG["providers"]["dyn_contentdesk"]["days_ahead"]))
    limit = int(provider_cfg.get("limit", DEFAULT_SCRAPER_CONFIG["providers"]["dyn_contentdesk"]["limit"]))
    if limit < 1 or limit > 100:
        limit = 50

    completion_states_raw = provider_cfg.get(
        "completion_states",
        DEFAULT_SCRAPER_CONFIG["providers"]["dyn_contentdesk"]["completion_states"],
    )
    if not isinstance(completion_states_raw, list):
        completion_states_raw = ["scheduled", "running"]
    completion_states = [str(state).strip().casefold() for state in completion_states_raw if str(state).strip()]
    if not completion_states:
        completion_states = ["scheduled", "running"]
    allowed_states = set(completion_states)

    stages_raw = provider_cfg.get("stages", DEFAULT_SCRAPER_CONFIG["providers"]["dyn_contentdesk"]["stages"])
    if not isinstance(stages_raw, list):
        stages_raw = [1, 2, 3, 4]
    stages: list[int] = []
    for raw in stages_raw:
        try:
            number = int(raw)
        except Exception:
            continue
        if 1 <= number <= 20 and number not in stages:
            stages.append(number)
    if not stages:
        stages = [1, 2, 3, 4]

    competitions = provider_cfg.get("competitions", DEFAULT_SCRAPER_CONFIG["providers"]["dyn_contentdesk"]["competitions"])
    if not isinstance(competitions, list):
        competitions = DEFAULT_SCRAPER_CONFIG["providers"]["dyn_contentdesk"]["competitions"]

    provider_status["base_url"] = base_url
    provider_status["days_ahead"] = days_ahead
    provider_status["completion_states"] = completion_states
    provider_status["competitions"] = [
        {"sport": c.get("sport"), "label": c.get("label"), "uuid": c.get("uuid")}
        for c in competitions if isinstance(c, dict)
    ]

    events: list[dict[str, Any]] = []

    for competition in competitions:
        if not isinstance(competition, dict):
            continue
        sport = str(competition.get("sport") or "").strip()
        uuid = str(competition.get("uuid") or "").strip()
        if not sport or not uuid:
            provider_status["errors"].append(f"competition skipped, missing sport/uuid: {competition!r}")
            continue

        for stage in stages:
            params: list[tuple[str, Any]] = []
            for state in completion_states:
                params.append(("completionStates", state))
            params.extend([
                ("competition", uuid),
                ("stage", stage),
                ("limit", limit),
            ])

            url = f"{base_url}/match/search/with-details?{urllib.parse.urlencode(params)}"
            endpoint_status = {
                "sport": sport,
                "competition": str(competition.get("label") or ""),
                "stage": stage,
                "url": url,
                "ok": False,
                "raw_items": 0,
                "parsed_items": 0,
                "error": "",
            }

            try:
                payload = http_json(url, timeout_seconds)
                endpoint_status["ok"] = True
            except urllib.error.HTTPError as exc:
                endpoint_status["error"] = f"HTTPError {exc.code}: {exc.reason}"
                provider_status["errors"].append(f"{sport}/{uuid}/stage {stage}: {endpoint_status['error']}")
                provider_status["endpoint_results"].append(endpoint_status)
                continue
            except Exception as exc:
                endpoint_status["error"] = f"{type(exc).__name__}: {exc}"
                provider_status["errors"].append(f"{sport}/{uuid}/stage {stage}: {endpoint_status['error']}")
                provider_status["endpoint_results"].append(endpoint_status)
                continue

            items = payload.get("items", []) if isinstance(payload, dict) else []
            if not isinstance(items, list):
                endpoint_status["error"] = "items missing or not list"
                provider_status["errors"].append(f"{sport}/{uuid}/stage {stage}: items missing or not list")
                provider_status["endpoint_results"].append(endpoint_status)
                continue

            endpoint_status["raw_items"] = len(items)
            provider_status["raw_items"] += len(items)

            for item in items:
                event = dyn_parse_match_item(item, competition, allowed_states, valid_channel_ids, provider_status)
                if event is None:
                    continue
                events.append(event)
                endpoint_status["parsed_items"] += 1
                provider_status["parsed_items"] += 1

            provider_status["endpoint_results"].append(endpoint_status)

    filtered_events, provider_status = filter_event_window(events, provider_status, days_ahead=days_ahead)
    filtered_events = distribute_overlapping_numeric_channels(filtered_events)
    provider_status["kept_events"] = len(filtered_events)
    provider_status["sample_kept_events"] = [
        {
            "channel": str(item.get("channel", "")),
            "start": item["start"].isoformat(),
            "stop": item["stop"].isoformat(),
            "title": str(item.get("title", "")),
            "sport": str(item.get("dyn_sport", "")),
            "competition": str(item.get("dyn_competition", "")),
            "state": str(item.get("dyn_state", "")),
        }
        for item in filtered_events[:25]
    ]
    return filtered_events, provider_status

def scrape_dazn_discovery_epg(config: dict[str, Any], valid_channel_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider_status: dict[str, Any] = {
        "source": "DAZN Discovery EPG",
        "base_url": "",
        "country": "de",
        "languageCode": "de",
        "days_ahead": 0,
        "allowed_types": [],
        "raw_events": 0,
        "parsed_events": 0,
        "kept_events": 0,
        "dropped_type_events": 0,
        "dropped_missing_fields": 0,
        "dropped_past_events": 0,
        "dropped_future_events": 0,
        "errors": [],
        "dates": {},
        "filter": "DAZN discovery API, keep Live/UpComing with stop > now - 2h",
        "sample_kept_events": [],
    }

    provider_cfg = config.get("providers", {}).get("dazn_discovery_epg", {})
    if not provider_cfg.get("enabled", True):
        provider_status["errors"].append("provider disabled")
        return [], provider_status

    base_url = str(provider_cfg.get("base_url", DEFAULT_SCRAPER_CONFIG["providers"]["dazn_discovery_epg"]["base_url"])).strip()
    country = str(provider_cfg.get("country", "de")).strip() or "de"
    language = str(provider_cfg.get("languageCode", "de")).strip() or "de"
    days_ahead = int(provider_cfg.get("days_ahead", 7))
    timeout_seconds = int(provider_cfg.get("timeout_seconds", 20))
    allowed_types = provider_cfg.get("allowed_types", ["Live", "UpComing"])
    if not isinstance(allowed_types, list):
        allowed_types = ["Live", "UpComing"]
    allowed_types_norm = {str(item).casefold() for item in allowed_types}

    provider_status["base_url"] = base_url
    provider_status["country"] = country
    provider_status["languageCode"] = language
    provider_status["days_ahead"] = days_ahead
    provider_status["allowed_types"] = list(allowed_types)

    today_local = datetime.now(BERLIN).date()
    parsed_items: list[dict[str, Any]] = []

    for offset in range(0, days_ahead + 1):
        date_text = (today_local + timedelta(days=offset)).isoformat()
        params = urllib.parse.urlencode({
            "$format": "json",
            "date": date_text,
            "country": country,
            "languageCode": language,
            "openBrowse": "true",
        })
        url = f"{base_url}?{params}"
        date_status = {"url": url, "raw_events": 0, "parsed_events": 0, "errors": []}
        provider_status["dates"][date_text] = date_status

        try:
            payload = http_json(url, timeout_seconds)
        except Exception as exc:
            msg = f"{date_text}: fetch failed: {type(exc).__name__}: {exc}"
            provider_status["errors"].append(msg)
            date_status["errors"].append(msg)
            continue

        tiles = payload.get("Tiles", []) if isinstance(payload, dict) else []
        if not isinstance(tiles, list):
            msg = f"{date_text}: Tiles missing or not a list"
            provider_status["errors"].append(msg)
            date_status["errors"].append(msg)
            continue

        date_status["raw_events"] = len(tiles)
        provider_status["raw_events"] += len(tiles)

        for tile in tiles:
            if not isinstance(tile, dict):
                continue
            typ = str(tile.get("Type") or tile.get("type") or "").strip()
            if allowed_types_norm and typ.casefold() not in allowed_types_norm:
                provider_status["dropped_type_events"] += 1
                continue
            event = parse_dazn_discovery_tile(tile, provider_status, valid_channel_ids)
            if event is None:
                continue
            parsed_items.append(event)
            date_status["parsed_events"] += 1

    provider_status["parsed_events"] = len(parsed_items)
    filtered_items, provider_status = filter_event_window(parsed_items, provider_status, days_ahead=days_ahead + 1)
    filtered_items = distribute_overlapping_numeric_channels(filtered_items)
    provider_status["kept_events"] = len(filtered_items)
    provider_status["sample_kept_events"] = [
        {
            "channel": str(item.get("channel", "")),
            "start": item["start"].isoformat(),
            "title": str(item.get("title", "")),
            "type": str(item.get("dazn_type", "")),
            "sport": str(item.get("dazn_sport", "")),
            "competition": str(item.get("dazn_competition", "")),
        }
        for item in filtered_items[:25]
    ]
    return filtered_items, provider_status


def build_demo_programmes(channels: list[tuple[str, str]]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0)
    stop = start + timedelta(hours=24)
    return [
        {
            "source": "demo",
            "channel": channel_id,
            "title": f"{name} - EPG Test",
            "desc": "Demo-Eintrag. Wenn du das im EPG siehst, funktioniert GitHub Pages + EPGImport.",
            "category": category_for_channel(channel_id),
            "start": start,
            "stop": stop,
        }
        for channel_id, name in channels
    ]


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
    lines.append('<tv generator-info-name="Secret_DE_EPG" generator-info-url="{}">'.format(esc(repo_pages_url())))

    for channel_id, name in channels:
        lines.append(f'  <channel id="{esc(channel_id)}">')
        lines.append(f'    <display-name lang="de">{esc(name)}</display-name>')
        lines.append('  </channel>')

    for event in events:
        lines.append(f'  <programme start="{xml_time(event["start"])}" stop="{xml_time(event["stop"])}" channel="{esc(event["channel"])}">')
        lines.append(f'    <title lang="de">{esc(event["title"])}</title>')
        if event.get("desc"):
            lines.append(f'    <desc lang="de">{esc(event["desc"])}</desc>')
        if event.get("category"):
            lines.append(f'    <category lang="de">{esc(event["category"])}</category>')
        lines.append('  </programme>')

    lines.append('</tv>')
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
        lines.append(f' source: {item["source"]}')
        lines.append(f' channel: {item["channel"]}')
        lines.append(f' title: {item["title"]}')
        lines.append(f' category: {item["category"]}')
        if item["desc"]:
            desc = item["desc"].replace("\n", " ").strip()
            if len(desc) > 240:
                desc = desc[:237] + "..."
            lines.append(f' desc: {desc}')
        lines.append("")

    (PUBLIC / "events-debug.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_epgimport_files(channels: list[tuple[str, str]]) -> None:
    base_url = repo_pages_url()
    source_xml = f'''<?xml version="1.0" encoding="utf-8"?>
<sources>
  <sourcecat sourcecatname="{esc(SOURCECAT_NAME)}">
    <source type="gen_xmltv" nocheck="1" channels="{ECHANNELIZER_CHANNELS_PATH}">
      <description>{esc(SOURCE_DESCRIPTION)}</description>
      <url><![CDATA[{base_url}/sports-events.xml.xz]]></url>
    </source>
  </sourcecat>
</sources>
'''
    (EPGIMPORT / "sports-events.sources.xml").write_text(source_xml, encoding="utf-8", newline="\n")

    # Compatibility only: the existing GitHub workflow checks that this file exists.
    # It is NOT used by the source above.
    channel_lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<channels>',
        '  <!-- Compatibility file only. Active mapping is E-Channelizer: {} -->'.format(esc(ECHANNELIZER_CHANNELS_PATH)),
    ]
    for channel_id, _name in channels:
        placeholder = "DEINE_SERVICE_REFERENCE_FUER_" + channel_id.upper().replace(".", "_").replace("-", "_")
        channel_lines.append(f'  <channel id="{esc(channel_id)}">{esc(placeholder)}</channel>')
    channel_lines.append('</channels>')
    (EPGIMPORT / "sports-events.channels.xml").write_text("\n".join(channel_lines) + "\n", encoding="utf-8", newline="\n")


def write_index(channels: list[tuple[str, str]], manual_count: int, scraped_count: int, fallback_used: bool) -> None:
    rows = []
    for prefix, label, start, end, suffix in CHANNEL_GROUPS:
        suffix_text = f" {suffix}" if suffix else ""
        rows.append(f'<li><code>{esc(prefix)}.01</code> bis <code>{esc(prefix)}.{end:02d}</code> — {esc(label)} 1-{end}{esc(suffix_text)}</li>')
    for channel_id, name in EXTRA_CHANNELS:
        rows.append(f'<li><code>{esc(channel_id)}</code> — {esc(name)}</li>')

    mode = "Demo-Fallback" if fallback_used else "Manuell/Scraper aktiv"
    html_doc = f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Secret DE EPG</title>
  <style>
    body {{ font-family: Arial, sans-serif; max-width: 1100px; margin: 30px auto; padding: 0 18px; line-height: 1.45; }}
    code {{ background: #f3f3f3; padding: 2px 5px; border-radius: 4px; }}
    .box {{ background: #f8f8f8; border: 1px solid #ddd; padding: 12px 15px; border-radius: 8px; }}
  </style>
</head>
<body>
  <h1>Secret DE EPG</h1>

  <div class="box">
    <p><strong>Modus:</strong> {esc(mode)}</p>
    <p><strong>Manuelle Events:</strong> {manual_count}</p>
    <p><strong>Scraper Events:</strong> {scraped_count}</p>
    <p><strong>XMLTV Feed:</strong> <a href="sports-events.xml.xz">sports-events.xml.xz</a></p>
    <p><strong>Unkomprimierte XML:</strong> <a href="sports-events.xml">sports-events.xml</a></p>
    <p><strong>Status:</strong> <a href="status.json">status.json</a></p>
    <p><strong>Events Debug JSON:</strong> <a href="events-debug.json">events-debug.json</a></p>
    <p><strong>Events Debug TXT:</strong> <a href="events-debug.txt">events-debug.txt</a></p>
    <p><strong>EPGImport Source:</strong> <a href="epgimport/sports-events.sources.xml">sports-events.sources.xml</a></p>
    <p><strong>EPGImport Channel-Mapping:</strong> lokal über <code>{esc(ECHANNELIZER_CHANNELS_PATH)}</code></p>
  </div>

  <h2>Wichtig für EPGImport</h2>
  <p>
    Die aktive Source nutzt absichtlich <strong>nicht</strong> <code>sports-events.channels.xml</code>,
    sondern die E-Channelizer-Datei <code>{esc(ECHANNELIZER_CHANNELS_PATH)}</code>.
    Die Datei <code>epgimport/sports-events.channels.xml</code> wird nur noch erzeugt,
    damit der bestehende GitHub-Workflow kompatibel bleibt.
  </p>

  <h2>Channel-ID-Gruppen</h2>
  <ul>{''.join(rows)}</ul>
  <p>Channels insgesamt: {len(channels)}</p>
</body>
</html>
'''
    (PUBLIC / "index.html").write_text(html_doc, encoding="utf-8", newline="\n")


def write_status(
    channels: list[tuple[str, str]],
    events: list[dict[str, Any]],
    manual_count: int,
    scraped_count: int,
    fallback_used: bool,
    manual_errors: list[str],
    config_errors: list[str],
    provider_statuses: dict[str, Any],
) -> None:
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
        "providers": provider_statuses,
        "events_by_source": events_by_source,
        "events_by_channel": events_by_channel,
        "epgimport_source_mapping": ECHANNELIZER_CHANNELS_PATH,
        "source_fix": "sports-events.sources.xml points to E-Channelizer mapping; sports-events.channels.xml is compatibility only",
    }
    (PUBLIC / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    channels = build_channels()
    valid_channel_ids = {channel_id for channel_id, _name in channels}

    config, config_errors = load_scraper_config()
    manual_events, manual_errors = load_manual_events(valid_channel_ids)

    scraped_events: list[dict[str, Any]] = []
    provider_statuses: dict[str, Any] = {}

    if config.get("scrapers_enabled", True):
        rtlplus_events, rtlplus_status = scrape_rtlplus(config, valid_channel_ids)
        provider_statuses["rtlplus"] = rtlplus_status
        scraped_events.extend(rtlplus_events)

        ufc_events, ufc_status = scrape_ufc_com(config, valid_channel_ids)
        provider_statuses["ufc_com"] = ufc_status
        scraped_events.extend(ufc_events)

        dyn_events, dyn_status = scrape_dyn_contentdesk(config, valid_channel_ids)
        provider_statuses["dyn_contentdesk"] = dyn_status
        scraped_events.extend(dyn_events)

        prime_events, prime_status = scrape_prime_video(config, valid_channel_ids)
        provider_statuses["prime_video"] = prime_status
        scraped_events.extend(prime_events)


        discoveryplus_eurosport_events, discoveryplus_eurosport_status = scrape_discoveryplus_eurosport(config, valid_channel_ids)
        provider_statuses["discoveryplus_eurosport"] = discoveryplus_eurosport_status
        scraped_events.extend(discoveryplus_eurosport_events)

        discovery_events, discovery_status = scrape_dazn_discovery_epg(config, valid_channel_ids)
        provider_statuses["dazn_discovery_epg"] = discovery_status
        scraped_events.extend(discovery_events)

        epgpw_events, epgpw_status = scrape_dazn_epgpw(config, valid_channel_ids)
        provider_statuses["dazn_epgpw"] = epgpw_status
        scraped_events.extend(epgpw_events)
    else:
        provider_statuses["scrapers"] = {"enabled": False, "errors": ["scrapers disabled"]}

    events = dedupe_events(manual_events + scraped_events)
    fallback_used = False
    if not events:
        fallback_used = True
        events = build_demo_programmes(channels)

    write_xmltv(channels, events)
    write_events_debug(events)
    write_epgimport_files(channels)
    write_index(channels, len(manual_events), len(scraped_events), fallback_used)
    write_status(channels, events, len(manual_events), len(scraped_events), fallback_used, manual_errors, config_errors, provider_statuses)

    print(f"Generated {len(events)} events for {len(channels)} channels")
    print(f"EPGImport source: {repo_pages_url()}/epgimport/sports-events.sources.xml")
    print(f"Mapping path: {ECHANNELIZER_CHANNELS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
