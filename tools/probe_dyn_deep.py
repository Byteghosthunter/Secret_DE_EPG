#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DYN deep probe for Secret_DE_EPG.

Safe standalone probe:
- Does NOT modify public/sports-events.xml.xz.
- Does NOT deploy GitHub Pages.
- Creates dyn-deep-results/dyn-deep-probe.json and .txt as an Actions artifact.

Goal:
Find where DYN hides real fixture/event data:
- API endpoints
- JSON embedded in HTML
- script asset URLs
- date contexts around competition pages
- possible GraphQL / REST / wp-json / api URLs
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
import json
import re
import urllib.error
import urllib.request


OUT_DIR = Path("dyn-deep-results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED_URLS = [
    "https://www.dyn.sport/deinsender/programm/",
    "https://www.dyn.sport/deinsender/handball-spielplaene/",
    "https://www.dyn.sport/deinsender/basketball-spielplane/",
    "https://www.dyn.sport/deinsender/volleyball-spielplaene/",
    "https://www.dyn.sport/deinsender/tischtennis-spielplaene/",
    "https://www.dyn.sport/competition/Daikin_Handball_Bundesliga_64994",
]

INTERESTING_TERMS = [
    "api",
    "graphql",
    "wp-json",
    "rest_route",
    "competition",
    "fixture",
    "fixtures",
    "match",
    "matches",
    "game",
    "games",
    "event",
    "events",
    "schedule",
    "spielplan",
    "startTime",
    "start_time",
    "startDate",
    "start_date",
    "kickoff",
    "livestream",
    "stream",
    "broadcast",
    "team",
    "homeTeam",
    "awayTeam",
    "home_team",
    "away_team",
]

DATE_RE = re.compile(r"\b[0-3]?\d\.[01]?\d\.(?:20[2-9][0-9]|\d{2})\b")
TIME_RE = re.compile(r"\b[0-2]?\d:[0-5]\d\b")
URL_RE = re.compile(r"(?i)(https?://[^\"'<>\\s)]+|/[A-Za-z0-9_./?=&:%+-]*(?:api|graphql|wp-json|competition|fixture|match|event|schedule|spielplan)[A-Za-z0-9_./?=&:%+-]*)")
SCRIPT_RE = re.compile(r"(?i)<script\b[^>]*\bsrc=[\"']([^\"']+)[\"']")
A_RE = re.compile(r"(?i)<a\b[^>]+href=[\"']([^\"']+)[\"']")


def fetch(url: str, limit: int = 2_000_000) -> tuple[str, dict]:
    info = {
        "url": url,
        "ok": False,
        "error": "",
        "status": None,
        "final_url": url,
        "content_type": "",
        "bytes": 0,
    }

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Secret_DE_EPG DYN Deep Probe",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json,text/javascript,*/*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
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
            body = exc.read(250000).decode("utf-8", errors="replace")
        except Exception:
            pass
        info["status"] = exc.code
        info["error"] = f"HTTPError {exc.code}: {exc.reason}"
        info["bytes"] = len(body.encode("utf-8", errors="replace"))
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


def unique(seq):
    seen = set()
    out = []
    for item in seq:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def extract_script_urls(html: str, base: str) -> list[str]:
    urls = []
    for src in SCRIPT_RE.findall(html):
        urls.append(urljoin(base, unescape(src)))
    return unique(urls)


def extract_candidate_links(html: str, base: str) -> list[str]:
    urls = []
    for href in A_RE.findall(html):
        href = unescape(href).strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        url = urljoin(base, href).split("#", 1)[0]
        if "dyn.sport" in url:
            urls.append(url)
    return unique(urls)


def extract_interesting_urls(blob: str, base: str) -> list[str]:
    urls = []
    for m in URL_RE.findall(blob):
        url = urljoin(base, unescape(m))
        url = url.replace("\\u0026", "&")
        url = url.split('"', 1)[0].split("'", 1)[0]
        urls.append(url)
    return unique(urls)


def contexts_for_regex(blob: str, regex: re.Pattern, radius: int = 260, limit: int = 50) -> list[str]:
    contexts = []
    for m in regex.finditer(blob):
        start = max(0, m.start() - radius)
        end = min(len(blob), m.end() + radius)
        ctx = blob[start:end]
        ctx = re.sub(r"\s+", " ", ctx)
        contexts.append(ctx)
        if len(contexts) >= limit:
            break
    return contexts


def term_counts(blob: str) -> dict[str, int]:
    low = blob.casefold()
    return {term: low.count(term.casefold()) for term in INTERESTING_TERMS if low.count(term.casefold())}


