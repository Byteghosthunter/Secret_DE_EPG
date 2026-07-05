#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse
import json
import re
import traceback
import urllib.error
import urllib.request

OUT_DIR = Path("discovery-eurosport-results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED_URLS = [
    "https://www.eurosport.de/watch/schedule.shtml",
    "https://www.eurosport.de/watch/",
    "https://www.eurosport.de/",
    "https://www.discoveryplus.com/de/de/watch-eurosport-on-discoveryplus",
    "https://www.discoveryplus.com/de/de",
    "https://www.discoveryplus.com/de/de/sport",
    "https://www.discoveryplus.com/de/de/sports",
]

KEY_TERMS = [
    "Eurosport", "discovery", "discovery+", "schedule", "Programm", "program",
    "guide", "live", "LIVE", "Livestream", "Event", "Events", "Tennis",
    "Wimbledon", "Tour de France", "Radsport", "Cycling", "Snooker",
    "Motorsport", "Formula", "Formel", "F1", "Biathlon", "api", "endpoint",
    "playout", "video", "content", "cms", "graphql",
]

SCRIPT_RE = re.compile(r"(?is)<script\b[^>]*?(?:src=[\"']([^\"']+)[\"'])?[^>]*>(.*?)</script>")
LINK_RE = re.compile(r"(?is)<a\b[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>")
URL_RE = re.compile(r"https?://[^\s\"'<>\\)]+|/[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]{6,}")
TIME_RE = re.compile(r"\b(?:[01]?\d|2[0-3])[:.][0-5]\d\s*(?:Uhr|CEST|CET|MESZ|MEZ|UTC|GMT)?\b", re.I)
DATE_RE = re.compile(
    r"\b(?:heute|morgen|today|tomorrow|mo|di|mi|do|fr|sa|so|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)\b"
    r"|(?:[0-3]?\d\.\s*(?:jan|feb|mär|mrz|apr|mai|jun|jul|aug|sep|okt|nov|dez)[a-zä]*\.?)"
    r"|(?:20[2-9]\d-[01]\d-[0-3]\d)",
    re.I,
)


def clean(value: object) -> str:
    text = unescape(str(value)).replace("\\u0026", "&").replace("\\/", "/")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def safe_join(base: str, raw: str) -> str:
    value = clean(raw).rstrip(".,;")
    if not value:
        return ""
    # avoid JS template/array fragments and malformed IPv6-like strings
    if any(ch in value for ch in ["[", "]", "{", "}", "`"]):
        return ""
    try:
        if value.startswith("/"):
            value = urljoin(base, value)
        # validate parse, can raise Invalid IPv6 URL
        urlparse(value)
    except ValueError:
        return ""
    return value


