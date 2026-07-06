#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MagentaSport API probe for Byteghosthunter/Secret_DE_EPG.

Purpose:
  Test MagentaSport metadata access BEFORE patching build_sports_events.py.

What this script does:
  - Calls the MagentaSport mobile API style endpoint with daily token logic.
  - Starts at /navigation.
  - Collects candidate football / 3. Liga / MagentaSport targets.
  - Follows candidate targets up to a safe page limit.
  - Extracts event-like JSON objects.
  - Writes detailed debug JSON files.
  - Builds a preview list mapped to magenta.sport.01-18.

It does NOT modify build_sports_events.py.
It does NOT modify public XMLTV files.
It does NOT need external packages.

Suggested GitHub/local command:
  python3 probe_magenta_sport.py --max-pages 40 --out-dir public/probes

Output:
  public/probes/magenta_probe_summary.json
  public/probes/magenta_probe_events_preview.json
  public/probes/magenta_probe_pages.json
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import argparse
import hashlib
import json
import re
import ssl
import sys
import time


API_SALT = "55!#r%Rn3%xn?U?PX*k"

DEFAULT_BASE_URL = "https://www.magentasport.de"
DEFAULT_API_PATH = "/api/v3/mobile"
DEFAULT_START_PATH = "/navigation"

KEYWORDS = [
    "3. liga",
    "3 liga",
    "dritte liga",
    "fußball",
    "fussball",
    "frauen-bundesliga",
    "frauen bundesliga",
    "magenta sport",
    "magentasport",
]

