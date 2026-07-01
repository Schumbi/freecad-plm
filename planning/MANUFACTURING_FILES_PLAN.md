# Manufacturing Files Plan

## Ziel

Eine CAD-Revision beschreibt, was konstruiert wurde. Die Manufacturing-Datei beschreibt, was tatsaechlich an den Drucker gegangen ist. Diese Dateien sollen unveraenderlich zur passenden Revision gespeichert werden, damit spaeter nachvollziehbar ist:

- Aus welcher `FCStd`-Revision wurde gedruckt?
- Welche Slicer-/Druckdatei wurde verwendet?
- Welche Prozessparameter, Materialien und Profile gehoerten dazu?
- Welche Datei wurde wirklich an den Drucker geschickt?
- Welche Qualitaets-/Ergebnisinformationen gehoeren zum Druck?

Der erste Fokus liegt auf 3D-Druck mit 3MF/G-Code. Das Datenmodell soll aber offen genug bleiben, um spaeter CNC, Laser, Zeichnungen oder externe Fertiger zu ergaenzen.

## Begriffe

- **CAD-Revision**: Die im PLM verwaltete `.FCStd`-Revision eines Teils oder einer Baugruppe.
- **Abgeleitetes Artefakt**: Vom PLM/Worker erzeugte Datei, z.B. STEP, STL, 3MF oder PNG. Aktuell `RevisionArtifact`.
- **Manufacturing File**: Von einem Menschen oder externem Tool hochgeladene Fertigungsdatei, z.B. geslicte 3MF, G-Code oder ein Slicer-Projekt. Sie ist nicht nur ein Export, sondern Produktionskontext.
- **Print Run / Fertigungslauf**: Optionaler spaeterer Nachweis, dass eine Manufacturing-Datei wirklich gedruckt wurde, inklusive Ergebnis, Materialcharge, Fotos und Bemerkungen.

## Grundentscheidung

Manufacturing-Dateien werden nicht als normale `RevisionArtifact` gespeichert.

Begruendung:

- `RevisionArtifact` ist heute primaer fuer automatisch erzeugte Dateien gedacht.
- Manufacturing-Dateien entstehen nachgelagert im Slicer und koennen Einstellungen enthalten, die FreeCAD nicht kennt.
- Eine Revision kann mehrere gueltige Manufacturing-Dateien haben, z.B. fuer verschiedene Drucker, Materialien, Duese, Qualitaetsprofile oder Bauraumorientierungen.
- Spaeter soll man unterscheiden koennen zwischen "vom PLM erzeugt", "fuer Fertigung freigegeben", "wirklich gedruckt" und "veraltet".

## Neues Datenmodell

### `ManufacturingFile`

Verknuepfung: `Revision` 1:n `ManufacturingFile`.

Felder:

- `revision`: Pflicht, Zielrevision.
- `file_type`: Auswahl, z.B. `slicer_3mf`, `gcode`, `bgcode`, `stl_print`, `step_vendor`, `pdf_drawing`, `other`.
- `purpose`: Auswahl, z.B. `print`, `external_manufacturing`, `inspection`, `documentation`.
- `status`: Auswahl, z.B. `draft`, `approved`, `printed`, `obsolete`.
- `file`: Upload-Datei.
- `original_filename`: Originalname.
- `sha256`: Hash zur Dubletten-/Nachweispruefung.
- `size_bytes`: Dateigroesse.
- `label`: Kurzer Anzeigename, z.B. `PETG 0.20mm X1C`.
- `description`: Freitext.
- `slicer_name`: z.B. PrusaSlicer, OrcaSlicer, Bambu Studio, Cura.
- `slicer_version`: optional.
- `printer_model`: optional.
- `printer_profile`: optional.
- `material`: optional, z.B. PETG, PLA-CF.
- `material_brand`: optional.
- `nozzle_diameter`: optional.
- `layer_height`: optional.
- `estimated_print_time_seconds`: optional.
- `estimated_material_g`: optional.
- `metadata`: JSON fuer ausgelesene Slicer-/3MF-Metadaten.
- `uploaded_by`, `created_at`, `updated_at`.

Storage-Pfad:

