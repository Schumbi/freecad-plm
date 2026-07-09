# Roadmap

## Zweck

Diese Datei haelt die grobe Entwicklungsreihenfolge fest. Die Roadmap ist bewusst pragmatisch und kann nach der Anforderungsrunde angepasst werden.

## V0: Fundament

- Neues Projektgeruest erstellen.
- Django-Projektstruktur anlegen.
- Settings fuer lokale Entwicklung vorbereiten.
- Basismodelle fuer Benutzer, Projekt, Teil/Baugruppe, Revision und Audit entwerfen.
- Einfache Admin-Oberflaeche aktivieren.
- Minimalen Upload-Prototyp fuer `FCStd` bauen.
- Tests fuer `FCStd`-Validierung starten.
- Akzeptanzkriterien aus `planning/ACCEPTANCE_CRITERIA.md` erfuellen.

## V1: Nutzbares LAN-PLM

- Login und Rollenmodell.
- Projektliste und Projekt-Detailansicht.
- Teile/Baugruppen je Projekt.
- Manuelle `FCStd`-Uploads.
- Immutable Revisionen mit Status.
- Download geschuetzt hinter Login.
- Audit-Trail fuer Upload, Release, Download und Admin-Aktionen.
- Suche nach Projekten, Teilen, Revisionen und Dateinamen.
- FreeCAD-Addon-Grundworkflow fuer Verbinden, Lesen, Checkout, Check-in, Cancel, Notizen, Anmerkungen, Teilanlage und Projektimport.
- FreeCADCmd-Analyse fuer Revisionen.
- Abgeleitete Artefakte fuer STEP, STL, 3MF und PNG-Ansichten.
- Visueller Vergleich von Revisionen ueber PNG-Ansichten.
- Schlichte, robuste Weboberflaeche.
- Lokale Installation dokumentieren.
- V1-Akzeptanzkriterien aus `planning/ACCEPTANCE_CRITERIA.md` erfuellen.

## V2: Deployment Und FreeCAD-Automation

- Dockerfile und Docker Compose.
- PostgreSQL als Compose-Datenbank.
- Medien-/Storage-Volume.
- Optionaler FreeCADCmd-Worker.
- Exportjobs fuer PDF, DXF und weitere Formate pruefen.
- VarSet-Parameterbearbeitung und Variantenexports pruefen.
- Jobstatus, Logs und Fehleranzeige.

## Spaeter

- Stuecklisten und Baugruppenbeziehungen.
- Nummernkreise.
- Mehrstufige Freigabeprozesse.
- Kommentare und Review-Flows.
- Benachrichtigungen.
- Externe API.
- Backup-/Restore-Werkzeuge.
- Internationalisierung.

## Implementierungsstand 2026-07-10

Die V1-Roadmap ist im Code umgesetzt. Docker Compose, Worker, Addon-API und modernisiertes Web-UI sind vorhanden. Vor einem formalen V1.0-Release fehlt die dokumentierte Browser-Abnahme (`planning/V1_ACCEPTANCE.md`) und die Betriebsabnahme auf dem Zielserver.
