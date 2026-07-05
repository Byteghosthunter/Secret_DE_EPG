#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
Amazon / Prime Video Events probe for Secret_DE_EPG.

Safe standalone probe:
- Does NOT modify public/sports-events.xml.xz.
- Does NOT deploy GitHub Pages.
- Creates prime-events-results/prime-events-probe.json and .txt as an Actions artifact.

Goal:
Find whether Prime Video public sports pages expose upcoming live events in:
- HTML text
- embedded JSON / scripts
- links to tournament/detail pages
- event cards containing title + date/time + live/upcoming markers
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


OUT_DIR = Path("prime-events-results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED_URLS = [
    "https://www.primevideo.com/-/de/sports",
    "https://www.primevideo.com/sports",
    "https://www.amazon.de/-/en/gp/video/sports",
    "https://www.primevideo.com/-/de/tournament/amzn1.dv.icid.f40b96cd-f09e-48db-a9ec-0b0e298a39c8",
    "https://www.primevideo.com/-/de/tournament/amzn1.dv.icid.95ab18a6-c3f1-40ba-86b5-1f3b1f51d09b",
]

SPORT_TERMS = [
    "Champions League", "UEFA", "UFC", "NBA", "NFL", "Bundesliga", "DFB",
    "Premier League", "Wimbledon", "Tennis", "F1", "Formula 1", "MotoGP",
    "live", "LIVE", "KOMMENDE", "Bevorstehende", "Upcoming", "Sports", "Sport",
    "event", "events", "schedule", "match", "vs.", " vs ", " gegen ",
]

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
LINK_RE = re.compile(r"(?is)<a\b[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>")
HREF_RE = re.compile(r"(?is)<a\b[^>]+href=[\"']([^\"']+)[\"']")
SCRIPT_SRC_RE = re.compile(r"(?is)<script\b[^>]*\bsrc=[\"']([^\"']+)[\"']")
JSON_SCRIPT_RE = re.compile(r"(?is)<script\b[^>]*>(.*?)</script>")
URL_RE = re.compile(r"(?i)(https?://[^\"'<>\s)]+|/[A-Za-z0-9_./?=&:%+-]*(?:sports|sport|tournament|detail|live|event|events|schedule|api|catalog|title|browse|watch)[A-Za-z0-9_./?=&:%+-]*)")
KEY_RE = re.compile(r"(?i)(live|upcoming|event|events|schedule|sports|sport|title|synopsis|startTime|startDate|date|time|tournament|fixture|match|UEFA|UFC|NBA|NFL|Bundesliga)")


