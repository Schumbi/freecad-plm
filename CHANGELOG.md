# Changelog

Alle wesentlichen Änderungen am FreeCAD-PLM-Server werden in dieser Datei
dokumentiert.

## [0.2.0] - 2026-09-16

### Hinzugefügt

- Projektbezogene Druckprojekte mit einer primären CAD-Revision, zusätzlichen
  PLM-Revisionen oder externen STL-Dateien als Quellen und einem gemeinsamen,
  veränderlichen 3MF-Arbeitsstand.
- Druckplatten, Vorschaubilder und Snapshots für Druckprojekte sowie API- und
  Web-Ansichten für Quellen, 3MF-Upload und Download.
- Nachverfolgbare Quellenzuordnung für Druckprojekte einschließlich lokaler
  CAD-Dateien und Revisionen aus demselben PLM-Projekt.
- STEP- und STL-Dateien als primäre Teilrevisionen mit schreibgeschütztem
  Öffnen im FreeCAD-Addon.
- Bambuddy-Anbindung für den sicheren Source-3MF-Upload und einen Link vom
  Druckarchiv zur eindeutig zugeordneten PLM-Revision. Synchronisationen sind
  standardmäßig deaktiviert und unterstützen einen Dry-Run.
- Kompatibilitäts-API für revisionsgebundene Slicer-Arbeitsstände älterer
  Addon-Versionen.
- Bestätigte Admin-Löschung für temporäre Fertigungsdateien einschließlich
  Storage-Bereinigung und Audit-Eintrag; von Fertigungsläufen verwendete
  Dateien bleiben geschützt.

### Geändert

- Projektsuche und Revisionsabläufe wurden erweitert; CAD- und
  Fertigungsdateien lassen sich per Drag-and-drop hochladen.
- Bambuddy-Drucknamen enthalten den Projektbezug, wobei ältere Namen weiterhin
  erkannt werden.
- Der Worker startet erst nach erfolgreicher Zustandsprüfung der Webanwendung.

### Behoben

- 3MF-Dateien ohne verwertbare Geometrie werden nicht als gültiger
  Slicer-Arbeitsstand übernommen.
- Die Bambuddy-Anbindung unterstützt die Antwortformate und Download-Routen
  der produktiv eingesetzten Version.
- Technische FreeCAD-Build-Metadaten erzeugen keine unnötigen Revisionen.

### Qualität

- 301 automatisierte Servertests; unter SQLite davon 4 erwartete Fehlschläge
  für offene Review-Befunde und ein übersprungener PostgreSQL-Paralleltest.
- Deaktivierte Benutzer werden bei der API-Token-Authentifizierung abgewiesen;
  abgewiesene Tokens aktualisieren den Zeitstempel `last_used_at` nicht.
- 8 zusätzliche HTTP-Vertragstests mit dem echten Addon-Client, separat über
  `scripts/run_contract_tests.py` ausführbar.
- Regressionstests für Tokens, plattformübergreifende Pfade, Upload-Konflikte,
  3MF-Geometrie und den Dateilebenszyklus; Transaktions- und CSRF-Tests für das
  Entfernen temporärer Fertigungsdateien.
- API-Tests für Druckprojekte, Quellen, Druckplatten und Bambuddy-Synchronisation.

## [0.1.0] - 2026-07-20

Erste versionierte Serververöffentlichung.

### Hinzugefügt

- Projekte, Teile und Baugruppen mit unveränderlichen FCStd-Revisionen,
  Revisionsstatus, Freigaben und Audit-Trail.
- Exklusive Projekt-Checkouts mit Manifest, Check-in, Abbruch sowie dem
  nachträglichen Hinzufügen und Entfernen von Nebenteilen.
- Token-geschützte JSON-API für das FreeCAD-Addon einschließlich Projektimport,
  Revisionsnotizen und objektbezogenen Anmerkungen.
- Projektstände aus ZIP-Dateien, rekursive FreeCAD-Verknüpfungen und Downloads
  mit wiederhergestellter Verzeichnisstruktur.
- Hintergrundverarbeitung mit FreeCADCmd für Analyse, STEP-, STL-, 3MF- und
  PNG-Artefakte.
- Web-UI mit Suche, Revisionsvergleich, responsiver 3D-Vorschau,
  Fertigungsdateien sowie Benutzer- und Tokenverwaltung.
- Anzeige der FreeCAD-Anmerkungen in der Teileansicht mit Status,
  Revisionsbezug, Objekt, Subelement und Urheber.
- Getrennte, gehärtete Docker-Images für Webanwendung und FreeCAD-Worker sowie
  automatisierte Tests und Image-Builds in Forgejo Actions.

### Behoben

- Vorschauen und Vergleiche älterer Revisionen verwenden den historischen
  Projektstand statt der aktuellen Revision.
- Robustere Auswahl exportierbarer FreeCAD-Objekte und bessere Unterstützung
  externer Modellteile in 3MF-Vorschauen.
- FreeCADCmd läuft im gehärteten Worker mit einem beschreibbaren temporären
  Home-Verzeichnis.

### Qualität

- 196 automatisierte Servertests.
- XML-Verarbeitung mit `defusedxml`, Upload- und ZIP-Größenlimits sowie
  token-only Authentifizierung für die Addon-API.
