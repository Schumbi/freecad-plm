# TODO

## Zweck

Diese Datei ist die operative Aufgabenliste. Sie soll kurz bleiben und den naechsten sinnvollen Schritt sichtbar machen.

## Jetzt

- Superuser fuer lokale Admin-Oberflaeche anlegen.
- Admin-Oberflaeche mit ersten Projekt-/Teil-/Revision-Daten testen.
- Upload-Service vorbereiten, der aus einer validierten `FCStd` eine Revision erzeugt.

## Als Naechstes

- Rollen und Berechtigungen konkretisieren.
- Revisionsnummern-Format verfeinern.
- Upload-Formular fuer `FCStd`-Revisionen bauen.
- Akzeptanzkriterien fuer v0 und v1 formulieren.
- Projekt-/Teil-Listen ausserhalb des Admins skizzieren.

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
