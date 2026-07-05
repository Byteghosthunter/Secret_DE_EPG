#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from html import unescape
import json
import re
import urllib.error
import urllib.request


OUT_DIR = Path("probe-results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

PROVIDERS = {
    "dyn_programm": {
        "url": "https://www.dyn.sport/deinsender/programm/",
        "group": "dyn.sport.*",
        "keywords": ["dyn", "programm", "handball", "basketball", "volleyball", "tischtennis", "hockey", "spielplan"],
    },
    "dyn_handball_spielplaene": {
        "url": "https://www.dyn.sport/deinsender/handball-spielplaene/",
        "group": "dyn.sport.*",
        "keywords": ["handball", "bundesliga", "spielpläne", "spielplan", "hbl", "dhb", "ehf"],
    },
    "dyn_basketball_spielplaene": {
        "url": "https://www.dyn.sport/deinsender/basketball-spielplane/",
        "group": "dyn.sport.*",
        "keywords": ["basketball", "bbl", "spielpläne", "spielplan", "pokal", "champions league"],
    },
    "dyn_volleyball_spielplaene": {
        "url": "https://www.dyn.sport/deinsender/volleyball-spielplaene/",
        "group": "dyn.sport.*",
        "keywords": ["volleyball", "bundesliga", "spielpläne", "spielplan"],
    },
    "dyn_tischtennis_spielplan": {
        "url": "https://www.dyn.sport/deinsender/tischtennis-spielplaene/",
        "group": "dyn.sport.*",
        "keywords": ["tischtennis", "spielplan", "bundesliga", "dyn"],
    },
    "ufc_events": {
        "url": "https://www.ufc.com/events",
        "group": "ufcfightpass.*",
        "keywords": ["ufc", "fight", "fight night", "main card", "prelims", "event"],
    },
    "ufc_fightpass_schedule": {
        "url": "https://welcome.ufcfightpass.com/schedule",
        "group": "ufcfightpass.*",
        "keywords": ["ufc", "fight pass", "schedule", "event", "live"],
    },
    "eurosport_schedule": {
        "url": "https://www.eurosport.de/watch/schedule.shtml",
        "group": "eurosport.extra.* / discovery.extra.*",
        "keywords": ["eurosport", "schedule", "programm", "sport", "live"],
    },
    "rtlplus_live_events": {
        "url": "https://plus.rtl.de/live-events",
        "group": "rtlplus.sport.*",
        "keywords": ["rtl", "live", "sport", "event", "europa league", "conference league", "nfl"],
    },
    "rtlplus_sport": {
        "url": "https://plus.rtl.de/rtlplus-root/sport-main-root-service-f_6",
        "group": "rtlplus.sport.*",
        "keywords": ["rtl", "sport", "live", "uefa", "europa league", "conference league", "nfl"],
    },
    "prime_video_sports_de": {
        "url": "https://www.amazon.de/-/en/gp/video/sports",
        "group": "amazon.live.* / prime.event.*",
        "keywords": ["prime", "sports", "live", "upcoming", "event", "champions league"],
    },
    "prime_video_sports_global": {
        "url": "https://www.primevideo.com/-/de/sports",
        "group": "amazon.live.* / prime.event.*",
        "keywords": ["prime", "sport", "live", "upcoming", "event"],
    },
}


def fetch(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Secret_DE_EPG Provider Probe",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Connection": "close",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read(900000)
            return {
                "ok": True,
                "http_status": getattr(resp, "status", None),
                "final_url": resp.geturl(),
                "content_type": resp.headers.get("content-type", ""),
                "bytes": len(raw),
                "body": raw.decode("utf-8", errors="replace"),
                "error": "",
            }
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(120000).decode("utf-8", errors="replace")
        except Exception:
            pass
        return {
            "ok": False,
            "http_status": exc.code,
            "final_url": url,
            "content_type": exc.headers.get("content-type", "") if exc.headers else "",
            "bytes": len(body.encode("utf-8", errors="replace")),
            "body": body,
            "error": f"HTTPError: {exc.code} {exc.reason}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "http_status": None,
            "final_url": url,
            "content_type": "",
            "bytes": 0,
            "body": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def normalize_text(html: str) -> str:
    text = re.sub(r"(?is)<script\b.*?</script>", " ", html)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def analyze(name: str, provider: dict, fetched: dict) -> dict:
    body = fetched.get("body", "") or ""
    body_l = body.casefold()
    text = normalize_text(body)

    keyword_counts = {
        kw: body_l.count(kw.casefold())
        for kw in provider.get("keywords", [])
    }

    hints = {
        "script_tags": len(re.findall(r"(?i)<script\b", body)),
        "__NEXT_DATA__": body.count("__NEXT_DATA__"),
        "application_ld_json": len(re.findall(r"(?i)application/ld\+json", body)),
        "json_like_dates": len(re.findall(r"\b20[2-9][0-9]-[01][0-9]-[0-3][0-9]\b", body)),
        "german_date_like": len(re.findall(r"\b[0-3]?[0-9]\.(?:[01]?[0-9])\.(?:20[2-9][0-9])?\b", body)),
        "time_like": len(re.findall(r"\b[0-2]?[0-9]:[0-5][0-9]\b", body)),
    }

    useful_score = 0
    if fetched.get("http_status") == 200:
        useful_score += 1
    if any(count > 0 for count in keyword_counts.values()):
        useful_score += 1
    if hints["json_like_dates"] or hints["german_date_like"]:
        useful_score += 1
    if hints["time_like"]:
        useful_score += 1
    if len(text) > 800:
        useful_score += 1

    if fetched.get("http_status") in (401, 403):
        verdict = "blocked_or_forbidden"
    elif not fetched.get("ok"):
        verdict = "failed"
    elif useful_score >= 4:
        verdict = "promising"
    elif useful_score >= 2:
        verdict = "reachable_but_unclear"
    else:
        verdict = "weak_or_js_only"

    return {
        "name": name,
        "url": provider["url"],
        "target_group": provider["group"],
        "ok": fetched.get("ok"),
        "http_status": fetched.get("http_status"),
        "final_url": fetched.get("final_url"),
        "content_type": fetched.get("content_type"),
        "bytes": fetched.get("bytes"),
        "error": fetched.get("error"),
        "keyword_counts": keyword_counts,
        "hints": hints,
        "useful_score": useful_score,
        "verdict": verdict,
        "snippet": text[:1600],
    }


def main() -> int:
    results = []

    for name, provider in PROVIDERS.items():
        fetched = fetch(provider["url"])
        results.append(analyze(name, provider, fetched))

    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "generated_at": generated_at,
        "note": "Probe only. A provider is not supported until a real scraper extracts future events with start/stop times.",
        "results": results,
    }

    (OUT_DIR / "provider-probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = [
        f"Provider probe generated at {generated_at}",
        "",
        "Legend:",
        "  promising = reachable and has some schedule-like signals",
        "  reachable_but_unclear = reachable, but real extraction still needs work",
        "  weak_or_js_only = mostly static shell/JS app, no obvious event data",
        "  blocked_or_forbidden = HTTP 401/403 or similar",
        "",
    ]

    for item in results:
        lines.append("=" * 90)
        lines.append(f"PROVIDER: {item['name']}")
        lines.append(f"TARGET GROUP: {item['target_group']}")
        lines.append(f"URL: {item['url']}")
        lines.append(f"HTTP: {item['http_status']}")
        lines.append(f"FINAL URL: {item['final_url']}")
        lines.append(f"CONTENT-TYPE: {item['content_type']}")
        lines.append(f"BYTES: {item['bytes']}")
        lines.append(f"VERDICT: {item['verdict']}")
        if item["error"]:
            lines.append(f"ERROR: {item['error']}")
        lines.append("KEYWORDS:")
        for kw, count in item["keyword_counts"].items():
            lines.append(f"  {kw}: {count}")
        lines.append("HINTS:")
        for key, value in item["hints"].items():
            lines.append(f"  {key}: {value}")
        lines.append("SNIPPET:")
        lines.append(item["snippet"])
        lines.append("")

    (OUT_DIR / "provider-probe.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"Wrote {OUT_DIR / 'provider-probe.txt'}")
    print(f"Wrote {OUT_DIR / 'provider-probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
