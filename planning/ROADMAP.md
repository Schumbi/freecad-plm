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

## V1: Nutzbares LAN-PLM

- Login und Rollenmodell.
- Projektliste und Projekt-Detailansicht.
- Teile/Baugruppen je Projekt.
- Manuelle `FCStd`-Uploads.
- Immutable Revisionen mit Status.
- Download geschuetzt hinter Login.
- Audit-Trail fuer Upload, Release, Download und Admin-Aktionen.
- Suche nach Projekten, Teilen, Revisionen und Dateinamen.
- Schlichte, robuste Weboberflaeche.
- Lokale Installation dokumentieren.

## V2: Deployment Und FreeCAD-Automation

- Dockerfile und Docker Compose.
- PostgreSQL als Compose-Datenbank.
- Medien-/Storage-Volume.
- Optionaler FreeCADCmd-Worker.
- Exportjobs fuer STEP, STL, PDF und DXF pruefen.
- Jobstatus, Logs und Fehleranzeige.

## Spaeter

- Ordnerimport bestehender FreeCAD-Projekte.
- Stuecklisten und Baugruppenbeziehungen.
- Nummernkreise.
- Mehrstufige Freigabeprozesse.
- Kommentare und Review-Flows.
- Benachrichtigungen.
- Externe API.
- Backup-/Restore-Werkzeuge.
- Internationalisierung.
