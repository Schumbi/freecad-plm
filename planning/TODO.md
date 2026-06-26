# TODO

## Zweck

Diese Datei ist die operative Aufgabenliste. Sie soll kurz bleiben und den naechsten sinnvollen Schritt sichtbar machen.

## Jetzt

- Upload im Browser erneut testen: gleicher Datei-Hash muss blockiert werden.
- Download-Link fuer gespeicherte Revisionen im Browser testen.
- Admin-Oberflaeche mit ersten Projekt-/Teil-/Revision-Daten pruefen.
- Reader-/Editor-Rollen im Browser mit Testnutzern pruefen.
- Freigabe-Button im Browser mit Admin/Superuser testen.
- Revisionsanmerkungen im Browser mit Editor und Reader testen.
- FreeCAD-Metadatenanzeige im Browser mit bestehenden Revisionen pruefen.
- Teil-/Baugruppenanlage mit initialer `.FCStd` im Browser testen.
- Projekt-ZIP-Import und Snapshot-Download im Browser testen.
- Baugruppen-Download mit Referenzen im Browser testen.

## Als Naechstes

- Revisionsnummern-Format verfeinern.
- Projekt-Anlage ausserhalb des Admins pruefen.
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
