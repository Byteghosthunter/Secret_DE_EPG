#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ByteGH / Secret_DE_EPG
DreamOS channel-list preview patcher for XMLTV.

Purpose:
- DreamOS native channel list only shows current Now/Next.
- Event channels often have real events days later, so the channel list looks empty.
- This script replaces long/generic current placeholder blocks with a current preview event:
  "Naechstes Event: Do 09.07 13:00 - ..."
- The real future event remains in the XMLTV file.

Run after public/sports-events.xml is generated and before public/sports-events.xml.xz is published.
"""

from __future__ import annotations

import calendar
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


PREVIEW_PREFIX = "Naechstes Event:"
PREVIEW_DAYS_LIMIT = 10
LONG_CURRENT_SECONDS = 8 * 3600
START_BACK_SECONDS = 10 * 60
STOP_BEFORE_NEXT_SECONDS = 60
DISPLAY_TZ_NAME = "Europe/Berlin"

TARGET_PREFIXES = [
    "magenta.sport.",
    "dazn.event.",
    "dazn.ufc.",
    "dazn.ucl.",
    "dazn.bundesliga.",
    "dazn.laliga.",
    "dazn.nba.",
    "dazn.nfl.",
    "dazn.ligue1.",
    "dazn.seriea.",
    "dyn.sport.",
    "amazon.live.",
    "prime.event.",
    "discovery.extra.",
    "eurosport.extra.",
    "rtlplus.sport.",
    "sporteurope.",
    "ufcfightpass.event.",
]

DAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def is_target_channel(channel_id: str | None) -> bool:
    if not channel_id:
        return False
    cid = channel_id.lower()
    return any(cid.startswith(prefix) for prefix in TARGET_PREFIXES)


def parse_xmltv_time(value: str | None) -> int | None:
    if not value:
        return None

    match = re.match(r"^(\d{14})(?:\s*([+-])(\d{2})(\d{2}))?", value.strip())
    if not match:
        return None

    raw = match.group(1)
    sign = match.group(2)
    off_h = match.group(3)
    off_m = match.group(4)

    year = int(raw[0:4])
    month = int(raw[4:6])
    day = int(raw[6:8])
    hour = int(raw[8:10])
    minute = int(raw[10:12])
    second = int(raw[12:14])

    epoch = calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0))

    if sign and off_h and off_m:
        offset = int(off_h) * 3600 + int(off_m) * 60
        if sign == "+":
            epoch -= offset
        else:
            epoch += offset
    else:
        epoch = int(time.mktime((year, month, day, hour, minute, second, 0, 0, -1)))

    return epoch


def format_xmltv_utc(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def display_datetime(epoch: int) -> str:
    dt_utc = datetime.fromtimestamp(epoch, timezone.utc)

    if ZoneInfo is not None:
        try:
            dt = dt_utc.astimezone(ZoneInfo(DISPLAY_TZ_NAME))
        except Exception:
            dt = dt_utc
    else:
        dt = dt_utc

    day_name = DAYS_DE[dt.weekday()]
    return f"{day_name} {dt.day:02d}.{dt.month:02d} {dt.hour:02d}:{dt.minute:02d}"


def get_title(programme: ET.Element) -> str:
    for child in list(programme):
        if child.tag == "title" and child.text:
            return child.text.strip()
    return ""


def is_old_preview(programme: ET.Element) -> bool:
    return get_title(programme).startswith(PREVIEW_PREFIX)


def looks_like_placeholder(title: str, duration: int) -> bool:
    text = (title or "").strip().lower()

    if not text:
        return True

    if duration >= LONG_CURRENT_SECONDS:
        return True

    generic_words = [
        "n/a",
        "na",
        "no information",
        "keine information",
        "sendepause",
        "programm",
        "programminformation",
        "event",
        "magenta sport",
        "dazn event",
        "live event",
    ]

    return any(text == word or text.startswith(word) for word in generic_words)


def add_text(programme: ET.Element, tag: str, text: str) -> None:
    child = ET.SubElement(programme, tag)
    child.set("lang", "de")
    child.text = text


def patch_xmltv(input_file: Path, output_file: Path) -> dict[str, int]:
    tree = ET.parse(input_file)
    root = tree.getroot()

    children = list(root)
    channel_nodes = [node for node in children if node.tag == "channel"]
    programme_nodes = [node for node in children if node.tag == "programme"]

    now = int(datetime.now(timezone.utc).timestamp())
    max_future = now + PREVIEW_DAYS_LIMIT * 86400

    clean_programmes: list[ET.Element] = []
    removed_old_preview = 0

    for programme in programme_nodes:
        if is_old_preview(programme):
            removed_old_preview += 1
        else:
            clean_programmes.append(programme)

    by_channel: dict[str, list[tuple[int, int, ET.Element]]] = {}

    for programme in clean_programmes:
        channel_id = programme.get("channel")
        if not is_target_channel(channel_id):
            continue

        start = parse_xmltv_time(programme.get("start"))
        stop = parse_xmltv_time(programme.get("stop"))

        if start is None or stop is None:
            continue

        by_channel.setdefault(channel_id, []).append((start, stop, programme))

    remove_ids: set[int] = set()
    preview_nodes: list[ET.Element] = []
    removed_blocker = 0
    added_preview = 0

    for channel_id, events in by_channel.items():
        events.sort(key=lambda item: item[0])

        current_events: list[tuple[int, int, ET.Element]] = []
        next_event: tuple[int, int, ET.Element] | None = None

        for start, stop, programme in events:
            if start <= now < stop:
                current_events.append((start, stop, programme))
            elif start > now and start <= max_future and next_event is None:
                next_event = (start, stop, programme)

        if next_event is None:
            continue

        should_add_preview = False

        if not current_events:
            should_add_preview = True
        else:
            all_current_are_placeholders = all(
                looks_like_placeholder(get_title(programme), stop - start)
                for start, stop, programme in current_events
            )

            if all_current_are_placeholders:
                should_add_preview = True
                for _start, _stop, programme in current_events:
                    remove_ids.add(id(programme))
                    removed_blocker += 1

        if not should_add_preview:
            continue

        next_start, _next_stop, next_programme = next_event

        preview_start = now - START_BACK_SECONDS
        preview_stop = next_start - STOP_BEFORE_NEXT_SECONDS

        if preview_stop <= preview_start:
            continue

        real_title = get_title(next_programme) or "Event"
        preview_title = f"{PREVIEW_PREFIX} {display_datetime(next_start)} - {real_title}"

        if len(preview_title) > 220:
            preview_title = preview_title[:217] + "..."

        preview = ET.Element("programme")
        preview.set("start", format_xmltv_utc(preview_start))
        preview.set("stop", format_xmltv_utc(preview_stop))
        preview.set("channel", channel_id)

        add_text(preview, "title", preview_title)
        add_text(
            preview,
            "desc",
            "Vorschau-Eintrag fuer DreamOS-Kanalliste. Das echte Event bleibt separat im EPG.",
        )

        preview_nodes.append(preview)
        added_preview += 1

    final_programmes = [
        programme for programme in clean_programmes if id(programme) not in remove_ids
    ]
    final_programmes.extend(preview_nodes)

    final_programmes.sort(
        key=lambda programme: (
            programme.get("channel") or "",
            parse_xmltv_time(programme.get("start")) or 0,
        )
    )

    root[:] = channel_nodes + final_programmes

    try:
        ET.indent(tree, space=" ", level=0)
    except AttributeError:
        pass

    tree.write(output_file, encoding="utf-8", xml_declaration=True, short_empty_elements=True)

    return {
        "removed_old_preview": removed_old_preview,
        "removed_blocker": removed_blocker,
        "added_preview": added_preview,
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: add_preview_now_events.py INPUT_XML OUTPUT_XML", file=sys.stderr)
        return 2

    input_file = Path(sys.argv[1])
    output_file = Path(sys.argv[2])

    if not input_file.exists():
        print(f"[ERROR] Input file not found: {input_file}", file=sys.stderr)
        return 1

    stats = patch_xmltv(input_file, output_file)

    print(f"[OK] DreamOS preview patch written: {output_file}")
    print(f"[OK] removed_old_preview={stats['removed_old_preview']}")
    print(f"[OK] removed_blocker={stats['removed_blocker']}")
    print(f"[OK] added_preview={stats['added_preview']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
