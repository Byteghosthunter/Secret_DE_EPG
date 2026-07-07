#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prime/Wimbledon probe for Secret_DE_EPG.

Goal:
- Fetch Amazon/Prime Video sports + tournament pages.
- Extract embedded JSON blocks and EVENT entities.
- Show whether Wimbledon/Djokovic/Auger-Aliassime/current court/slot info exists.
- Do NOT generate XMLTV. This is only diagnostics before patching build_sports_events.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

DEFAULT_URLS = [
    "https://www.amazon.de/-/de/gp/video/sports",
    "https://www.amazon.de/-/en/gp/video/sports",
    # Known/likely tournament URL variants. Probe keeps failures in summary.
    "https://www.amazon.de/-/de/gp/video/tournament/amzn1.dv.icid.b5ef0949-90f0-4cd8-a515-973f91398ec0",
    "https://www.amazon.de/-/en/gp/video/tournament/amzn1.dv.icid.b5ef0949-90f0-4cd8-a515-973f91398ec0",
    "https://www.primevideo.com/-/de/tournament/amzn1.dv.icid.b5ef0949-90f0-4cd8-a515-973f91398ec0",
    "https://www.primevideo.com/-/de/tournament/amzn1.dv.icid.27f877e0-f507-4734-9d3c-6b62de04d485",
]

DEFAULT_KEYWORDS = [
    "wimbledon",
    "djokovic",
    "auger",
    "aliassime",
    "felix",
    "félix",
    "lincer",
    "maria",
    "centre court",
    "center court",
    "court",
    "tennis",
    "atp",
    "wta",
    "challenger",
]

SCRIPT_RE = re.compile(r"(?is)<script\b[^>]*>(.*?)</script>")
TAG_RE = re.compile(r"(?is)<[^>]+>")

KEY_HINT_RE = re.compile(
    r"(?i)(slot|channel|linear|stream|feed|court|venue|rank|position|event|title|asin|gti|catalog|id)"
)


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = unescape(text)
    text = TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_text(url: str, timeout: int) -> tuple[str, dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 Secret_DE_EPG PrimeWimbledonProbe/1.0",
        "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
    }
    request = urllib.request.Request(url, headers=headers, method="GET")
    info: dict[str, Any] = {
        "url": url,
        "ok": False,
        "status": None,
        "final_url": "",
        "content_type": "",
        "bytes": 0,
        "error": "",
        "sample": "",
    }
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            info["status"] = getattr(response, "status", None)
            info["final_url"] = getattr(response, "url", url)
            info["content_type"] = response.headers.get("Content-Type", "")
            info["bytes"] = len(body)
            text = body.decode("utf-8", "replace")
            info["sample"] = text[:500]
            info["ok"] = True
            return text, info
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
            sample = body.decode("utf-8", "replace")[:500]
        except Exception:
            sample = ""
        info.update({
            "status": exc.code,
            "final_url": getattr(exc, "url", url),
            "error": f"HTTPError: {exc.code} {exc.reason}",
            "sample": sample,
        })
        return "", info
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        return "", info


def balanced_json_prefix(candidate: str) -> str | None:
    candidate = candidate.strip()
    if not candidate or candidate[0] not in "[{":
        return None
    open_ch = candidate[0]
    close_ch = "}" if open_ch == "{" else "]"
    stack = []
    in_string = False
    escaped = False
    for index, ch in enumerate(candidate):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            stack.append(ch)
        elif ch in "]}":
            if not stack:
                return None
            prev = stack.pop()
            if (prev == "{" and ch != "}") or (prev == "[" and ch != "]"):
                return None
            if not stack:
                return candidate[: index + 1]
    return None


