#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prime Live-TV / PrimeHD Probe

Goal:
- Build our OWN PrimeHD direction, not using EPGShare as feed.
- Probe Prime Video Live-TV pages where linear stations + schedules are exposed.
- Search specifically for Prime/Prime HD/Sport/Tennis/Football/Wimbledon station candidates.
- Extract station + schedule structures if present.

Diagnostic only. It does not change the XMLTV feed.
Outputs go to public/probes/.
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

URLS = [
    "https://www.primevideo.com/-/de/livetv",
    "https://www.primevideo.com/-/en/livetv",
    "https://www.primevideo.com/-/de/sports?ref_=atv_hm_sports_c_9zZ8D2_hom",
    "https://www.primevideo.com/-/en/sports?ref_=atv_hm_sports_c_9zZ8D2_hom",
    "https://www.amazon.de/-/de/gp/video/livetv",
    "https://www.amazon.de/-/en/gp/video/livetv",
    "https://www.amazon.de/-/de/gp/video/sports",
    "https://www.amazon.de/-/en/gp/video/sports",
]

KEYWORDS = [
    "prime",
    "prime hd",
    "amazon prime",
    "prime video",
    "sport",
    "sports",
    "live tv",
    "livetv",
    "linear",
    "channel",
    "station",
    "schedule",
    "tennis",
    "wimbledon",
    "australian open",
    "us open",
    "roland garros",
    "french open",
    "atp",
    "wta",
    "fußball",
    "fussball",
    "football",
    "world cup",
    "wm",
    "soccer",
]

PRIMEHD_HINTS = [
    "prime",
    "prime hd",
    "amazon prime",
    "prime video",
]

SPORT_ALLOW_HINTS = [
    "sport",
    "sports",
    "tennis",
    "wimbledon",
    "australian open",
    "us open",
    "roland garros",
    "french open",
    "atp",
    "wta",
    "fußball",
    "fussball",
    "football",
    "world cup",
    "wm",
    "soccer",
]

BLOCK_HINT_KEYS = [
    "station",
    "stations",
    "schedule",
    "schedules",
    "airing",
    "airings",
    "channel",
    "channels",
    "linear",
    "epg",
    "live",
    "broadcast",
    "playback",
    "titleid",
    "gti",
    "asin",
    "id",
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
    "Gecko/20100101 Firefox/128.0"
)


def dump_json(name: str, data: Any) -> None:
    with open(os.path.join(OUT_DIR, name), "w", encoding="utf-8") as f:
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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            final_url = r.geturl()
            enc = r.headers.get_content_charset() or "utf-8"
            return True, raw.decode(enc, errors="replace"), "", final_url
    except Exception as exc:
        return False, "", "%s: %s" % (type(exc).__name__, exc), url


def clean(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, (dict, list)):
        try:
            x = json.dumps(x, ensure_ascii=False)
        except Exception:
            x = str(x)
    s = html.unescape(str(x))
    s = s.replace("\\u002F", "/").replace("\\/", "/")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_url(url: str, base: str) -> str:
    url = clean(url)
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    url = urllib.parse.urljoin(base, url)
    p = urllib.parse.urlparse(url)
    if not p.scheme.startswith("http"):
        return ""
    return urllib.parse.urlunparse((p.scheme, p.netloc, p.path, "", p.query, ""))


