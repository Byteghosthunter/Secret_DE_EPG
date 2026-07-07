#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prime Sports Discovery Probe

Goal:
- Not Wimbledon-only.
- Start from Prime Video sports hub + Amazon sports hub.
- Discover sports/tournament/live/detail links from HTML and JSON.
- Fetch discovered pages.
- Extract containers, events, titles, liveInfo, venues, titleIDs, URLs.
- Search for slot/channel/stream/live-tv style hints.

Diagnostic only. Does not change the XMLTV feed.
Outputs are written to public/probes/.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from typing import Any


OUT_DIR = os.path.join("public", "probes")
os.makedirs(OUT_DIR, exist_ok=True)

SEED_URLS = [
    "https://www.primevideo.com/-/de/sports?ref_=atv_hm_sports_c_9zZ8D2_hom",
    "https://www.primevideo.com/-/en/sports?ref_=atv_hm_sports_c_9zZ8D2_hom",
    "https://www.amazon.de/-/de/gp/video/sports",
    "https://www.amazon.de/-/en/gp/video/sports",
]

# Known pages that helped during previous probes. These are not the only source.
KNOWN_EXTRA_URLS = [
    "https://www.primevideo.com/-/de/tournament/amzn1.dv.icid.70b8ac67-d420-4c70-a0b7-3e53868a4968?tr=at",
    "https://www.amazon.de/-/de/gp/video/tournament/amzn1.dv.icid.70b8ac67-d420-4c70-a0b7-3e53868a4968",
]

KEYWORDS = [
    "live tv",
    "livetv",
    "live-tv",
    "linear",
    "channel",
    "channels",
    "stream",
    "sport",
    "sports",
    "tournament",
    "turnier",
    "fußball",
    "fussball",
    "football",
    "wimbledon",
    "tennis",
    "atp",
    "wta",
    "f1",
    "formel",
    "ufc",
    "aew",
    "wrestling",
    "basketball",
    "nba",
    "cricket",
    "world cup",
    "wm",
    "prime",
    "event",
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
    "tournament",
    "league",
    "sport",
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
    "Gecko/20100101 Firefox/128.0"
)


def dump_json(name: str, data: Any) -> None:
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)


def fetch(url: str, timeout: int = 25) -> tuple[bool, str, str, str]:
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    req = urllib.request.Request(url, headers=headers)
    final_url = url
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            final_url = r.geturl()
            enc = r.headers.get_content_charset() or "utf-8"
            return True, raw.decode(enc, errors="replace"), "", final_url
    except Exception as exc:
        return False, "", "%s: %s" % (type(exc).__name__, exc), final_url


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


def normalize_url(url: str, base: str) -> str:
    url = html.unescape(url.strip())
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    url = urllib.parse.urljoin(base, url)
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme.startswith("http"):
        return ""
    # Keep useful query for Prime sometimes, but remove common UI ref noise where safe.
    qs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    keep_qs = []
    for k, v in qs:
        if k.lower() in ("ref_", "ref", "pf_rd_r", "pf_rd_p"):
            continue
        keep_qs.append((k, v))
    query = urllib.parse.urlencode(keep_qs)
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", query, ""))


def discover_links_from_html(page: str, base_url: str) -> list[dict[str, str]]:
    links = []
    patterns = [
        r'href=["\']([^"\']+)["\']',
        r'"url"\s*:\s*"([^"]+)"',
        r'"href"\s*:\s*"([^"]+)"',
    ]
    seen = set()
    for pat in patterns:
        for m in re.finditer(pat, page, re.I):
            raw = m.group(1).replace("\\u002F", "/").replace("\\/", "/")
            u = normalize_url(raw, base_url)
            if not u:
                continue
            low = u.lower()
            if not any(token in low for token in (
                "/sports", "/sport", "/tournament/", "/detail/", "/live", "/channels", "/channel", "/storefront"
            )):
                continue
            if "primevideo.com" not in low and "amazon.de" not in low:
                continue
            if u in seen:
                continue
            seen.add(u)
            links.append({"source_url": base_url, "url": u, "reason": "html"})
    return links


