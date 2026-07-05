#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DYN matchups probe for Secret_DE_EPG.

Safe standalone probe:
- Does NOT modify public/sports-events.xml.xz.
- Does NOT deploy GitHub Pages.
- Creates dyn-matchups-results/dyn-matchups-probe.json and .txt as an Actions artifact.

Goal:
DYN deep probe showed that useful routes are:
- /matchups/<sport>/<id>?matchLinkPath=...
- /competition/<id-or-name>
- production-static app scripts

This probe follows matchups routes and tries to extract:
- startDate / startTime / scheduledStartTime
- gamedayId / eventId
- homeTeam / awayTeam
- generated /match/<gamedayId> links
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, quote
import json
import re
import urllib.error
import urllib.request


OUT_DIR = Path("dyn-matchups-results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED_PAGES = [
    "https://www.dyn.sport/deinsender/handball-spielplaene/",
    "https://www.dyn.sport/deinsender/basketball-spielplane/",
    "https://www.dyn.sport/deinsender/volleyball-spielplaene/",
    "https://www.dyn.sport/deinsender/tischtennis-spielplaene/",
]

MANUAL_MATCHUPS = [
    "https://www.dyn.sport/matchups/handball/Q7Zk5rLkdJxBZgaXExX7Vb?matchLinkPath=https%3A%2F%2Fwww.dyn.sport%2Fmatch%2F%7BgamedayId%7D",
    "https://www.dyn.sport/matchups/basketball/NCmk4W4gjZ5PcD9y7K3hiZ?matchLinkPath=https%3A%2F%2Fwww.dyn.sport%2Fmatch%2F%7BgamedayId%7D",
    "https://www.dyn.sport/matchups/volleyball/LpS8QMGJSs4D4XiyM3ULZo?matchLinkPath=https%3A%2F%2Fwww.dyn.sport%2Fmatch%2F%7BgamedayId%7D",
    "https://www.dyn.sport/matchups/tabletennis/8HKTtNzWTZJBZii8ZSKh5h?matchLinkPath=https%3A%2F%2Fwww.dyn.sport%2Fmatch%2F%7BgamedayId%7D",
]

COMPETITIONS = [
    "https://www.dyn.sport/competition/Daikin_Handball_Bundesliga_64994",
    "https://www.dyn.sport/competition/easyCredit_BBL_65002",
    "https://www.dyn.sport/competition/79806",
]