def parse_json_blocks(html: str) -> list[Any]:
    blocks: list[Any] = []
    seen: set[str] = set()
    starts = [
        '{"init"',
        '{"props"',
        '{"pageContext"',
        '{"resource"',
        '{"widgets"',
        '{"apolloState"',
        '{"state"',
        '{"data"',
        '[{"',
    ]
    for script in SCRIPT_RE.findall(html):
        raw = clean(script)
        if not raw:
            continue
        candidates: list[str] = []
        if raw.startswith("{") or raw.startswith("["):
            candidates.append(raw[:-1] if raw.endswith("};") else raw)
        for token in starts:
            start = 0
            while True:
                idx = raw.find(token, start)
                if idx < 0:
                    break
                candidates.append(raw[idx:])
                start = idx + 1
        for candidate in candidates:
            prefix = balanced_json_prefix(candidate)
            if not prefix:
                continue
            digest = prefix[:1000] + str(len(prefix))
            if digest in seen:
                continue
            seen.add(digest)
            try:
                data = json.loads(prefix)
            except Exception:
                continue
            blocks.append(data)
    return blocks


def iter_json(obj: Any, path: str = "$"):
    yield path, obj
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from iter_json(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            yield from iter_json(value, f"{path}[{idx}]")


def iter_dicts(obj: Any):
    for _path, value in iter_json(obj):
        if isinstance(value, dict):
            yield value


def find_request_context(data: Any) -> dict[str, Any] | None:
    for item in iter_dicts(data):
        if "RequestContext" in item and isinstance(item["RequestContext"], dict):
            return item["RequestContext"]
        if any(key in item for key in ("recordTerritory", "currentTerritory", "marketplaceID", "originalURI")):
            return item
    return None


def object_title(value: Any) -> str:
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, dict):
        for key in ("text", "title", "displayTitle", "label", "value"):
            if clean(value.get(key)):
                return clean(value.get(key))
        for nested in value.values():
            if isinstance(nested, str) and clean(nested):
                return clean(nested)
    return ""


def container_title(item: dict[str, Any]) -> str:
    for key in ("title", "displayTitle", "label", "heading", "collectionTitle"):
        title = object_title(item.get(key))
        if title:
            return title
    return ""


def walk_containers(data: Any) -> list[tuple[str, str, list[Any], str]]:
    containers: list[tuple[str, str, list[Any], str]] = []
    for path, item in iter_json(data):
        if not isinstance(item, dict):
            continue
        entities = item.get("entities")
        if not isinstance(entities, list):
            continue
        containers.append((clean(item.get("containerType")), container_title(item), entities, path))
    return containers


def get_entity_title(entity: dict[str, Any]) -> str:
    for key in ("displayTitle", "eventTitle", "name", "headline"):
        title = clean(entity.get(key))
        if title:
            return title
    title = object_title(entity.get("title"))
    if title:
        return title
    return ""


def get_entity_url(entity: dict[str, Any], source_url: str) -> str:
    link = entity.get("link") if isinstance(entity.get("link"), dict) else {}
    for holder in (link, entity):
        if not isinstance(holder, dict):
            continue
        for key in ("url", "href", "target", "canonicalUrl", "detailUrl"):
            raw = clean(holder.get(key))
            if raw:
                return urllib.parse.urljoin(source_url, raw)
    return ""


