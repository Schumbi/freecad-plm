# Changelog

Alle wesentlichen Änderungen am FreeCAD-PLM-Server werden in dieser Datei
dokumentiert.

## [Unreleased] - 2026-11-14

- **GLB-Vorschau:** Der Worker erzeugt zusätzlich zum 3MF ein binäres GLB
  (Positionen/Indizes, Farbe je Solid). Der Viewer lädt GLB bevorzugt und
  berechnet Normals im Client. Messung am 4,4-MB-3MF: Parsing 4,6 s → 0,08 s,
  Zeit bis zum Modell inkl. Download/Render < 0,5 s. 3MF bleibt Fallback.

### 3D-Anzeige beschleunigt

- 3D-Artefakte werden mit `ETag` und `Cache-Control` ausgeliefert; erneutes
  Öffnen lädt nur noch 304-Header statt mehrerer Megabyte.
- Der Viewer zeigt das erste Bild vor der teuren Kantengeometrie und lädt
  Anmerkungen asynchron nach. Die Vorschau-Warteschlange fragt im
  Sekundentakt statt alle drei Sekunden.
- Ein neuer, schlanker `viewer`-Job erzeugt beim ersten Öffnen nur das
  3MF statt zusätzlich sieben PNG-Ansichten (Messung: 3,3 s statt
  durchschnittlich 35,6 s bei bestehenden `png_views`-Jobs).
- `manage.py backfill_viewer_previews` listet veraltete Vorschauen und legt
  mit `--apply` Hintergrundjobs an.

### UX-, Usability- und Accessibility-Überarbeitung

Grundlage: `planning/UX_AUDIT_2026-11-14.md`. Alle Änderungen sind mit
`UX QW-*`, `UX HI-*`, `UX ST-*` bzw. `UX OP-*` committet.

- Globales Suchfeld wieder lesbar (Padding/Spezifität), einheitliche
  Fokusringe und WCAG-AA-Kontraste für Primäraktionen und Sekundärtext.
- Aktiver Arbeitsbereich in der Navigation inkl. `aria-current`; sprechende
  Seitentitel und bereichsrichtige Breadcrumbs.
- Responsive Korrekturen: Revisionskarte und Seitenkopf stapeln unter
  1500 px, mobile Navigation als Off-Canvas-Drawer (standardmäßig zu,
  Zustand gemerkt), mobile Kopfzeile mit Such-Overlay und Benutzermenü.
- Formulare: Pflichtfeldmarker, Fehlerzusammenfassung, `aria-invalid`,
  eindeutige Feld-IDs in Dialogen, Labels ohne Doppelpunkt, echte Umlaute,
  gruppiertes Fertigungsformular mit eingeklappten Prozessparametern.
- Tabellen und Listen: Teilezeilen mit echten Links (Tastatur/neuer Tab),
  Aktionsspalte in der Projektliste, Dateityp-Filter in der Dateiübersicht.
- Aktionen: destruktive Aktionen aus der Primärreihe in Menüs, Bestätigung
  für Obsolet-Markierungen, Projekte per Dialog verschiebbar.
- Suche/Filter: ein Suchfeld, Facetten greifen sofort, aktive Filter als
  entfernbare Chips, Leerzustände mit Aktionen.
- Statusmeldungen als Live-Region; Fehler bleiben stehen; Skip-Link;
  Aktivitätsprotokoll in der Verwaltung; Tastaturkürzel (`/`, `g p`,
  `g v`, `?`); Druckansicht; `prefers-reduced-motion`.
- Neue Dokumentation: `planning/UI_COMPONENTS.md`, `planning/GLOSSARY.md`.
- Neue Regressionstests: `plm/test_ux_accessibility.py`.

## [2026-10-09]

- Teile-Tags sind strukturiert: zentrales `PartTag`-Modell, Migration der
  bisherigen kommagetrennten Freitextwerte (0036–0038), Bearbeitung in den
  Teileigenschaften, Tag-Chips auf der Teilseite und Suche über Tag-Namen.
- Die Teile-API bleibt abwärtskompatibel: `tags` wird weiterhin als String
  geliefert, zusätzlich gibt es `tag_items` mit ID und Name. Schreibzugriffe
  akzeptieren String oder Namensliste; ein fehlendes Feld erhält vorhandene
  Tags, `""` oder `[]` entfernt sie.

- 3D- und PNG-Vorschauen bevorzugen eine eindeutig sichtbare, exportierbare
  FreeCAD-Baugruppe. Sichtbare Quellkörper außerhalb der Baugruppe werden dann
  nicht doppelt dargestellt; vorhandene Vorschauen werden beim nächsten Aufruf
  bei Bedarf neu erzeugt.

- Geometrische Teilevarianten mit optionaler Teilefamilie und konkreter
  Herkunftsrevision. Jede Variante hat eigene Revisionen und Druckprojekte.
- Variantenanlage aus dem FreeCAD-Add-on inklusive verknüpfter Parameter-
  und CAD-Dateien, eigenem Projektstand und Checkout sowie Rechteprüfung.
- Familiennavigation und Herkunft auf der Teilseite; Migration 0027.

- Zentrale Projekt-Tags mit Mehrfachzuordnung, Web-/API-Filtern, kombinierter
  Textsuche und Tag-Verwaltung (Umbenennen, Zusammenführen, Entfernen).
- Bestehende Clients behalten Tags bei Updates ohne Tag-Feld; Migration 0026
  ergänzt ausschließlich neue Tabellen/Zuordnungen und Audit-Auswahl.
- Bambuddy erkennt Drucknamen mit `_plate_N` und hängt den zeitlich belegbaren,
  gesicherten PLM-3MF-Stand automatisch an.

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

- 302 automatisierte Servertests; unter SQLite ohne erwartete Fehlschläge
  und mit einem übersprungenen PostgreSQL-Paralleltest.
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