MATCHUPS_RE = re.compile(r"https://www\.dyn\.sport/matchups/[A-Za-z0-9/_-]+(?:\?matchLinkPath=[^\"'<>\s]+)?")
COMPETITION_RE = re.compile(r"https://www\.dyn\.sport/competition/[A-Za-z0-9_%.-]+")
EVENT_RE = re.compile(r"https://www\.dyn\.sport/event/[A-Za-z0-9_%!().-]+")
MATCH_RE = re.compile(r"https://www\.dyn\.sport/match/[A-Za-z0-9_%.-]+")
ISO_DATE_RE = re.compile(r"20[2-9][0-9]-[01]\d-[0-3]\d(?:T[0-2]\d:[0-5]\d(?::[0-5]\d)?(?:\.\d+)?Z?)?")
GERMAN_DATE_RE = re.compile(r"\b[0-3]?\d\.[01]?\d\.(?:20[2-9][0-9]|\d{2})\b")
TIME_RE = re.compile(r"\b[0-2]?\d:[0-5]\d\b")
KEY_RE = re.compile(r"(?i)(startDate|startTime|scheduledStart|gamedayId|eventId|fixture|fixtures|homeTeam|awayTeam|teamName|competition|broadcast|airing|schedule|matchup|matchups|game)")


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
            "User-Agent": "Mozilla/5.0 Secret_DE_EPG DYN Matchups Probe",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json,text/javascript,*/*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Referer": "https://www.dyn.sport/deinsender/handball-spielplaene/",
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
            body = exc.read(500_000).decode("utf-8", errors="replace")
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
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def extract_urls(blob: str) -> dict:
    return {
        "matchups": unique(MATCHUPS_RE.findall(blob)),
        "competitions": unique(COMPETITION_RE.findall(blob)),
        "events": unique(EVENT_RE.findall(blob)),
        "matches": unique(MATCH_RE.findall(blob)),
    }


def contexts(blob: str, regex: re.Pattern, radius: int = 360, limit: int = 80) -> list[str]:
    out = []
    for m in regex.finditer(blob):
        s = max(0, m.start() - radius)
        e = min(len(blob), m.end() + radius)
        ctx = blob[s:e]
        ctx = unescape(ctx)
        ctx = ctx.replace("\\u0026", "&")
        ctx = re.sub(r"\s+", " ", ctx)
        out.append(ctx)
        if len(out) >= limit:
            break
    return out


def try_parse_jsonish_objects(blob: str) -> list[dict]:
    """
    Conservative extraction: not a full JS parser.
    Finds small JSON-like object contexts around important keys so we can inspect structure.
    """
    objects = []
    seen = set()

    for m in KEY_RE.finditer(blob):
        pos = m.start()
        left = blob.rfind("{", 0, pos)
        right = blob.find("}", pos)
        if left == -1 or right == -1:
            continue
        if right - left > 5000:
            continue
        raw = blob[left:right + 1]
        key = raw[:300]
        if key in seen:
            continue
        seen.add(key)

        clean = unescape(raw).replace("\\u0026", "&")
        clean = re.sub(r"\s+", " ", clean)

        objects.append({
            "key": m.group(1),
            "raw": clean[:2500],
        })
        if len(objects) >= 80:
            break

    return objects


def analyze_url(url: str) -> dict:
    body, info = fetch(url)
    text = textify(body)
    urls = extract_urls(body)

    result = {
        **info,
        "text_length": len(text),
        "iso_date_count": len(ISO_DATE_RE.findall(body)),
        "german_date_count_text": len(GERMAN_DATE_RE.findall(text)),
        "german_date_count_raw": len(GERMAN_DATE_RE.findall(body)),
        "time_count_text": len(TIME_RE.findall(text)),
        "time_count_raw": len(TIME_RE.findall(body)),
        "key_count": len(KEY_RE.findall(body)),
        "urls": {k: v[:100] for k, v in urls.items()},
        "contexts_iso_dates": contexts(body, ISO_DATE_RE, limit=30),
        "contexts_german_dates": contexts(body, GERMAN_DATE_RE, limit=30),
        "contexts_keys": contexts(body, KEY_RE, limit=50),
        "objects": try_parse_jsonish_objects(body),
        "snippet_text": text[:1600],
    }

    return result


def main() -> int:
    discovered_matchups = []
    discovered_competitions = []
    seed_results = []

    for page in SEED_PAGES:
        body, info = fetch(page)
        urls = extract_urls(body)
        seed_results.append({
            **info,
            "matchups_found": urls["matchups"],
            "competitions_found": urls["competitions"],
            "events_found": urls["events"][:40],
            "matches_found": urls["matches"][:40],
            "snippet": textify(body)[:1000],
        })
        discovered_matchups.extend(urls["matchups"])
        discovered_competitions.extend(urls["competitions"])

    matchups = unique(MANUAL_MATCHUPS + discovered_matchups)[:80]
    competitions = unique(COMPETITIONS + discovered_competitions)[:30]

    matchup_results = [analyze_url(url) for url in matchups]
    competition_results = [analyze_url(url) for url in competitions]

    # Also follow discovered event/match links from competition pages, limited.
    detail_urls = []
    for result in competition_results + matchup_results:
        detail_urls.extend(result["urls"].get("events", []))
        detail_urls.extend(result["urls"].get("matches", []))
    detail_urls = unique(detail_urls)[:40]
    detail_results = [analyze_url(url) for url in detail_urls]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "dyn_matchups_probe",
        "seed_pages": seed_results,
        "matchups_checked": matchups,
        "competitions_checked": competitions,
        "detail_urls_checked": detail_urls,
        "matchup_results": matchup_results,
        "competition_results": competition_results,
        "detail_results": detail_results,
    }

    (OUT_DIR / "dyn-matchups-probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = []
    lines.append(f"DYN matchups probe generated at {payload['generated_at']}")
    lines.append("")
    lines.append(f"seed_pages: {len(seed_results)}")
    lines.append(f"matchups_checked: {len(matchups)}")
    lines.append(f"competitions_checked: {len(competitions)}")
    lines.append(f"detail_urls_checked: {len(detail_urls)}")
    lines.append("")

    lines.append("SEED DISCOVERY")
    for seed in seed_results:
        lines.append("=" * 90)
        lines.append(f"URL: {seed['url']}")
        lines.append(f"OK: {seed['ok']} STATUS: {seed['status']} BYTES: {seed['bytes']} ERROR: {seed['error']}")
        lines.append(f"matchups_found={len(seed['matchups_found'])} competitions_found={len(seed['competitions_found'])} events_found={len(seed['events_found'])} matches_found={len(seed['matches_found'])}")
        for u in seed["matchups_found"][:30]:
            lines.append(f"  MATCHUP {u}")
        for u in seed["competitions_found"][:20]:
            lines.append(f"  COMPETITION {u}")

    def write_result_section(title: str, results: list[dict], max_items: int = 80):
        lines.append("")
        lines.append(title)
        for res in results[:max_items]:
            lines.append("=" * 90)
            lines.append(f"URL: {res['url']}")
            lines.append(f"OK: {res['ok']} STATUS: {res['status']} BYTES: {res['bytes']} CONTENT: {res['content_type']} ERROR: {res['error']}")
            lines.append(
                f"text_length={res['text_length']} iso_dates={res['iso_date_count']} "
                f"german_dates_text={res['german_date_count_text']} german_dates_raw={res['german_date_count_raw']} "
                f"times_text={res['time_count_text']} times_raw={res['time_count_raw']} key_count={res['key_count']}"
            )
            lines.append(f"url_counts matchups={len(res['urls']['matchups'])} competitions={len(res['urls']['competitions'])} events={len(res['urls']['events'])} matches={len(res['urls']['matches'])}")

            lines.append("Found events/matches:")
            for u in (res["urls"]["events"] + res["urls"]["matches"])[:30]:
                lines.append(f"  {u}")

            lines.append("ISO date contexts:")
            for ctx in res["contexts_iso_dates"][:10]:
                lines.append(f"  - {ctx}")

            lines.append("German date contexts:")
            for ctx in res["contexts_german_dates"][:10]:
                lines.append(f"  - {ctx}")

            lines.append("Key contexts:")
            for ctx in res["contexts_keys"][:14]:
                lines.append(f"  - {ctx}")

            lines.append("JSON-ish objects:")
            for obj in res["objects"][:8]:
                lines.append(f"  KEY={obj['key']} OBJ={obj['raw'][:1000]}")

            lines.append("Text snippet:")
            lines.append(res["snippet_text"][:1200])

    write_result_section("MATCHUP RESULTS", matchup_results)
    write_result_section("COMPETITION RESULTS", competition_results)
    write_result_section("DETAIL RESULTS", detail_results, max_items=40)

    (OUT_DIR / "dyn-matchups-probe.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"Wrote {OUT_DIR / 'dyn-matchups-probe.txt'}")
    print(f"Wrote {OUT_DIR / 'dyn-matchups-probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