def fetch(url: str, limit: int = 4_000_000) -> tuple[str, dict]:
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
            "User-Agent": "Mozilla/5.0 Secret_DE_EPG Prime Events Probe",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json,text/javascript,*/*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8,en-US;q=0.7",
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


def clean_html_fragment(fragment: str) -> str:
    text = re.sub(r"(?is)<[^>]+>", " ", fragment)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def unique(seq):
    seen = set()
    out = []
    for item in seq:
        item = unescape(str(item)).replace("\\u0026", "&").replace("\\/", "/").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def contexts(blob: str, regex: re.Pattern, radius: int = 360, limit: int = 80) -> list[str]:
    out = []
    for m in regex.finditer(blob):
        s = max(0, m.start() - radius)
        e = min(len(blob), m.end() + radius)
        ctx = blob[s:e]
        ctx = unescape(ctx).replace("\\u0026", "&").replace("\\/", "/")
        ctx = re.sub(r"\s+", " ", ctx)
        out.append(ctx)
        if len(out) >= limit:
            break
    return out


def extract_links(html: str, base: str) -> list[dict]:
    links = []
    for href, body in LINK_RE.findall(html):
        full = urljoin(base, unescape(href).replace("\\u0026", "&"))
        label = clean_html_fragment(body)
        low = f"{full} {label}".casefold()
        if any(term.casefold() in low for term in SPORT_TERMS) or any(x in full for x in ["/sports", "/sport", "/tournament", "/detail"]):
            links.append({"url": full, "label": label[:300]})
    return links[:200]


def extract_urls(html: str, base: str) -> list[str]:
    urls = []
    for m in URL_RE.findall(html):
        urls.append(urljoin(base, unescape(m).replace("\\u0026", "&").replace("\\/", "/")))
    for src in SCRIPT_SRC_RE.findall(html):
        urls.append(urljoin(base, unescape(src).replace("\\u0026", "&")))
    return unique(urls)[:250]


def extract_jsonish_blocks(html: str) -> list[dict]:
    blocks = []
    for raw in JSON_SCRIPT_RE.findall(html):
        if len(raw) < 50:
            continue
        low = raw.casefold()
        if not any(term.casefold() in low for term in ["event", "sport", "title", "live", "schedule", "tournament", "uefa", "ufc", "nba", "nfl"]):
            continue
        compact = unescape(raw).replace("\\u0026", "&").replace("\\/", "/")
        compact = re.sub(r"\s+", " ", compact).strip()
        blocks.append({
            "length": len(raw),
            "key_count": len(KEY_RE.findall(raw)),
            "iso_count": len(ISO_RE.findall(raw)),
            "date_de_count": len(DATE_DE_RE.findall(raw)),
            "date_en_count": len(DATE_EN_RE.findall(raw)),
            "time_count": len(TIME_RE.findall(raw)),
            "snippet": compact[:2500],
        })
        if len(blocks) >= 60:
            break
    return blocks


def extract_possible_event_lines(text: str) -> list[str]:
    lines = []
    patterns = [DATE_DE_RE, DATE_EN_RE, TIME_RE, re.compile(r"(?i)\b(?:LIVE|KOMMENDE|Upcoming|Bevorstehende|Live um|Heute|Morgen)\b")]
    for pat in patterns:
        for ctx in contexts(text, pat, radius=180, limit=80):
            if any(term.casefold() in ctx.casefold() for term in SPORT_TERMS) or TIME_RE.search(ctx) or DATE_DE_RE.search(ctx) or DATE_EN_RE.search(ctx):
                lines.append(ctx)
    return unique(lines)[:120]


def term_counts(blob: str) -> dict:
    low = blob.casefold()
    return {term: low.count(term.casefold()) for term in SPORT_TERMS if low.count(term.casefold())}


def analyze_page(url: str) -> tuple[dict, list[str]]:
    html, info = fetch(url)
    text = textify(html)
    urls = extract_urls(html, url)

    result = {
        **info,
        "text_length": len(text),
        "term_counts": term_counts(html + "\n" + text),
        "links": extract_links(html, url),
        "interesting_urls": urls,
        "script_urls": [u for u in urls if any(ext in u.casefold() for ext in [".js", "script"])][:100],
        "jsonish_blocks": extract_jsonish_blocks(html),
        "iso_count_raw": len(ISO_RE.findall(html)),
        "date_de_count_text": len(DATE_DE_RE.findall(text)),
        "date_en_count_text": len(DATE_EN_RE.findall(text)),
        "time_count_text": len(TIME_RE.findall(text)),
        "key_count_raw": len(KEY_RE.findall(html)),
        "contexts_iso": contexts(html, ISO_RE, limit=30),
        "contexts_dates_de": contexts(text, DATE_DE_RE, limit=30),
        "contexts_dates_en": contexts(text, DATE_EN_RE, limit=30),
        "contexts_times": contexts(text, TIME_RE, limit=30),
        "contexts_keys_raw": contexts(html, KEY_RE, limit=40),
        "possible_event_lines": extract_possible_event_lines(text),
        "snippet_text": text[:2200],
    }

    return result, urls


def analyze_asset(url: str) -> dict:
    body, info = fetch(url, limit=2_000_000)
    return {
        **info,
        "term_counts": term_counts(body),
        "interesting_urls": extract_urls(body, url),
        "iso_count": len(ISO_RE.findall(body)),
        "date_de_count": len(DATE_DE_RE.findall(body)),
        "date_en_count": len(DATE_EN_RE.findall(body)),
        "time_count": len(TIME_RE.findall(body)),
        "key_count": len(KEY_RE.findall(body)),
        "contexts_keys": contexts(body, KEY_RE, limit=50),
        "contexts_iso": contexts(body, ISO_RE, limit=20),
        "snippet": body[:1800],
    }


def main() -> int:
    page_results = []
    discovered_urls = []

    for seed in SEED_URLS:
        result, urls = analyze_page(seed)
        page_results.append(result)
        discovered_urls.extend(urls)
        for link in result["links"]:
            discovered_urls.append(link["url"])

    follow_urls = []
    for u in unique(discovered_urls):
        low = u.casefold()
        if not any(host in low for host in ["primevideo.com", "amazon.de"]):
            continue
        if any(token in low for token in ["/sports", "/sport", "/tournament", "/detail", "/gp/video"]):
            follow_urls.append(u)
    follow_urls = unique(follow_urls)[:80]

    follow_results = []
    for url in follow_urls:
        if url in SEED_URLS:
            continue
        res, _ = analyze_page(url)
        follow_results.append(res)

    script_urls = []
    for res in page_results + follow_results:
        script_urls.extend(res["script_urls"])
    script_urls = unique([
        u for u in script_urls
        if any(host in u.casefold() for host in ["primevideo.com", "amazon.de", "amazon.com"])
        and not any(ext in u.casefold() for ext in [".css", ".png", ".jpg", ".jpeg", ".svg", ".woff", ".ico"])
    ])[:40]

    script_results = []
    for url in script_urls:
        script_results.append(analyze_asset(url))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "prime_video_events_probe",
        "seed_urls": SEED_URLS,
        "follow_urls_checked": follow_urls,
        "script_urls_checked": script_urls,
        "pages": page_results,
        "follow_pages": follow_results,
        "scripts": script_results,
    }

    (OUT_DIR / "prime-events-probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = []
    lines.append(f"Prime Video events probe generated at {payload['generated_at']}")
    lines.append(f"seed_pages: {len(page_results)}")
    lines.append(f"follow_pages: {len(follow_results)}")
    lines.append(f"scripts_checked: {len(script_results)}")
    lines.append("")

    def write_page_section(title: str, results: list[dict], max_items: int = 120):
        lines.append(title)
        for page in results[:max_items]:
            lines.append("=" * 100)
            lines.append(f"URL: {page['url']}")
            lines.append(f"OK: {page['ok']} STATUS: {page['status']} BYTES: {page['bytes']} CONTENT: {page['content_type']} ERROR: {page['error']}")
            lines.append(f"final_url: {page['final_url']}")
            lines.append(
                f"text_length={page['text_length']} iso_raw={page['iso_count_raw']} "
                f"date_de_text={page['date_de_count_text']} date_en_text={page['date_en_count_text']} "
                f"time_text={page['time_count_text']} key_raw={page['key_count_raw']}"
            )
            lines.append(f"term_counts={page['term_counts']}")

            lines.append("SPORT / EVENT LINKS:")
            for link in page["links"][:40]:
                lines.append(f"  {link['label'][:120]} -> {link['url']}")

            lines.append("INTERESTING URLs:")
            for u in page["interesting_urls"][:50]:
                lines.append(f"  {u}")

            lines.append("POSSIBLE EVENT LINES:")
            for ev in page["possible_event_lines"][:30]:
                lines.append(f"  - {ev}")

            lines.append("JSON-ish blocks:")
            for block in page["jsonish_blocks"][:8]:
                lines.append(
                    f"  len={block['length']} key={block['key_count']} iso={block['iso_count']} "
                    f"date_de={block['date_de_count']} date_en={block['date_en_count']} time={block['time_count']} "
                    f"snippet={block['snippet'][:1200]}"
                )

            lines.append("KEY contexts raw:")
            for ctx in page["contexts_keys_raw"][:15]:
                lines.append(f"  - {ctx}")

            lines.append("SNIPPET:")
            lines.append(page["snippet_text"][:1600])
            lines.append("")

    write_page_section("SEED PAGE RESULTS", page_results)
    write_page_section("FOLLOW PAGE RESULTS", follow_results)

    lines.append("SCRIPT RESULTS")
    for script in script_results:
        show = script["key_count"] > 0 or script["iso_count"] > 0 or script["time_count"] > 0 or script["term_counts"]
        if not show:
            continue
        lines.append("=" * 100)
        lines.append(f"URL: {script['url']}")
        lines.append(f"OK: {script['ok']} STATUS: {script['status']} BYTES: {script['bytes']} CONTENT: {script['content_type']} ERROR: {script['error']}")
        lines.append(f"term_counts={script['term_counts']}")
        lines.append(f"iso={script['iso_count']} date_de={script['date_de_count']} date_en={script['date_en_count']} time={script['time_count']} key={script['key_count']}")
        lines.append("Interesting URLs:")
        for u in script["interesting_urls"][:50]:
            lines.append(f"  {u}")
        lines.append("Key contexts:")
        for ctx in script["contexts_keys"][:20]:
            lines.append(f"  - {ctx}")
        lines.append("Snippet:")
        lines.append(script["snippet"][:1400])
        lines.append("")

    (OUT_DIR / "prime-events-probe.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"Wrote {OUT_DIR / 'prime-events-probe.txt'}")
    print(f"Wrote {OUT_DIR / 'prime-events-probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
