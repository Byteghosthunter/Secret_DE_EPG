#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
Prime Video structured sports-event probe for Secret_DE_EPG.

Safe standalone probe:
- Does NOT modify public/sports-events.xml.xz.
- Does NOT deploy GitHub Pages.
- Creates prime-structured-results/*.txt and *.json as GitHub Actions artifact.

Why:
The first Prime probe found:
- public sports pages are reachable
- big embedded JSON store state exists
- visible event lines contain "LIVE", "DEMNÄCHST VERFÜGBAR", date/time and titles
- PrimeVideo.com from GitHub may report recordTerritory/currentTerritory = US

This probe does the next step:
- parse embedded JSON blocks, especially {"init": ...}
- extract RequestContext territory/marketplace signals
- extract containers and entities with displayTitle/titleId/detail links
- collect all date/time/live/upcoming strings from each entity
- create a concise event-candidate list for integration decisions
'''

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
import json
import re
import urllib.error
import urllib.request


OUT_DIR = Path("prime-structured-results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED_URLS = [
    "https://www.primevideo.com/-/de/sports",
    "https://www.primevideo.com/sports",
    "https://www.amazon.de/-/de/gp/video/sports",
    "https://www.amazon.de/-/en/gp/video/sports",
]

SPORT_TERMS = [
    "Champions League", "UEFA", "UFC", "NBA", "NFL", "Bundesliga", "DFB",
    "Premier League", "Wimbledon", "Tennis", "F1", "Formula 1", "MotoGP",
    "World Cup", "FIFA", "WNBA", "MLB", "Indy", "Cricket",
    "live", "LIVE", "KOMMENDE", "Bevorstehende", "Upcoming", "Sports", "Sport",
    "event", "events", "schedule", "match", "vs.", " vs ", " gegen ",
]

EVENT_HINT_RE = re.compile(
    r"(?i)(LIVE|DEM[NÄ]CHST VERF[ÜU]GBAR|KOMMENDE|BEVORSTEHENDE|Upcoming|Live um|"
    r"Today|Tomorrow|Heute|Morgen|vs\.| vs | gegen |Champions League|UEFA|UFC|NBA|NFL|FIFA|World Cup|Bundesliga|DFB)"
)
DATE_DE_RE = re.compile(
    r"\b(?:Mo|Di|Mi|Do|Fr|Sa|So|Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)?\.?,?\s*"
    r"(?:[0-3]?\d\.\s*[01]?\d\.(?:20[2-9][0-9]|\d{2})|[0-3]?\d\.\s*(?:Jan|Feb|Mär|Mrz|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez)[a-zä]*\.?(?:\s*20[2-9][0-9])?)",
    re.I,
)
DATE_EN_RE = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?\.?,?\s*"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+[0-3]?\d(?:,\s*20[2-9][0-9])?"
    r"|\b(?:Today|Tomorrow|Heute|Morgen)\b",
    re.I,
)
TIME_RE = re.compile(r"\b(?:[01]?\d|2[0-3])[:.][0-5]\d\s*(?:Uhr|AM|PM|EDT|EST|CET|CEST|GMT|UTC)?\b", re.I)
ISO_RE = re.compile(r"20[2-9][0-9]-[01]\d-[0-3]\d(?:T[0-2]\d:[0-5]\d(?::[0-5]\d)?(?:\.\d+)?Z?)?")
SCRIPT_RE = re.compile(r"(?is)<script\b[^>]*>(.*?)</script>")
LINK_RE = re.compile(r"(?is)<a\b[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>")


def fetch(url: str, limit: int = 5_000_000) -> tuple[str, dict]:
    info = {
        "url": url,
        "ok": False,
        "status": None,
        "error": "",
        "final_url": url,
        "content_type": "",
        "bytes": 0,
    }
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Secret_DE_EPG Prime Structured Probe",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json,text/javascript,*/*",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.7,en;q=0.6",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            raw = resp.read(limit)
            info["ok"] = True
            info["status"] = getattr(resp, "status", None)
            info["final_url"] = resp.geturl()
            info["content_type"] = resp.headers.get("content-type", "")
            info["bytes"] = len(raw)
            return raw.decode("utf-8", errors="replace"), info
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            raw = exc.read(1_000_000)
            body = raw.decode("utf-8", errors="replace")
            info["bytes"] = len(raw)
        except Exception:
            pass
        info["status"] = exc.code
        info["error"] = f"HTTPError {exc.code}: {exc.reason}"
        info["content_type"] = exc.headers.get("content-type", "") if exc.headers else ""
        return body, info
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        return "", info