def is_first_party(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = parsed.netloc.casefold()
    if not host:
        return False
    return any(token in host for token in [
        "eurosport.", "discoveryplus.", "disco-api.", "wbd.", "wbdndiscovery.",
        "discovery.", "eurosportplayer.", "tntsports.", "static-eu",
    ])


def unique(seq):
    seen = set()
    out = []
    for item in seq:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, dict) else clean(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def fetch(url: str, limit: int = 6_000_000) -> tuple[str, dict]:
    info = {
        "url": url, "ok": False, "status": None, "error": "",
        "final_url": url, "content_type": "", "bytes": 0,
    }
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,text/javascript,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-GB;q=0.7,en;q=0.6",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "DNT": "1",
            "Connection": "close",
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
        try:
            raw = exc.read(1_000_000)
            body = raw.decode("utf-8", errors="replace")
            info["bytes"] = len(raw)
        except Exception:
            body = ""
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
    return clean(text)


def extract_links(html: str, base_url: str) -> list[dict]:
    links = []
    for href, body in LINK_RE.findall(html):
        full = safe_join(base_url, href)
        if not full:
            continue
        label = clean(re.sub(r"(?is)<[^>]+>", " ", body))
        combined = f"{label} {full}"
        if any(term.casefold() in combined.casefold() for term in KEY_TERMS):
            links.append({"label": label[:250], "url": full})
    return unique(links)[:250]


def extract_script_urls(html: str, base_url: str) -> list[str]:
    urls = []
    for src, _body in SCRIPT_RE.findall(html):
        if src:
            full = safe_join(base_url, src)
            if full:
                urls.append(full)
    for raw in URL_RE.findall(html):
        full = safe_join(base_url, raw)
        if not full:
            continue
        if full.endswith((".js", ".mjs")) or "/_next/static/" in full or "/assets/" in full:
            urls.append(full)
    return [u for u in unique(urls) if is_first_party(u)][:100]


def extract_interesting_urls(text: str, base_url: str) -> list[str]:
    urls = []
    for raw in URL_RE.findall(text):
        full = safe_join(base_url, raw)
        if not full:
            continue
        if any(term.casefold() in full.casefold() for term in [
            "api", "schedule", "program", "programme", "guide", "event", "events",
            "content", "cms", "graphql", "playout", "video", "eurosport",
            "discovery", "watch", "live",
        ]):
            urls.append(full)
    return [u for u in unique(urls) if is_first_party(u)][:300]


def extract_json_blocks(html: str) -> list[dict]:
    blocks = []
    for _src, body in SCRIPT_RE.findall(html):
        raw = clean(body)
        if not raw:
            continue
        candidates = []
        if raw.startswith("{") and raw.endswith("}"):
            candidates.append(raw)
        if raw.startswith("{") and raw.endswith("};"):
            candidates.append(raw[:-1])
        for marker in ['{"props"', '{"pageProps"', '{"data"', '{"initialState"', '{"schedule"', '{"content"', '{"items"']:
            idx = raw.find(marker)
            if idx >= 0:
                candidates.append(raw[idx:])

        for candidate in candidates:
            depth = 0
            end = None
            in_string = False
            escaped = False
            for i, ch in enumerate(candidate):
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
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end is None:
                continue
            try:
                data = json.loads(candidate[:end])
            except Exception:
                continue
            txt = json.dumps(data, ensure_ascii=False)[:10000]
            blocks.append({
                "length": end,
                "top_keys": list(data.keys())[:30] if isinstance(data, dict) else [],
                "key_term_count": sum(txt.casefold().count(term.casefold()) for term in KEY_TERMS),
                "time_count": len(TIME_RE.findall(txt)),
                "date_count": len(DATE_RE.findall(txt)),
                "snippet": txt[:1600],
            })
            break
    blocks.sort(key=lambda b: (b["key_term_count"], b["time_count"], b["date_count"], b["length"]), reverse=True)
    return blocks[:60]


def extract_event_lines(text: str) -> list[str]:
    lines = []
    pattern = r"(?i)(eurosport|live|programm|schedule|event|tennis|tour de france|radsport|snooker|wimbledon|motorsport|formel|f1|cycling|biathlon)"
    for match in re.finditer(pattern, text):
        start = max(0, match.start() - 260)
        end = min(len(text), match.end() + 420)
        ctx = clean(text[start:end])
        if TIME_RE.search(ctx) or DATE_RE.search(ctx) or any(term.casefold() in ctx.casefold() for term in ["live", "programm", "schedule"]):
            lines.append(ctx)
    return unique(lines)[:180]


def analyze_page(url: str) -> dict:
    html, info = fetch(url)
    text = textify(html)
    return {
        **info,
        "text_length": len(text),
        "term_counts": {term: text.casefold().count(term.casefold()) for term in KEY_TERMS if text.casefold().count(term.casefold())},
        "time_count": len(TIME_RE.findall(text)),
        "date_count": len(DATE_RE.findall(text)),
        "links": extract_links(html, info["final_url"] or url),
        "script_urls": extract_script_urls(html, info["final_url"] or url),
        "interesting_urls": extract_interesting_urls(html, info["final_url"] or url),
        "json_blocks": extract_json_blocks(html),
        "event_lines": extract_event_lines(text),
        "snippet": text[:1800],
    }


def analyze_script(url: str) -> dict:
    body, info = fetch(url)
    return {
        **info,
        "term_counts": {term: body.casefold().count(term.casefold()) for term in KEY_TERMS if body.casefold().count(term.casefold())},
        "time_count": len(TIME_RE.findall(body)),
        "date_count": len(DATE_RE.findall(body)),
        "interesting_urls": extract_interesting_urls(body, info["final_url"] or url),
        "contexts": extract_event_lines(clean(body))[:100],
        "snippet": body[:1400],
    }


def main() -> int:
    page_results = []
    script_urls = []
    script_results = []
    discovered_urls = []
    errors = []

    for url in SEED_URLS:
        try:
            result = analyze_page(url)
            page_results.append(result)
            script_urls.extend(result["script_urls"])
        except Exception as exc:
            errors.append(f"page {url}: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")

    for url in unique(script_urls)[:80]:
        try:
            result = analyze_script(url)
            script_results.append(result)
            discovered_urls.extend(result["interesting_urls"])
        except Exception as exc:
            errors.append(f"script {url}: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")

    discovered_urls = unique(discovered_urls)[:200]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "discovery_eurosport_probe_fixed",
        "seed_urls": SEED_URLS,
        "seed_pages": page_results,
        "scripts_checked": script_results,
        "discovered_urls": discovered_urls,
        "errors": errors,
    }

    (OUT_DIR / "discovery-eurosport-probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = []
    lines.append(f"Discovery/Eurosport fixed probe generated at {payload['generated_at']}")
    lines.append(f"seed_pages: {len(page_results)}")
    lines.append(f"scripts_checked: {len(script_results)}")
    lines.append(f"discovered_urls: {len(discovered_urls)}")
    lines.append(f"errors: {len(errors)}")
    lines.append("")

    if errors:
        lines.append("ERRORS")
        for err in errors[:30]:
            lines.append("- " + err.replace("\n", "\n  "))

    lines.append("SEED PAGE RESULTS")
    for result in page_results:
        lines.append("=" * 100)
        lines.append(f"URL: {result['url']}")
        lines.append(f"OK: {result['ok']} STATUS: {result['status']} BYTES: {result['bytes']} CONTENT: {result['content_type']} ERROR: {result['error']}")
        lines.append(f"FINAL: {result['final_url']}")
        lines.append(f"text_length={result['text_length']} time_count={result['time_count']} date_count={result['date_count']}")
        lines.append(f"term_counts={result['term_counts']}")
        if result["links"]:
            lines.append("LINKS:")
            for link in result["links"][:60]:
                lines.append(f"  {link['label']} -> {link['url']}")
        if result["interesting_urls"]:
            lines.append("INTERESTING URLS:")
            for item in result["interesting_urls"][:90]:
                lines.append(f"  {item}")
        if result["script_urls"]:
            lines.append("SCRIPT URLS:")
            for item in result["script_urls"][:50]:
                lines.append(f"  {item}")
        if result["json_blocks"]:
            lines.append("JSON BLOCKS:")
            for block in result["json_blocks"][:15]:
                lines.append(f"  len={block['length']} keys={block['top_keys']} key_terms={block['key_term_count']} time={block['time_count']} date={block['date_count']} snippet={block['snippet'][:700]}")
        if result["event_lines"]:
            lines.append("EVENT/SCHEDULE LINES:")
            for item in result["event_lines"][:80]:
                lines.append(f"  - {item}")
        lines.append("SNIPPET:")
        lines.append(result["snippet"][:1400])

    lines.append("")
    lines.append("SCRIPT RESULTS")
    for result in script_results:
        lines.append("=" * 100)
        lines.append(f"URL: {result['url']}")
        lines.append(f"OK: {result['ok']} STATUS: {result['status']} BYTES: {result['bytes']} CONTENT: {result['content_type']} ERROR: {result['error']}")
        lines.append(f"term_counts={result['term_counts']} time_count={result['time_count']} date_count={result['date_count']}")
        if result["interesting_urls"]:
            lines.append("INTERESTING URLS:")
            for item in result["interesting_urls"][:90]:
                lines.append(f"  {item}")
        if result["contexts"]:
            lines.append("CONTEXTS:")
            for item in result["contexts"][:50]:
                lines.append(f"  - {item}")

    lines.append("")
    lines.append("DISCOVERED URLS")
    for item in discovered_urls:
        lines.append(f"  {item}")

    full_text = "\n".join(lines) + "\n"
    (OUT_DIR / "discovery-eurosport-probe.txt").write_text(full_text, encoding="utf-8", newline="\n")

    small = []
    small.append(f"Discovery/Eurosport fixed candidates generated at {payload['generated_at']}")
    small.append(f"errors: {len(errors)}")
    small.append("")
    for result in page_results:
        small.append(f"PAGE {result['url']} ok={result['ok']} status={result['status']} bytes={result['bytes']} time_count={result['time_count']} date_count={result['date_count']}")
        for item in result["event_lines"][:35]:
            small.append(f"  LINE {item}")
        for item in result["interesting_urls"][:50]:
            small.append(f"  URL {item}")
    small.append("")
    small.append("DISCOVERED")
    for item in discovered_urls[:150]:
        small.append(f"  {item}")
    (OUT_DIR / "discovery-eurosport-candidates.txt").write_text(
        "\n".join(small) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(full_text[:100000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
