#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DYN fixtures/spiele probe for Secret_DE_EPG.

Safe standalone probe:
- Does NOT modify public/sports-events.xml.xz.
- Does NOT deploy GitHub Pages.
- Creates dyn-fixtures-results/dyn-fixtures-probe.json and .txt as an Actions artifact.

Why:
Previous probes showed:
- /matchups/... currently returns 404
- competition pages expose app routes:
  /spiele/<sport>/<competition_id>
  /fixtures/<sport>/<competition_id>
These routes are likely where live fixture data or a webview/widget is loaded.
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


OUT_DIR = Path("dyn-fixtures-results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ROUTES = [
    # Spiele routes from app header / DYN route table
    "https://www.dyn.sport/spiele/handball/Daikin_Handball_Bundesliga_64994",
    "https://www.dyn.sport/spiele/handball/64994",
    "https://www.dyn.sport/spiele/basketball/easyCredit_BBL_65002",
    "https://www.dyn.sport/spiele/basketball/65002",
    "https://www.dyn.sport/spiele/tabletennis/79806",
    "https://www.dyn.sport/spiele/volleyball/",
    # Fixtures routes from app route table
    "https://www.dyn.sport/fixtures/handball/Daikin_Handball_Bundesliga_64994",
    "https://www.dyn.sport/fixtures/handball/64994",
    "https://www.dyn.sport/fixtures/basketball/easyCredit_BBL_65002",
    "https://www.dyn.sport/fixtures/basketball/65002",
    "https://www.dyn.sport/fixtures/tabletennis/79806",
    "https://www.dyn.sport/fixtures/volleyball/79806",
]

# Also try likely embedded widget URLs directly if visible on pages.
DIRECT_WIDGET_CANDIDATES = [
    "https://widget.gameday.de",
    "https://widget.gameday.de/fixtures",
    "https://widget.gameday.de/matchups",
    "https://widget.gameday.de/handball",
    "https://widget.gameday.de/basketball",
]

DATE_DE_RE = re.compile(r"\b(?:Mo|Di|Mi|Do|Fr|Sa|So)?\.?,?\s*[0-3]?\d\.[01]?\d\.(?:20[2-9][0-9]|\d{2})\b", re.I)
TIME_RE = re.compile(r"\b[0-2]?\d:[0-5]\d\b")
ISO_RE = re.compile(r"20[2-9][0-9]-[01]\d-[0-3]\d(?:T[0-2]\d:[0-5]\d(?::[0-5]\d)?(?:\.\d+)?Z?)?")
IFRAME_RE = re.compile(r"(?is)<iframe\b[^>]*(?:src|data-src)=[\"']([^\"']+)[\"']")
SCRIPT_RE = re.compile(r"(?is)<script\b[^>]*\bsrc=[\"']([^\"']+)[\"']")
A_RE = re.compile(r"(?is)<a\b[^>]+href=[\"']([^\"']+)[\"']")
URL_ANY_RE = re.compile(r"(?i)(https?://[^\"'<>\s)]+|/[A-Za-z0-9_./?=&:%+-]*(?:fixtures|spiele|match|matches|event|events|schedule|api|graphql|gameday|widget)[A-Za-z0-9_./?=&:%+-]*)")
KEY_RE = re.compile(r"(?i)(fixture|fixtures|gameday|gameDay|match|matches|event|events|startDate|startTime|scheduled|kickoff|homeTeam|awayTeam|teamName|competition|widget|iframe|api|graphql)")


