#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse
import json, re, traceback, urllib.request, urllib.error

OUT = Path("discovery-eurosport-detail-results")
OUT.mkdir(parents=True, exist_ok=True)

LANDING = "https://www.discoveryplus.com/de/de/watch-eurosport-on-discoveryplus"
MAX_DETAILS = 50

A_RE = re.compile(r"(?is)<a\b[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>")
SCRIPT_RE = re.compile(r"(?is)<script\b[^>]*?(?:type=[\"']([^\"']+)[\"'])?[^>]*>(.*?)</script>")
SPORT_RE = re.compile(r"^https://www\.discoveryplus\.com/de/de/sports/\d{4}-\d{1,2}-\d{1,2}/[0-9a-f-]{20,}$", re.I)
TIME_RE = re.compile(r"\b([A-Z][a-z]{2})\s+(\d{1,2}),\s+(\d{1,2}):(\d{2})(am|pm)\b")
TIME_STOP_RE = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{1,2}:\d{2}(?:am|pm)\b", re.I)
KEYS = {"title","name","displayName","description","shortDescription","longDescription","start","startTime","end","endTime","duration","scheduledStart","scheduledEnd","sport","competition","tournament","league","season","episode","event","image","images","thumbnail","poster","video","content","metadata"}


def clean(x):
    return re.sub(r"\s+", " ", unescape(str(x)).replace("\\u0026","&").replace("\\/","/")).strip()


def textify(html):
    html = re.sub(r"(?is)<script\b.*?</script>", " ", html)
    html = re.sub(r"(?is)<style\b.*?</style>", " ", html)
    html = re.sub(r"(?is)<[^>]+>", " ", html)
    return clean(html)


def safe_url(base, href):
    href = clean(href).rstrip(".,;'")
    if not href or any(c in href for c in '[]{}"`'):
        return ""
    try:
        if href.startswith("/"):
            href = urljoin(base, href)
        urlparse(href)
    except ValueError:
        return ""
    return href