def extract_script_json_blocks(page: str) -> list[Any]:
    blocks = []

    for m in re.finditer(r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>', page, re.S | re.I):
        raw = html.unescape(m.group(1)).strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except Exception:
            pass

    markers = [
        '"containers"',
        '"entityType"',
        '"liveInfo"',
        '"displayTitle"',
        '"titleID"',
        '"tournament"',
        '"sport"',
        '"navigation"',
        '"links"',
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
            for i in range(start, min(len(page), start + 300000)):
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
                    blocks.append(json.loads(raw))
                except Exception:
                    pass
            pos = idx + len(marker)

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


def title_from_obj(e: dict[str, Any]) -> str:
    for key in ("displayTitle", "title", "name", "label", "text"):
        v = e.get(key)
        if isinstance(v, str) and v.strip():
            return clean_text(v)
        if isinstance(v, dict):
            for kk in ("text", "value", "title", "label"):
                if isinstance(v.get(kk), str) and v.get(kk).strip():
                    return clean_text(v.get(kk))
    return ""


def id_fields(obj: Any, base_path: str = "$") -> dict[str, Any]:
    out = {}
    for path, v in walk(obj, base_path):
        key = path.split(".")[-1].lower()
        if any(tok in key for tok in ("id", "asin", "gti")):
            if isinstance(v, (str, int, float)):
                s = clean_text(v)
                if s and len(out) < 100:
                    out[path] = s
    return out


def slot_hints(obj: Any, base_path: str = "$") -> list[dict[str, str]]:
    hints = []
    for path, v in walk(obj, base_path):
        key = path.split(".")[-1].lower()
        if any(tok in key for tok in SLOT_KEYS):
            if isinstance(v, (str, int, float, bool)):
                val = clean_text(v)
                if val and len(val) <= 700:
                    hints.append({"path": path, "key": key, "value": val})
        elif isinstance(v, str):
            s = clean_text(v)
            low = s.lower()
            if any(tok in low for tok in (
                "prime 1", "prime event", "event 1", "stream 1", "channel 1",
                "live tv", "livetv", "center court", "centre court", "court 1"
            )):
                hints.append({"path": path, "key": key, "value": s[:700]})
    seen = set()
    out = []
    for h in hints:
        key = (h["path"], h["value"])
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out[:250]


def event_url_from_obj(e: dict[str, Any], source_url: str) -> str:
    candidates = []
    for link_key in ("link", "links", "action", "clickAction"):
        link = e.get(link_key)
        if isinstance(link, dict):
            for key in ("url", "href", "target", "deepLink"):
                if isinstance(link.get(key), str):
                    candidates.append(link.get(key))
        elif isinstance(link, str):
            candidates.append(link)
    for key in ("url", "href", "detailUrl", "canonicalUrl", "deepLink"):
        if isinstance(e.get(key), str):
            candidates.append(e.get(key))
    title_id = clean_text(e.get("titleID") or e.get("impressionId") or "")
    if title_id:
        candidates.append("/gp/video/detail/%s" % title_id)
    for c in candidates:
        c = clean_text(c).replace("\\u002F", "/").replace("\\/", "/")
        u = normalize_url(c, source_url)
        if u:
            return u
    return ""


def discover_links_from_json(blocks: list[Any], base_url: str) -> list[dict[str, str]]:
    links = []
    seen = set()
    for bi, b in enumerate(blocks):
        for path, v in walk(b):
            if isinstance(v, str):
                raw = v.replace("\\u002F", "/").replace("\\/", "/")
                if "http" in raw or raw.startswith("/") or "/gp/video/" in raw:
                    u = normalize_url(raw, base_url)
                    if not u:
                        continue
                    low = u.lower()
                    if not any(token in low for token in (
                        "/sports", "/sport", "/tournament/", "/detail/", "/live", "/channels", "/channel", "/storefront"
                    )):
                        continue
                    if "primevideo.com" not in low and "amazon.de" not in low:
                        continue
                    if u in seen:
                        continue
                    seen.add(u)
                    links.append({"source_url": base_url, "url": u, "reason": "json:%s" % path[:200]})
    return links


def extract_containers(blocks: list[Any], source_url: str) -> list[dict[str, Any]]:
    containers = []
    for bi, b in enumerate(blocks):
        for path, obj in walk(b):
            if isinstance(obj, dict):
                entities = obj.get("entities")
                if isinstance(entities, list):
                    containers.append({
                        "source_url": source_url,
                        "block_index": bi,
                        "json_path": path,
                        "container_type": clean_text(obj.get("containerType") or obj.get("type") or obj.get("widgetType")),
                        "container_title": title_from_obj(obj),
                        "entities_count": len(entities),
                    })
    return containers


def extract_events(blocks: list[Any], source_url: str) -> list[dict[str, Any]]:
    events = []
    for bi, b in enumerate(blocks):
        for path, obj in walk(b):
            if not isinstance(obj, dict):
                continue
            etype = clean_text(obj.get("entityType") or obj.get("type") or obj.get("contentType")).upper()
            has_live = isinstance(obj.get("liveInfo"), dict)
            title = title_from_obj(obj)
            if not title:
                continue
            looks_event = etype == "EVENT" or has_live
            if not looks_event:
                continue
            li = obj.get("liveInfo") if isinstance(obj.get("liveInfo"), dict) else {}
            cues = obj.get("entitlementCues") if isinstance(obj.get("entitlementCues"), dict) else {}
            badge = cues.get("titleMetadataBadge") if isinstance(cues.get("titleMetadataBadge"), dict) else {}
            event = {
                "source_url": source_url,
                "block_index": bi,
                "json_path": path,
                "entity_type": etype,
                "title": title,
                "status": clean_text(li.get("status")),
                "time_badge": clean_text(li.get("timeBadge")),
                "venue": clean_text(li.get("venue")),
                "badge_message": clean_text(badge.get("message")),
                "event_url": event_url_from_obj(obj, source_url),
                "id_fields": id_fields(obj),
                "slot_hints": slot_hints(obj),
            }
            blob = json.dumps(event, ensure_ascii=False).lower()
            event["keyword_match"] = any(k in blob for k in KEYWORDS)
            events.append(event)
    return events


def page_keyword_hits(page: str) -> list[dict[str, Any]]:
    low = page.lower()
    out = []
    for k in KEYWORDS:
        c = low.count(k)
        if c:
            out.append({"keyword": k, "count": c})
    return out


# Phase 1: fetch seeds + known extras
pages = []
all_links = []
all_containers = []
all_events = []
all_slot_hints = []

initial_urls = SEED_URLS + KNOWN_EXTRA_URLS
for url in initial_urls:
    ok, page, err, final_url = fetch(url)
    rec = {
        "url": url,
        "final_url": final_url,
        "ok": ok,
        "error": err,
        "bytes": len(page.encode("utf-8", errors="replace")) if ok else 0,
        "json_blocks": 0,
        "html_keyword_hits": [],
    }
    if ok:
        rec["html_keyword_hits"] = page_keyword_hits(page)
        blocks = extract_script_json_blocks(page)
        rec["json_blocks"] = len(blocks)
        all_links.extend(discover_links_from_html(page, final_url))
        all_links.extend(discover_links_from_json(blocks, final_url))
        containers = extract_containers(blocks, final_url)
        events = extract_events(blocks, final_url)
        all_containers.extend(containers)
        all_events.extend(events)
        for bi, b in enumerate(blocks):
            for h in slot_hints(b):
                h2 = dict(h)
                h2["source_url"] = final_url
                h2["block_index"] = bi
                all_slot_hints.append(h2)
    pages.append(rec)

# Rank discovered links.
link_seen = set()
dedup_links = []
for l in all_links:
    u = l["url"]
    if u in link_seen:
        continue
    link_seen.add(u)
    dedup_links.append(l)

def link_score(u: str) -> int:
    low = u.lower()
    score = 0
    for token in ("/sports", "/tournament/", "/live", "/channels", "/channel", "/detail/"):
        if token in low:
            score += 10
    for token in ("primevideo.com", "amazon.de"):
        if token in low:
            score += 5
    for token in ("wimbledon", "atp", "sport", "live", "channel"):
        if token in low:
            score += 3
    return score

dedup_links.sort(key=lambda x: (-link_score(x["url"]), x["url"]))

# Phase 2: fetch top discovered non-detail pages plus a limited number of detail pages.
fetch_targets = []
seen_targets = set(initial_urls)
for l in dedup_links:
    u = l["url"]
    if u in seen_targets:
        continue
    low = u.lower()
    # Keep it bounded.
    if "/detail/" in low and len([x for x in fetch_targets if "/detail/" in x["url"].lower()]) >= 40:
        continue
    if "/detail/" not in low and len([x for x in fetch_targets if "/detail/" not in x["url"].lower()]) >= 60:
        continue
    seen_targets.add(u)
    fetch_targets.append(l)
    if len(fetch_targets) >= 100:
        break

fetched_discovered = []
for i, target in enumerate(fetch_targets):
    time.sleep(0.12)
    url = target["url"]
    ok, page, err, final_url = fetch(url)
    rec = {
        "url": url,
        "final_url": final_url,
        "source_url": target.get("source_url"),
        "reason": target.get("reason"),
        "ok": ok,
        "error": err,
        "bytes": len(page.encode("utf-8", errors="replace")) if ok else 0,
        "json_blocks": 0,
        "html_keyword_hits": [],
        "containers": 0,
        "events": 0,
    }
    if ok:
        rec["html_keyword_hits"] = page_keyword_hits(page)
        blocks = extract_script_json_blocks(page)
        rec["json_blocks"] = len(blocks)
        containers = extract_containers(blocks, final_url)
        events = extract_events(blocks, final_url)
        rec["containers"] = len(containers)
        rec["events"] = len(events)
        all_containers.extend(containers)
        all_events.extend(events)
        all_links.extend(discover_links_from_html(page, final_url))
        all_links.extend(discover_links_from_json(blocks, final_url))
        for bi, b in enumerate(blocks):
            for h in slot_hints(b):
                h2 = dict(h)
                h2["source_url"] = final_url
                h2["block_index"] = bi
                all_slot_hints.append(h2)
    fetched_discovered.append(rec)

# Deduplicate events.
unique_events = []
seen_event = set()
for e in all_events:
    title_id = ""
    for k, v in (e.get("id_fields") or {}).items():
        if "titleid" in k.lower():
            title_id = str(v)
            break
    if not title_id:
        m = re.search(r"/detail/([^/?#]+)", e.get("event_url", ""))
        title_id = m.group(1) if m else ""
    key = (title_id or e.get("title"), e.get("time_badge"), e.get("source_url"))
    if key in seen_event:
        continue
    seen_event.add(key)
    unique_events.append(e)

keyword_events = [e for e in unique_events if e.get("keyword_match")]
live_tv_like = []
for e in unique_events:
    blob = json.dumps(e, ensure_ascii=False).lower()
    if any(k in blob for k in ("live tv", "livetv", "linear", "channel", "stream", "prime 1", "event 1", "prime event")):
        live_tv_like.append(e)

# Deduplicate slot hints.
slot_seen = set()
dedup_slot_hints = []
for h in all_slot_hints:
    key = (h.get("source_url"), h.get("path"), h.get("value"))
    if key in slot_seen:
        continue
    slot_seen.add(key)
    dedup_slot_hints.append(h)

container_counter = Counter()
for c in all_containers:
    name = (c.get("container_title") or "")[:120]
    if name:
        container_counter[name] += 1

summary = {
    "ok": True,
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "seed_urls": SEED_URLS,
    "known_extra_urls": KNOWN_EXTRA_URLS,
    "pages_total": len(pages),
    "pages_ok": sum(1 for p in pages if p["ok"]),
    "discovered_links_total": len(dedup_links),
    "fetched_discovered_total": len(fetched_discovered),
    "fetched_discovered_ok": sum(1 for p in fetched_discovered if p["ok"]),
    "containers_total": len(all_containers),
    "events_total": len(all_events),
    "events_unique": len(unique_events),
    "keyword_events": len(keyword_events),
    "live_tv_like_events": len(live_tv_like),
    "slot_hints": len(dedup_slot_hints),
    "top_containers": container_counter.most_common(80),
    "top_event_titles": Counter(e.get("title","") for e in unique_events).most_common(80),
    "files": {
        "summary": "public/probes/prime_sports_discovery_summary.json",
        "seed_pages": "public/probes/prime_sports_discovery_seed_pages.json",
        "discovered_links": "public/probes/prime_sports_discovery_links.json",
        "fetched_discovered": "public/probes/prime_sports_discovery_fetched.json",
        "containers": "public/probes/prime_sports_discovery_containers.json",
        "events": "public/probes/prime_sports_discovery_events.json",
        "keyword_events": "public/probes/prime_sports_discovery_keyword_events.json",
        "live_tv_like_events": "public/probes/prime_sports_discovery_live_tv_like_events.json",
        "slot_hints": "public/probes/prime_sports_discovery_slot_hints.json",
    },
}

dump_json("prime_sports_discovery_summary.json", summary)
dump_json("prime_sports_discovery_seed_pages.json", pages)
dump_json("prime_sports_discovery_links.json", dedup_links[:2000])
dump_json("prime_sports_discovery_fetched.json", fetched_discovered)
dump_json("prime_sports_discovery_containers.json", all_containers[:5000])
dump_json("prime_sports_discovery_events.json", unique_events[:5000])
dump_json("prime_sports_discovery_keyword_events.json", keyword_events[:2000])
dump_json("prime_sports_discovery_live_tv_like_events.json", live_tv_like[:2000])
dump_json("prime_sports_discovery_slot_hints.json", dedup_slot_hints[:5000])

print(json.dumps(summary, ensure_ascii=False, indent=2))
