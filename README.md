# Sports Event EPG

Starter-Projekt für einen öffentlichen XMLTV/EPGImport-Feed über GitHub Actions + GitHub Pages.

## Ziel

GitHub Actions erzeugt regelmäßig `sports-events.xml.xz`. GitHub Pages veröffentlicht diese Datei. Enigma2/EPGImport lädt sie wie eine normale Rytec-Quelle.

## GitHub Pages einrichten

1. Repository auf GitHub erstellen, am besten public: `sports-event-epg`
2. Diese Dateien in das Repository hochladen.
3. In GitHub: Settings → Pages → Source: **GitHub Actions** auswählen.
4. In GitHub: Actions → **Build and publish Sports Event EPG** → **Run workflow** starten.
5. Danach ist der Feed erreichbar unter:

```text
https://DEIN-GITHUB-NAME.github.io/REPO-NAME/sports-events.xml.xz
```

## Dateien für EPGImport

Nach dem ersten Lauf liegen auf GitHub Pages:

```text
/epgimport/sports-events.sources.xml
/epgimport/sports-events.channels.xml
/sports-events.xml.xz
```

Auf der Dreambox müssen später lokal liegen:

```text
/etc/epgimport/sports-events.sources.xml
/etc/epgimport/sports-events.channels.xml
```

Die `channels.xml` enthält Platzhalter. Die Service-References müssen mit e-channelizer oder manuell angepasst werden.

## Aktueller Stand

Diese Starter-Version erzeugt gültige Demo-EPG-Daten. Die echten Scraper für DAZN, DYN, Prime, Discovery, Eurosport, Sporteurope/SportDeutschland und RTL+ werden später in `builder/build_sports_events.py` ergänzt.
