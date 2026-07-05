#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
DYN ContentDesk API probe for Secret_DE_EPG.

Safe standalone probe:
- Does NOT modify public/sports-events.xml.xz.
- Does NOT deploy GitHub Pages.
- Creates dyn-contentdesk-results/dyn-contentdesk-probe.json and .txt as an Actions artifact.
'''

from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from pathlib import Path
import json
import re
import urllib.error
import urllib.request


OUT_DIR = Path("dyn-contentdesk-results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

WIDGET_JS = "https://widgets.desk.dyn.sport/assets/index-Ckqv9Q4x.js"

COMPETITIONS = {
    "handball": {
        "id": "Q7Zk5rLkdJxBZgaXExX7Vb",
        "scope": "64994",
        "slug": "Daikin_Handball_Bundesliga_64994",
        "name": "Daikin Handball Bundesliga",
    },
    "basketball": {
        "id": "NCmk4W4gjZ5PcD9y7K3hiZ",
        "scope": "65002",
        "slug": "easyCredit_BBL_65002",
        "name": "easyCredit BBL",
    },
    "volleyball": {
        "id": "LpS8QMGJSs4D4XiyM3ULZo",
        "scope": "",
        "slug": "",
        "name": "Volleyball",
    },
    "tabletennis": {
        "id": "8HKTtNzWTZJBZii8ZSKh5h",
        "scope": "79806",
        "slug": "79806",
        "name": "Tischtennis",
    },
}

BASES = [
    "https://api.contentdesk.sport/public",
    "https://widgets.contentdesk.sport",
    "https://api.contentdesk.sport",
]

BASE_CONTEXT_TERMS = [
    "api.contentdesk.sport/public",
    "widgets.contentdesk.sport",
    "api.contentdesk.sport/image",
    "matchups/:sport/:competitionId",
    "matchups",
    "competitionId",
    "gamedayId",
    "homeTeam",
    "awayTeam",
    "startDate",
    "startTime",
    "fixture",
    "fixtures",
]

KEY_RE = re.compile(
    r"(?i)(api\.contentdesk|widgets\.contentdesk|matchups|fixtures|fixture|competitionId|competitionID|gamedayId|gameDay|"
    r"homeTeam|awayTeam|teamName|startDate|startTime|scheduled|schedule|event|events|public|image|profile|standalone)"
)
URL_RE = re.compile(r"(?i)(https?://[^\"'`<>\s)]+|/[A-Za-z0-9_./?=&:%+-]*(?:public|matchups|fixtures|fixture|competition|gameday|event|events|team|teams|profile|image|api)[A-Za-z0-9_./?=&:%+-]*)")
PATH_RE = re.compile(r"[\"'`](/?[A-Za-z0-9_./?=&:%{}:\-]*(?:matchups|fixtures|fixture|competition|gameday|event|events|team|teams|profile|image|public)[A-Za-z0-9_./?=&:%{}:\-]*)[\"'`]")
ISO_RE = re.compile(r"20[2-9][0-9]-[01]\d-[0-3]\d(?:T[0-2]\d:[0-5]\d(?::[0-5]\d)?(?:\.\d+)?Z?)?")
DE_DATE_RE = re.compile(r"\b[0-3]?\d\.[01]?\d\.(?:20[2-9][0-9]|\d{2})\b")
TIME_RE = re.compile(r"\b[0-2]?\d:[0-5]\d\b")


def fetch(url: str, *, method: str = "GET", body: bytes | None = None, headers: dict | None = None, limit: int = 5_000_000) -> tuple[str, dict]:
    final_headers = {
        "User-Agent": "Mozilla/5.0 Secret_DE_EPG DYN ContentDesk Probe",
        "Accept": "application/json,text/plain,text/html,application/xhtml+xml,application/xml,text/javascript,*/*",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Origin": "https://widgets.desk.dyn.sport",
        "Referer": "https://widgets.desk.dyn.sport/matchups/handball/Q7Zk5rLkdJxBZgaXExX7Vb?/profile",
    }
    if headers:
        final_headers.update(headers)

    info = {
        "url": url,
        "method": method,
        "ok": False,
        "status": None,
        "error": "",
        "final_url": url,
        "content_type": "",
        "bytes": 0,
    }

    req = urllib.request.Request(url, data=body, headers=final_headers, method=method)

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
        response_body = ""
        try:
            response_body = exc.read(1_000_000).decode("utf-8", errors="replace")
        except Exception:
            pass
        info["status"] = exc.code
        info["error"] = f"HTTPError {exc.code}: {exc.reason}"
        info["content_type"] = exc.headers.get("content-type", "") if exc.headers else ""
        info["bytes"] = len(response_body.encode("utf-8", errors="replace"))
        return response_body, info
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        return "", info


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


def contexts(blob: str, regex: re.Pattern, radius: int = 500, limit: int = 120) -> list[str]:
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


def extract_strings_and_paths(js: str) -> dict:
    urls = []
    for m in URL_RE.findall(js):
        urls.append(m)

    paths = []
    for m in PATH_RE.findall(js):
        paths.append(m)

    filtered = []
    for x in unique(urls + paths):
        low = x.casefold()
        if any(term in low for term in [
            "contentdesk", "matchup", "fixture", "competition", "gameday",
            "event", "events", "team", "profile", "image", "public"
        ]):
            filtered.append(x)

    return {
        "urls": unique(urls)[:400],
        "paths": unique(paths)[:400],
        "filtered": filtered[:600],
    }


def substitute_path(path: str, sport: str, data: dict) -> str:
    p = path
    replacements = {
        ":sport": sport,
        "{sport}": sport,
        ":competitionId": data["id"],
        "{competitionId}": data["id"],
        ":competitionID": data["id"],
        "{competitionID}": data["id"],
        ":id": data["id"],
        "{id}": data["id"],
        ":scope": data["scope"],
        "{scope}": data["scope"],
        ":gamedayId": data["id"],
        "{gamedayId}": data["id"],
    }
    for k, v in replacements.items():
        p = p.replace(k, v)
    return p


def candidate_urls_from_known_patterns() -> list[str]:
    urls = []

    endpoint_patterns = [
        "/matchups/{sport}/{id}",
        "/matchups/{sport}/{id}/profile",
        "/matchups/{sport}/{id}?profile",
        "/matchups/{sport}/{id}?standalone=true",
        "/matchups/{sport}/{id}?matchLinkPath=https%3A%2F%2Fwww.dyn.sport%2Fmatch%2F%7BgamedayId%7D",
        "/widgets/matchups/{sport}/{id}",
        "/widgets/matchups/{sport}/{id}/profile",
        "/fixture/{sport}/{id}",
        "/fixtures/{sport}/{id}",
        "/fixtures/{sport}/{id}/profile",
        "/fixtures/{sport}/{scope}",
        "/fixtures/{sport}/{slug}",
        "/competitions/{id}",
        "/competitions/{id}/fixtures",
        "/competitions/{id}/matchups",
        "/competitions/{scope}",
        "/competitions/{scope}/fixtures",
        "/competition/{id}",
        "/competition/{id}/fixtures",
        "/competition/{scope}",
        "/competition/{scope}/fixtures",
        "/events/{id}",
        "/events/{scope}",
        "/events?competitionId={id}",
        "/events?competitionId={scope}",
        "/events?sport={sport}&competitionId={id}",
        "/fixtures?competitionId={id}",
        "/fixtures?competitionId={scope}",
        "/fixtures?sport={sport}&competitionId={id}",
        "/matchups?competitionId={id}",
        "/matchups?competitionId={scope}",
        "/matchups?sport={sport}&competitionId={id}",
        "/public/matchups/{sport}/{id}",
        "/public/fixtures/{sport}/{id}",
        "/public/events?competitionId={id}",
        "/public/competition/{id}",
        "/public/competitions/{id}",
    ]

    for sport, data in COMPETITIONS.items():
        for base in BASES:
            for pattern in endpoint_patterns:
                p = pattern.format(
                    sport=sport,
                    id=data["id"],
                    scope=data["scope"],
                    slug=data["slug"],
                )
                if p.endswith("/"):
                    continue
                urls.append(base.rstrip("/") + "/" + p.lstrip("/"))

    return unique(urls)


def candidate_urls_from_js(js: str) -> list[str]:
    extracted = extract_strings_and_paths(js)
    urls = []
    for item in extracted["filtered"]:
        for sport, data in COMPETITIONS.items():
            p = substitute_path(item, sport, data)
            if p.startswith("http"):
                urls.append(p)
            else:
                for base in BASES:
                    urls.append(base.rstrip("/") + "/" + p.lstrip("/"))
    return unique(urls)


def try_json_summary(text: str) -> dict:
    summary = {
        "is_json": False,
        "top_type": "",
        "top_keys": [],
        "list_len": None,
        "first_item_keys": [],
        "interesting_values": [],
    }
    try:
        data = json.loads(text)
    except Exception:
        return summary

    summary["is_json"] = True
    summary["top_type"] = type(data).__name__

    if isinstance(data, dict):
        summary["top_keys"] = list(data.keys())[:80]
        roots = [data]
    elif isinstance(data, list):
        summary["list_len"] = len(data)
        roots = data[:10]
        if data and isinstance(data[0], dict):
            summary["first_item_keys"] = list(data[0].keys())[:80]
    else:
        roots = []

    interesting = []
    wanted = {
        "startDate", "startTime", "scheduledStart", "gamedayId", "gameDayId", "eventId",
        "homeTeam", "awayTeam", "teamName", "name", "title", "competition", "competitionId",
        "fixtures", "events", "matches", "matchups", "date", "time"
    }

    def walk(obj, depth=0):
        if depth > 4 or len(interesting) >= 120:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in wanted or any(w.casefold() in str(k).casefold() for w in wanted):
                    interesting.append({str(k): str(v)[:300]})
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(obj, list):
            for it in obj[:15]:
                walk(it, depth + 1)

    for root in roots:
        walk(root)

    summary["interesting_values"] = interesting[:120]
    return summary


def analyze_response(text: str, info: dict) -> dict:
    return {
        **info,
        "json_summary": try_json_summary(text),
        "iso_count": len(ISO_RE.findall(text)),
        "de_date_count": len(DE_DATE_RE.findall(text)),
        "time_count": len(TIME_RE.findall(text)),
        "key_count": len(KEY_RE.findall(text)),
        "contexts_iso": contexts(text, ISO_RE, limit=20),
        "contexts_de_date": contexts(text, DE_DATE_RE, limit=20),
        "contexts_time": contexts(text, TIME_RE, limit=20),
        "contexts_keys": contexts(text, KEY_RE, limit=40),
        "snippet": text[:2500],
    }


def main() -> int:
    js, js_info = fetch(WIDGET_JS)
    extracted = extract_strings_and_paths(js)

    js_analysis = {
        **js_info,
        "filtered_count": len(extracted["filtered"]),
        "filtered_strings": extracted["filtered"][:300],
        "contexts_key": contexts(js, KEY_RE, limit=120),
        "contexts_base_terms": {
            term: contexts(js, re.compile(re.escape(term), re.I), limit=30)
            for term in BASE_CONTEXT_TERMS
        },
    }

    candidates = []
    candidates.extend(candidate_urls_from_known_patterns())
    candidates.extend(candidate_urls_from_js(js))
    candidates = unique(candidates)

    filtered_candidates = []
    for url in candidates:
        low = url.casefold()
        if any(ext in low for ext in [".png", ".jpg", ".jpeg", ".svg", ".woff", ".woff2", ".css", ".ico"]):
            continue
        if len(url) > 450:
            continue
        filtered_candidates.append(url)

    filtered_candidates = unique(filtered_candidates)[:240]

    results = []
    for url in filtered_candidates:
        text, info = fetch(url)
        results.append(analyze_response(text, info))

    post_results = []
    post_bodies = []
    for sport, data in COMPETITIONS.items():
        post_bodies.extend([
            ("POST", "https://api.contentdesk.sport/public/matchups", {"sport": sport, "competitionId": data["id"]}),
            ("POST", "https://api.contentdesk.sport/public/fixtures", {"sport": sport, "competitionId": data["id"]}),
            ("POST", "https://widgets.contentdesk.sport/matchups", {"sport": sport, "competitionId": data["id"]}),
            ("POST", "https://widgets.contentdesk.sport/fixtures", {"sport": sport, "competitionId": data["id"]}),
        ])

    for method, url, payload in post_bodies[:40]:
        body = json.dumps(payload).encode("utf-8")
        text, info = fetch(
            url,
            method=method,
            body=body,
            headers={"Content-Type": "application/json"},
        )
        info["post_payload"] = payload
        post_results.append(analyze_response(text, info))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "dyn_contentdesk_probe",
        "widget_js": WIDGET_JS,
        "js_analysis": js_analysis,
        "candidate_count": len(filtered_candidates),
        "candidate_urls": filtered_candidates,
        "candidate_results": results,
        "post_results": post_results,
    }

    (OUT_DIR / "dyn-contentdesk-probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = []
    lines.append(f"DYN ContentDesk probe generated at {payload['generated_at']}")
    lines.append(f"widget_js_ok: {js_info['ok']} status={js_info['status']} bytes={js_info['bytes']}")
    lines.append(f"filtered_js_strings: {js_analysis['filtered_count']}")
    lines.append(f"candidate_urls_checked: {len(results)}")
    lines.append(f"post_urls_checked: {len(post_results)}")
    lines.append("")

    lines.append("IMPORTANT JS STRINGS")
    for s in js_analysis["filtered_strings"][:160]:
        lines.append(f"  {s}")

    lines.append("")
    lines.append("BASE TERM CONTEXTS")
    for term, ctxs in js_analysis["contexts_base_terms"].items():
        lines.append("=" * 90)
        lines.append(f"TERM: {term} count={len(ctxs)}")
        for ctx in ctxs[:10]:
            lines.append(f"  - {ctx}")

    def write_results(title: str, entries: list[dict], max_entries: int = 300):
        lines.append("")
        lines.append(title)
        for res in entries[:max_entries]:
            show = (
                res["ok"]
                or res["json_summary"]["is_json"]
                or res["iso_count"] > 0
                or res["key_count"] > 0
                or (res["status"] not in (404, 405, None))
            )
            if not show:
                continue

            lines.append("=" * 90)
            lines.append(f"URL: {res['url']}")
            if "post_payload" in res:
                lines.append(f"POST_PAYLOAD: {res['post_payload']}")
            lines.append(f"OK: {res['ok']} STATUS: {res['status']} BYTES: {res['bytes']} CONTENT: {res['content_type']} ERROR: {res['error']}")
            lines.append(f"final_url: {res['final_url']}")
            lines.append(
                f"is_json={res['json_summary']['is_json']} top_type={res['json_summary']['top_type']} "
                f"top_keys={res['json_summary']['top_keys']} list_len={res['json_summary']['list_len']} "
                f"first_item_keys={res['json_summary']['first_item_keys']}"
            )
            if res["json_summary"]["interesting_values"]:
                lines.append("JSON interesting values:")
                for item in res["json_summary"]["interesting_values"][:30]:
                    lines.append(f"  {item}")

            lines.append(f"iso={res['iso_count']} de_date={res['de_date_count']} time={res['time_count']} key={res['key_count']}")
            lines.append("ISO contexts:")
            for ctx in res["contexts_iso"][:8]:
                lines.append(f"  - {ctx}")
            lines.append("DATE contexts:")
            for ctx in res["contexts_de_date"][:8]:
                lines.append(f"  - {ctx}")
            lines.append("TIME contexts:")
            for ctx in res["contexts_time"][:8]:
                lines.append(f"  - {ctx}")
            lines.append("KEY contexts:")
            for ctx in res["contexts_keys"][:16]:
                lines.append(f"  - {ctx}")

            snippet = res["snippet"].replace("\n", "\\n")
            lines.append("SNIPPET:")
            lines.append(snippet[:1600])

    write_results("GET CANDIDATE RESULTS", results)
    write_results("POST CANDIDATE RESULTS", post_results)

    (OUT_DIR / "dyn-contentdesk-probe.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"Wrote {OUT_DIR / 'dyn-contentdesk-probe.txt'}")
    print(f"Wrote {OUT_DIR / 'dyn-contentdesk-probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
