#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prime/Wimbledon Detail Probe

Purpose:
- Fetch Amazon/Prime Video sports + tournament pages.
- Extract EVENT title cards.
- De-duplicate by titleID/detail id.
- Fetch detail pages for candidate events.
- Search both overview JSON and detail-page JSON/HTML for:
  Djokovic, Auger, Aliassime, Felix, Wimbledon, court, centre/center court,
  slot/channel/stream style hints.

This is diagnostic only. It does not change the XMLTV feed.
Outputs are written to public/probes/.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any


OUT_DIR = os.path.join("public", "probes")
os.makedirs(OUT_DIR, exist_ok=True)

URLS = [
    "https://www.amazon.de/-/de/gp/video/sports",
    "https://www.amazon.de/-/en/gp/video/sports",
    "https://www.amazon.de/-/de/gp/video/tournament/amzn1.dv.icid.b5ef0949-90f0-4cd8-a515-973f91398ec0",
    "https://www.amazon.de/-/en/gp/video/tournament/amzn1.dv.icid.b5ef0949-90f0-4cd8-a515-973f91398ec0",
    "https://www.primevideo.com/-/de/tournament/amzn1.dv.icid.b5ef0949-90f0-4cd8-a515-973f91398ec0",
    "https://www.primevideo.com/-/de/tournament/amzn1.dv.icid.27f877e0-f507-4734-9d3c-6b62de04d485",
]

KEYWORDS = [
    "wimbledon",
    "djokovic",
    "auger",
    "aliassime",
    "felix",
    "centre court",
    "center court",
    "court",
    "tennis",
    "atp",
    "wta",
    "challenger",
    "lincer",
    "maria",
]

SLOT_KEYS = [
    "slot",
    "channel",
    "channels",
    "channelid",
    "stream",
    "streamid",
    "linear",
    "station",
    "network",
    "broadcast",
    "playback",
    "live",
    "venue",
    "court",
    "titleid",
    "impressionid",
    "catalogid",
    "gti",
    "asin",
    "watchid",
    "videoid",
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
    "Gecko/20100101 Firefox/128.0"
)


def dump_json(name: str, data: Any) -> None:
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)


def fetch(url: str, timeout: int = 25) -> tuple[bool, str, str]:
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            enc = r.headers.get_content_charset() or "utf-8"
            return True, raw.decode(enc, errors="replace"), ""
    except Exception as exc:
        return False, "", "%s: %s" % (type(exc).__name__, exc)


