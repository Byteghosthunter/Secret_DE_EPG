#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("public/provider-probe.txt")
OUT.parent.mkdir(parents=True, exist_ok=True)

URLS = {
    "dyn": "https://www.dyn.sport/deinsender/programm/",
    "ufc_events": "https://www.ufc.com/events",
    "ufc_fightpass": "https://welcome.ufcfightpass.com/schedule",
    "eurosport": "https://www.eurosport.de/watch/schedule.shtml",
    "rtlplus_live_events": "https://plus.rtl.de/live-events",
    "rtlplus_sport": "https://plus.rtl.de/rtlplus-root/sport-main-root-service-f_6",
    "prime_video_sports_de": "https://www.amazon.de/-/en/gp/video/sports",
    "prime_video_sports": "https://www.primevideo.com/-/de/sports",
}

KEYWORDS = {
    "dyn": ["handball", "basketball", "volleyball", "tischtennis", "hockey", "dyn"],
    "ufc_events": ["ufc", "fight pass", "main card", "prelims", "watch"],
    "ufc_fightpass": ["schedule", "fight", "ufc", "pass"],
    "eurosport": ["schedule", "programm", "eurosport", "sport"],
    "rtlplus_live_events": ["live", "sport", "bundesliga", "nfl", "oktogan", "europa league"],
    "rtlplus_sport": ["sport", "uefa", "europa league", "conference league", "nfl"],
    "prime_video_sports_de": ["sports", "live", "upcoming", "champions league", "event"],
    "prime_video_sports": ["sport", "live", "upcoming", "event"],
}

def fetch(url: str) -> tuple[int | None, str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Secret_DE_EPG Provider Probe",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json,*/*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            status = getattr(resp, "status", None)
            ctype = resp.headers.get("content-type", "")
            body = resp.read(500000).decode("utf-8", errors="replace")
            return status, ctype, body
    except Exception as exc:
        return None, "", f"ERROR: {type(exc).__name__}: {exc}"

def count_keywords(name: str, body: str) -> dict[str, int]:
    body_l = body.casefold()
    return {kw: body_l.count(kw.casefold()) for kw in KEYWORDS.get(name, [])}

def main() -> int:
    lines = []
    lines.append(f"Provider probe generated at {datetime.now(timezone.utc).isoformat()}")
    lines.append("")

    for name, url in URLS.items():
        status, ctype, body = fetch(url)
        lines.append("=" * 80)
        lines.append(f"PROVIDER: {name}")
        lines.append(f"URL: {url}")
        lines.append(f"HTTP: {status}")
        lines.append(f"CONTENT-TYPE: {ctype}")
        lines.append(f"BYTES_READ: {len(body.encode('utf-8', errors='replace'))}")

        if body.startswith("ERROR:"):
            lines.append(body)
            lines.append("")
            continue

        kws = count_keywords(name, body)
        lines.append("KEYWORDS:")
        for kw, count in kws.items():
            lines.append(f"  {kw}: {count}")

        # grober Hinweis, ob Daten eher im HTML stehen oder JS-App leer lädt
        script_count = len(re.findall(r"<script\b", body, flags=re.I))
        json_like = body.count("__NEXT_DATA__") + body.count("application/ld+json")
        lines.append(f"SCRIPT_TAGS: {script_count}")
        lines.append(f"JSON_HINTS: {json_like}")

        clean = re.sub(r"\s+", " ", body)
        lines.append("SNIPPET:")
        lines.append(clean[:1200])
        lines.append("")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {OUT}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
