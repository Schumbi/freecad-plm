# Begriffsleitfaden (UI)

Ein Begriff pro Konzept. Technische Rohbezeichnungen erscheinen nur in
Detaildialogen („Jobs und Artefakte“), nicht in der Standardansicht.

| Konzept | Verbindlicher Begriff | Nicht verwenden |
|---|---|---|
| Oberste Ebene | Projekt | Auftrag, Vorgang |
| Bauteil/Baugruppe | Teil, Baugruppe | Komponente, Objekt |
| Version eines Teils | Revision (R0001) | Version, Stand (als Synonym) |
| Gesicherter Projektzustand | Projektstand | Snapshot, Stand, ZIP |
| Datei aus dem PLM holen | Herunterladen | Download, laden (allein) |
| Revision in FreeCAD öffnen | In FreeCAD bearbeiten | Checkout, auschecken |
| Automatisch erzeugte Ansichten | Vorschau (3D, Ansichten) | Artefakt, PNG back, STEP preview |
| Fertigung | Fertigungsdatei, Druckprojekt | Job, Druckjob |
| Hintergrundverarbeitung | Hintergrundjobs | Tasks, Jobs (ohne Kontext) |

## Regeln

- Aktionsverben zuerst, Objekt danach („Fertigungsdatei hochladen“).
- Einheiten in Klammern: „Düse (mm)“, nicht „Duese mm“.
- Umlaute ausschreiben (ä, ö, ü, ß) – keine ae/oe/ue-Umschrift in der UI.
- Zähler immer mit korrekter Pluralform; bei unregelmäßigen Formen
  explizit im Template unterscheiden („1 Projektstand“ / „2 Projektstände“).
- Interne Dateinamen (z. B. `R0001-back.png`) nur in Dateilisten und
  Artefakt-Dialogen zeigen, dort mit deutschem Anzeigenamen.
