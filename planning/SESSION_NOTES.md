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

### Fortschritt Einfache Freigabe

- `can_release_revision()` ergaenzt.
- Service-Funktion `release_revision()` angelegt.
- Revisionen koennen von `draft` auf `released` gesetzt werden.
- `released_at` wird beim Freigeben gesetzt.
- Freigabe erzeugt ein `AuditEvent` mit Aktion `revision_released`.
- Freigabe ist auf Superuser und Rolle `admin` begrenzt.
- Die Teildetail-Seite zeigt fuer Draft-Revisionen einen Button `Freigeben`, wenn der Nutzer freigeben darf.
- Tests fuer Service, Login-Schutz, Superuser-Freigabe und Editor-Verbot wurden ergaenzt.
- `manage.py test plm` laeuft mit 24 Tests erfolgreich.
- Scope-Entscheidung: Vorerst bleibt es bei dieser einfachen Freigabe. Kein mehrstufiger Review- oder Approval-Workflow.

### Naechster Kleiner Schritt Nach Einfacher Freigabe

Freigabe im Browser testen und danach committen. Danach wieder auf Nutzbarkeit konzentrieren, nicht auf mehr Prozess-Tiefe.

### Fortschritt Revisionsanmerkungen

- `Revision.notes` als Freitextfeld angelegt.
- Teildetail zeigt pro Revision einen aufklappbaren Bereich `Anmerkungen`.
- Eingeloggte Nutzer koennen vorhandene Anmerkungen lesen.
- Superuser, `admin` und `editor` koennen Anmerkungen bearbeiten.
- `reader` kann Anmerkungen lesen, aber nicht bearbeiten.
- Jede Aenderung erzeugt ein `AuditEvent` mit Aktion `revision_notes_updated`.
- Migration `plm.0002_revision_notes_alter_auditevent_action` wurde erstellt und lokal angewendet.
- `manage.py test plm` laeuft mit 27 Tests erfolgreich.

### Naechster Kleiner Schritt Nach Revisionsanmerkungen

Revisionsanmerkungen im Browser testen und danach committen.

### Fortschritt FreeCAD-Metadaten

- `validate_fcstd_upload()` extrahiert jetzt Metadaten aus `Document.xml`.
- Erfasste Werte:
  - SchemaVersion
  - ProgramVersion
  - FileVersion
  - Label
  - Comment
  - Company
  - CreatedBy
  - CreationDate
  - LastModifiedBy
  - LastModifiedDate
  - License
  - LicenseURL
  - Uid
- Die Metadaten werden in `Revision.extracted_metadata["freecad_document"]` gespeichert.
- Die Teildetail-Seite zeigt pro Revision einen aufklappbaren Bereich `FreeCAD` / `Metadaten`.
- Bestehende lokale Revisionen wurden aus den gespeicherten `.FCStd`-Dateien nachgezogen.
- `manage.py test plm` laeuft mit 28 Tests erfolgreich.

### Naechster Kleiner Schritt Nach FreeCAD-Metadaten

Metadatenanzeige im Browser pruefen und danach committen.

### Fortschritt Teil-/Baugruppenanlage Im Web

- `PartForm` angelegt.
- Projekt-Detailseite zeigt fuer berechtigte Nutzer einen Link `Neues Teil oder Baugruppe anlegen`.
- Neue Route `projects/<project_id>/parts/new/` angelegt.
- `editor`, `admin` und Superuser koennen Teile/Baugruppen anlegen.
- `reader` darf keine Teile/Baugruppen anlegen.
- Doppelte Teilenummern innerhalb eines Projekts werden im Formular abgefangen.
- Die Anlage erfordert jetzt eine initiale `.FCStd`-Datei.
- Beim Anlegen wird direkt die erste Revision `R0001` erzeugt.
- Wenn die Teilenummer leer bleibt, nutzt das PLM zuerst FreeCAD-`Id`; wenn keine `Id` vorhanden ist, erzeugt es automatisch die naechste Nummer im Format `P-001`, `P-002`, ...
- Wenn der Name leer bleibt, nutzt das PLM FreeCAD-`Label`.
- Die FreeCAD-Property `Id` wird beim Upload mit aus `Document.xml` extrahiert.
- Beim Anlegen wird ein `AuditEvent` mit Aktion `part_created` geschrieben.
- `test-model/` wurde in `.gitignore` aufgenommen.
- `manage.py test plm` laeuft mit 35 Tests erfolgreich.

### Naechster Kleiner Schritt Nach Teilanlage

Browser-Test der Teilanlage, danach committen. Danach V0-Akzeptanzkriterien formulieren.