def get_id_fields(entity: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path, value in iter_json(entity):
        if not isinstance(value, (str, int, float)):
            continue
        key = path.split(".")[-1]
        if re.search(r"(?i)^(id|asin|gti|catalogId|contentId|titleId|eventId|entityId|streamId)$", key):
            result[path] = clean(value)
    return dict(list(result.items())[:40])


def collect_hints(entity: dict[str, Any], limit: int = 80) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    for path, value in iter_json(entity):
        key = path.split(".")[-1]
        if not KEY_HINT_RE.search(key):
            continue
        if isinstance(value, (dict, list)):
            continue
        val = clean(value)
        if not val:
            continue
        hints.append({"path": path, "key": key, "value": val[:300]})
        if len(hints) >= limit:
            break
    return hints


def normalize_event(entity: dict[str, Any], source_url: str, container_type: str, cont_title: str, container_path: str, block_index: int, entity_path: str) -> dict[str, Any]:
    live_info = entity.get("liveInfo") if isinstance(entity.get("liveInfo"), dict) else {}
    entitlement = entity.get("entitlementCues") if isinstance(entity.get("entitlementCues"), dict) else {}
    badge = entitlement.get("titleMetadataBadge") if isinstance(entitlement.get("titleMetadataBadge"), dict) else {}
    venue = clean(live_info.get("venue"))
    title = get_entity_title(entity)
    event_url = get_entity_url(entity, source_url)
    hints = collect_hints(entity)
    blob = " ".join([
        title,
        cont_title,
        clean(live_info.get("status")),
        clean(live_info.get("timeBadge")),
        venue,
        clean(badge.get("message")),
        event_url,
        " ".join(h["value"] for h in hints[:20]),
    ]).casefold()
    return {
        "source_url": source_url,
        "block_index": block_index,
        "json_path": entity_path,
        "container_path": container_path,
        "container_type": container_type,
        "container_title": cont_title,
        "entity_type": clean(entity.get("entityType")),
        "title": title,
        "status": clean(live_info.get("status")),
        "time_badge": clean(live_info.get("timeBadge")),
        "venue": venue,
        "badge_message": clean(badge.get("message")),
        "event_url": event_url,
        "id_fields": get_id_fields(entity),
        "slot_hints": hints,
        "blob": blob,
    }


def extract_events_from_block(data: Any, source_url: str, block_index: int) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    container_count = 0
    for container_type, cont_title, entities, container_path in walk_containers(data):
        container_count += 1
        for idx, entity in enumerate(entities):
            if not isinstance(entity, dict):
                continue
            obj_id = id(entity)
            if obj_id in seen_ids:
                continue
            seen_ids.add(obj_id)
            if clean(entity.get("entityType")).upper() != "EVENT":
                continue
            event = normalize_event(
                entity,
                source_url,
                container_type,
                cont_title,
                container_path,
                block_index,
                f"{container_path}.entities[{idx}]",
            )
            events.append(event)

    # Fallback: not every Prime page uses container.entities. Scan all EVENT dicts.
    for path, item in iter_json(data):
        if not isinstance(item, dict):
            continue
        if id(item) in seen_ids:
            continue
        if clean(item.get("entityType")).upper() != "EVENT":
            continue
        seen_ids.add(id(item))
        events.append(normalize_event(item, source_url, "", "", "", block_index, path))
    return events, container_count


def keyword_match(event: dict[str, Any], keywords: list[str]) -> bool:
    blob = str(event.get("blob", "")).casefold()
    return any(k.casefold() in blob for k in keywords if k)


def strip_blob(event: dict[str, Any]) -> dict[str, Any]:
    e = dict(event)
    e.pop("blob", None)
    return e


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Prime Video Wimbledon/tournament data")
    parser.add_argument("--url", action="append", default=[], help="URL to probe. Can be used multiple times.")
    parser.add_argument("--extra-url", action="append", default=[], help="Extra URL to add to defaults. Can be used multiple times.")
    parser.add_argument("--keywords", default=",".join(DEFAULT_KEYWORDS), help="Comma-separated keywords for hit filtering.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--out-dir", default="public/probes")
    parser.add_argument("--max-events", type=int, default=500)
    parser.add_argument("--max-raw-samples", type=int, default=40)
    args = parser.parse_args()

    urls = args.url if args.url else list(DEFAULT_URLS)
    urls.extend(args.extra_url or [])
    # dedupe URLs preserving order
    seen_urls: set[str] = set()
    urls = [u.strip() for u in urls if u and u.strip() and not (u.strip() in seen_urls or seen_urls.add(u.strip()))]
    keywords = [k.strip().casefold() for k in args.keywords.split(",") if k.strip()]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pages: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []
    keyword_hits: list[dict[str, Any]] = []
    html_keyword_hits: list[dict[str, Any]] = []
    raw_samples: list[dict[str, Any]] = []

    for url in urls:
        started = time.time()
        html, info = fetch_text(url, args.timeout)
        page_status = dict(info)
        page_status.update({
            "json_blocks": 0,
            "containers": 0,
            "event_objects": 0,
            "keyword_events": 0,
            "html_keyword_counts": {},
            "elapsed_seconds": round(time.time() - started, 3),
        })
        if html:
            html_lower = html.casefold()
            for kw in keywords:
                count = html_lower.count(kw)
                if count:
                    page_status["html_keyword_counts"][kw] = count
                    html_keyword_hits.append({"url": url, "keyword": kw, "count": count})

            blocks = parse_json_blocks(html)
            page_status["json_blocks"] = len(blocks)
            for block_index, data in enumerate(blocks):
                ctx = find_request_context(data) or {}
                if ctx:
                    page_status.setdefault("request_contexts", [])
                    page_status["request_contexts"].append({
                        "block_index": block_index,
                        "recordTerritory": clean(ctx.get("recordTerritory")),
                        "currentTerritory": clean(ctx.get("currentTerritory")),
                        "marketplaceID": clean(ctx.get("marketplaceID")),
                        "originalURI": clean(ctx.get("originalURI")),
                    })
                events, container_count = extract_events_from_block(data, url, block_index)
                page_status["containers"] += container_count
                page_status["event_objects"] += len(events)
                for event in events:
                    if len(all_events) < args.max_events:
                        all_events.append(strip_blob(event))
                    if keyword_match(event, keywords):
                        page_status["keyword_events"] += 1
                        keyword_hits.append(strip_blob(event))
                    if len(raw_samples) < args.max_raw_samples:
                        raw_samples.append(strip_blob(event))
        pages.append(page_status)

    # Build slot/court/channel hint overview.
    slot_hint_values: dict[str, list[dict[str, Any]]] = {}
    for event in keyword_hits or all_events:
        for hint in event.get("slot_hints", []):
            key = hint.get("key", "")
            if re.search(r"(?i)(slot|channel|linear|stream|feed|court|venue|position|rank)", key):
                slot_hint_values.setdefault(key, [])
                if len(slot_hint_values[key]) < 50:
                    slot_hint_values[key].append({
                        "title": event.get("title", ""),
                        "time_badge": event.get("time_badge", ""),
                        "value": hint.get("value", ""),
                        "path": hint.get("path", ""),
                        "source_url": event.get("source_url", ""),
                    })

    summary = {
        "ok": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "urls": urls,
        "keywords": keywords,
        "pages_total": len(pages),
        "pages_ok": sum(1 for p in pages if p.get("ok")),
        "json_blocks_total": sum(int(p.get("json_blocks", 0)) for p in pages),
        "containers_total": sum(int(p.get("containers", 0)) for p in pages),
        "event_objects_total": sum(int(p.get("event_objects", 0)) for p in pages),
        "keyword_events_total": len(keyword_hits),
        "html_keyword_hits": html_keyword_hits,
        "files": {
            "summary": str(out_dir / "prime_wimbledon_probe_summary.json"),
            "pages": str(out_dir / "prime_wimbledon_probe_pages.json"),
            "events": str(out_dir / "prime_wimbledon_probe_events.json"),
            "keyword_hits": str(out_dir / "prime_wimbledon_probe_keyword_hits.json"),
            "slot_hints": str(out_dir / "prime_wimbledon_probe_slot_hints.json"),
            "raw_samples": str(out_dir / "prime_wimbledon_probe_raw_samples.json"),
        },
    }

    (out_dir / "prime_wimbledon_probe_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "prime_wimbledon_probe_pages.json").write_text(json.dumps(pages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "prime_wimbledon_probe_events.json").write_text(json.dumps(all_events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "prime_wimbledon_probe_keyword_hits.json").write_text(json.dumps(keyword_hits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "prime_wimbledon_probe_slot_hints.json").write_text(json.dumps(slot_hint_values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "prime_wimbledon_probe_raw_samples.json").write_text(json.dumps(raw_samples, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nKeyword hit preview:")
    for item in keyword_hits[:25]:
        print(f"- {item.get('title')} | {item.get('time_badge')} | {item.get('container_title')} | {item.get('source_url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