def clean_text(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, (dict, list)):
        try:
            x = json.dumps(x, ensure_ascii=False)
        except Exception:
            x = str(x)
    s = html.unescape(str(x))
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_script_json_blocks(page: str) -> list[Any]:
    blocks = []

    # JSON script tags
    for m in re.finditer(r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>', page, re.S | re.I):
        raw = html.unescape(m.group(1)).strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except Exception:
            pass

    # Prime/Amazon embeds often include JSON inside state blobs.
    # Try broad balanced object extraction around useful markers.
    markers = [
        '"containers"',
        '"entityType"',
        '"liveInfo"',
        '"displayTitle"',
        '"titleID"',
        '"detail"',
        '"tournament"',
    ]
    for marker in markers:
        pos = 0
        while True:
            idx = page.find(marker, pos)
            if idx < 0:
                break
            start = page.rfind("{", 0, idx)
            if start < 0:
                pos = idx + len(marker)
                continue

            depth = 0
            in_str = False
            esc = False
            end = None
            for i in range(start, min(len(page), start + 250000)):
                ch = page[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break

            if end:
                raw = page[start:end]
                try:
                    obj = json.loads(raw)
                    blocks.append(obj)
                except Exception:
                    pass
            pos = idx + len(marker)

    # De-dupe by serialized prefix/hash-ish
    out = []
    seen = set()
    for b in blocks:
        try:
            key = json.dumps(b, sort_keys=True, ensure_ascii=False)[:5000]
        except Exception:
            key = str(type(b)) + str(id(b))
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out


def walk(obj: Any, path: str = "$"):
    yield path, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, path + "." + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, path + "[%d]" % i)


def title_from_entity(e: dict[str, Any]) -> str:
    for key in ("displayTitle", "title", "name", "text"):
        v = e.get(key)
        if isinstance(v, str) and v.strip():
            return clean_text(v)
        if isinstance(v, dict):
            for kk in ("text", "value", "title"):
                if isinstance(v.get(kk), str) and v.get(kk).strip():
                    return clean_text(v.get(kk))
    return ""


def event_url_from_entity(e: dict[str, Any], source_url: str) -> str:
    candidates = []

    link = e.get("link")
    if isinstance(link, dict):
        for key in ("url", "href", "target"):
            if isinstance(link.get(key), str):
                candidates.append(link.get(key))

    for key in ("url", "href", "detailUrl", "canonicalUrl"):
        if isinstance(e.get(key), str):
            candidates.append(e.get(key))

    title_id = clean_text(e.get("titleID") or e.get("impressionId") or "")
    if title_id:
        candidates.append("/gp/video/detail/%s" % title_id)

    for c in candidates:
        c = clean_text(c)
        if not c:
            continue
        return urllib.parse.urljoin(source_url, c)
    return ""


def live_info(e: dict[str, Any]) -> dict[str, Any]:
    li = e.get("liveInfo")
    return li if isinstance(li, dict) else {}


def id_fields(obj: Any, base_path: str = "$") -> dict[str, Any]:
    out = {}
    for path, v in walk(obj, base_path):
        key = path.split(".")[-1].lower()
        if any(tok in key for tok in ("id", "asin", "gti")):
            if isinstance(v, (str, int, float)):
                s = clean_text(v)
                if s and len(out) < 80:
                    out[path] = s
    return out


def slot_hints(obj: Any, base_path: str = "$") -> list[dict[str, str]]:
    hints = []
    for path, v in walk(obj, base_path):
        key = path.split(".")[-1].lower()
        if any(tok in key for tok in SLOT_KEYS):
            if isinstance(v, (str, int, float, bool)):
                val = clean_text(v)
                if val and len(val) <= 500:
                    hints.append({"path": path, "key": key, "value": val})
        elif isinstance(v, str):
            s = clean_text(v)
            low = s.lower()
            if any(tok in low for tok in ("prime 1", "prime event", "center court", "centre court", "court 1", "court no", "stream 1", "channel 1")):
                hints.append({"path": path, "key": key, "value": s[:500]})
    # de-dupe
    seen = set()
    out = []
    for h in hints:
        key = (h["path"], h["value"])
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out[:200]


def keyword_match_blob(*parts: Any) -> bool:
    blob = " ".join(clean_text(p).lower() for p in parts)
    return any(k in blob for k in KEYWORDS)


def extract_events_from_block(block: Any, source_url: str, block_index: int) -> list[dict[str, Any]]:
    events = []
    for path, obj in walk(block):
        if not isinstance(obj, dict):
            continue

        etype = clean_text(obj.get("entityType") or obj.get("type") or obj.get("contentType")).upper()
        has_live = isinstance(obj.get("liveInfo"), dict)
        title = title_from_entity(obj)

        looks_event = etype == "EVENT" or has_live or bool(re.search(r"/gp/video/detail/", json.dumps(obj, ensure_ascii=False)[:3000]))
        if not looks_event or not title:
            continue

        li = live_info(obj)
        ev = {
            "source_url": source_url,
            "block_index": block_index,
            "json_path": path,
            "entity_type": etype,
            "title": title,
            "status": clean_text(li.get("status")),
            "time_badge": clean_text(li.get("timeBadge")),
            "venue": clean_text(li.get("venue")),
            "badge_message": clean_text(((obj.get("entitlementCues") or {}).get("titleMetadataBadge") or {}).get("message") if isinstance(obj.get("entitlementCues"), dict) else ""),
            "event_url": event_url_from_entity(obj, source_url),
            "id_fields": id_fields(obj),
            "slot_hints": slot_hints(obj),
            "keyword_match": keyword_match_blob(title, li, obj),
        }
        events.append(ev)
    return events


pages = []
overview_events = []

for url in URLS:
    ok, page, err = fetch(url)
    rec = {
        "url": url,
        "ok": ok,
        "error": err,
        "bytes": len(page.encode("utf-8", errors="replace")) if ok else 0,
        "json_blocks": 0,
        "html_keyword_hits": [],
    }
    if ok:
        low = page.lower()
        for k in KEYWORDS:
            c = low.count(k)
            if c:
                rec["html_keyword_hits"].append({"keyword": k, "count": c})
        blocks = extract_script_json_blocks(page)
        rec["json_blocks"] = len(blocks)
        for i, b in enumerate(blocks):
            overview_events.extend(extract_events_from_block(b, url, i))
    pages.append(rec)

# De-duplicate overview events by titleID/detail ID/title/time/source type.
unique = []
seen = set()
for e in overview_events:
    ids = e.get("id_fields") or {}
    title_id = ""
    for k, v in ids.items():
        if k.lower().endswith("titleid") or "titleid" in k.lower():
            title_id = str(v)
            break
    if not title_id:
        m = re.search(r"/detail/([^/?#]+)", e.get("event_url", ""))
        title_id = m.group(1) if m else ""
    key = (title_id or e["title"], e.get("time_badge", ""), e.get("source_url", ""))
    if key in seen:
        continue
    seen.add(key)
    unique.append(e)

candidate_events = []
for e in unique:
    if e.get("keyword_match") or any(k in (e.get("title","").lower()) for k in ("live", "court", "vs.", " v ")):
        candidate_events.append(e)

# Limit detail fetches to avoid hammering Amazon; candidates first, then all unique
detail_targets = []
seen_url = set()
for e in candidate_events + unique:
    u = e.get("event_url", "")
    if u and u not in seen_url:
        seen_url.add(u)
        detail_targets.append({"url": u, "overview_title": e.get("title"), "overview_time_badge": e.get("time_badge"), "overview_source": e.get("source_url")})
    if len(detail_targets) >= 80:
        break

detail_results = []
detail_keyword_hits = []
detail_slot_hints = []
for i, target in enumerate(detail_targets):
    time.sleep(0.15)
    ok, page, err = fetch(target["url"], timeout=25)
    rec = dict(target)
    rec.update({
        "ok": ok,
        "error": err,
        "bytes": len(page.encode("utf-8", errors="replace")) if ok else 0,
        "json_blocks": 0,
        "html_keyword_hits": [],
        "events_found": 0,
        "events": [],
        "slot_hints": [],
    })

    if ok:
        low = page.lower()
        for k in KEYWORDS:
            c = low.count(k)
            if c:
                rec["html_keyword_hits"].append({"keyword": k, "count": c})
        blocks = extract_script_json_blocks(page)
        rec["json_blocks"] = len(blocks)
        detail_events = []
        for bi, b in enumerate(blocks):
            evs = extract_events_from_block(b, target["url"], bi)
            detail_events.extend(evs)
            for h in slot_hints(b):
                detail_slot_hints.append({
                    "detail_url": target["url"],
                    "overview_title": target["overview_title"],
                    "path": h["path"],
                    "key": h["key"],
                    "value": h["value"],
                })
        rec["events_found"] = len(detail_events)
        rec["events"] = detail_events[:20]
        rec["slot_hints"] = rec["slot_hints"][:50]

        if rec["html_keyword_hits"] or any(e.get("keyword_match") for e in detail_events):
            detail_keyword_hits.append(rec)

    detail_results.append(rec)

summary = {
    "ok": True,
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "overview_urls": URLS,
    "pages_total": len(pages),
    "pages_ok": sum(1 for p in pages if p["ok"]),
    "overview_events_total": len(overview_events),
    "overview_events_unique": len(unique),
    "overview_keyword_events": sum(1 for e in unique if e.get("keyword_match")),
    "detail_targets": len(detail_targets),
    "detail_pages_ok": sum(1 for d in detail_results if d["ok"]),
    "detail_keyword_pages": len(detail_keyword_hits),
    "keyword_counter_overview_titles": Counter(e["title"] for e in unique if e.get("keyword_match")).most_common(80),
    "html_keyword_hits": [h for p in pages for h in [{"url": p["url"], **x} for x in p["html_keyword_hits"]]],
    "files": {
        "summary": "public/probes/prime_wimbledon_detail_summary.json",
        "overview_pages": "public/probes/prime_wimbledon_detail_overview_pages.json",
        "overview_events": "public/probes/prime_wimbledon_detail_overview_events.json",
        "candidate_events": "public/probes/prime_wimbledon_detail_candidate_events.json",
        "detail_results": "public/probes/prime_wimbledon_detail_results.json",
        "detail_keyword_hits": "public/probes/prime_wimbledon_detail_keyword_hits.json",
        "detail_slot_hints": "public/probes/prime_wimbledon_detail_slot_hints.json",
    },
}

dump_json("prime_wimbledon_detail_summary.json", summary)
dump_json("prime_wimbledon_detail_overview_pages.json", pages)
dump_json("prime_wimbledon_detail_overview_events.json", unique)
dump_json("prime_wimbledon_detail_candidate_events.json", candidate_events)
dump_json("prime_wimbledon_detail_results.json", detail_results)
dump_json("prime_wimbledon_detail_keyword_hits.json", detail_keyword_hits)
dump_json("prime_wimbledon_detail_slot_hints.json", detail_slot_hints[:3000])

print(json.dumps(summary, ensure_ascii=False, indent=2))