```text
storage/
  projects/<project_id>/
    parts/<part_id>/
      revisions/<revision_code>/
        manufacturing/
          <manufacturing_file_id>/
            <original-or-safe-filename>
```

### `PrintRun` / `ManufacturingRun` Spaeter

Nicht zwingend fuer den ersten Schritt, aber im Modell vorsehen.

Felder:

- `manufacturing_file`: Pflicht.
- `status`: `planned`, `running`, `succeeded`, `failed`, `scrapped`.
- `printed_at`: Datum/Uhrzeit.
- `operator`: Nutzer.
- `printer_name`: konkreter Drucker.
- `material_batch`: Materialcharge/Rolle.
- `quantity`: Anzahl.
- `result_notes`: Ergebnisnotiz.
- `attachments`: Fotos, Messprotokolle, Fehlerbilder.

Der erste Schritt kann ohne `PrintRun` starten. Wichtig ist aber, dass `ManufacturingFile.status=printed` nicht zu viel vorgaukelt. Ein echter Drucknachweis gehoert langfristig in einen eigenen Lauf.

## Upload-Workflow

### Revision-Detailseite

Auf der Teil-/Revisionsseite bekommt jede Revision einen Bereich:

```text
Fertigung
  Manufacturing-Datei hochladen
  Liste vorhandener Dateien
```

Uploadfelder:

- Datei
- Typ
- Label
- Slicer
- Drucker/Profil
- Material
- Beschreibung

Nach Upload:

- Datei validieren.
- SHA-256 berechnen.
- Dublette pro Revision blockieren oder deutlich anzeigen.
- Optional Metadaten auslesen.
- AuditEvent erzeugen.
- Datei in der Revisionsansicht anzeigen und downloadbar machen.

### FreeCAD-Addon

Das Addon muss Manufacturing-Dateien nicht erzeugen. Es sollte sie aber sehen und herunterladen koennen, damit ein Konstrukteur erkennt, ob eine Revision schon produktionsnah vorbereitet wurde.

API spaeter:

- `GET /api/revisions/<id>/manufacturing-files/`
- `POST /api/revisions/<id>/manufacturing-files/`
- `GET /api/manufacturing-files/<id>/download/`

## 3MF-Spezialfall

3MF ist ein ZIP-Container. Viele Slicer speichern darin neben Geometrie auch Druckprofile, Slicer-Einstellungen, Thumbnails und Herstellerdaten.

Erster Schritt:

- Datei als ZIP pruefen.
- `.3mf` akzeptieren.
- Basisdaten speichern: Dateiname, Groesse, SHA-256.
- Optional `metadata.json`/bekannte Slicer-Dateien roh inventarisieren.

Spaeter:

- PrusaSlicer/OrcaSlicer/Bambu-Studio-Profile auslesen.
- Thumbnails extrahieren und als Vorschaubild anzeigen.
- Slicer, Drucker, Material, Layerhoehe, Duese, Infill, Supports, Druckzeit und Materialmenge automatisch befuellen, soweit vorhanden.

## Welche Dateien Zu Einem Projekt Gehoeren Koennen

### Konstruktionsquelle

- `.FCStd`: Primaere FreeCAD-Datei, versionspflichtig.
- Referenzierte `.FCStd`: Abhaengige Teile/Baugruppen.
- Externe Referenzgeometrie: STEP/STL/OBJ, wenn sie als Eingangsdaten genutzt wird.

### PLM-Artefakte

- STEP: neutraler Austausch und robuster Zwischenstand.
- STL/3MF aus FreeCAD: Geometrieexport fuer Vorschau oder Slicer-Startpunkt.
- PNG-Ansichten: visueller Revisionsvergleich.
- Metadaten/Analyseergebnisse: exportierbare Objekte, Abhaengigkeiten, Properties.

### Fertigung

- Slicer-Projekt `.3mf`: Enthaltene Orientierung, Supports, Druckplatten, Profile.
- Druckdatei `.gcode`, `.bgcode`, `.ufp` oder herstellerspezifische Varianten.
- Fertigungs-PDFs: Zeichnungen, Montageblaetter, externe Bestellunterlagen.
- CNC-/Laser-Dateien spaeter: DXF, SVG, STEP-CAM, NC/G-Code.

