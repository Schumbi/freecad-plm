# TODO

## Zweck

Diese Datei ist die operative Aufgabenliste. Sie soll kurz bleiben und den naechsten sinnvollen Schritt sichtbar machen.

## Jetzt

- V1-Browser-Abnahme gemaess `planning/V1_ACCEPTANCE.md` durchgehen und dokumentieren.
- V0-Browser-Abnahme aus `planning/ACCEPTANCE_CRITERIA.md` mitlaufen lassen, falls noch nicht erledigt.
- Echten Analyse-/Exportlauf fuer STEP/STL/3MF mit FreeCADCmd auf dem Zielserver abhaken.
- PNG-Ansichten, 3D-Preview und Revisionsvergleich auf der laufenden Instanz mit echtem Worker pruefen.
- FreeCAD-Addon End-to-End gegen die laufende Instanz einmal durchspielen.
- Docker-Compose-Stack und Backup-Strategie fuer `storage/` und PostgreSQL auf dem Zielserver festhalten.

## Als Naechstes

- Nach erfolgreicher Abnahme: Git-Tag `v1.0.0` und kurze Release-Notiz.
- VarSet-Parameterbearbeitung und ManufacturingRun-UI planen (V2/spaeter).

## Spaeter

- Weitere Exportformate und Jobmodell-Ausbau planen.
- Bulk-ZIP-Import aus `planning/BULK_IMPORT_PLAN.md` umsetzen.

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
- Einfache Freigabe-Aktion `draft` -> `released` fuer Revisionen angelegt.
- Freigabe auf Superuser und `admin` begrenzt.
- AuditEvent fuer freigegebene Revisionen umgesetzt.
- Freitext-Anmerkungen fuer Revisionen angelegt.
- Anmerkungen sind fuer eingeloggte Nutzer sichtbar und fuer Editor/Admin/Superuser editierbar.
- FreeCAD-Dokumentmetadaten aus `Document.xml` werden beim Upload extrahiert.
- FreeCAD-Metadaten werden pro Revision angezeigt.
- Teile und Baugruppen koennen in der Weboberflaeche innerhalb eines Projekts angelegt werden.
- Leere Teilenummern werden automatisch als `P-001`, `P-002`, ... pro Projekt vergeben.
- FreeCAD-Property `Id` wird als Dokumentmetadatum extrahiert.
- Teil-/Baugruppenanlage erfordert eine initiale `.FCStd` und erzeugt direkt `R0001`.
- Leere Teilenummer nutzt zuerst FreeCAD-`Id`, sonst automatische Nummerierung.
- Leerer Name nutzt FreeCAD-`Label`.
- Projektstaende/Snapshots fuer mehrere `FCStd`-Dateien aus ZIP angelegt.
- Snapshot-Download stellt die importierten relativen Pfade wieder als ZIP her.
- FreeCAD-`XLink`-Referenzen werden extrahiert.
- Einzeldatei-Download aus Snapshot kann rekursiv referenzierte `FCStd`-Dateien als ZIP mitnehmen.
- `test-model/` wird ignoriert.
- Revisionscode-Format `R0001`, `R0002`, ... zentral im Paket `plm/services/` definiert und gegen nicht-kanonische Alt-/Testcodes abgesichert.
- FreeCAD-Property `PLMRevision` wird extrahiert und beim Revisionsupload gegen den PLM-Revisionscode geprueft.
- Revisionsupload kann fehlende oder abweichende `PLMRevision` als normalisierte FCStd-Kopie speichern.
- Projekte koennen von `admin` und Superuser ausserhalb der Django-Admin-Oberflaeche angelegt werden.
- Normaler Download einer referenzierten FCStd-Revision liefert ein ZIP mit rekursiv referenzierten Dateien oder wird ohne Snapshot-Kontext blockiert.
- Akzeptanzkriterien fuer V0 und V1 formuliert.
- FreeCADCmd-Jobmodell fuer Analyse, Export und PNG-Ansichten angelegt.
- Revision-Artefakte fuer STEP, STL, 3MF und PNG angelegt.
- Artefaktdownloads und visueller PNG-Vergleich von Revisionen angelegt.
- Upload-Aenderungsnotiz als Revisionsnotiz und Audit-Metadatum umgesetzt.
- Lokaler Flatpak-FreeCADCmd-Aufruf ohne Desktop-GUI mit `--command=FreeCADCmd` verifiziert.
- PNG-Erzeugung auf deterministisches STL-Mesh-Rendering ohne FreeCAD-GUI-Viewport umgestellt.
- Docker-Compose-Grundlage mit Web, PostgreSQL, Media-Volume und FreeCAD-Worker angelegt.
- JSON-API fuer FreeCAD-Addon-Grundworkflows angelegt.
- API-Token-Modell fuer Addon-Nutzung angelegt: gehashte Tokens, Scopes, Admin, Management-Command und Bearer-Auth fuer `/api/`.
- `/api/` auf token-only umgestellt; Django-Browser-Sessions reichen fuer API-Zugriff nicht mehr aus.
- Exklusiver Checkout mit Manifest, Check-in und Cancel angelegt.
- Objektbezogene Anmerkungen fuer Teile/Revisionen angelegt.
- Addon-Uebergabeplan mit API-Vertrag und Implementierungsvorgaben in `planning/FREECAD_ADDON_PLAN.md` angelegt.
- FreeCAD-Addon-Grundworkflow gegen die `/api/`-Schnittstelle umgesetzt: Verbinden, Lesen, read-only Oeffnen, Checkout, Check-in, Cancel, aktive Checkouts, Notizen, Anmerkungen, Teilanlage, Projektmetadaten und Projektimport.
- Projektbearbeitung und Archivierung ausserhalb der Django-Admin-Oberflaeche umgesetzt.
- Bestehende FreeCAD-Ordnerimport-Funktion fuer das Addon umgesetzt und dokumentiert.
- Manufacturing-Dateien fuer gedruckte Revisionen angelegt: Datenmodell, Upload, Download, 3MF-Basisvalidierung, Maschinenbezug und spaeter erweiterbare Fertigungslauf-/Anhangmodelle.
- Schwebenden 3D-Viewer fuer Revisionen, Artefakte und Fertigungsdateien angelegt; STL/3MF werden direkt angezeigt, FCStd/STEP nutzen ein gespeichertes STL-Preview-Artefakt.
- Upload-/ZIP-Budgets fuer FCStd, Projekt-ZIP und 3MF eingefuehrt; grobe DoS-/Zip-Bomb-Grenzen liegen jetzt als konfigurierbare `PLM_MAX_*`-Werte in den Settings.
- Worker-Container im Compose gehärtet: keine Linux-Caps, `no-new-privileges`, read-only Root-FS, `tmpfs` fuer `/tmp` und `/var/tmp`, sowie einfache CPU-/RAM-/PID-Limits.
- Snapshot-Projektprüfung im Checkout-API-Pfad umgesetzt; fremde `snapshot_id`-Werte liefern jetzt `404`.
- XML-Parserpfade fuer FCStd, technische Signaturen und 3MF-Configs auf `defusedxml` umgestellt; gefaehrliche `Document.xml`-Inhalte werden jetzt mit `ValidationError` abgewiesen.
- Eigene PLM-Login-Seite unter `/login/` umgesetzt; Logout und Login fuehren in das PLM-WebUI statt in den Django-Admin.
- Web-UI modernisiert: App-Shell, Sidebar, Job-Panel, seitenlokale Listenfilter.
- Hintergrundjobs des Nutzers in der Sidebar mit Live-Polling (`GET /jobs/status/`).
- Revisionsvergleich mit Live-Status und Auto-Reload bei laufenden PNG-Jobs.
- Auto-Queue fuer Analyse- und PNG-Jobs nach Upload, Import und API-Check-in (`plm/derivatives.py`).
- Recovery haengengebliebener Exportjobs (`EXPORT_JOB_STALE_SECONDS`).
- Globale PLM-Suche unter `/search/` fuer Projekte, Teile, Revisionen und Dateipfade in Projektstaenden.
- Freigegebene Revisionen koennen in der Web-UI als obsolet markiert werden (`revision_obsoleted` im Audit-Trail).
- Forgejo-CI fuehrt vor dem Push die 194 Tests im gebauten Image aus; Testlauf durch MD5-Hasher im Testmodus und `--parallel` von ~266s auf wenige Sekunden beschleunigt.
- Web- und Worker-Image als getrennte Docker-Targets; Web ohne FreeCAD, Worker mit dem offiziellen, per SHA-256 gepinnten FreeCAD-1.1.1-AppImage; CI baut/pusht beide Images.
- Kernmodule `services.py`, `views.py` und `api.py` in Pakete `plm/services/`, `plm/views/`, `plm/api/` mit re-exportierender Fassade aufgeteilt (Finding 2.1 / A5).