### Fortschritt Projektstaende / ZIP-Snapshots

- Modelle `ProjectSnapshot` und `ProjectSnapshotEntry` angelegt.
- Ein Projektstand speichert eine Sammlung konkreter Revisionen mit ihren relativen ZIP-Pfaden.
- Projekt-ZIP-Import angelegt:
  - liest alle `.FCStd`-Dateien aus einem ZIP
  - legt passende Teile/Baugruppen an, falls sie noch fehlen
  - erzeugt oder nutzt passende Revisionen
  - erzeugt einen Snapshot mit Dateipfad -> Revision-Zuordnung
- Snapshot-Download erzeugt wieder ein ZIP mit den gespeicherten relativen Pfaden.
- Download einer einzelnen Snapshot-Datei mit Referenzen angelegt.
- Die Referenzauflösung bleibt im Snapshot-Kontext und sammelt rekursiv `XLink`-Referenzen ein.
- FreeCAD-Dokumentanalyse erkennt:
  - `assembly`, wenn `Assembly::AssemblyObject` vorhanden ist
  - `parameters`, wenn `App::VarSet` vorhanden ist
  - sonst `part`

- FreeCAD-`XLink`-Referenzen werden extrahiert.
- Echter Testimport von `test-model/Sommerrodelbahn-Chipbox.zip`:
  - `Box.FCStd`: part, referenziert u.a. `Chip.FCStd`
  - `Chip.FCStd`: parameters
  - `Deckel.FCStd`: part, referenziert `Chip.FCStd`
  - `Druck.FCStd`: assembly, referenziert `Box.FCStd` und `Deckel.FCStd`
  - `Zusammenbau.FCStd`: assembly, referenziert `Box.FCStd` und `Deckel.FCStd`
- Referenzdownload fuer `Druck.FCStd` im echten Snapshot sammelt:
  - `Box.FCStd`
  - `Chip.FCStd`
  - `Deckel.FCStd`
  - `Druck.FCStd`
- `manage.py test plm` laeuft mit 43 Tests erfolgreich.

### Naechster Kleiner Schritt Nach Snapshots

Projekt-ZIP-Import und Snapshot-Download im Browser testen, danach committen.

### Fortschritt Revisionscode-Format

- Das kanonische Revisionsformat ist jetzt zentral in `plm/services.py` definiert:
  - Prefix `R`
  - vierstellige Nummer
  - gueltiger Bereich `R0001` bis `R9999`
- `next_revision_code(part)` ignoriert nicht-kanonische Alt-/Testcodes bei der Nummernermittlung.
- Beim Ueberschreiten von `R9999` wird eine klare `ValidationError` ausgeloest.
- `planning/DECISIONS.md` dokumentiert die Formatentscheidung.
- `planning/TODO.md` fuehrt den zugehoerigen TODO-Punkt unter `Erledigt`.
- `.venv/bin/python manage.py test plm` laeuft mit 43 Tests erfolgreich.

### Fortschritt PLMRevision-Abgleich

- FreeCAD-Property `PLMRevision` wird aus `Document.xml` extrahiert.
- Das PLM bleibt fuehrend fuer Revisionscodes; `Id` bleibt Teil-/Dokumentkennung.
- Beim normalen Revisionsupload wird `PLMRevision` gegen den erwarteten PLM-Code geprueft.
- Fehlt `PLMRevision` oder weicht sie ab, zeigt die Weboberflaeche eine Bestaetigungsseite.
- Nutzer koennen den Upload verwerfen oder eine PLM-normalisierte Kopie speichern.
- Die Normalisierung passt nur `Document.xml` im gespeicherten FCStd-ZIP an.
- Original-Hash, hochgeladener Wert, erwarteter Wert und gespeicherter Hash werden in Metadaten und AuditEvent festgehalten.
- Projekt-ZIP-Import normalisiert nicht interaktiv, damit Snapshots reproduzierbar importierbar bleiben; unveraenderte Rohdateien werden ueber den Original-Hash wiedererkannt.
- `.venv/bin/python manage.py test plm` laeuft mit 50 Tests erfolgreich.

### Fortschritt Projektanlage In Der PLM-Oberflaeche

- Projektliste zeigt fuer Superuser und Rolle `admin` den Link `Neues Projekt anlegen`.
- Route `projects/new/` und `ProjectForm` angelegt.
- Projektanlage schreibt ein `AuditEvent` mit Aktion `project_created`.
- `editor` und `reader` duerfen keine Projekte anlegen.
- Test-Fixtures fuer ZIP-/FCStd-Dateien schreiben feste ZIP-Zeitstempel, damit Hash-basierte Snapshot-Reuse-Tests deterministisch bleiben.
- `.venv/bin/python manage.py test plm` laeuft mit 54 Tests erfolgreich.