### Qualitaet Und Nachweis

- Fotos des gedruckten Teils.
- Messprotokolle, z.B. PDF/CSV.
- Druckerlog oder Slicer-Report.
- Materialcharge/Rollen-ID.
- Nacharbeits- oder Montagehinweise.
- Fehlerbilder und Lessons Learned.

### Projektorganisation

- BOM/Stueckliste.
- Montageanleitung.
- README/Notizen.
- Lieferantenangebote/Rechnungsreferenzen spaeter nur, wenn das PLM auch Beschaffung abbilden soll.

## UI-Konzept

Desktop-first:

- In der Revisionsansicht ein eigener Tab/Abschnitt `Fertigung`.
- Manufacturing-Dateien als kompakte Tabelle:
  - Label
  - Typ
  - Status
  - Slicer
  - Drucker
  - Material
  - Erstellt/Hochgeladen
  - Aktionen: Details, Download, Obsolet setzen
- Details in demselben Floating-Dialog-Stil wie Metadaten/Eigenschaften.
- Upload als Dialog oder rechte Eigenschaftenleiste, nicht als lange Zusatzseite.

Statuslogik:

- `draft`: hochgeladen, aber nicht final.
- `approved`: diese Datei ist fuer die Revision als Fertigungsdatei freigegeben.
- `printed`: wurde fuer einen Druck verwendet, kurzfristig ohne eigenen PrintRun.
- `obsolete`: nicht mehr verwenden.

## Rechte Und Sicherheit

Kurzfristig an bestehende Rollen koppeln:

- `reader`: ansehen und herunterladen.
- `editor`: hochladen und eigene Eintraege bearbeiten.
- `admin`: Status aendern, obsolet setzen, loeschen falls noetig.

Validierung:

- erlaubte Endungen und MIME grob pruefen.
- maximale Uploadgroesse konfigurierbar halten.
- Uploads niemals ausfuehren.
- G-Code nur als Datei speichern und ausliefern, nicht serverseitig interpretieren.

## Audit Und Nachvollziehbarkeit

Neue AuditEvents:

- `manufacturing_file_uploaded`
- `manufacturing_file_updated`
- `manufacturing_file_status_changed`
- spaeter `manufacturing_run_created`

Im Audit-Metadata speichern:

- ManufacturingFile-ID
- Revision-ID
- SHA-256
- Typ/Status
- relevante Slicer-/Druckerfelder

## Umsetzungsschritte

### Schritt 1: Datenmodell Und Upload

- `ManufacturingFile`-Modell anlegen.
- Migration erstellen.
- Admin-Registrierung.
- Upload-Service mit Hash, Groesse, Basismetadaten.
- Tests fuer Upload, Dublette, Download, Projektloeschung.

### Schritt 2: Web-UI

- Revisionsdetail um Bereich `Fertigung` erweitern.
- Upload-Dialog einbauen.
- Detaildialog fuer Metadaten.
- Download und Statuswechsel.

### Schritt 3: API

- Manufacturing-Dateien in Revisions-API anzeigen.
- Upload- und Download-Endpunkte fuer Addon/Automatisierung.

### Schritt 4: 3MF-Metadaten

- 3MF als ZIP inventarisieren.
- bekannte Slicer-Metadaten auslesen, erst konservativ.
- Thumbnail extrahieren, falls vorhanden.

### Schritt 5: PrintRun

- Eigenes Modell fuer echte Drucklaeufe.
- Ergebnis, Materialcharge, Drucker, Menge, Fotos und Messprotokolle.
- Aus Manufacturing-Datei heraus `Druck dokumentieren`.

## Offene Entscheidungen

- Soll eine Revision genau eine `approved` Manufacturing-Datei pro Drucker/Material erlauben oder mehrere?
- Sollen G-Code-Dateien direkt hochgeladen werden duerfen oder zuerst nur 3MF/Slicer-Projekte?
- Wie gross darf ein Upload sein?
- Sollen Manufacturing-Dateien geloescht werden koennen oder nur `obsolete` werden?
- Brauchen wir kurzfristig schon Fotos/Messprotokolle oder reicht das im PrintRun-Ausbau?