def textify(html: str) -> str:
    text = re.sub(r"(?is)<style\b.*?</style>", " ", html)
    text = re.sub(r"(?is)<script\b.*?</script>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean(s: object) -> str:
    text = unescape(str(s)).replace("\\u0026", "&").replace("\\/", "/")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def unique(seq):
    seen = set()
    out = []
    for item in seq:
        item = clean(item)
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def walk(obj, path="$", depth=0):
    if depth > 12:
        return
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}", depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]", depth + 1)


def iter_strings(obj, depth=0):
    if depth > 10:
        return
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from iter_strings(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_strings(v, depth + 1)


def parse_json_blocks(html: str) -> list[dict]:
    blocks = []
    for script in SCRIPT_RE.findall(html):
        raw = clean(script)
        if not raw:
            continue

        candidates = []
        if raw.startswith("{") and raw.endswith("}"):
            candidates.append(raw)

        # Some blocks contain only the state JSON but with semicolon.
        if raw.startswith("{") and raw.endswith("};"):
            candidates.append(raw[:-1])

        # Robust: look for JSON object that starts with {"init":
        idx = raw.find('{"init"')
        if idx >= 0:
            candidates.append(raw[idx:])

        for candidate in candidates:
            # Trim trailing JS if present by balancing braces.
            candidate = candidate.strip()
            if not candidate.startswith("{"):
                continue
            depth = 0
            end = None
            in_str = False
            esc = False
            for i, ch in enumerate(candidate):
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
            if end is None:
                continue
            trimmed = candidate[:end]
            try:
                data = json.loads(trimmed)
            except Exception:
                continue
            blocks.append({
                "length": len(trimmed),
                "top_keys": list(data.keys()) if isinstance(data, dict) else [],
                "data": data,
            })
            break

    return blocks


def extract_request_contexts(data) -> list[dict]:
    contexts = []
    for path, d in walk(data):
        if not isinstance(d, dict):
            continue
        if "RequestContext" in d and isinstance(d["RequestContext"], dict):
            rc = d["RequestContext"]
            contexts.append({"path": path + ".RequestContext", **rc})
        # Sometimes the object itself is RequestContext-shaped.
        if any(k in d for k in ["recordTerritory", "currentTerritory", "marketplaceID", "customerIPAddress", "originalURI"]):
            contexts.append({"path": path, **d})
    return contexts[:20]


def extract_container_title(container: dict) -> str:
    for key in ("title", "displayTitle", "label", "heading", "collectionTitle"):
        value = container.get(key)
        if isinstance(value, str) and value.strip():
            return clean(value)
        if isinstance(value, dict):
            for vv in value.values():
                if isinstance(vv, str) and vv.strip():
                    return clean(vv)
    # Search shallow strings.
    for s in iter_strings(container, depth=0):
        if len(s) > 3 and len(s) < 100 and any(term.casefold() in s.casefold() for term in SPORT_TERMS):
            return clean(s)
    return ""


def find_links_in_obj(obj, base_url: str) -> list[str]:
    links = []
    for s in iter_strings(obj):
        st = clean(s)
        if "/detail/" in st or "/tournament/" in st or "/gp/video/detail/" in st or "/gp/video/tournament/" in st:
            if st.startswith("http"):
                links.append(st)
            elif st.startswith("www."):
                links.append("https://" + st)
            elif st.startswith("/"):
                links.append(urljoin(base_url, st))
        elif re.match(r"^[A-Z0-9]{10,}$", st) and len(st) <= 18:
            # Possible title id, not direct link.
            pass
    return unique(links)[:20]


def find_title_id(obj) -> str:
    for path, d in walk(obj):
        if not isinstance(d, dict):
            continue
        for key in ("titleId", "catalogId", "gti", "asin", "id"):
            value = d.get(key)
            if isinstance(value, str) and re.match(r"^(?:amzn1\.|[A-Z0-9]{8,})", value):
                return clean(value)
    return ""


def find_datetime_strings(obj) -> list[str]:
    found = []
    for s in iter_strings(obj):
        st = clean(s)
        if ISO_RE.search(st) or DATE_DE_RE.search(st) or DATE_EN_RE.search(st) or TIME_RE.search(st):
            # Avoid CSS/font timing junk.
            if len(st) <= 400:
                found.append(st)
    return unique(found)[:40]


def find_event_hint_strings(obj) -> list[str]:
    found = []
    for s in iter_strings(obj):
        st = clean(s)
        if len(st) > 500:
            continue
        if EVENT_HINT_RE.search(st):
            found.append(st)
    return unique(found)[:80]


def entity_score(entity: dict) -> int:
    blob = json.dumps(entity, ensure_ascii=False)
    score = 0
    score += 10 if "displayTitle" in entity else 0
    score += 10 if any(x in blob for x in ["LIVE", "live", "Upcoming", "DEMNÄCHST", "Bevorstehende"]) else 0
    score += 8 if (DATE_DE_RE.search(blob) or DATE_EN_RE.search(blob) or ISO_RE.search(blob) or TIME_RE.search(blob)) else 0
    score += 8 if any(term.casefold() in blob.casefold() for term in SPORT_TERMS) else 0
    score += 8 if "/detail/" in blob or "/tournament/" in blob or "/gp/video/" in blob else 0
    return score


def extract_entities_from_data(data, page_url: str) -> tuple[list[dict], list[dict]]:
    containers_out = []
    candidates = []

    # Prefer body containers when present.
    for path, d in walk(data):
        if not isinstance(d, dict):
            continue
        if isinstance(d.get("containers"), list):
            for idx, container in enumerate(d["containers"]):
                if not isinstance(container, dict):
                    continue
                container_title = extract_container_title(container)
                container_type = clean(container.get("containerType", ""))
                entities = container.get("entities")
                if not isinstance(entities, list):
                    continue
                containers_out.append({
                    "path": f"{path}.containers[{idx}]",
                    "containerType": container_type,
                    "containerTitle": container_title,
                    "entity_count": len(entities),
                })
                for e_idx, entity in enumerate(entities):
                    if not isinstance(entity, dict):
                        continue
                    title = clean(entity.get("displayTitle") or entity.get("title") or entity.get("name") or "")
                    if not title:
                        continue
                    score = entity_score(entity)
                    if score < 15:
                        continue
                    candidates.append({
                        "source_page": page_url,
                        "container_path": f"{path}.containers[{idx}].entities[{e_idx}]",
                        "containerType": container_type,
                        "containerTitle": container_title,
                        "score": score,
                        "displayTitle": title,
                        "entityType": clean(entity.get("entityType", "")),
                        "titleId": find_title_id(entity),
                        "links": find_links_in_obj(entity, page_url),
                        "datetime_strings": find_datetime_strings(entity),
                        "event_hint_strings": find_event_hint_strings(entity),
                        "raw_keys": list(entity.keys())[:80],
                        "raw_snippet": json.dumps(entity, ensure_ascii=False)[:1800],
                    })

    # Fallback: any dict with displayTitle.
    if not candidates:
        for path, d in walk(data):
            if not isinstance(d, dict) or "displayTitle" not in d:
                continue
            title = clean(d.get("displayTitle", ""))
            if not title:
                continue
            score = entity_score(d)
            if score < 15:
                continue
            candidates.append({
                "source_page": page_url,
                "container_path": path,
                "containerType": "",
                "containerTitle": "",
                "score": score,
                "displayTitle": title,
                "entityType": clean(d.get("entityType", "")),
                "titleId": find_title_id(d),
                "links": find_links_in_obj(d, page_url),
                "datetime_strings": find_datetime_strings(d),
                "event_hint_strings": find_event_hint_strings(d),
                "raw_keys": list(d.keys())[:80],
                "raw_snippet": json.dumps(d, ensure_ascii=False)[:1800],
            })

    # Deduplicate.
    seen = set()
    deduped = []
    for c in candidates:
        key = (c["source_page"], c["displayTitle"], c["titleId"], tuple(c["datetime_strings"][:5]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    deduped.sort(key=lambda x: (-x["score"], x["displayTitle"]))
    return containers_out, deduped


def extract_visible_lines(text: str) -> list[str]:
    lines = []
    for match in EVENT_HINT_RE.finditer(text):
        s = max(0, match.start() - 220)
        e = min(len(text), match.end() + 320)
        ctx = clean(text[s:e])
        if TIME_RE.search(ctx) or DATE_DE_RE.search(ctx) or DATE_EN_RE.search(ctx) or "LIVE" in ctx.upper():
            lines.append(ctx)
    return unique(lines)[:200]


def analyze_page(url: str) -> dict:
    html, info = fetch(url)
    visible_text = textify(html)
    json_blocks = parse_json_blocks(html)

    request_contexts = []
    containers = []
    candidates = []

    for block in json_blocks:
        data = block["data"]
        request_contexts.extend(extract_request_contexts(data))
        cts, ents = extract_entities_from_data(data, url)
        containers.extend(cts)
        candidates.extend(ents)

    # Links from HTML can seed future detail probes.
    html_links = []
    for href, body in LINK_RE.findall(html):
        label = clean(re.sub(r"(?is)<[^>]+>", " ", body))
        full = urljoin(url, clean(href))
        low = f"{label} {full}".casefold()
        if any(term.casefold() in low for term in SPORT_TERMS) or "/detail/" in full or "/tournament/" in full:
            html_links.append({"label": label[:200], "url": full})

    return {
        **info,
        "visible_text_len": len(visible_text),
        "json_block_count": len(json_blocks),
        "json_block_summaries": [
            {"length": b["length"], "top_keys": b["top_keys"][:20]}
            for b in json_blocks
        ],
        "request_contexts": request_contexts[:20],
        "containers": containers[:120],
        "candidate_count": len(candidates),
        "candidates": candidates[:200],
        "visible_event_lines": extract_visible_lines(visible_text),
        "html_links": html_links[:200],
    }


def main() -> int:
    page_results = []
    follow_urls = []

    for seed in SEED_URLS:
        result = analyze_page(seed)
        page_results.append(result)
        for link in result["html_links"]:
            url = link["url"]
            low = url.casefold()
            if any(token in low for token in ["/detail/", "/tournament/", "/gp/video/detail/", "/gp/video/tournament/"]):
                follow_urls.append(url)

    follow_urls = unique(follow_urls)[:80]
    follow_results = []

    for url in follow_urls:
        follow_results.append(analyze_page(url))

    all_candidates = []
    for result in page_results + follow_results:
        all_candidates.extend(result["candidates"])

    # Deduplicate globally.
    seen = set()
    deduped_candidates = []
    for c in all_candidates:
        key = (c["displayTitle"], c["titleId"], tuple(c["datetime_strings"][:5]), tuple(c["links"][:2]))
        if key in seen:
            continue
        seen.add(key)
        deduped_candidates.append(c)
    deduped_candidates.sort(key=lambda x: (-x["score"], x["displayTitle"]))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "prime_video_structured_probe",
        "seed_urls": SEED_URLS,
        "follow_urls_checked": follow_urls,
        "seed_results": page_results,
        "follow_results": follow_results,
        "candidate_count": len(deduped_candidates),
        "candidates": deduped_candidates[:400],
    }

    (OUT_DIR / "prime-structured-probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = []
    lines.append(f"Prime structured probe generated at {payload['generated_at']}")
    lines.append(f"seed_pages: {len(page_results)}")
    lines.append(f"follow_pages: {len(follow_results)}")
    lines.append(f"candidate_count: {len(deduped_candidates)}")
    lines.append("")

    lines.append("REQUEST CONTEXTS / TERRITORY")
    for result in page_results + follow_results[:10]:
        lines.append("=" * 100)
        lines.append(f"URL: {result['url']}")
        lines.append(f"OK: {result['ok']} STATUS: {result['status']} BYTES: {result['bytes']} FINAL: {result['final_url']}")
        if result["request_contexts"]:
            for rc in result["request_contexts"][:5]:
                keys = [
                    "path", "marketplaceID", "recordTerritory", "currentTerritory",
                    "osLocale", "locale", "originalURI", "serverName", "customerIPAddress",
                ]
                lines.append("  " + " | ".join(f"{k}={rc.get(k)}" for k in keys if k in rc))
        else:
            lines.append("  no RequestContext found")

    lines.append("")
    lines.append("CONTAINERS")
    for result in page_results[:8]:
        lines.append("=" * 100)
        lines.append(f"URL: {result['url']}")
        for c in result["containers"][:50]:
            lines.append(
                f"  type={c['containerType']} title={c['containerTitle']} entities={c['entity_count']} path={c['path']}"
            )

    lines.append("")
    lines.append("STRUCTURED EVENT CANDIDATES")
    for c in deduped_candidates[:250]:
        lines.append("=" * 100)
        lines.append(f"TITLE: {c['displayTitle']}")
        lines.append(f"SCORE: {c['score']} TYPE: {c['entityType']} TITLE_ID: {c['titleId']}")
        lines.append(f"CONTAINER: {c['containerTitle']} / {c['containerType']}")
        lines.append(f"SOURCE: {c['source_page']}")
        if c["links"]:
            lines.append("LINKS:")
            for link in c["links"][:8]:
                lines.append(f"  {link}")
        if c["datetime_strings"]:
            lines.append("DATETIME_STRINGS:")
            for value in c["datetime_strings"][:15]:
                lines.append(f"  {value}")
        if c["event_hint_strings"]:
            lines.append("EVENT_HINT_STRINGS:")
            for value in c["event_hint_strings"][:20]:
                lines.append(f"  {value}")
        lines.append(f"RAW_KEYS: {c['raw_keys']}")
        lines.append(f"RAW_SNIPPET: {c['raw_snippet'][:1400]}")

    lines.append("")
    lines.append("VISIBLE EVENT LINES")
    for result in page_results[:8]:
        lines.append("=" * 100)
        lines.append(f"URL: {result['url']}")
        for line in result["visible_event_lines"][:80]:
            lines.append(f"  - {line}")

    (OUT_DIR / "prime-structured-probe.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # Smaller candidate-only file for easier upload/read.
    cand_lines = []
    cand_lines.append(f"Prime structured candidates generated at {payload['generated_at']}")
    cand_lines.append(f"candidate_count: {len(deduped_candidates)}")
    for c in deduped_candidates[:300]:
        cand_lines.append(
            f"{c['displayTitle']} | score={c['score']} | type={c['entityType']} | "
            f"container={c['containerTitle']} | dates={'; '.join(c['datetime_strings'][:5])} | "
            f"links={'; '.join(c['links'][:3])}"
        )
    (OUT_DIR / "prime-structured-candidates.txt").write_text(
        "\n".join(cand_lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"Wrote {OUT_DIR / 'prime-structured-probe.txt'}")
    print(f"Wrote {OUT_DIR / 'prime-structured-candidates.txt'}")
    print(f"Wrote {OUT_DIR / 'prime-structured-probe.json'}")
    print(f"candidate_count={len(deduped_candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
