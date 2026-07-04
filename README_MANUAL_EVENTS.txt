# Manual Events Update

Diese Version unterstützt `data/manual_events.json`.

Wenn `manual_events.json` leer ist (`[]`), erzeugt der Builder weiter Demo-EPG.
Sobald mindestens ein gültiges Event eingetragen ist, werden nur die manuellen Events als XMLTV geschrieben.

Format:

[
  {
    "channel": "amazon.live.01",
    "start": "2026-07-05T20:15:00+02:00",
    "duration_minutes": 150,
    "title": "Amazon Live Event",
    "category": "Sport",
    "desc": "Beschreibung"
  }
]

Alternativ zu `duration_minutes` kannst du `stop` verwenden:

"stop": "2026-07-05T22:45:00+02:00"