def fetch(url, limit=7000000):
    info = {"url":url,"ok":False,"status":None,"final_url":url,"content_type":"","bytes":0,"error":""}
    req = urllib.request.Request(url, headers={
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,application/json,text/javascript,*/*;q=0.8",
        "Accept-Language":"de-DE,de;q=0.9,en-GB;q=0.7,en;q=0.6",
        "Cache-Control":"no-cache","Pragma":"no-cache","DNT":"1","Connection":"close",
    })
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read(limit)
            info.update(ok=True,status=getattr(r,"status",None),final_url=r.geturl(),content_type=r.headers.get("content-type",""),bytes=len(raw))
            return raw.decode("utf-8","replace"), info
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(1000000)
            body = raw.decode("utf-8","replace")
            info["bytes"] = len(raw)
        except Exception:
            body = ""
        info.update(status=e.code,content_type=e.headers.get("content-type","") if e.headers else "",error=f"HTTPError {e.code}: {e.reason}")
        return body, info
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
        return "", info


def uniq(seq):
    seen, out = set(), []
    for x in seq:
        k = json.dumps(x, ensure_ascii=False, sort_keys=True) if isinstance(x, dict) else clean(x)
        if k and k not in seen:
            seen.add(k); out.append(x)
    return out


def landing_events(html, base):
    out = []
    for href, body in A_RE.findall(html):
        url = safe_url(base, href)
        if not SPORT_RE.match(url):
            continue
        raw = clean(re.sub(r"(?is)<[^>]+>", " ", body))
        raw = re.sub(r"^(?:Demnächst|Jetzt Live|Live)\s+", "", raw, flags=re.I).strip()
        m = TIME_RE.search(raw)
        start_label = m.group(0) if m else ""
        title = TIME_STOP_RE.split(raw, 1)[0].strip()
        title = re.sub(r"^(?:Radsport|Motorsport|Tennis|Snooker|Wintersport|Olympia|Olympics)\s+", "", title, flags=re.I).strip()
        out.append({"title": title, "start_label": start_label, "url": url, "raw": raw})
    return uniq(out)


def json_ld(html):
    blocks = []
    for typ, body in SCRIPT_RE.findall(html):
        if "ld+json" not in typ.lower():
            continue
        try:
            data = json.loads(clean(body))
        except Exception:
            continue
        if isinstance(data, list):
            blocks += [x for x in data if isinstance(x, dict)]
        elif isinstance(data, dict):
            blocks.append(data)
    return blocks[:20]


def balanced(raw, idx):
    if idx < 0 or idx >= len(raw) or raw[idx] not in "{[":
        return ""
    op, cl = raw[idx], ("}" if raw[idx] == "{" else "]")
    depth = 0; instr = False; esc = False
    for pos, ch in enumerate(raw[idx:], idx):
        if instr:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == '"': instr = False
            continue
        if ch == '"': instr = True
        elif ch == op: depth += 1
        elif ch == cl:
            depth -= 1
            if depth == 0:
                return raw[idx:pos+1]
    return ""


def app_json(html):
    markers = ['{"props"','{"pageProps"','{"data"','{"content"','{"video"','{"title"','{"__typename"','{"initialState"','{"apolloState"']
    cands = []
    for _typ, body in SCRIPT_RE.findall(html):
        raw = clean(body)
        for marker in markers:
            idx = raw.find(marker)
            if idx < 0:
                continue
            block = balanced(raw, idx)
            if not block:
                continue
            try:
                data = json.loads(block)
            except Exception:
                continue
            txt = json.dumps(data, ensure_ascii=False)
            score = sum(txt.lower().count(k.lower()) for k in KEYS)
            cands.append({"score": score, "length": len(block), "keys": list(data.keys())[:25] if isinstance(data, dict) else [], "snippet": txt[:3000], "data": data})
            break
    cands.sort(key=lambda x: (x["score"], x["length"]), reverse=True)
    return cands[:10]


def kv_extract(obj, maxn=160):
    found = []
    def walk(v, path=""):
        if len(found) >= maxn:
            return
        if isinstance(v, dict):
            for k, val in v.items():
                p = f"{path}.{k}" if path else str(k)
                if str(k) in KEYS or str(k).lower() in {x.lower() for x in KEYS}:
                    if isinstance(val, (str,int,float,bool)) or val is None:
                        found.append({"path":p, "value":val})
                    else:
                        found.append({"path":p, "type":type(val).__name__, "preview":clean(str(val))[:350]})
                walk(val, p)
        elif isinstance(v, list):
            for i, item in enumerate(v[:60]):
                walk(item, f"{path}[{i}]")
    walk(obj)
    return found


def analyze(ev):
    html, info = fetch(ev["url"])
    txt = textify(html)
    jld = json_ld(html)
    aj = app_json(html)
    kv = []
    for b in jld:
        kv += kv_extract(b, 80)
    for cand in aj[:4]:
        kv += kv_extract(cand["data"], 120)
    for cand in aj:
        cand.pop("data", None)
    return {**info, "landing":ev, "text_length":len(txt), "snippet":txt[:2200], "json_ld":jld, "app_json":aj, "key_values":uniq(kv)[:200]}


def main():
    errors = []
    html, info = fetch(LANDING)
    evs = landing_events(html, info.get("final_url") or LANDING)
    details = []
    for ev in evs[:MAX_DETAILS]:
        try:
            details.append(analyze(ev))
        except Exception as e:
            errors.append(f"{ev.get('url')}: {type(e).__name__}: {e}\n{traceback.format_exc()}")

    payload = {"generated_at":datetime.now(timezone.utc).isoformat(),"landing_info":info,"landing_events_count":len(evs),"landing_events":evs,"details_checked":len(details),"details":details,"errors":errors}
    (OUT/"discovery-eurosport-detail-probe.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    lines = []
    lines.append(f"Discovery/Eurosport detail probe generated at {payload['generated_at']}")
    lines.append(f"landing_ok={info['ok']} status={info['status']} bytes={info['bytes']} final={info['final_url']}")
    lines.append(f"landing_events_count={len(evs)} details_checked={len(details)} errors={len(errors)}")
    lines.append("")
    if errors:
        lines.append("ERRORS")
        lines += [e.replace("\n","\n  ") for e in errors[:20]]
        lines.append("")
    lines.append("LANDING EVENTS")
    for i, ev in enumerate(evs[:120], 1):
        lines.append(f"{i:03d}. {ev['start_label']} | {ev['title']} | {ev['url']}")
    lines.append("")
    lines.append("DETAILS")
    for i, d in enumerate(details[:60],1):
        ev = d["landing"]
        lines.append("="*120)
        lines.append(f"{i:03d}. {ev['start_label']} | {ev['title']}")
        lines.append(f"URL: {d['url']}")
        lines.append(f"OK={d['ok']} STATUS={d['status']} BYTES={d['bytes']} FINAL={d['final_url']} ERROR={d['error']}")
        lines.append(f"text_length={d['text_length']} json_ld={len(d['json_ld'])} app_json={len(d['app_json'])} key_values={len(d['key_values'])}")
        if d["json_ld"]:
            lines.append("JSON-LD:")
            for b in d["json_ld"][:3]:
                lines.append(json.dumps(b,ensure_ascii=False)[:1600])
        if d["app_json"]:
            lines.append("APP JSON:")
            for c in d["app_json"][:4]:
                lines.append(f"score={c['score']} length={c['length']} keys={c['keys']} snippet={c['snippet'][:1600]}")
        if d["key_values"]:
            lines.append("KEY VALUES:")
            for kv in d["key_values"][:70]:
                lines.append(json.dumps(kv,ensure_ascii=False)[:800])
        lines.append("TEXT:")
        lines.append(d["snippet"][:1600])

    full = "\n".join(lines) + "\n"
    (OUT/"discovery-eurosport-detail-probe.txt").write_text(full,encoding="utf-8")

    small = [f"Discovery/Eurosport detail candidates generated at {payload['generated_at']}", f"landing_events_count={len(evs)} details_checked={len(details)} errors={len(errors)}", ""]
    for i, d in enumerate(details[:60],1):
        ev = d["landing"]
        small.append(f"{i:03d}. {ev['start_label']} | {ev['title']}")
        small.append(f"     url={ev['url']}")
        small.append(f"     ok={d['ok']} status={d['status']} bytes={d['bytes']} json_ld={len(d['json_ld'])} app_json={len(d['app_json'])} key_values={len(d['key_values'])}")
        for kv in d["key_values"][:18]:
            small.append("     KV " + json.dumps(kv,ensure_ascii=False)[:650])
    (OUT/"discovery-eurosport-detail-candidates.txt").write_text("\n".join(small)+"\n",encoding="utf-8")
    print(full[:150000])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
