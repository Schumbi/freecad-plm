# TODO

## Zweck

Diese Datei ist die operative Aufgabenliste. Sie soll kurz bleiben und den naechsten sinnvollen Schritt sichtbar machen.

## Jetzt

- Upload im Browser erneut testen: gleicher Datei-Hash muss blockiert werden.
- Download-Link fuer gespeicherte Revisionen im Browser testen.
- Admin-Oberflaeche mit ersten Projekt-/Teil-/Revision-Daten pruefen.
- Reader-/Editor-Rollen im Browser mit Testnutzern pruefen.

## Als Naechstes

- Freigabe-Aktion fuer Revisionen konkretisieren und bauen.
- Revisionsnummern-Format verfeinern.
- Einfache Projekt-/Teil-Listen ausserhalb des Admins bauen.
- Akzeptanzkriterien fuer v0 und v1 formulieren.

## Spaeter

- Docker-Compose-Zielbild konkretisieren.
- FreeCADCmd-Worker fuer v2 evaluieren.
- Exportformate und Jobmodell planen.
- Bestehende FreeCAD-Ordnerimport-Funktion pruefen.

## Erledigt

- Altes nanoPLM grob analysiert.
- Altes nanoPLM nach `old/` verschoben.
- Eigenes PLM als neues Projekt festgelegt.
- `planning/` als dauerhafte Kontextablage festgelegt.
- Flask als Default-Technologie infrage gestellt.
- Django als aktueller Favorit festgehalten.
- Django-Projektgeruest erzeugt.
- App `plm` mit Basismodellen fuer Projekt, Teil/Baugruppe, Revision und AuditEvent angelegt.
- Erste Admin-Oberflaeche fuer die Basismodelle registriert.
- Lokale SQLite-Migrationen erstellt und angewendet.
- Kurze lokale Entwicklungsanleitung in der Root-`README.md` angelegt.
- `FCStd`-Validierungsmodul mit ZIP-Pruefung, Hash und Basis-Metadaten angelegt.
- Tests fuer gueltige, falsch benannte, defekte und leere `FCStd`-Uploads angelegt.
- Upload-Service angelegt, der validierte `FCStd`-Dateien als neue `Revision` speichert.
- Automatische Revisionscodes `R0001`, `R0002`, ... im Upload-Service umgesetzt.
- AuditEvent fuer hochgeladene Revisionen im Upload-Service umgesetzt.
- Erste Weboberflaeche fuer Projektliste, Projektdetail, Teildetail und Revision-Upload angelegt.
- Browser-Upload-Pfad mit Tests abgesichert.
- Doppelte `FCStd`-Uploads mit gleichem SHA-256 pro Teil werden blockiert.
- Login-geschuetzter Download-Link fuer gespeicherte Revisionen angelegt.
- AuditEvent fuer heruntergeladene Revisionen umgesetzt.
- Rollen-Gruppen `admin`, `editor`, `reader` mit Management-Command angelegt.
- Upload-Recht auf Superuser, `admin` und `editor` begrenzt; `reader` darf nicht hochladen.
