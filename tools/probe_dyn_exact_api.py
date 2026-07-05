#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DYN exact ContentDesk API probe for Secret_DE_EPG.

Safe standalone probe:
- Does NOT modify public/sports-events.xml.xz.
- Does NOT deploy GitHub Pages.
- Creates dyn-exact-api-results/dyn-exact-api-probe.json and .txt as an Actions artifact.

Why:
The previous ContentDesk probe found the exact JS API constructors:

  publicApiUrl = https://api.contentdesk.sport/public

  competition list:
    /competition/list/with-details?sport={sport}
    /competition/list/with-details?sport={sport}&gamedayId={uuid}

  competition detail:
    /competition/{uuid}/with-details

  match list:
    /sport/{sport}/match/list/with-details?competition={uuid}&stage=1&round=1

  match search:
    /match/search/with-details?
      completionStates=completed
      completionStates=running
      completionStates=scheduled
      competition={uuid}
      stage={stage}
      group={group}
      round={round}
      limit=50

This probe tests those exact routes, parses competition details, then tries all
available stages/groups/rounds and extracts possible matches/events.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
import json
import re
import urllib.error
import urllib.request


OUT_DIR = Path("dyn-exact-api-results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE = "https://api.contentdesk.sport/public"

COMPETITIONS = {
    "handball": [
        {
            "label": "Daikin Handball Bundesliga",
            "uuid": "Q7Zk5rLkdJxBZgaXExX7Vb",
            "scope": "64994",
            "default_stage": 1,
            "default_round": 1,
        },
    ],
    "basketball": [
        {
            "label": "easyCredit BBL",
            "uuid": "NCmk4W4gjZ5PcD9y7K3hiZ",
            "scope": "65002",
            "default_stage": 1,
            "default_round": 1,
        },
    ],
    "volleyball": [
        {
            "label": "Volleyball Bundesliga",
            "uuid": "LpS8QMGJSs4D4XiyM3ULZo",
            "scope": "",
            "default_stage": 1,
            "default_round": 1,
        },
    ],
    "tabletennis": [
        {
            "label": "Tischtennis",
            "uuid": "8HKTtNzWTZJBZii8ZSKh5h",
            "scope": "79806",
            "default_stage": 1,
            "default_round": 1,
        },
    ],
}

COMPLETION_STATES = ["scheduled", "running", "completed"]

DATE_KEYS = [
    "startDate", "startTime", "scheduledStart", "scheduledStartTime",
    "date", "matchDate", "gamedayDate", "plannedStartTime", "kickoff",
    "beginTime", "startsAt", "start",
]
TITLE_KEYS = ["title", "name", "displayName", "shortName"]
ISO_RE = re.compile(r"20[2-9][0-9]-[01]\d-[0-3]\d(?:T[0-2]\d:[0-5]\d(?::[0-5]\d)?(?:\.\d+)?Z?)?")
DE_DATE_RE = re.compile(r"\b[0-3]?\d\.[01]?\d\.(?:20[2-9][0-9]|\d{2})\b")
TIME_RE = re.compile(r"\b[0-2]?\d:[0-5]\d\b")


def fetch_json(url: str) -> tuple[object | None, str, dict]:
    info = {
        "url": url,
        "ok": False,
        "status": None,
        "error": "",
        "content_type": "",
        "bytes": 0,
        "is_json": False,
    }

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Secret_DE_EPG DYN Exact API Probe",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Origin": "https://widgets.desk.dyn.sport",
            "Referer": "https://widgets.desk.dyn.sport/matchups/handball/Q7Zk5rLkdJxBZgaXExX7Vb?/profile",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            raw = resp.read(8_000_000)
            info["ok"] = True
            info["status"] = getattr(resp, "status", None)
            info["content_type"] = resp.headers.get("content-type", "")
            info["bytes"] = len(raw)
            text = raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        text = ""
        try:
            raw = exc.read(2_000_000)
            text = raw.decode("utf-8", errors="replace")
            info["bytes"] = len(raw)
        except Exception:
            pass
        info["status"] = exc.code
        info["error"] = f"HTTPError {exc.code}: {exc.reason}"
        info["content_type"] = exc.headers.get("content-type", "") if exc.headers else ""
    except Exception as exc:
        text = ""
        info["error"] = f"{type(exc).__name__}: {exc}"

    data = None
    try:
        data = json.loads(text)
        info["is_json"] = True
    except Exception:
        pass

    return data, text, info


def q(params: list[tuple[str, object]]) -> str:
    # urllib.urlencode supports repeated keys when given a list of tuples.
    return urlencode([(k, str(v)) for k, v in params if v is not None and str(v) != ""])


def summarize_json(data: object) -> dict:
    summary = {
        "type": type(data).__name__,
        "top_keys": [],
        "list_len": None,
        "items_len": None,
        "first_item_keys": [],
    }

    if isinstance(data, dict):
        summary["top_keys"] = list(data.keys())[:80]
        items = data.get("items")
        if isinstance(items, list):
            summary["items_len"] = len(items)
            if items and isinstance(items[0], dict):
                summary["first_item_keys"] = list(items[0].keys())[:80]
    elif isinstance(data, list):
        summary["list_len"] = len(data)
        if data and isinstance(data[0], dict):
            summary["first_item_keys"] = list(data[0].keys())[:80]

    return summary


def iter_dicts(obj: object, depth: int = 0):
    if depth > 7:
        return
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            if isinstance(v, (dict, list)):
                yield from iter_dicts(v, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_dicts(item, depth + 1)


def get_path_value(obj: dict, paths: list[list[str]]) -> str:
    for path in paths:
        cur = obj
        ok = True
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok and cur not in (None, ""):
            return str(cur)
    return ""


def find_datetime_value(obj: dict) -> str:
    # Direct keys first.
    for key in DATE_KEYS:
        value = obj.get(key)
        if isinstance(value, str) and (ISO_RE.search(value) or DE_DATE_RE.search(value) or TIME_RE.search(value)):
            return value

    # Nested search.
    for d in iter_dicts(obj):
        for key in DATE_KEYS:
            value = d.get(key)
            if isinstance(value, str) and (ISO_RE.search(value) or DE_DATE_RE.search(value) or TIME_RE.search(value)):
                return value

    # Any ISO anywhere in values.
    blob = json.dumps(obj, ensure_ascii=False)
    m = ISO_RE.search(blob)
    if m:
        return m.group(0)
    return ""


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None

    v = value.strip()
    # ISO-ish.
    m = ISO_RE.search(v)
    if m:
        iso = m.group(0)
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass

    # German date + optional time fallback.
    dm = DE_DATE_RE.search(v)
    tm = TIME_RE.search(v)
    if dm:
        raw = dm.group(0)
        parts = re.findall(r"\d+", raw)
        if len(parts) >= 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            if year < 100:
                year += 2000
            hour, minute = (12, 0)
            if tm:
                hour, minute = map(int, tm.group(0).split(":"))
            return datetime(year, month, day, hour, minute, tzinfo=timezone(timedelta(hours=2)))

    return None


def extract_match_event(obj: dict, source_url: str, sport: str) -> dict | None:
    # Heuristic: a real match usually has sides/teams and an id/date/state.
    has_match_signal = any(k in obj for k in [
        "homeSide", "awaySide", "homeTeam", "awayTeam", "home", "away",
        "gamedayId", "uuid", "externalDataProviderId", "completionState",
        "liveBroadcast",
    ])
    if not has_match_signal:
        return None

    home = get_path_value(obj, [
        ["homeSide", "name"], ["homeTeam", "name"], ["home", "name"],
        ["homeSide", "shortName"], ["homeTeam", "shortName"], ["home", "shortName"],
    ])
    away = get_path_value(obj, [
        ["awaySide", "name"], ["awayTeam", "name"], ["away", "name"],
        ["awaySide", "shortName"], ["awayTeam", "shortName"], ["away", "shortName"],
    ])

    title = ""
    if home or away:
        title = f"{home or 'TBD'} - {away or 'TBD'}"
    else:
        for key in TITLE_KEYS:
            if obj.get(key):
                title = str(obj[key])
                break

    dt_value = find_datetime_value(obj)
    dt = parse_datetime(dt_value)

    # Accept if it looks like match/team object even without time; we need to inspect.
    if not title and not dt:
        return None

    return {
        "source_url": source_url,
        "sport": sport,
        "uuid": str(obj.get("uuid") or obj.get("id") or ""),
        "gamedayId": str(obj.get("gamedayId") or obj.get("gamedayID") or ""),
        "completionState": str(obj.get("completionState") or ""),
        "title": title or "(no title)",
        "home": home,
        "away": away,
        "datetime_raw": dt_value,
        "datetime_iso": dt.isoformat() if dt else "",
        "raw_keys": list(obj.keys())[:80],
        "raw": obj,
    }


def extract_events_from_json(data: object, source_url: str, sport: str) -> list[dict]:
    events = []
    seen = set()
    for d in iter_dicts(data):
        ev = extract_match_event(d, source_url, sport)
        if not ev:
            continue
        key = (ev["title"], ev["datetime_raw"], ev["uuid"], ev["gamedayId"])
        if key in seen:
            continue
        seen.add(key)
        events.append(ev)
    return events


def get_stages_rounds_groups(competition_detail: object) -> tuple[list[int], list[int], list[int]]:
    stages = set([1])
    rounds = set([1])
    groups = set()

    for d in iter_dicts(competition_detail):
        if "number" in d and any(k in d for k in ["rounds", "groups", "matchFixtureSettings", "rankingSettings", "isActive"]):
            try:
                stages.add(int(d["number"]))
            except Exception:
                pass
        if "rounds" in d and isinstance(d["rounds"], list):
            for r in d["rounds"]:
                if isinstance(r, dict) and "number" in r:
                    try:
                        rounds.add(int(r["number"]))
                    except Exception:
                        pass
        if "groups" in d and isinstance(d["groups"], list):
            for g in d["groups"]:
                if isinstance(g, dict) and "number" in g:
                    try:
                        groups.add(int(g["number"]))
                    except Exception:
                        pass

    return sorted(stages)[:12], sorted(rounds)[:40], sorted(groups)[:20]


def analyze_url(url: str, sport: str) -> dict:
    data, text, info = fetch_json(url)
    events = extract_events_from_json(data, url, sport) if data is not None else []
    return {
        **info,
        "summary": summarize_json(data) if data is not None else {},
        "iso_count": len(ISO_RE.findall(text)),
        "de_date_count": len(DE_DATE_RE.findall(text)),
        "time_count": len(TIME_RE.findall(text)),
        "event_count": len(events),
        "events_preview": [
            {
                "title": e["title"],
                "datetime_raw": e["datetime_raw"],
                "datetime_iso": e["datetime_iso"],
                "completionState": e["completionState"],
                "uuid": e["uuid"],
                "gamedayId": e["gamedayId"],
            }
            for e in events[:20]
        ],
        "text_snippet": text[:1500],
        "data": data,
    }


def main() -> int:
    results = []
    all_events = []

    for sport, comps in COMPETITIONS.items():
        # sport-level competition list
        for url in [
            f"{BASE}/competition/list/with-details?{q([('sport', sport)])}",
        ]:
            res = analyze_url(url, sport)
            results.append(res)
            all_events.extend(extract_events_from_json(res.get("data"), url, sport) if res.get("data") is not None else [])

        for comp in comps:
            uuid = comp["uuid"]
            # Known exact endpoints from JS.
            candidate_urls = [
                f"{BASE}/competition/list/with-details?{q([('sport', sport), ('gamedayId', uuid)])}",
                f"{BASE}/competition/{uuid}/with-details",
                f"{BASE}/sport/{sport}/match/list/with-details?{q([('competition', uuid), ('stage', 1), ('round', 1)])}",
            ]

            # First fetch competition detail to discover active stages/rounds/groups.
            detail_url = f"{BASE}/competition/{uuid}/with-details"
            detail_data, detail_text, detail_info = fetch_json(detail_url)
            detail_res = {
                **detail_info,
                "summary": summarize_json(detail_data) if detail_data is not None else {},
                "iso_count": len(ISO_RE.findall(detail_text)),
                "de_date_count": len(DE_DATE_RE.findall(detail_text)),
                "time_count": len(TIME_RE.findall(detail_text)),
                "event_count": len(extract_events_from_json(detail_data, detail_url, sport)) if detail_data is not None else 0,
                "events_preview": [],
                "text_snippet": detail_text[:1500],
                "data": detail_data,
            }
            results.append(detail_res)

            stages, rounds, groups = get_stages_rounds_groups(detail_data)
            if not stages:
                stages = [1]
            if not rounds:
                rounds = [1]

            # Build exact match/list and match/search variants.
            for stage in stages[:8]:
                for round_no in rounds[:20]:
                    candidate_urls.append(
                        f"{BASE}/sport/{sport}/match/list/with-details?{q([('competition', uuid), ('stage', stage), ('round', round_no)])}"
                    )

            for stage in stages[:8]:
                # repeated completionStates variant, exactly URLSearchParams style for arrays if appended.
                base_params = [
                    ("completionStates", "completed"),
                    ("completionStates", "running"),
                    ("completionStates", "scheduled"),
                    ("competition", uuid),
                    ("stage", stage),
                    ("limit", 50),
                ]
                candidate_urls.append(f"{BASE}/match/search/with-details?{q(base_params)}")

                # comma variant just in case API expects CSV.
                candidate_urls.append(
                    f"{BASE}/match/search/with-details?{q([('completionStates','completed,running,scheduled'), ('competition', uuid), ('stage', stage), ('limit', 50)])}"
                )

                for round_no in rounds[:20]:
                    candidate_urls.append(
                        f"{BASE}/match/search/with-details?{q(base_params + [('round', round_no)])}"
                    )

                for group_no in groups[:12]:
                    candidate_urls.append(
                        f"{BASE}/match/search/with-details?{q(base_params + [('group', group_no)])}"
                    )

                for group_no in groups[:8]:
                    for round_no in rounds[:12]:
                        candidate_urls.append(
                            f"{BASE}/match/search/with-details?{q(base_params + [('group', group_no), ('round', round_no)])}"
                        )

            seen_urls = set()
            for url in candidate_urls:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                res = analyze_url(url, sport)
                results.append(res)
                if res.get("data") is not None:
                    all_events.extend(extract_events_from_json(res["data"], url, sport))

    # De-duplicate extracted events.
    deduped = []
    seen = set()
    for ev in all_events:
        key = (ev["sport"], ev["title"], ev["datetime_raw"], ev["uuid"], ev["gamedayId"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ev)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": "dyn_exact_api_probe",
        "result_count": len(results),
        "event_count": len(deduped),
        "results": results,
        "events": deduped,
    }

    # Store compact JSON without gigantic data payloads.
    compact_results = []
    for r in results:
        rr = {k: v for k, v in r.items() if k != "data"}
        compact_results.append(rr)

    compact_payload = {
        **{k: v for k, v in payload.items() if k not in ("results", "events")},
        "results": compact_results,
        "events": [
            {k: v for k, v in e.items() if k != "raw"}
            for e in deduped
        ],
    }

    (OUT_DIR / "dyn-exact-api-probe.json").write_text(
        json.dumps(compact_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = []
    lines.append(f"DYN exact API probe generated at {payload['generated_at']}")
    lines.append(f"result_count: {len(results)}")
    lines.append(f"event_count: {len(deduped)}")
    lines.append("")

    lines.append("EXTRACTED EVENTS")
    for ev in deduped[:200]:
        lines.append(
            f"- {ev['sport']} | {ev['datetime_iso'] or ev['datetime_raw'] or 'NO_DATE'} | "
            f"{ev['title']} | state={ev['completionState']} uuid={ev['uuid']} gamedayId={ev['gamedayId']}"
        )
        lines.append(f"  source={ev['source_url']}")

    lines.append("")
    lines.append("API RESULTS")
    for res in results:
        # Show successes and useful failures only.
        show = (
            res["ok"]
            or res["event_count"] > 0
            or res["iso_count"] > 0
            or res["time_count"] > 0
            or res["de_date_count"] > 0
            or res["status"] not in (404, 405, None)
        )
        if not show:
            continue

        lines.append("=" * 100)
        lines.append(f"URL: {res['url']}")
        lines.append(f"OK: {res['ok']} STATUS: {res['status']} BYTES: {res['bytes']} CONTENT: {res['content_type']} ERROR: {res['error']}")
        lines.append(f"is_json: {res['is_json']} summary: {res['summary']}")
        lines.append(f"iso_count={res['iso_count']} de_date_count={res['de_date_count']} time_count={res['time_count']} event_count={res['event_count']}")
        if res["events_preview"]:
            lines.append("events_preview:")
            for ev in res["events_preview"]:
                lines.append(f"  - {ev}")
        lines.append("snippet:")
        lines.append(str(res["text_snippet"]).replace("\n", "\\n")[:1800])

    (OUT_DIR / "dyn-exact-api-probe.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"Wrote {OUT_DIR / 'dyn-exact-api-probe.txt'}")
    print(f"Wrote {OUT_DIR / 'dyn-exact-api-probe.json'}")
    print(f"event_count={len(deduped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