### Fortschritt Referenzierter FCStd-Download

- Der separate Link `mit Referenzen herunterladen` wurde wieder entfernt.
- Der normale Revisionsdownload ist die einzige Download-Aktion fuer einzelne Revisionen.
- Revisionen ohne FreeCAD-Referenzen bleiben beim bisherigen FCStd-Einzeldownload.
- Revisionen mit FreeCAD-Referenzen werden nur zusammen mit ihren rekursiv referenzierten Dateien heruntergeladen.
- Wenn ein Snapshot-Kontext vorhanden ist, liefert `download_revision` ein ZIP mit der Datei und den referenzierten Dateien aus demselben Snapshot.
- Wenn eine Revision Referenzen hat, aber kein Snapshot-Kontext vorhanden ist, blockiert der Download mit HTTP 403 statt eine unvollstaendige Einzeldatei auszugeben.
- AuditEvent fuer Downloads speichert `download_mode` als `single_file` oder `referenced_zip`.
- `.venv/bin/python manage.py test plm` laeuft mit 55 Tests erfolgreich.

## 2026-06-27

### Planung Aufgeraeumt

- Die Planungsdateien wurden in der in `planning/README.md` beschriebenen Reihenfolge gelesen.
- `planning/ACCEPTANCE_CRITERIA.md` wurde angelegt.
- V0-Akzeptanzkriterien beschreiben jetzt den lokalen Kernpfad fuer einzelne `.FCStd`-Revisionen.
- V1-Akzeptanzkriterien beschreiben den Zielzustand fuer ein nutzbares LAN-PLM inklusive Projektstaenden, PLMRevision-Konfliktbehandlung und Suche.
- `planning/README.md`, `planning/ROADMAP.md` und `planning/TODO.md` wurden auf die neue Akzeptanzkriterien-Datei abgestimmt.
- `manage.py test plm` lief mit 55 Tests erfolgreich.

### Aktueller Fokus

- Als naechstes die V0-Browser-Abnahme mit lokalen Testnutzern durchgehen.
- Danach fehlende V1-Funktionen priorisieren, insbesondere Suche sowie Projektbearbeitung und Archivierung in der PLM-Oberflaeche.

### Fortschritt FreeCADCmd-Artefakte

- `ExportJob` und `RevisionArtifact` wurden angelegt.
- FreeCADCmd-Aufruf ist ueber `FREECADCMD_COMMAND` konfigurierbar; Default ist `FreeCADCmd` mit Flatpak-Fallback auf `org.freecad.FreeCAD`.
- Management-Command `process_export_jobs` verarbeitet wartende Jobs.
- Analysejobs lesen exportierbare Objekte und VarSet-Parameter in `Revision.extracted_metadata["freecadcmd"]`.
- Exportjobs erzeugen STEP-, STL- oder 3MF-Artefakte fuer ausgewaehlte Objekte.
- PNG-Jobs erzeugen die Standardansichten front, back, left, right, top, bottom und isometric.
- Revisionsseite zeigt Jobs, Artefakte, PNG-Galerie und VarSet-Anzeige.
- Vergleichsseite zeigt gleichnamige PNG-Ansichten zweier Revisionen desselben Teils nebeneinander.
- Uploads koennen eine Aenderungsnotiz erfassen; sie landet in `Revision.notes` und im AuditEvent.
- Lokaler Hinweis: natives `FreeCADCmd` wurde auf dem System nicht im PATH gefunden, aber `flatpak run --branch=stable --arch=x86_64 --command=FreeCADCmd org.freecad.FreeCAD --version` liefert FreeCAD 1.1.1.
- Der Flatpak-Aufruf mit `--command=FreeCADCmd` ist fuer CLI-/Headless-Verarbeitung geeignet; der Desktop-Launcher mit `--command=FreeCAD --file-forwarding ... --single-instance` ist dafuer nicht der passende Pfad.
- STEP/STL/3MF sollten ueber FreeCADCmd ohne normale GUI erzeugbar sein.
- PNG-Ansichten sind riskanter, weil sie typischerweise `FreeCADGui`/Viewport brauchen; auf dem spaeteren Heimserver muss Offscreen-Rendering separat geprueft werden.
- `.venv/bin/python manage.py test plm` laeuft mit 60 Tests erfolgreich.

### Fix PNG-Erzeugung Mit Flatpak-FreeCAD

