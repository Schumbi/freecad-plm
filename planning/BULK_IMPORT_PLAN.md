# Bulk-ZIP-Import Fuer Mehrere Projekte

## Ziel

Ein einzelnes ZIP soll mehrere FreeCAD-PLM-Projekte importieren koennen. Die erste Ordner-Ebene im ZIP entspricht jeweils einem neuen PLM-Projekt. Innerhalb dieser Projektordner koennen beliebige Unterordner liegen.

Unterstuetzte Dateien:

- `.FCStd`: wird als CAD-Datei importiert.
- `.FCBak`: wird ignoriert.
- `.3mf`: wird als Fertigungsdatei importiert, wenn sie eindeutig zu einer `.FCStd` passt.

## Fachliche Regeln

- Jeder direkte Unterordner im ZIP wird ein eigenes Projekt.
- Projektcodes werden automatisch vergeben.
- Projektname ist der Ordnername.
- Empfohlenes Codeformat: `IMP-001`, `IMP-002`, ...
- Top-Level-Dateien ohne Projektordner werden nicht importiert, aber im Ergebnisbericht genannt.
- `.FCBak` wird case-insensitive ignoriert.
- `.FCStd`-Dateien werden innerhalb ihres Projekts mit relativem Pfad importiert, also ohne den Projektordner aus dem ZIP.
- Pro Projekt wird ein `ProjectSnapshot` angelegt.
- Der Snapshot-Name soll aus ZIP-Dateiname und Projektordner entstehen, z.B. `bulk-import/ProjektA`.
- Import ist atomar pro Projektordner, nicht fuer das gesamte ZIP: ein fehlerhaftes Projekt blockiert nicht die erfolgreich importierten anderen Projekte.

## 3MF-Zuordnung

Eine `.3mf`-Datei wird einer CAD-Revision zugeordnet, wenn alle Bedingungen gelten:

- Sie liegt im selben relativen Ordner wie eine `.FCStd`.
- Sie hat denselben Basisnamen.
- Beispiel:
  - `ProjektA/Gehause/Deckel.FCStd`
  - `ProjektA/Gehause/Deckel.3mf`

Die Fertigungsdatei wird mit dem bestehenden Manufacturing-Service gespeichert:

- `purpose`: `print`
- `status`: `approved`
- `label`: Dateiname ohne Endung
- Datei-Hash, Groesse, 3MF-Inventur und Thumbnail-Extraktion bleiben wie beim normalen Manufacturing-Upload.

Nicht zuordenbare `.3mf`-Dateien werden nicht importiert und im Ergebnisbericht genannt.

## Technischer Ansatz

### Service

Neuer Service in `plm/services.py`:

```python
import_bulk_project_zip(uploaded_zip, created_by)
```

Aufgaben:

- ZIP mit `read_uploaded_file()` lesen.
- Pfade mit bestehender Logik analog `safe_snapshot_path()` absichern.
- Dateien nach erstem Pfadsegment gruppieren.
- Pro Projektgruppe:
  - neues `Project` mit automatisch generiertem Code anlegen,
  - `.FCStd`-Dateien in ein projektspezifisches In-Memory-ZIP mit relativen Pfaden schreiben,
  - vorhandenes `import_project_snapshot()` wiederverwenden,
  - danach passende `.3mf`-Dateien anhand relativer Pfade und Basisnamen importieren.
- Summary-Dict zurueckgeben.

Empfohlene Summary-Struktur:

```python
{
    "created_projects": 2,
    "created_parts": 5,
    "created_revisions": 5,
    "reused_revisions": 0,
    "manufacturing_files": 3,
    "ignored_fcbak": ["ProjektA/Teil.FCBak"],
    "skipped_top_level_files": ["README.txt"],
    "unmatched_manufacturing_files": ["ProjektA/Gehause/Alt.3mf"],
    "failed_projects": [
        {"folder": "ProjektB", "error": "..."}
    ],
    "projects": [
        {
            "folder": "ProjektA",
            "project_id": 12,
            "project_code": "IMP-001",
            "project_name": "ProjektA",
            "snapshot_id": 44,
            "created_parts": 3,
            "created_revisions": 3,
            "reused_revisions": 0,
            "manufacturing_files": 2,
        }
    ],
}
```

### Auto-Projektcodes

Neuer Helper:

```python
next_import_project_code()
```

Regeln:

- Prefix `IMP`.
- Dreistellige Nummer.
- Vorhandene Codes `IMP-001`, `IMP-002`, ... werden ausgewertet.
- Naechster freier Code wird vergeben.
- Nicht passende Codes werden ignoriert.

### UI

Projektliste:

- Fuer Admin/Superuser zusaetzlicher Button `Bulk-ZIP importieren`.
- Schwebender Dialog analog bestehender Importdialoge.
- Formular:
  - `file`: ZIP-Datei

Neue View:

```python
bulk_import_projects(request)
```

Route:

```text
projects/bulk-import/
```

Rechte:

- Nur Superuser und Rolle `admin`.
- `editor` und `reader` erhalten HTTP 403.

Nach Erfolg:

- Redirect zur Projektliste.
- Erfolgsmeldung mit Kurzsummary.
- Detailsummary ueber Messages oder eigene Ergebnisansicht. Fuer den ersten Schritt reicht eine kompakte Message mit Zahlen plus Hinweis auf ignorierte/nicht zuordenbare Dateien.

## Audit

Bestehende Einzelereignisse bleiben erhalten:

- `project_created`
- `part_created`
- `revision_uploaded`
- `project_snapshot_created`
- `manufacturing_file_uploaded`

Zusaetzlich sollte eine neue AuditAction angelegt werden:

```python
BULK_IMPORT_COMPLETED = "bulk_import_completed", "Bulk-Import abgeschlossen"
```

Metadata enthaelt die Summary des Imports.

## Tests

### Service-Tests

- ZIP mit zwei Top-Level-Ordnern erzeugt zwei Projekte.
- Projektcodes werden automatisch als `IMP-001`, `IMP-002` vergeben.
- Projektname entspricht dem Ordnernamen.
- `.FCBak` wird ignoriert.
- `.FCStd` in Unterordnern wird mit relativem Pfad ohne Top-Level-Projektordner als SnapshotEntry gespeichert.
- `Teil.FCStd` plus `Teil.3mf` im selben Ordner erzeugt eine `ManufacturingFile` zur importierten Revision.
- Nicht zuordenbare `.3mf` wird nicht importiert und erscheint in `unmatched_manufacturing_files`.
- Top-Level-Dateien werden nicht importiert und erscheinen in `skipped_top_level_files`.
- Fehler in einem Projektordner werden in `failed_projects` gemeldet, andere Projektordner werden importiert.

### View-Tests

- Admin/Superuser sieht den Bulk-Import-Button auf der Projektliste.
- Admin/Superuser kann ein Bulk-ZIP hochladen.
- Erfolgreicher Import redirectet zur Projektliste und zeigt eine Summary-Message.
- Editor und Reader bekommen beim POST HTTP 403.
- Ungueltige Dateiendung wird im Formular abgelehnt.

### Regression

- Bestehender `import_project_snapshot()`-Workflow bleibt unveraendert.
- `manage.py test plm` laeuft erfolgreich.

## Offene Spaetere Erweiterungen

- Optionaler Dry-Run vor dem Import.
- Eigene Ergebnisdetailseite mit vollstaendiger Datei- und Fehlerliste.
- Manifest-Datei im ZIP fuer explizite Projektcodes und Metadaten.
- Import vorhandener Projekte statt immer neuer Projekte.
- Weitere Fertigungsdateitypen neben `.3mf`.
