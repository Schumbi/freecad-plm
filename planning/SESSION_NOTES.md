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

### Fortschritt Browser-Upload

- `plm/forms.py` mit `RevisionUploadForm` angelegt.
- `plm/urls.py` angelegt und im Haupt-URLConf eingebunden.
- Erste serverseitige Views angelegt:
  - Projektliste
  - Projektdetail mit Teilen/Baugruppen
  - Teildetail mit Revisionen
  - POST-Upload fuer neue Revisionen
- Erste Templates unter `plm/templates/plm/` angelegt.
- Uploads sind login-geschuetzt und nutzen den bestehenden Upload-Service.
- Ungueltige Uploads werden im Formular angezeigt und erzeugen keine Revision.
- Tests fuer Login-Schutz, Upload-Formular, erfolgreichen Upload und fehlerhaften Upload wurden ergaenzt.
- `manage.py test plm` laeuft mit 12 Tests erfolgreich.
- Lokale Demo-Daten wurden angelegt:
  - Projekt `DEMO`
  - Teil `DEMO-001`

### Naechster Kleiner Schritt Nach Browser-Upload

Einen geschuetzten Download-Link fuer gespeicherte Revisionen bauen, damit Upload und spaeterer Zugriff zusammenpassen.

### Fortschritt Download Und Duplikatschutz

- Der Upload-Service blockiert jetzt Uploads, wenn fuer dasselbe Teil bereits eine Revision mit gleichem SHA-256 existiert.
- Die Teildetail-Seite zeigt fuer jede Revision einen Download-Link.
- `download_revision` liefert die Datei als Attachment mit Originaldateiname aus.
- Downloads sind login-geschuetzt.
- Jeder Download erzeugt ein `AuditEvent` mit Aktion `revision_downloaded`.
- Tests fuer Duplikatblockade, Login-Schutz beim Download und Download-Audit wurden ergaenzt.
- `manage.py test plm` laeuft mit 16 Tests erfolgreich.
- Lokaler Ist-Zustand: Die zwei vor der Regel hochgeladenen Demo-Revisionen sind Duplikate; neue Duplikate werden ab jetzt blockiert.

### Naechster Kleiner Schritt Nach Download

Den aktuellen Web-Upload/Download-Pfad im Browser testen und danach committen.

### Fortschritt Rollen

- `plm/permissions.py` angelegt.
- Rollen-Gruppen festgelegt:
  - `admin`
  - `editor`
  - `reader`
- Management-Command `setup_plm_roles` angelegt.
- Der Command erstellt die Gruppen und weist erste Django-Modellrechte zu:
  - `reader`: View-Rechte
  - `editor`: View/Add/Change-Rechte, keine Delete-Rechte
  - `admin`: alle PLM-Modellrechte
- Upload von Revisionen ist nur fuer Superuser, `admin` und `editor` erlaubt.
- `reader` sieht auf der Teildetail-Seite kein Upload-Formular und bekommt beim POST einen HTTP-403.
- Die lokalen Gruppen wurden mit `manage.py setup_plm_roles` angelegt.
- `manage.py test plm` laeuft mit 19 Tests erfolgreich.

### Naechster Kleiner Schritt Nach Rollen

Eine Freigabe-Aktion fuer Revisionen bauen: Entwurf zu `released`, mit Rollenpruefung und AuditEvent.