- Ursache 1: FreeCADCmd wurde mit Script- und JSON-Pfaden als normale Dateiargumente gestartet; FreeCAD versuchte dadurch `job_spec.json` als Dokument zu oeffnen.
- Ursache 2: Flatpak konnte die Worker-Dateien unter `/tmp` ohne `--filesystem=/tmp` nicht lesen.
- Ursache 3: PNG-Jobs brauchen `FreeCADGui`; mit Flatpak muss dafuer der GUI-Binary `FreeCAD` statt `FreeCADCmd` verwendet werden.
- Ursache 4: `runpy.run_path()` verhindert in FreeCAD 1.1.1, dass `FreeCADGui.showMainWindow()` sauber ein MainWindow erzeugt; direkter `exec(compile(...))` funktioniert.
- Ursache 5: `ActiveView.viewDirection()` existiert in FreeCAD 1.1.1 nicht; die fertigen View-Methoden wie `viewFront()`, `viewTop()` und `viewIsometric()` funktionieren.
- Der Worker schreibt jetzt das ausgefuehrte Kommando und Display-Umgebung in den Job-Log.
- Lokaler echter Lauf mit Flatpak FreeCAD 1.1.1 erzeugte erfolgreich sieben PNG-Artefakte fuer einen Job: front, back, left, right, top, bottom und isometric.
- Hinweis: Flatpak-FreeCAD segfaultet lokal beim Beenden nach GUI-Nutzung, aber erst nachdem die Ergebnisdatei geschrieben ist; der Worker akzeptiert deshalb vorhandene Ergebnisdaten trotz nicht-null Exitcode.
- `.venv/bin/python manage.py test plm` laeuft mit 61 Tests erfolgreich.

### Neuer Headless-Pfad Fuer PNG-Ansichten

- PNG-Jobs nutzen keinen `FreeCADGui`-/Viewport-Pfad mehr.
- FreeCADCmd oeffnet die FCStd-Datei, exportiert ein STEP-Artefakt und ein temporaeres STL-Vorschau-Mesh.
- Das PLM rendert daraus selbst feste PNG-Ansichten fuer front, back, left, right, top, bottom und isometric.
- Referenzierte FCStd-Dateien aus demselben Projekt werden vor dem FreeCADCmd-Aufruf in den temporaeren Arbeitsordner kopiert.
- Lokaler echter Lauf mit Flatpak FreeCAD 1.1.1 erzeugte erfolgreich ein STEP-Artefakt plus sieben PNG-Artefakte ohne fehlende Link-Warnungen.
- `.venv/bin/python manage.py test` laeuft mit 83 Tests erfolgreich.

### PNG-Button Verarbeitet Direkt

- Nutzerbeobachtung: Klick auf `PNG-Ansichten` wirkte, als passiere nichts.
- Ursache: Die View legte nur einen `png_views`-Job an; ohne separaten Lauf von `process_export_jobs` blieb der Job auf `queued`.
- Fuer den lokalen Prototyp verarbeitet der Button `PNG-Ansichten` den Job jetzt direkt per `process_export_job(job)`.
- Bei Erfolg erscheint eine Erfolgsmeldung, bei Fehlern bleibt der Job-Fehler sichtbar und die Oberflaeche meldet den Fehlschlag.
- Echter lokaler POST auf `create_revision_png_job` erzeugte direkt einen erfolgreichen Job und sieben PNG-Artefakte.
- `.venv/bin/python manage.py test plm` laeuft mit 63 Tests erfolgreich.

### Einmaliger Worker-Knopf In Der Oberflaeche

- Auf der Teildetailseite gibt es fuer Editor/Admin/Superuser jetzt den Button `Wartende Jobs starten`.
- Der Button ruft `process_queued_export_jobs()` einmalig auf und verarbeitet alle aktuell wartenden Jobs.
- Die Rueckmeldung nennt Anzahl, erfolgreiche Jobs und fehlgeschlagene Jobs.
- Damit lassen sich Analyse- und Exportjobs ohne Terminal aus der Oberflaeche abarbeiten.
- `.venv/bin/python manage.py test plm` laeuft mit 64 Tests erfolgreich.

## 2026-06-28

### Server- Und Addon-Grundlage

