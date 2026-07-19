# Changelog

Alle wesentlichen Änderungen am FreeCAD-PLM-Server werden in dieser Datei
dokumentiert.

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
