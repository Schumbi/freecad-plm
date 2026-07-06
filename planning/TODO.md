# TODO

## Zweck

Diese Datei ist die operative Aufgabenliste. Sie soll kurz bleiben und den naechsten sinnvollen Schritt sichtbar machen.

## Jetzt

- V0-Browser-Abnahme aus `planning/ACCEPTANCE_CRITERIA.md` durchgehen.
- V1-Browser-Abnahme aus `planning/ACCEPTANCE_CRITERIA.md` starten, soweit die jeweilige Funktion bereits implementiert ist.
- Echten Analyse-/Exportlauf fuer STEP/STL/3MF mit Flatpak-FreeCADCmd oder gesetztem `FREECADCMD_COMMAND` testen.
- PNG-Ansichten auf einem spaeteren Server ohne Desktop mit `xvfb-run` oder separatem Preview-Worker pruefen.
- Management-Command `process_export_jobs` mit echten FCStd-Testdateien ausfuehren.
- Docker-Compose-Stack auf dem Zielserver mit echtem Media-Volume und PostgreSQL testen.
- FreeCAD-Addon-Prototyp gegen die neue `/api/`-Schnittstelle anhand `planning/FREECAD_ADDON_PLAN.md` bauen.
- Fehlende Suche fuer Projekte, Teile, Revisionen und Dateinamen entwerfen und umsetzen.
- Projektbearbeitung und Archivierung ausserhalb der Django-Admin-Oberflaeche entwerfen und umsetzen.
- Folgeausbau fuer VarSet-Parameterbearbeitung und Neurendern planen.
- ManufacturingRun-UI und Maschinenintegration fuer Bambu/andere Herstellungsmaschinen planen und umsetzen.
- 3D-Viewer im Browser mit echten FCStd-, STEP-, STL- und 3MF-Dateien auf der laufenden Instanz testen.
- STEP-/FCStd-Viewer-Preview-Erzeugung auf dem Server mit echtem FreeCADCmd-Worker gegen reale Dateien pruefen.

## Als Naechstes

- Browser-Abnahme mit lokalen Testnutzern dokumentieren.
- Danach V0-Status gegen die Akzeptanzkriterien bewerten.

## Spaeter

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
- Revisionscode-Format `R0001`, `R0002`, ... zentral in `plm/services.py` definiert und gegen nicht-kanonische Alt-/Testcodes abgesichert.
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
- Lokale PNG-Erzeugung mit Flatpak-FreeCAD-GUI-Binary verifiziert; Worker nutzt fuer PNG-Jobs automatisch `--command=FreeCAD`.
- Docker-Compose-Grundlage mit Web, PostgreSQL, Media-Volume und FreeCAD-Worker angelegt.
- JSON-API fuer FreeCAD-Addon-Grundworkflows angelegt.
- API-Token-Modell fuer Addon-Nutzung angelegt: gehashte Tokens, Scopes, Admin, Management-Command und Bearer-Auth fuer `/api/`.
- `/api/` auf token-only umgestellt; Django-Browser-Sessions reichen fuer API-Zugriff nicht mehr aus.
- Exklusiver Checkout mit Manifest, Check-in und Cancel angelegt.
- Objektbezogene Anmerkungen fuer Teile/Revisionen angelegt.
- Addon-Uebergabeplan mit API-Vertrag und Implementierungsvorgaben in `planning/FREECAD_ADDON_PLAN.md` angelegt.
- Manufacturing-Dateien fuer gedruckte Revisionen angelegt: Datenmodell, Upload, Download, 3MF-Basisvalidierung, Maschinenbezug und spaeter erweiterbare Fertigungslauf-/Anhangmodelle.
- Schwebenden 3D-Viewer fuer Revisionen, Artefakte und Fertigungsdateien angelegt; STL/3MF werden direkt angezeigt, FCStd/STEP nutzen ein gespeichertes STL-Preview-Artefakt.