- Dockerfile und `docker-compose.yml` fuer einen Serverbetrieb mit `web`, PostgreSQL, persistentem Media-Volume und separatem FreeCAD-Worker angelegt.
- Django-Settings lesen jetzt `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` und PostgreSQL-Umgebungsvariablen, bleiben ohne PostgreSQL aber SQLite-kompatibel.
- `Checkout` als exklusiver Lock pro Teil/Baugruppe angelegt.
- Checkouts speichern Basisrevision, optionalen Projektstand/Snapshot, Bearbeiter, Status und abgeschlossene Revision.
- Checkout-Manifeste liefern Root-Datei, snapshot-genaue Abhaengigkeiten, relative Pfade, Revisionen, Hashes und Dateigroessen.
- Check-in erzeugt immer eine neue unveraenderliche Revision und beendet den Checkout.
- `Annotation` fuer Anmerkungen an Teil, optional Revision, FreeCAD-Objektname und Subelement angelegt.
- Erste JSON-API unter `/api/` fuer Projekte, Teile, Revisionen, Dateien, Checkout, Check-in, Cancel und Anmerkungen angelegt.
- Die API nutzt zunaechst bestehende Django-Logins; Addon-spezifische Token-Authentifizierung bleibt ein spaeterer Schritt.
- `.venv/bin/python manage.py test plm` laeuft mit 69 Tests erfolgreich.

### FreeCAD-Addon-Uebergabeplan

- `planning/FREECAD_ADDON_PLAN.md` angelegt.
- Das Dokument beschreibt Zielbild, Addon-Repo-Struktur, Konfiguration, API-Vertrag, Checkout-/Check-in-Workflow, lokale Workspace-Regeln, UI-Anforderungen, Implementierungsbausteine und Tests.
- Zweck: Eine neue Codex-Instanz kann daraus ein separates FreeCAD-Addon fuer die vorhandene Server-API bauen.

## 2026-07-01

### Manufacturing-Dateien Fuer Gedruckte Revisionen

- `ManufacturingMachine`, `ManufacturingFile`, `ManufacturingRun` und `ManufacturingRunAttachment` angelegt.
- Manufacturing-Dateien haengen an einer Revision und speichern Slicer-/Druckdateien wie 3MF, G-Code, BGCode, STL, STEP oder PDF inklusive Hash, Groesse, Status, Material, Slicer und optionalem Maschinenbezug.
- 3MF-Uploads werden als ZIP-Container geprueft und mit einfacher Inhaltsinventur gespeichert.
- Die Teildetailseite zeigt pro Revision einen Fertigungsdialog mit Upload, Liste, Download und Obsolet-Aktion.
- `ManufacturingRun` und Attachments sind modellseitig vorbereitet, damit spaeter ein Bambu-/Maschinenanschluss Bilder, Logs und Reports einem konkreten Fertigungslauf zuordnen kann.
- Projektloeschung raeumt Manufacturing-Dateien und spaetere Run-Anhaenge aus Storage und Datenbank auf.
- `.venv/bin/python manage.py test plm` laeuft mit 97 Tests erfolgreich.

## 2026-07-02

### 3D-Viewer Fuer Modell-Dateien

- Three.js 0.160.0 wurde lokal unter `plm/static/plm/vendor/three/` abgelegt.
- Globaler schwebender Dialog `3D-Modell` in `base.html` angelegt.
- `plm/static/plm/model-viewer.js` rendert STL und 3MF mit OrbitControls, Auto-Fit, Reset und Drahtgitter-Umschaltung.
- Die Teildetailseite zeigt separate Buttons `3D anzeigen` fuer:
  - Revisionen
  - viewerfaehige Artefakte
  - viewerfaehige Fertigungsdateien
- Neue Viewer-Quellendpunkte angelegt:
  - `revision_viewer_source`
  - `artifact_viewer_source`
  - `manufacturing_file_viewer_source`
- Direkte STL- und 3MF-Dateien werden inline an den Browser-Viewer geliefert.
- FCStd- und STEP-Kontexte nutzen ein gespeichertes STL-Preview-Artefakt der Revision.
- Der bestehende PNG-/Preview-Job speichert das temporaere STL-Mesh jetzt zusaetzlich als `RevisionArtifact` mit `artifact_type=stl` und `view_name=viewer-preview`.
- Neuer Button/Endpunkt `3D-Vorschau erzeugen` nutzt die bestehende PNG-/Preview-Pipeline, damit FCStd-Revisionen eine 3D-Viewer-Quelle bekommen.
- Windows-Kompatibilitaet verbessert:
  - `FREECADCMD_COMMAND` nutzt auf Windows passendes `shlex.split(..., posix=False)`.
  - `.py`-Kommandos werden fuer Tests ueber den aktuellen Python-Interpreter ausgefuehrt.
  - FieldFile-Reads werden nach dem Lesen wieder geschlossen, wenn die Datei vorher geschlossen war.
- Lokale `.venv` wurde auf Windows angelegt und `requirements.txt` installiert.
- `node --check plm/static/plm/model-viewer.js` ist gruen.
- `manage.py check` ist gruen.
- `manage.py test plm` laeuft mit 107 Tests erfolgreich.