EVENT_TYPE_HINTS = {
    "event",
    "conferenceEvent",
    "skyConferenceEvent",
    "video",
    "livestream",
    "liveevent",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def lower_blob(*values: Any) -> str:
    return " ".join(safe_text(v).casefold() for v in values if v is not None)


def as_path(value: Any) -> str:
    text = safe_text(value)
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        # Convert full Magenta URL to API path if possible.
        # Example:
        #   https://www.magentasport.de/foo -> /foo
        m = re.match(r"^https?://[^/]+(/.*)$", text)
        text = m.group(1) if m else text
    if not text.startswith("/"):
        text = "/" + text
    # strip token/noisy query, keep actual query only if it is not token-only
    if "?token=" in text:
        text = text.split("?token=", 1)[0]
    return text


def token_day_timestamp() -> int:
    """
    Same logic as the old TelekomSport/MagentaSport Enigma2 plugin:
      now - 5 hours -> start of that day -> epoch seconds
    """
    d = datetime.now() - timedelta(hours=5)
    d = d.replace(hour=0, minute=0, second=0, microsecond=0)
    epoch = datetime(1970, 1, 1)
    return int((d - epoch).total_seconds())


def generate_token(api_path: str, url_end: str) -> str:
    token_path = api_path.rstrip("/") + as_path(url_end)
    raw = f"{API_SALT}{token_day_timestamp()}{token_path}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_api_url(base_url: str, api_path: str, url_end: str) -> str:
    base = base_url.rstrip("/")
    api = api_path.rstrip("/")
    path = as_path(url_end)
    token = generate_token(api, path)
    sep = "&" if "?" in path else "?"
    return f"{base}{api}{path}{sep}{urlencode({'token': token})}"


def fetch_json(url: str, timeout: int = 20, insecure: bool = False) -> tuple[Any | None, dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 Secret_DE_EPG MagentaSportProbe/1.0",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
        "Cache-Control": "no-cache",
    }

    req = Request(url, headers=headers, method="GET")
    ctx = None
    if insecure:
        ctx = ssl._create_unverified_context()

    info: dict[str, Any] = {
        "url": url,
        "ok": False,
        "status": None,
        "content_type": "",
        "bytes": 0,
        "error": "",
        "sample": "",
    }

    try:
        with urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read()
            info["status"] = getattr(resp, "status", None)
            info["content_type"] = resp.headers.get("Content-Type", "")
            info["bytes"] = len(body)
            text = body.decode("utf-8", "replace")
            info["sample"] = text[:500]
            data = json.loads(text)
            info["ok"] = True
            return data, info
    except HTTPError as exc:
        body = exc.read()
        text = body.decode("utf-8", "replace") if body else ""
        info["status"] = exc.code
        info["content_type"] = exc.headers.get("Content-Type", "") if exc.headers else ""
        info["bytes"] = len(body or b"")
        info["error"] = f"HTTPError: {exc.code} {exc.reason}"
        info["sample"] = text[:500]
        return None, info
    except URLError as exc:
        info["error"] = f"URLError: {exc.reason}"
        return None, info
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        return None, info


def walk_json(obj: Any, path: str = "$"):
    yield path, obj
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from walk_json(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            yield from walk_json(value, f"{path}[{idx}]")


def collect_text(obj: Any, max_chars: int = 6000) -> str:
    parts: list[str] = []
    for _, value in walk_json(obj):
        if isinstance(value, (str, int, float)):
            text = safe_text(value)
            if text:
                parts.append(text)
        if sum(len(p) for p in parts) > max_chars:
            break
    return " ".join(parts)


def find_candidate_paths(data: Any, keywords: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    key_names = {
        "target", "path", "href", "url", "link", "deeplink", "deepLink",
        "actionUrl", "actionURL", "pageUrl", "pageURL"
    }

    for json_path, obj in walk_json(data):
        if not isinstance(obj, dict):
            continue

        blob = lower_blob(
            obj.get("title"),
            obj.get("name"),
            obj.get("headline"),
            obj.get("label"),
            obj.get("teaser"),
            obj.get("description"),
            obj.get("sport"),
            obj.get("competition"),
            obj.get("league"),
        )

        if not any(k in blob for k in keywords):
            # Also allow objects where the path itself contains football-ish hints.
            path_blob = lower_blob(*[obj.get(k) for k in key_names])
            if not any(k in path_blob for k in keywords):
                continue

        for key in key_names:
            p = as_path(obj.get(key))
            if not p:
                continue
            if p.startswith("/api/"):
                continue
            if p not in seen:
                seen.add(p)
                candidates.append({
                    "path": p,
                    "json_path": json_path,
                    "title": safe_text(obj.get("title") or obj.get("name") or obj.get("headline") or obj.get("label")),
                    "reason_blob": blob[:300],
                })

    return candidates


def looks_event_like(obj: dict[str, Any]) -> bool:
    typ = safe_text(obj.get("type") or obj.get("target_type") or obj.get("targetType")).casefold()
    if typ in {t.casefold() for t in EVENT_TYPE_HINTS}:
        return True

    metadata = obj.get("metadata")
    if isinstance(metadata, dict):
        if "details" in metadata or "startTime" in metadata or "start_time" in metadata or "startDate" in metadata:
            return True

    # direct fields
    keys = set(obj.keys())
    if {"title", "startTime"} & keys or {"name", "startTime"} & keys:
        return True

    blob = lower_blob(obj.get("title"), obj.get("name"), obj.get("teaser"))
    if (" vs " in blob or " - " in blob or "3. liga" in blob) and any(k.lower() in "".join(keys).lower() for k in ["start", "date", "time"]):
        return True

    return False


def event_objects_from_page(data: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for json_path, obj in walk_json(data):
        if isinstance(obj, dict) and looks_event_like(obj):
            obj_id = id(obj)
            if obj_id not in seen:
                seen.add(obj_id)
                copy = dict(obj)
                copy["_json_path"] = json_path
                out.append(copy)
    return out


def parse_datetime(value: Any) -> datetime | None:
    text = safe_text(value)
    if not text:
        return None

    # epoch milliseconds / seconds
    if re.fullmatch(r"\d{13}", text):
        try:
            return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc)
        except Exception:
            return None
    if re.fullmatch(r"\d{10}", text):
        try:
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        except Exception:
            return None

    # ISO-ish
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        pass

    # German date fallback: 07.07.2026 19:00
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4}).*?(\d{1,2}):(\d{2})", text)
    if m:
        d, mo, y, h, mi = map(int, m.groups())
        return datetime(y, mo, d, h, mi, tzinfo=timezone(timedelta(hours=2)))

    return None


def first_datetime_in_obj(obj: dict[str, Any]) -> datetime | None:
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    details = metadata.get("details") if isinstance(metadata.get("details"), dict) else {}

    keys = [
        "startTime", "start_time", "startDate", "start_date", "start",
        "date", "airtime", "airTime", "liveStart", "begin", "beginTime",
    ]

    for holder in (metadata, details, obj):
        for key in keys:
            dt = parse_datetime(holder.get(key))
            if dt:
                return dt

    # Search shallow text values as fallback.
    for _, value in walk_json(obj):
        if isinstance(value, (str, int)):
            dt = parse_datetime(value)
            if dt:
                return dt

    return None


def pick_title(obj: dict[str, Any]) -> str:
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    details = metadata.get("details") if isinstance(metadata.get("details"), dict) else {}

    # team title if present
    home = ""
    away = ""
    for side, target in (("home", "home"), ("away", "away"), ("teamHome", "home"), ("teamAway", "away")):
        team = details.get(side)
        if isinstance(team, dict):
            name = safe_text(team.get("name") or team.get("shortName") or team.get("title"))
            if target == "home":
                home = home or name
            else:
                away = away or name

    if home and away:
        return f"{home} - {away}"

    for holder in (metadata, details, obj):
        for key in ("title", "name", "headline", "eventTitle", "label"):
            text = safe_text(holder.get(key))
            if text:
                return text

    blob = collect_text(obj, max_chars=300)
    return blob[:100] if blob else "MagentaSport Event"


def object_matches_keywords(obj: dict[str, Any], keywords: list[str]) -> bool:
    blob = lower_blob(collect_text(obj, max_chars=5000))
    return any(k in blob for k in keywords)


def map_preview_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []

    for obj in events:
        dt = first_datetime_in_obj(obj)
        title = pick_title(obj)
        if not dt:
            continue
        parsed.append({
            "start": dt.astimezone(timezone.utc).isoformat(),
            "title": title,
            "json_path": obj.get("_json_path", ""),
            "target": safe_text(obj.get("target") or obj.get("path") or obj.get("url")),
            "raw_type": safe_text(obj.get("type") or obj.get("target_type") or obj.get("targetType")),
        })

    parsed.sort(key=lambda x: (x["start"], x["title"]))

    # assign channel slots per identical start time
    result: list[dict[str, Any]] = []
    slots_by_start: dict[str, int] = {}
    for item in parsed:
        start_key = item["start"][:16]
        slot = slots_by_start.get(start_key, 0) + 1
        slots_by_start[start_key] = slot
        if slot > 18:
            slot = 18
        item["channel_id"] = f"magenta.sport.{slot:02d}"
        result.append(item)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe MagentaSport API before integrating into build_sports_events.py")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-path", default=DEFAULT_API_PATH)
    parser.add_argument("--start-path", default=DEFAULT_START_PATH)
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--out-dir", default="public/probes")
    parser.add_argument("--keyword", action="append", default=[], help="Extra keyword to match candidate targets/events")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    keywords = [k.casefold() for k in KEYWORDS + args.keyword]

    summary: dict[str, Any] = {
        "ok": False,
        "generated_at_utc": now_utc().isoformat(),
        "base_url": args.base_url,
        "api_path": args.api_path,
        "start_path": args.start_path,
        "max_pages": args.max_pages,
        "keywords": keywords,
        "token_day_timestamp": token_day_timestamp(),
        "pages_fetched": 0,
        "pages_ok": 0,
        "candidate_paths_found": 0,
        "event_objects_found": 0,
        "keyword_event_objects": 0,
        "preview_events": 0,
        "errors": [],
    }

    pages_debug: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []

    queue: list[str] = [as_path(args.start_path)]
    seen_paths: set[str] = set()

    while queue and len(seen_paths) < args.max_pages:
        path = as_path(queue.pop(0))
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)

        url = build_api_url(args.base_url, args.api_path, path)
        data, info = fetch_json(url, timeout=args.timeout, insecure=args.insecure)
        summary["pages_fetched"] += 1
        if info.get("ok"):
            summary["pages_ok"] += 1
        else:
            summary["errors"].append({
                "path": path,
                "status": info.get("status"),
                "error": info.get("error"),
                "sample": info.get("sample", "")[:200],
            })

        page_record = {
            "path": path,
            "url": url,
            "fetch": info,
            "candidate_paths": [],
            "event_count": 0,
            "keyword_event_count": 0,
        }

        if data is not None:
            candidates = find_candidate_paths(data, keywords)
            page_record["candidate_paths"] = candidates[:50]

            for c in candidates:
                p = as_path(c.get("path"))
                if p and p not in seen_paths and p not in queue and len(seen_paths) + len(queue) < args.max_pages:
                    queue.append(p)

            events = event_objects_from_page(data)
            keyword_events = [e for e in events if object_matches_keywords(e, keywords)]

            page_record["event_count"] = len(events)
            page_record["keyword_event_count"] = len(keyword_events)

            # Keep all keyword events, but if none matched, keep a few raw event objects for debugging.
            for event in keyword_events:
                all_events.append(event)

            if not keyword_events and events:
                for event in events[:5]:
                    event["_debug_non_keyword"] = True
                    all_events.append(event)

        pages_debug.append(page_record)
        time.sleep(max(0.0, args.sleep))

    # Build counts and preview.
    candidate_paths_total = sum(len(p.get("candidate_paths", [])) for p in pages_debug)
    keyword_events = [e for e in all_events if not e.get("_debug_non_keyword")]
    preview = map_preview_events(keyword_events)

    summary.update({
        "ok": summary["pages_ok"] > 0,
        "candidate_paths_found": candidate_paths_total,
        "event_objects_found": len(all_events),
        "keyword_event_objects": len(keyword_events),
        "preview_events": len(preview),
        "visited_paths": sorted(seen_paths),
        "next_queue_left": queue[:30],
        "files": {
            "summary": str(out_dir / "magenta_probe_summary.json"),
            "events_preview": str(out_dir / "magenta_probe_events_preview.json"),
            "pages": str(out_dir / "magenta_probe_pages.json"),
        },
    })

    (out_dir / "magenta_probe_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "magenta_probe_events_preview.json").write_text(
        json.dumps(preview, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "magenta_probe_pages.json").write_text(
        json.dumps(pages_debug, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("=== MagentaSport Probe Summary ===")
    print(f"ok: {summary['ok']}")
    print(f"pages_fetched: {summary['pages_fetched']}")
    print(f"pages_ok: {summary['pages_ok']}")
    print(f"candidate_paths_found: {summary['candidate_paths_found']}")
    print(f"event_objects_found: {summary['event_objects_found']}")
    print(f"keyword_event_objects: {summary['keyword_event_objects']}")
    print(f"preview_events: {summary['preview_events']}")
    print("")
    print("Files:")
    print(summary["files"]["summary"])
    print(summary["files"]["events_preview"])
    print(summary["files"]["pages"])

    if summary["errors"]:
        print("")
        print("First errors:")
        for err in summary["errors"][:5]:
            print(f"- {err.get('path')}: {err.get('status')} {err.get('error')}")

    # Probe should not fail the Action just because API changed.
    # It exits 0 if it could run and write debug files.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