def analyze_page(url: str) -> tuple[dict, list[str]]:
    html, info = fetch(url)
    text = textify(html)

    script_urls = extract_script_urls(html, url)
    links = extract_candidate_links(html, url)
    interesting_urls = extract_interesting_urls(html, url)

    result = {
        **info,
        "text_length": len(text),
        "script_count": len(script_urls),
        "link_count": len(links),
        "interesting_url_count": len(interesting_urls),
        "date_count_text": len(DATE_RE.findall(text)),
        "time_count_text": len(TIME_RE.findall(text)),
        "date_count_raw": len(DATE_RE.findall(html)),
        "time_count_raw": len(TIME_RE.findall(html)),
        "term_counts": term_counts(html),
        "script_urls": script_urls[:80],
        "candidate_links": links[:120],
        "interesting_urls": interesting_urls[:120],
        "date_contexts_text": contexts_for_regex(text, DATE_RE, limit=30),
        "date_contexts_raw": contexts_for_regex(html, DATE_RE, limit=30),
        "snippet_text": text[:1800],
    }
    return result, script_urls


def analyze_script(url: str) -> dict:
    body, info = fetch(url, limit=1_500_000)
    interesting_urls = extract_interesting_urls(body, url)
    return {
        **info,
        "term_counts": term_counts(body),
        "interesting_url_count": len(interesting_urls),
        "interesting_urls": interesting_urls[:80],
        "date_count_raw": len(DATE_RE.findall(body)),
        "time_count_raw": len(TIME_RE.findall(body)),
        "contexts_api": contexts_for_regex(
            body,
            re.compile(r"(?i)(api|graphql|wp-json|fixture|match|event|schedule|competition)"),
            radius=220,
            limit=30,
        ),
    }


def main() -> int:
    page_results = []
    all_scripts = []

    for url in SEED_URLS:
        result, scripts = analyze_page(url)
        page_results.append(result)
        all_scripts.extend(scripts)

    all_scripts = unique([
        s for s in all_scripts
        if "dyn.sport" in s or "wp-content" in s or "wp-includes" in s
    ])[:80]

    script_results = []
    for script_url in all_scripts:
        script_results.append(analyze_script(script_url))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "dyn_deep_probe",
        "seed_urls": SEED_URLS,
        "pages": page_results,
        "scripts": script_results,
    }

    (OUT_DIR / "dyn-deep-probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = []
    lines.append(f"DYN deep probe generated at {payload['generated_at']}")
    lines.append("")
    lines.append("PAGES")
    for page in page_results:
        lines.append("=" * 90)
        lines.append(f"URL: {page['url']}")
        lines.append(f"OK: {page['ok']} STATUS: {page['status']} BYTES: {page['bytes']} CONTENT: {page['content_type']}")
        lines.append(f"text_length={page['text_length']} scripts={page['script_count']} links={page['link_count']} interesting_urls={page['interesting_url_count']}")
        lines.append(f"dates_text={page['date_count_text']} times_text={page['time_count_text']} dates_raw={page['date_count_raw']} times_raw={page['time_count_raw']}")
        lines.append(f"term_counts={page['term_counts']}")
        lines.append("")
        lines.append("Interesting URLs:")
        for u in page["interesting_urls"][:30]:
            lines.append(f"  {u}")
        lines.append("")
        lines.append("Script URLs:")
        for u in page["script_urls"][:30]:
            lines.append(f"  {u}")
        lines.append("")
        lines.append("Date contexts TEXT:")
        for ctx in page["date_contexts_text"][:12]:
            lines.append(f"  - {ctx}")
        lines.append("")
        lines.append("Date contexts RAW:")
        for ctx in page["date_contexts_raw"][:12]:
            lines.append(f"  - {ctx}")
        lines.append("")
        lines.append("Snippet:")
        lines.append(page["snippet_text"][:1200])

    lines.append("")
    lines.append("SCRIPTS")
    for script in script_results:
        if not script["term_counts"] and script["interesting_url_count"] == 0:
            continue
        lines.append("=" * 90)
        lines.append(f"URL: {script['url']}")
        lines.append(f"OK: {script['ok']} STATUS: {script['status']} BYTES: {script['bytes']} CONTENT: {script['content_type']}")
        lines.append(f"term_counts={script['term_counts']}")
        lines.append(f"interesting_url_count={script['interesting_url_count']} dates_raw={script['date_count_raw']} times_raw={script['time_count_raw']}")
        lines.append("Interesting URLs:")
        for u in script["interesting_urls"][:40]:
            lines.append(f"  {u}")
        lines.append("API contexts:")
        for ctx in script["contexts_api"][:12]:
            lines.append(f"  - {ctx}")

    (OUT_DIR / "dyn-deep-probe.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"Wrote {OUT_DIR / 'dyn-deep-probe.txt'}")
    print(f"Wrote {OUT_DIR / 'dyn-deep-probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