def extract_json_blocks(page: str) -> list[Any]:
    blocks = []
    for m in re.finditer(r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>', page, re.S | re.I):
        raw = html.unescape(m.group(1)).strip()
        if raw:
            try:
                blocks.append(json.loads(raw))
            except Exception:
                pass

    markers = [
        '"containers"',
        '"entities"',
        '"station"',
        '"schedule"',
        '"liveInfo"',
        '"displayTitle"',
        '"titleID"',
        '"playback"',
        '"epg"',
        '"channel"',
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
            for i in range(start, min(len(page), start + 350000)):
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
            k = json.dumps(b, sort_keys=True, ensure_ascii=False)[:8000]
        except Exception:
            k = str(type(b)) + str(id(b))
        if k not in seen:
            seen.add(k)
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


def title_from_obj(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    for key in ("displayTitle", "title", "name", "label", "text", "stationName", "channelName"):
        v = obj.get(key)
        if isinstance(v, str) and clean(v):
            return clean(v)
        if isinstance(v, dict):
            for kk in ("text", "value", "title", "label", "name"):
                if isinstance(v.get(kk), str) and clean(v.get(kk)):
                    return clean(v.get(kk))
    return ""


def id_fields(obj: Any) -> dict[str, str]:
    out = {}
    for path, v in walk(obj):
        key = path.split(".")[-1].lower()
        if any(tok in key for tok in ("id", "asin", "gti", "station", "channel")):
            if isinstance(v, (str, int, float)):
                s = clean(v)
                if s and len(out) < 120:
                    out[path] = s
    return out


def hint_fields(obj: Any) -> list[dict[str, str]]:
    out = []
    for path, v in walk(obj):
        key = path.split(".")[-1].lower()
        if any(tok in key for tok in BLOCK_HINT_KEYS):
            if isinstance(v, (str, int, float, bool)):
                val = clean(v)
                if val and len(val) <= 800:
                    out.append({"path": path, "key": key, "value": val})
        elif isinstance(v, str):
            val = clean(v)
            low = val.lower()
            if any(k in low for k in KEYWORDS):
                out.append({"path": path, "key": key, "value": val[:800]})
    seen = set()
    dedup = []
    for h in out:
        k = (h["path"], h["value"])
        if k not in seen:
            seen.add(k)
            dedup.append(h)
    return dedup[:300]


def link_from_obj(obj: dict[str, Any], base_url: str) -> str:
    candidates = []
    for lk in ("link", "links", "action", "clickAction", "playbackAction"):
        v = obj.get(lk)
        if isinstance(v, dict):
            for kk in ("url", "href", "target", "deepLink"):
                if isinstance(v.get(kk), str):
                    candidates.append(v.get(kk))
        elif isinstance(v, str):
            candidates.append(v)
    for kk in ("url", "href", "canonicalUrl", "detailUrl", "deepLink"):
        if isinstance(obj.get(kk), str):
            candidates.append(obj.get(kk))
    tid = clean(obj.get("titleID") or obj.get("impressionId") or "")
    if tid:
        candidates.append("/gp/video/detail/%s" % tid)
    for c in candidates:
        u = normalize_url(c, base_url)
        if u:
            return u
    return ""


def classify_blob(obj: Any) -> str:
    blob = json.dumps(obj, ensure_ascii=False).lower()
    if any(k in blob for k in PRIMEHD_HINTS) and any(k in blob for k in SPORT_ALLOW_HINTS):
        return "prime_sport_candidate"
    if any(k in blob for k in PRIMEHD_HINTS):
        return "prime_candidate"
    if any(k in blob for k in SPORT_ALLOW_HINTS):
        return "sport_candidate"
    return ""


def extract_station_schedule_candidates(blocks: list[Any], source_url: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stations = []
    schedule_events = []

    for bi, block in enumerate(blocks):
        for path, obj in walk(block):
            if not isinstance(obj, dict):
                continue

            keys_lower = {str(k).lower() for k in obj.keys()}
            has_station = any("station" in k or "channel" in k or "linear" in k for k in keys_lower)
            has_schedule = any("schedule" in k or "airing" in k or "liveinfo" in k for k in keys_lower)
            title = title_from_obj(obj)

            if has_station or (title and any(k in title.lower() for k in PRIMEHD_HINTS + SPORT_ALLOW_HINTS)):
                blob_class = classify_blob(obj)
                if blob_class or has_schedule or has_station:
                    stations.append({
                        "source_url": source_url,
                        "block_index": bi,
                        "json_path": path,
                        "class": blob_class,
                        "title": title,
                        "keys": sorted(list(keys_lower))[:80],
                        "ids": id_fields(obj),
                        "link": link_from_obj(obj, source_url),
                        "hints": hint_fields(obj),
                    })

            # Extract schedule-like event cards
            etype = clean(obj.get("entityType") or obj.get("type") or obj.get("contentType")).upper()
            live_info = obj.get("liveInfo") if isinstance(obj.get("liveInfo"), dict) else {}
            if title and (etype == "EVENT" or live_info or has_schedule):
                blob_class = classify_blob(obj)
                blob = json.dumps(obj, ensure_ascii=False).lower()
                if blob_class or any(k in blob for k in KEYWORDS):
                    schedule_events.append({
                        "source_url": source_url,
                        "block_index": bi,
                        "json_path": path,
                        "class": blob_class,
                        "entity_type": etype,
                        "title": title,
                        "status": clean(live_info.get("status")),
                        "time_badge": clean(live_info.get("timeBadge")),
                        "venue": clean(live_info.get("venue")),
                        "ids": id_fields(obj),
                        "link": link_from_obj(obj, source_url),
                        "hints": hint_fields(obj),
                    })

    return stations, schedule_events


def discover_links(page: str, source_url: str) -> list[dict[str, str]]:
    links = []
    seen = set()
    patterns = [
        r'href=["\']([^"\']+)["\']',
        r'"url"\s*:\s*"([^"]+)"',
        r'"href"\s*:\s*"([^"]+)"',
    ]
    for pat in patterns:
        for m in re.finditer(pat, page, re.I):
            u = normalize_url(m.group(1), source_url)
            if not u:
                continue
            low = u.lower()
            if "primevideo.com" not in low and "amazon.de" not in low:
                continue
            if not any(t in low for t in ("/livetv", "/sports", "/sport", "/detail/", "/tournament/", "/channel", "/channels")):
                continue
            if u in seen:
                continue
            seen.add(u)
            links.append({"source_url": source_url, "url": u})
    return links


pages = []
links = []
all_stations = []
all_schedule_events = []
all_hints = []

# First fetch seed URLs
for url in URLS:
    ok, page, err, final = fetch(url)
    rec = {
        "url": url,
        "final_url": final,
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
        blocks = extract_json_blocks(page)
        rec["json_blocks"] = len(blocks)
        st, ev = extract_station_schedule_candidates(blocks, final)
        all_stations.extend(st)
        all_schedule_events.extend(ev)
        links.extend(discover_links(page, final))
        for bi, b in enumerate(blocks):
            for h in hint_fields(b):
                hh = dict(h)
                hh["source_url"] = final
                hh["block_index"] = bi
                all_hints.append(hh)
    pages.append(rec)

# Fetch a bounded set of discovered links.
seen_url = set(URLS)
dedup_links = []
for l in links:
    u = l["url"]
    if u not in seen_url:
        seen_url.add(u)
        dedup_links.append(l)

def link_score(u: str) -> int:
    low = u.lower()
    score = 0
    for tok in ("/livetv", "/sports", "/tournament/", "/detail/", "/channel", "/channels"):
        if tok in low:
            score += 10
    for tok in ("prime", "sport", "live", "tennis", "football"):
        if tok in low:
            score += 3
    return score

dedup_links.sort(key=lambda l: (-link_score(l["url"]), l["url"]))
fetch_links = []
detail_count = 0
other_count = 0
for l in dedup_links:
    low = l["url"].lower()
    if "/detail/" in low:
        if detail_count >= 30:
            continue
        detail_count += 1
    else:
        if other_count >= 70:
            continue
        other_count += 1
    fetch_links.append(l)
    if len(fetch_links) >= 100:
        break

fetched_links = []
for l in fetch_links:
    time.sleep(0.10)
    ok, page, err, final = fetch(l["url"])
    rec = {
        "url": l["url"],
        "source_url": l.get("source_url"),
        "final_url": final,
        "ok": ok,
        "error": err,
        "bytes": len(page.encode("utf-8", errors="replace")) if ok else 0,
        "json_blocks": 0,
        "stations": 0,
        "schedule_events": 0,
        "html_keyword_hits": [],
    }
    if ok:
        low = page.lower()
        for k in KEYWORDS:
            c = low.count(k)
            if c:
                rec["html_keyword_hits"].append({"keyword": k, "count": c})
        blocks = extract_json_blocks(page)
        rec["json_blocks"] = len(blocks)
        st, ev = extract_station_schedule_candidates(blocks, final)
        rec["stations"] = len(st)
        rec["schedule_events"] = len(ev)
        all_stations.extend(st)
        all_schedule_events.extend(ev)
        for bi, b in enumerate(blocks):
            for h in hint_fields(b):
                hh = dict(h)
                hh["source_url"] = final
                hh["block_index"] = bi
                all_hints.append(hh)
    fetched_links.append(rec)

# Deduplicate station/event/hint records.
def dedup_records(records: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for r in records:
        k = tuple(clean(r.get(x)) for x in keys)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out

stations = dedup_records(all_stations, ["source_url", "json_path", "title"])
events = dedup_records(all_schedule_events, ["source_url", "json_path", "title", "time_badge"])
hints = dedup_records(all_hints, ["source_url", "path", "value"])

prime_candidates = []
for r in stations + events:
    blob = json.dumps(r, ensure_ascii=False).lower()
    if any(k in blob for k in PRIMEHD_HINTS):
        prime_candidates.append(r)

prime_sport_candidates = []
for r in prime_candidates:
    blob = json.dumps(r, ensure_ascii=False).lower()
    if any(k in blob for k in SPORT_ALLOW_HINTS):
        prime_sport_candidates.append(r)

summary = {
    "ok": True,
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "urls": URLS,
    "pages_total": len(pages),
    "pages_ok": sum(1 for p in pages if p["ok"]),
    "discovered_links": len(dedup_links),
    "fetched_links": len(fetched_links),
    "fetched_links_ok": sum(1 for p in fetched_links if p["ok"]),
    "stations": len(stations),
    "schedule_events": len(events),
    "prime_candidates": len(prime_candidates),
    "prime_sport_candidates": len(prime_sport_candidates),
    "hints": len(hints),
    "top_station_titles": Counter(clean(s.get("title")) for s in stations if clean(s.get("title"))).most_common(100),
    "top_event_titles": Counter(clean(e.get("title")) for e in events if clean(e.get("title"))).most_common(100),
    "files": {
        "summary": "public/probes/prime_livetv_primehd_summary.json",
        "pages": "public/probes/prime_livetv_primehd_pages.json",
        "links": "public/probes/prime_livetv_primehd_links.json",
        "fetched_links": "public/probes/prime_livetv_primehd_fetched_links.json",
        "stations": "public/probes/prime_livetv_primehd_stations.json",
        "schedule_events": "public/probes/prime_livetv_primehd_schedule_events.json",
        "prime_candidates": "public/probes/prime_livetv_primehd_prime_candidates.json",
        "prime_sport_candidates": "public/probes/prime_livetv_primehd_prime_sport_candidates.json",
        "hints": "public/probes/prime_livetv_primehd_hints.json",
    },
}

dump_json("prime_livetv_primehd_summary.json", summary)
dump_json("prime_livetv_primehd_pages.json", pages)
dump_json("prime_livetv_primehd_links.json", dedup_links[:2000])
dump_json("prime_livetv_primehd_fetched_links.json", fetched_links)
dump_json("prime_livetv_primehd_stations.json", stations[:5000])
dump_json("prime_livetv_primehd_schedule_events.json", events[:5000])
dump_json("prime_livetv_primehd_prime_candidates.json", prime_candidates[:2000])
dump_json("prime_livetv_primehd_prime_sport_candidates.json", prime_sport_candidates[:2000])
dump_json("prime_livetv_primehd_hints.json", hints[:5000])

print(json.dumps(summary, ensure_ascii=False, indent=2))
