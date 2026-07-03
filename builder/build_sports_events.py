#!/usr/bin/env python3
from pathlib import Path
import lzma
from datetime import datetime, timezone, timedelta
import html

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
EPGIMPORT = PUBLIC / "epgimport"

PUBLIC.mkdir(parents=True, exist_ok=True)
EPGIMPORT.mkdir(parents=True, exist_ok=True)

channels = []

def add_channel(channel_id, name):
    channels.append((channel_id, name))

for i in range(1, 11):
    add_channel(f"dazn.event.{i:02d}", f"DAZN Event {i} FHD")
for i in range(1, 11):
    add_channel(f"dazn.bundesliga.{i:02d}", f"DAZN Bundesliga {i} FHD")
for i in range(1, 26):
    add_channel(f"dyn.sport.{i:02d}", f"DYN Sport {i}")
for i in range(1, 10):
    add_channel(f"prime.event.{i:02d}", f"Amazon Prime Event {i}")
for i in range(1, 17):
    add_channel(f"discovery.extra.{i:02d}", f"Discovery Extra {i}")
for i in range(1, 17):
    add_channel(f"eurosport.extra.{i:02d}", f"Eurosport Extra {i}")
for i in range(1, 21):
    add_channel(f"sporteurope.tv.{i:02d}", f"SportDeutschland.TV {i}")
add_channel("sporteurope.del2", "Sport.DE DEL 2")

now = datetime.now(timezone.utc)
start = now.replace(minute=0, second=0, microsecond=0)
stop = start + timedelta(hours=2)

def xml_time(dt):
    return dt.astimezone(timezone(timedelta(hours=2))).strftime("%Y%m%d%H%M%S +0200")

xml = ['<?xml version="1.0" encoding="UTF-8"?>']
xml.append('<tv generator-info-name="Secret_DE_EPG">')

for channel_id, name in channels:
    xml.append(f'  <channel id="{html.escape(channel_id)}">')
    xml.append(f'    <display-name>{html.escape(name)}</display-name>')
    xml.append('  </channel>')

for channel_id, name in channels:
    xml.append(f'  <programme start="{xml_time(start)}" stop="{xml_time(stop)}" channel="{html.escape(channel_id)}">')
    xml.append(f'    <title lang="de">{html.escape(name)} - EPG Test</title>')
    xml.append('    <desc lang="de">Demo-Eintrag. Wenn du das im EPG siehst, funktioniert GitHub Pages + EPGImport.</desc>')
    xml.append('    <category lang="de">Sport</category>')
    xml.append('  </programme>')

xml.append('</tv>')
xml_text = "\n".join(xml) + "\n"

xml_path = PUBLIC / "sports-events.xml"
xz_path = PUBLIC / "sports-events.xml.xz"
xml_path.write_text(xml_text, encoding="utf-8")

with lzma.open(xz_path, "wb", preset=6) as f:
    f.write(xml_text.encode("utf-8"))

source_xml = '''<?xml version="1.0" encoding="utf-8"?>
<sources>
  <sourcecat sourcecatname="Secret DE Sports Event EPG">
    <source type="gen_xmltv" nocheck="1" channels="/etc/epgimport/sports-events.channels.xml">
      <description>Secret DE Sports Event EPG</description>
      <url>https://Byteghosthunter.github.io/Secret_DE_EPG/sports-events.xml.xz</url>
    </source>
  </sourcecat>
</sources>
'''
(EPGIMPORT / "sports-events.sources.xml").write_text(source_xml, encoding="utf-8")

channels_xml = ['<?xml version="1.0" encoding="utf-8"?>', '<channels>']
for channel_id, name in channels:
    channels_xml.append(f'  <channel id="{channel_id}">DEINE_SERVICE_REFERENCE_FUER_{channel_id.upper().replace(".", "_")}</channel>')
channels_xml.append('</channels>')
(EPGIMPORT / "sports-events.channels.xml").write_text("\n".join(channels_xml) + "\n", encoding="utf-8")

index = '''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <title>Secret DE EPG</title>
</head>
<body>
  <h1>Secret DE EPG</h1>
  <p>XMLTV Feed: <a href="sports-events.xml.xz">sports-events.xml.xz</a></p>
  <p>EPGImport Source: <a href="epgimport/sports-events.sources.xml">sports-events.sources.xml</a></p>
  <p>EPGImport Channels: <a href="epgimport/sports-events.channels.xml">sports-events.channels.xml</a></p>
</body>
</html>
'''
(PUBLIC / "index.html").write_text(index, encoding="utf-8")

print(f"Wrote {xml_path}")
print(f"Wrote {xz_path}")