def fetch(url: str, limit: int = 3_000_000) -> tuple[str, dict]:
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
            "User-Agent": "Mozilla/5.0 Secret_DE_EPG DYN Fixtures Probe",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json,text/javascript,*/*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Referer": "https://www.dyn.sport/competition/Daikin_Handball_Bundesliga_64994",
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
            body = exc.read(750_000).decode("utf-8", errors="replace")
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
        item = unescape(item).replace("\\u0026", "&")
        item = item.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def extract_urls(body: str, base_url: str) -> dict:
    iframes = [urljoin(base_url, u) for u in IFRAME_RE.findall(body)]
    scripts = [urljoin(base_url, u) for u in SCRIPT_RE.findall(body)]
    links = [urljoin(base_url, u) for u in A_RE.findall(body)]

    interesting = []
    for u in URL_ANY_RE.findall(body):
        full = urljoin(base_url, unescape(u).replace("\\u0026", "&"))
        interesting.append(full)

    return {
        "iframes": unique(iframes),
        "scripts": unique(scripts),
        "links": unique(links),
        "interesting": unique(interesting),
    }


def contexts(blob: str, regex: re.Pattern, radius: int = 300, limit: int = 60) -> list[str]:
    out = []
    for m in regex.finditer(blob):
        s = max(0, m.start() - radius)
        e = min(len(blob), m.end() + radius)
        ctx = blob[s:e]
        ctx = unescape(ctx).replace("\\u0026", "&")
        ctx = re.sub(r"\s+", " ", ctx)
        out.append(ctx)
        if len(out) >= limit:
            break
    return out


def analyze(url: str) -> dict:
    body, info = fetch(url)
    text = textify(body)
    urls = extract_urls(body, url)

    return {
        **info,
        "text_length": len(text),
        "date_de_text": len(DATE_DE_RE.findall(text)),
        "date_de_raw": len(DATE_DE_RE.findall(body)),
        "time_text": len(TIME_RE.findall(text)),
        "time_raw": len(TIME_RE.findall(body)),
        "iso_raw": len(ISO_RE.findall(body)),
        "key_raw": len(KEY_RE.findall(body)),
        "urls": {
            "iframes": urls["iframes"][:80],
            "scripts": urls["scripts"][:80],
            "interesting": urls["interesting"][:160],
        },
        "contexts_dates": contexts(body, DATE_DE_RE, limit=25),
        "contexts_times": contexts(body, TIME_RE, limit=25),
        "contexts_iso": contexts(body, ISO_RE, limit=25),
        "contexts_keys": contexts(body, KEY_RE, limit=60),
        "snippet": text[:2000],
    }


def main() -> int:
    route_results = [analyze(url) for url in ROUTES]

    # Follow iframe/widget/fixture/api URLs discovered from route pages.
    discovered = []
    for result in route_results:
        for group in ["iframes", "interesting"]:
            for url in result["urls"].get(group, []):
                low = url.casefold()
                if any(token in low for token in ["fixture", "spiel", "match", "event", "schedule", "api", "graphql", "gameday", "widget"]):
                    discovered.append(url)

    discovered.extend(DIRECT_WIDGET_CANDIDATES)
    discovered = unique(discovered)[:80]

    discovered_results = []
    for url in discovered:
        discovered_results.append(analyze(url))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "dyn_fixtures_probe",
        "routes_checked": ROUTES,
        "discovered_checked": discovered,
        "route_results": route_results,
        "discovered_results": discovered_results,
    }

    (OUT_DIR / "dyn-fixtures-probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = []
    lines.append(f"DYN fixtures probe generated at {payload['generated_at']}")
    lines.append(f"routes_checked: {len(route_results)}")
    lines.append(f"discovered_checked: {len(discovered_results)}")
    lines.append("")

    def write_section(title: str, results: list[dict]):
        lines.append(title)
        for res in results:
            lines.append("=" * 90)
            lines.append(f"URL: {res['url']}")
            lines.append(f"OK: {res['ok']} STATUS: {res['status']} BYTES: {res['bytes']} CONTENT: {res['content_type']} ERROR: {res['error']}")
            lines.append(f"final_url: {res['final_url']}")
            lines.append(
                f"text_length={res['text_length']} date_de_text={res['date_de_text']} "
                f"date_de_raw={res['date_de_raw']} time_text={res['time_text']} "
                f"time_raw={res['time_raw']} iso_raw={res['iso_raw']} key_raw={res['key_raw']}"
            )

            lines.append("IFRAMES:")
            for u in res["urls"]["iframes"][:30]:
                lines.append(f"  {u}")

            lines.append("INTERESTING URLs:")
            for u in res["urls"]["interesting"][:50]:
                lines.append(f"  {u}")

            lines.append("DATE contexts:")
            for ctx in res["contexts_dates"][:10]:
                lines.append(f"  - {ctx}")

            lines.append("TIME contexts:")
            for ctx in res["contexts_times"][:10]:
                lines.append(f"  - {ctx}")

            lines.append("ISO contexts:")
            for ctx in res["contexts_iso"][:10]:
                lines.append(f"  - {ctx}")

            lines.append("KEY contexts:")
            for ctx in res["contexts_keys"][:18]:
                lines.append(f"  - {ctx}")

            lines.append("SNIPPET:")
            lines.append(res["snippet"][:1400])
            lines.append("")

    write_section("ROUTE RESULTS", route_results)
    write_section("DISCOVERED/WIDGET RESULTS", discovered_results)

    (OUT_DIR / "dyn-fixtures-probe.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"Wrote {OUT_DIR / 'dyn-fixtures-probe.txt'}")
    print(f"Wrote {OUT_DIR / 'dyn-fixtures-probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
