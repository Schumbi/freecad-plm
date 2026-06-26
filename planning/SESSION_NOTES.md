# Session Notes

## Zweck

Diese Datei haelt laufenden Kontext fest, damit spaetere Sessions nicht bei null anfangen. Neue Erkenntnisse sollen mit Datum ergaenzt werden.

## 2026-06-26

### Ausgangslage

- Workspace: `/home/ralf/devel/freecad-plm`.
- Das urspruengliche nanoPLM wurde angeschaut.
- nanoPLM war ein kleines Flask/SQLAlchemy-Projekt mit SQLite, Bootstrap-Templates, Demo-Produkten und ersten FreeCAD-Exportideen.
- Die vorhandene FreeCAD-Integration war noch stark demohaft und Windows-gepraegt.
- Der Nutzer hat das alte nanoPLM in den Unterordner `old/` verschoben.

### Wichtige Erkenntnisse Aus nanoPLM

- Der Fokus auf lokale Nutzung und FreeCAD ist passend.
- Die bestehende UI-Idee als einfache Arbeitsoberflaeche ist interessant.
- Das vorhandene Datenmodell ist fuer ein echtes PLM zu duenn.
- Persistente Dateirevisionen, Rollen, Audit und saubere Uploads fehlen.
- Der alte Demo-Produktworkflow sollte nicht direkt uebernommen werden.

### Bisherige Planungsentscheidungen

- Das neue PLM entsteht als eigenes Projekt.
- V1 soll zuerst FreeCAD-Dateiverwaltung leisten, nicht vollstaendige Stuecklistenverwaltung.
- Zielnutzung ist ein kleines LAN-Team.
- Dateien werden im Filesystem abgelegt, Metadaten in der DB.
- Revisionen sollen immutable sein.
- Login und Rollen sind fuer v1 vorgesehen.
- Manuelle Uploads reichen fuer v1.
- FreeCADCmd-Exporte werden auf spaetere Versionen verschoben.
- Django ist aktuell die bevorzugte technische Basis.
- Docker Compose soll spaeter moeglich sein und jetzt mitgedacht werden.

### Naechster Sinnvoller Schritt

Die Anforderungen fuer v1 gemeinsam ausarbeiten:

- Welche Nutzerrollen gibt es genau?
- Welche Felder brauchen Projekt, Teil/Baugruppe und Revision?
- Wie entstehen Teilenummern und Revisionsnummern?
- Was bedeutet Freigabe konkret?
- Welche Suche und Filter braucht der Alltag?
- Welche `FCStd`-Metadaten sollen sichtbar werden?

### Resume-Hinweis

Bei einer neuen Session zuerst `planning/README.md` lesen und danach die dort genannte Lesereihenfolge verwenden.

### Fortschritt Danach

- Django 5.2 wurde in einer frisch erzeugten lokalen `.venv` installiert.
- Das Projektgeruest `freecad_plm` wurde angelegt.
- Die App `plm` wurde angelegt und in `INSTALLED_APPS` registriert.
- Basismodelle wurden erstellt:
  - `Project`
  - `Part` mit gemeinsamer Kategorie fuer Teil/Baugruppe
  - `Revision`
  - `AuditEvent`
- Die Modelle wurden in der Django-Admin-Oberflaeche registriert.
- Lokale Settings wurden auf Deutsch/Europe-Berlin und `MEDIA_ROOT=storage` gesetzt.
- `requirements.txt`, `.gitignore` und eine kurze Root-`README.md` wurden angelegt.
- `manage.py check`, `makemigrations plm` und `migrate` liefen erfolgreich.

### Naechster Kleiner Schritt

Superuser anlegen und im Admin pruefen, ob Projekt, Teil/Baugruppe und Revision sinnvoll erfassbar sind. Danach `FCStd`-Validierung und Upload-Service bauen.

### Fortschritt FCStd-Validierung

- Modul `plm/fcstd.py` angelegt.
- `validate_fcstd_upload()` prueft:
  - Dateiendung `.FCStd`
  - nicht-leeren Inhalt
  - gueltiges ZIP-Archiv
  - ZIP-Mitglieder
- Die Validierung liefert erste Metadaten:
  - Originaldateiname
  - Dateigroesse
  - SHA-256
  - Anzahl ZIP-Mitglieder
  - Hinweise auf `Document.xml` und `GuiDocument.xml`
- Vier Tests in `plm/tests.py` laufen erfolgreich.

### Naechster Kleiner Schritt Nach Validierung

Einen Upload-Service bauen, der eine validierte Datei als neue `Revision` anlegt und die Metadaten automatisch in `Revision` schreibt.

### Fortschritt Upload-Service

- Modul `plm/services.py` angelegt.
- `next_revision_code(part)` erzeugt fortlaufende Codes im Format `R0001`, `R0002`, ...
- `create_revision_from_upload(part, uploaded_file, created_by)`:
  - validiert die Datei mit `validate_fcstd_upload()`
  - speichert eine neue `Revision` im Status `draft`
  - uebernimmt Originaldateiname, Dateigroesse, SHA-256 und extrahierte Basis-Metadaten
  - legt ein `AuditEvent` fuer den Upload an
- Tests fuer Start-Revisionscode, Metadaten, Code-Inkrement und fehlgeschlagene Uploads wurden ergaenzt.
- `manage.py test plm` laeuft mit 8 Tests erfolgreich.

### Naechster Kleiner Schritt Nach Upload-Service

Ein Formular oder eine kleine View bauen, mit der ein angemeldeter Benutzer zu einem Teil eine `.FCStd`-Revision hochladen kann.
