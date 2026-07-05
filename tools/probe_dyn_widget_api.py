#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DYN Widget/API probe for Secret_DE_EPG.

Safe standalone probe:
- Does NOT modify public/sports-events.xml.xz.
- Does NOT deploy GitHub Pages.
- Creates dyn-widget-results/dyn-widget-api-probe.json and .txt as an Actions artifact.

Why:
Previous probe showed /spiele/... pages embed iframes like:
https://widgets.desk.dyn.sport/matchups/handball/<ContentDeskId>?/profile

The iframe HTML itself is only "Dyn Widget Configurator".
This probe fetches the widget assets and scans JavaScript for API endpoints,
matchup endpoints, asset URLs, runtime config and possible fixture data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse
import json
import re
import urllib.error
import urllib.request


OUT_DIR = Path("dyn-widget-results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

WIDGET_URLS = [
    "https://widgets.desk.dyn.sport/matchups/handball/Q7Zk5rLkdJxBZgaXExX7Vb?/profile",
    "https://widgets.desk.dyn.sport/matchups/basketball/NCmk4W4gjZ5PcD9y7K3hiZ?/profile&standalone=true",
    "https://widgets.desk.dyn.sport/matchups/volleyball/LpS8QMGJSs4D4XiyM3ULZo?/profile",
    "https://widgets.desk.dyn.sport/matchups/tabletennis/8HKTtNzWTZJBZii8ZSKh5h?/profile",
]

IDS = {
    "handball": "Q7Zk5rLkdJxBZgaXExX7Vb",
    "basketball": "NCmk4W4gjZ5PcD9y7K3hiZ",
    "volleyball": "LpS8QMGJSs4D4XiyM3ULZo",
    "tabletennis": "8HKTtNzWTZJBZii8ZSKh5h",
}

# Likely candidate APIs. Many will fail; that is fine.
CANDIDATE_TEMPLATES = [
    "https://widgets.desk.dyn.sport/api/matchups/{sport}/{id}",
    "https://widgets.desk.dyn.sport/api/matchups/{sport}/{id}/profile",
    "https://widgets.desk.dyn.sport/api/matchups/{sport}/{id}?profile",
    "https://widgets.desk.dyn.sport/matchups/{sport}/{id}/api",
    "https://widgets.desk.dyn.sport/matchups/{sport}/{id}/data",
    "https://widgets.desk.dyn.sport/assets/{sport}/{id}.json",
    "https://widgets.desk.dyn.sport/config/{sport}/{id}.json",
    "https://widgets.desk.dyn.sport/fixtures/{sport}/{id}",
    "https://widgets.desk.dyn.sport/matches/{sport}/{id}",
    "https://widgets.desk.dyn.sport/events/{sport}/{id}",
]

SRC_RE = re.compile(r"(?is)<(?:script|link)\b[^>]*(?:src|href)=[\"']([^\"']+)[\"']")
ANY_URL_RE = re.compile(r"(?i)(https?://[^\"'`<>\s)]+|/[A-Za-z0-9_./?=&:%+-]*(?:api|matchup|matchups|fixture|fixtures|event|events|game|games|schedule|config|assets|gameday)[A-Za-z0-9_./?=&:%+-]*)")
KEY_RE = re.compile(r"(?i)(api|baseURL|baseUrl|matchup|matchups|fixture|fixtures|gameday|gameDay|event|events|startDate|startTime|scheduled|kickoff|homeTeam|awayTeam|teamName|competition|profile|standalone|widget|contentDesk|ContentDeskId)")
ISO_RE = re.compile(r"20[2-9][0-9]-[01]\d-[0-3]\d(?:T[0-2]\d:[0-5]\d(?::[0-5]\d)?(?:\.\d+)?Z?)?")
DATE_DE_RE = re.compile(r"\b(?:Mo|Di|Mi|Do|Fr|Sa|So)?\.?,?\s*[0-3]?\d\.[01]?\d\.(?:20[2-9][0-9]|\d{2})\b", re.I)
TIME_RE = re.compile(r"\b[0-2]?\d:[0-5]\d\b")


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
            "User-Agent": "Mozilla/5.0 Secret_DE_EPG DYN Widget API Probe",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json,text/javascript,*/*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Referer": "https://www.dyn.sport/spiele/handball/64994",
            "Origin": "https://www.dyn.sport",
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
            body = exc.read(1_000_000).decode("utf-8", errors="replace")
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
        item = unescape(item).replace("\\u0026", "&").replace("\\/", "/")
        item = item.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def extract_asset_urls(html: str, base_url: str) -> list[str]:
    urls = []
    for value in SRC_RE.findall(html):
        url = urljoin(base_url, unescape(value))
        urls.append(url)
    return unique(urls)


def extract_interesting_urls(blob: str, base_url: str) -> list[str]:
    urls = []
    for value in ANY_URL_RE.findall(blob):
        value = unescape(value).replace("\\u0026", "&").replace("\\/", "/")
        url = urljoin(base_url, value)
        urls.append(url)
    return unique(urls)


def contexts(blob: str, regex: re.Pattern, radius: int = 320, limit: int = 80) -> list[str]:
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


def analyze_blob(url: str, body: str, info: dict) -> dict:
    text = textify(body) if "html" in (info.get("content_type") or "") else ""
    interesting = extract_interesting_urls(body, url)

    return {
        **info,
        "text_length": len(text),
        "asset_urls": extract_asset_urls(body, url)[:120],
        "interesting_urls": interesting[:200],
        "iso_count": len(ISO_RE.findall(body)),
        "date_de_count": len(DATE_DE_RE.findall(body)),
        "time_count": len(TIME_RE.findall(body)),
        "key_count": len(KEY_RE.findall(body)),
        "contexts_iso": contexts(body, ISO_RE, limit=25),
        "contexts_date_de": contexts(body, DATE_DE_RE, limit=25),
        "contexts_time": contexts(body, TIME_RE, limit=25),
        "contexts_keys": contexts(body, KEY_RE, limit=80),
        "snippet_text": text[:1200] if text else body[:1200],
    }


def analyze_url(url: str) -> dict:
    body, info = fetch(url)
    return analyze_blob(url, body, info)


def make_candidates() -> list[str]:
    out = []
    for sport, id_value in IDS.items():
        for tmpl in CANDIDATE_TEMPLATES:
            out.append(tmpl.format(sport=sport, id=id_value))
    return unique(out)


def main() -> int:
    widget_results = []
    asset_urls = []

    for url in WIDGET_URLS:
        body, info = fetch(url)
        result = analyze_blob(url, body, info)
        widget_results.append(result)
        asset_urls.extend(result["asset_urls"])
        asset_urls.extend([
            u for u in result["interesting_urls"]
            if "widgets.desk.dyn.sport" in u or "/assets/" in u
        ])

    # Keep only likely JS/CSS/JSON assets from widget host.
    asset_urls = unique([
        u for u in asset_urls
        if (
            "widgets.desk.dyn.sport" in u
            and any(ext in u.casefold() for ext in [".js", ".css", ".json", "/assets/"])
        )
    ])[:100]

    asset_results = [analyze_url(url) for url in asset_urls]

    candidate_urls = make_candidates()

    # Add API-ish URLs discovered from JS assets.
    for res in asset_results:
        for u in res["interesting_urls"]:
            low = u.casefold()
            if any(token in low for token in ["api", "matchup", "fixture", "event", "schedule", "gameday"]):
                candidate_urls.append(u)

    candidate_urls = unique(candidate_urls)[:160]
    candidate_results = [analyze_url(url) for url in candidate_urls]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "dyn_widget_api_probe",
        "widget_urls": WIDGET_URLS,
        "asset_urls_checked": asset_urls,
        "candidate_urls_checked": candidate_urls,
        "widget_results": widget_results,
        "asset_results": asset_results,
        "candidate_results": candidate_results,
    }

    (OUT_DIR / "dyn-widget-api-probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = []
    lines.append(f"DYN widget/api probe generated at {payload['generated_at']}")
    lines.append(f"widgets_checked: {len(widget_results)}")
    lines.append(f"assets_checked: {len(asset_results)}")
    lines.append(f"candidate_urls_checked: {len(candidate_results)}")
    lines.append("")

    def write_section(title: str, results: list[dict], max_results: int = 100):
        lines.append(title)
        for res in results[:max_results]:
            lines.append("=" * 90)
            lines.append(f"URL: {res['url']}")
            lines.append(f"OK: {res['ok']} STATUS: {res['status']} BYTES: {res['bytes']} CONTENT: {res['content_type']} ERROR: {res['error']}")
            lines.append(f"final_url: {res['final_url']}")
            lines.append(
                f"text_length={res['text_length']} assets={len(res['asset_urls'])} interesting={len(res['interesting_urls'])} "
                f"iso={res['iso_count']} date_de={res['date_de_count']} time={res['time_count']} key={res['key_count']}"
            )

            lines.append("ASSET URLs:")
            for u in res["asset_urls"][:30]:
                lines.append(f"  {u}")

            lines.append("INTERESTING URLs:")
            for u in res["interesting_urls"][:50]:
                lines.append(f"  {u}")

            lines.append("ISO contexts:")
            for ctx in res["contexts_iso"][:10]:
                lines.append(f"  - {ctx}")

            lines.append("German date contexts:")
            for ctx in res["contexts_date_de"][:10]:
                lines.append(f"  - {ctx}")

            lines.append("Time contexts:")
            for ctx in res["contexts_time"][:10]:
                lines.append(f"  - {ctx}")

            lines.append("Key contexts:")
            for ctx in res["contexts_keys"][:22]:
                lines.append(f"  - {ctx}")

            lines.append("Snippet:")
            lines.append(res["snippet_text"][:1200])
            lines.append("")

    write_section("WIDGET HTML RESULTS", widget_results)
    write_section("ASSET RESULTS", asset_results)
    write_section("CANDIDATE API RESULTS", candidate_results, max_results=160)

    (OUT_DIR / "dyn-widget-api-probe.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"Wrote {OUT_DIR / 'dyn-widget-api-probe.txt'}")
    print(f"Wrote {OUT_DIR / 'dyn-widget-api-probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
