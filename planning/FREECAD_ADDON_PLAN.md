# FreeCAD Addon Plan

## Zweck

Dieses Dokument ist die Uebergabe fuer eine neue Codex-Instanz, die ein separates FreeCAD-Addon fuer das FreeCAD-PLM bauen soll. Der Server existiert in diesem Repo als Django-App. Das Addon soll in einem vanilla FreeCAD laufen und ueber die bestehende `/api/`-Schnittstelle mit dem PLM sprechen.

## Zielbild

Das Addon ist eine FreeCAD-Workbench mit einem Dock/Task-Panel fuer PLM-Arbeit:

- PLM-Server konfigurieren und verbinden.
- Projekte anzeigen.
- Teile/Baugruppen eines Projekts anzeigen.
- Revisionen eines Teils anzeigen.
- Revision auschecken.
- Checkout-Manifest laden.
- Alle benoetigten `.FCStd`-Dateien lokal mit den serverseitigen relativen Pfaden speichern.
- Root-Datei in FreeCAD oeffnen.
- Geaenderte Root-Datei als neue PLM-Revision einchecken.
- Checkout abbrechen.
- Anmerkungen zu Teil, Revision und optional FreeCAD-Objekt speichern und anzeigen.

Nicht Ziel fuer die erste Addon-Version:

- Eigene Benutzerverwaltung.
- Vollstaendige Rechteverwaltung im Addon.
- 3D-Marker/Annotationen im Viewport.
- Automatische Konfliktloesung bei parallelen Bearbeitungen.
- Eigenes Server-Backend.

## Empfohlene Addon-Struktur

Repository-Name: `freecad-plm-addon`

```text
freecad-plm-addon/
  Init.py
  InitGui.py
  freecad_plm_addon/
    __init__.py
    api_client.py
    config.py
    workbench.py
    commands.py
    panel.py
    workspace.py
    fcstd.py
    icons/
  tests/
    test_api_client.py
    test_workspace.py
  README.md
```

Technik:

- Python, kompatibel mit FreeCADs Python.
- UI mit PySide/Qt, ueber FreeCADs vorhandene Qt-Bindings.
- HTTP mit Python-Standardbibliothek oder `requests`, falls in der Ziel-FreeCAD-Umgebung vorhanden. Robustere Wahl: Standardbibliothek, damit vanilla FreeCAD weniger Zusatzpakete braucht.
- Persistente Einstellungen ueber `FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeCADPLM")`.

## Addon-Konfiguration

Zu speichern:

- `server_url`, z.B. `http://127.0.0.1:8000`
- `username`
- `api_token`, erzeugt serverseitig mit `manage.py create_api_token`
- `workspace_root`, Default: `~/FreeCAD-PLM`
- letzter Projektkontext

Wichtig: Die Server-API ist token-only. Die erste Addon-Version muss den Token als `Authorization: Bearer ...` senden. Django-Browser-Sessions reichen fuer `/api/` nicht aus.

## Server-API

Basis-URL in Beispielen: `http://127.0.0.1:8000`

Alle JSON-Requests:

- `Content-Type: application/json`
- `Authorization: Bearer <api_token>`
- Antworten sind JSON, ausser Datei-Downloads.
- Bei Fehlern liefert der Server meist `{"error": "...", "messages": ["..."]}`.
- Relevante Statuscodes:
  - `200`: gelesen/geaendert
  - `201`: angelegt
  - `400`: ungueltige Eingabe
  - `403`: keine Berechtigung
  - `404`: nicht gefunden
  - `409`: fachlicher Konflikt, z.B. aktiver Checkout oder PLMRevision-Konflikt

### Projekte

`GET /api/projects/`

Antwort:

```json
{
  "projects": [
    {
      "id": 1,
      "code": "PRJ",
      "name": "Projekt",
      "description": "",
      "is_archived": false
    }
  ]
}
```

`POST /api/projects/`

Request:

```json
{
  "code": "PRJ",
  "name": "Projekt",
  "description": "Optional"
}
```

Antwort `201`:

```json
{
  "project": {
    "id": 1,
    "code": "PRJ",
    "name": "Projekt",
    "description": "Optional",
    "is_archived": false
  }
}
```

`GET /api/projects/<project_id>/`

Antwort:

```json
{
  "project": {
    "id": 1,
    "code": "PRJ",
    "name": "Projekt",
    "description": "",
    "is_archived": false
  }
}
```

`POST /api/projects/<project_id>/`

Request-Felder optional: `name`, `description`, `is_archived`.

### Teile/Baugruppen

`GET /api/projects/<project_id>/parts/`

Antwort:

```json
{
  "parts": [
    {
      "id": 1,
      "project_id": 1,
      "number": "P-001",
      "name": "Testteil",
      "category": "part",
      "description": "",
      "material": "",
      "supplier": "",
      "tags": "",
      "is_archived": false
    }
  ]
}
```

`POST /api/projects/<project_id>/parts/`

Request:

```json
{
  "number": "P-002",
  "name": "Halter",
  "category": "part",
  "description": "",
  "material": "",
  "supplier": "",
  "tags": ""
}
```

`category` ist `part` oder `assembly`. Wenn `number` leer ist, vergibt der Server automatisch die naechste Nummer.

`GET /api/parts/<part_id>/`

Antwort:

```json
{
  "part": {
    "id": 1,
    "project_id": 1,
    "number": "P-001",
    "name": "Testteil",
    "category": "part",
    "description": "",
    "material": "",
    "supplier": "",
    "tags": "",
    "is_archived": false
  },
  "revisions": [
    {
      "id": 1,
      "part_id": 1,
      "revision_code": "R0001",
      "status": "draft",
      "original_filename": "part.FCStd",
      "sha256": "...",
      "size_bytes": 1234,
      "notes": "",
      "extracted_metadata": {},
      "created_at": "2026-06-28T...",
      "released_at": null,
      "download_url": "http://127.0.0.1:8000/api/revisions/1/file/"
    }
  ],
  "active_checkout": null
}
```

`POST /api/parts/<part_id>/`

Request-Felder optional: `name`, `description`, `material`, `supplier`, `tags`, `category`, `is_archived`.

### Revisionen Und Dateien

`GET /api/revisions/<revision_id>/`

Antwort:

```json
{
  "revision": {
    "id": 1,
    "part_id": 1,
    "revision_code": "R0001",
    "status": "draft",
    "original_filename": "part.FCStd",
    "sha256": "...",
    "size_bytes": 1234,
    "notes": "",
    "extracted_metadata": {},
    "created_at": "2026-06-28T...",
    "released_at": null,
    "download_url": "http://127.0.0.1:8000/api/revisions/1/file/"
  }
}
```

`GET /api/revisions/<revision_id>/file/`

Antwort: Datei-Download der `.FCStd`-Datei.

`POST /api/revisions/<revision_id>/notes/`

Request:

```json
{
  "notes": "Vor Serienfreigabe in Baugruppe pruefen."
}
```

Antwort:

```json
{
  "revision": {
    "id": 1,
    "revision_code": "R0001",
    "notes": "Vor Serienfreigabe in Baugruppe pruefen."
  }
}
```

Der Endpunkt aktualisiert nur `Revision.notes`, erzeugt keine neue Revision und
schreibt ein AuditEvent `revision_notes_updated`. Leere Notizen sind erlaubt.

Das Addon muss den Download nach dem Speichern lokal per SHA-256 gegen `sha256` aus Revision oder Manifest pruefen.

### Read-only Manifest

`GET /api/revisions/<revision_id>/manifest/`

Optional:

`GET /api/revisions/<revision_id>/manifest/?snapshot_id=<snapshot_id>`

Scope: `read`.

Der Endpunkt erzeugt keinen Checkout und setzt keinen Lock. Er liefert dieselbe Datei-Aufloesung wie Checkout-Manifeste, damit read-only Oeffnen und Checkout dieselbe Downloadlogik nutzen koennen.

Wenn `snapshot_id` angegeben ist, werden referenzierte Dateien aus genau diesem Projektstand aufgeloest. Wenn eine Revision externe FreeCAD-Referenzen enthaelt und kein passender Snapshot-Kontext verfuegbar ist, antwortet der Server mit `409`.

Antwort:

```json
{
  "manifest": {
    "project": {
      "id": 1,
      "code": "PRJ",
      "name": "Projekt"
    },
    "part": {
      "id": 1,
      "number": "P-001",
      "name": "Testteil",
      "category": "assembly"
    },
    "revision": {
      "id": 1,
      "revision_code": "R0001",
      "status": "draft",
      "original_filename": "Assembly.FCStd",
      "sha256": "...",
      "size_bytes": 1234,
      "download_url": "http://127.0.0.1:8000/api/revisions/1/file/"
    },
    "snapshot": {
      "id": 1,
      "name": "Arbeitsstand"
    },
    "files": [
      {
        "path": "Assembly.FCStd",
        "is_root": true,
        "revision_id": 1,
        "part_id": 1,
        "part_number": "P-001",
        "revision_code": "R0001",
        "filename": "Assembly.FCStd",
        "sha256": "...",
        "size_bytes": 1234,
        "download_url": "http://127.0.0.1:8000/api/revisions/1/file/"
      }
    ]
  }
}
```

Das Addon soll fuer read-only Oeffnen `manifest.files` herunterladen, SHA-256 pruefen, `manifest.json` schreiben und die Datei mit `is_root: true` oeffnen.

### Checkout

`POST /api/revisions/<revision_id>/checkout/`

Request:

```json
{
  "snapshot_id": 1,
  "workspace_hint": "~/FreeCAD-PLM/PRJ/checkout-1"
}
```

`snapshot_id` darf fehlen, wenn die Revision keine externen FreeCAD-Referenzen braucht. Fuer Baugruppen mit XLink-Referenzen muss ein Snapshot-Kontext vorhanden sein, sonst antwortet der Server mit `409`.

Antwort `201`:

```json
{
  "checkout": {
    "id": 1,
    "part_id": 1,
    "base_revision_id": 1,
    "snapshot_id": 1,
    "status": "active",
    "checked_out_by": "addon-user",
    "workspace_hint": "~/FreeCAD-PLM/PRJ/checkout-1",
    "completed_revision_id": null,
    "created_at": "2026-06-28T...",
    "completed_at": null,
    "canceled_at": null
  },
  "manifest": {
    "checkout_id": 1,
    "status": "active",
    "project": {
      "id": 1,
      "code": "PRJ",
      "name": "Projekt"
    },
    "part": {
      "id": 1,
      "number": "P-001",
      "name": "Testteil",
      "category": "assembly"
    },
    "base_revision": {
      "id": 1,
      "revision_code": "R0001",
      "sha256": "..."
    },
    "snapshot": {
      "id": 1,
      "name": "Arbeitsstand"
    },
    "files": [
      {
        "path": "Assembly.FCStd",
        "is_root": true,
        "revision_id": 1,
        "part_id": 1,
        "part_number": "P-001",
        "revision_code": "R0001",
        "filename": "Assembly.FCStd",
        "sha256": "...",
        "size_bytes": 1234,
        "download_url": "http://127.0.0.1:8000/api/revisions/1/file/"
      }
    ]
  }
}
```

Hinweis: Direkt nach Checkout enthaelt das Manifest bereits `download_url` pro Datei. Das Addon kann trotzdem `GET /api/checkouts/<checkout_id>/manifest/` erneut laden, wenn es einen gespeicherten Checkout spaeter fortsetzt.

`GET /api/checkouts/<checkout_id>/manifest/`

Wie oben: jedes Element in `manifest.files` enthaelt eine Download-URL.

```json
{
  "download_url": "http://127.0.0.1:8000/api/revisions/1/file/"
}
```

### Aktive Checkouts

`GET /api/checkouts/active/`

Scope: `checkout`.

Der Endpunkt liefert nur aktive Checkouts des aktuellen API-Users. Er erzeugt
keine neuen Checkouts und veraendert keine Locks. Das Addon nutzt ihn beim
Verbinden, um serverseitig aktive Checkout-Locks nach einem FreeCAD-Neustart
wieder im Panel anzuzeigen.

Antwort:

```json
{
  "checkouts": [
    {
      "id": 1,
      "status": "active",
      "created_at": "2026-07-06T12:00:00+00:00",
      "updated_at": "2026-07-06T12:10:00+00:00",
      "workspace_hint": "/home/ralf/FreeCAD-PLM",
      "project": {
        "id": 1,
        "code": "PRJ",
        "name": "Projekt"
      },
      "part": {
        "id": 1,
        "number": "P-001",
        "name": "Testteil"
      },
      "revision": {
        "id": 1,
        "revision_code": "R0001",
        "original_filename": "Assembly.FCStd"
      },
      "snapshot": null,
      "manifest_url": "/api/checkouts/1/manifest/"
    }
  ]
}
```

`POST /api/checkouts/<checkout_id>/cancel/`

Antwort:

```json
{
  "checkout": {
    "id": 1,
    "status": "canceled"
  }
}
```

`POST /api/checkouts/<checkout_id>/checkin/`

Single-File-Multipart-Request fuer reine Root-Aenderungen:

Multipart-Form-Request:

- `file`: geaenderte Root-`.FCStd`
- `change_summary`: Aenderungsnotiz

Multi-Datei-Multipart-Request fuer Baugruppen mit geaenderten referenzierten Dateien:

- `files_metadata`: JSON-Liste mit `field`, `path`, `revision_id`, `base_sha256`, `sha256`, `is_root`
- `file_0`, `file_1`, ...: geaenderte `.FCStd`-Dateien
- `change_summary`: Aenderungsnotiz

Beispiel fuer `files_metadata`:

```json
[
  {
    "field": "file_0",
    "path": "Assembly.FCStd",
    "revision_id": 1,
    "base_sha256": "...",
    "sha256": "...",
    "is_root": true
  },
  {
    "field": "file_1",
    "path": "parts/Child.FCStd",
    "revision_id": 2,
    "base_sha256": "...",
    "sha256": "...",
    "is_root": false
  }
]
```

Unveraenderte Dateien muessen nicht hochgeladen werden. Wenn nur referenzierte
Dateien geaendert wurden, wird der Checkout trotzdem abgeschlossen; `revision`
ist dann `null`, und die erzeugten Revisionen stehen in `revisions`.

Der Server prueft jede hochgeladene FCStd-Datei zusaetzlich mit seiner
technischen Signatur. Reine FreeCAD-Speicherartefakte zaehlen nicht als
modellrelevante Aenderung:

- `GuiDocument.xml`
- `ShapeAppearance*`
- BREP-/Shape-Cache-Dateien als alleiniger Unterschied
- `LastModified*`, `PLMRevision`, `status`, `stamp`, `Touched`
- lokale Checkout-Pfade in BOM-/XML-Attributen wie
  `.../checkout-2/files/Box.FCStd`
- winziges Placement-Floating-Point-Rauschen nahe `0`

Wenn nach dieser Filterung keine modellrelevante Datei uebrig bleibt, antwortet
der Server mit `200`, laesst den Checkout aktiv und listet die ignorierten
Dateien in `ignored_files`.

Antwort `201`:

```json
{
  "checkout": {
    "id": 1,
    "status": "completed",
    "completed_revision_id": 2
  },
  "revision": {
    "id": 2,
    "part_id": 1,
    "revision_code": "R0002",
    "status": "draft",
    "original_filename": "updated.FCStd",
    "sha256": "...",
    "size_bytes": 2345,
    "notes": "Geometrie angepasst.",
    "extracted_metadata": {},
    "created_at": "2026-06-28T...",
    "released_at": null,
    "download_url": "http://127.0.0.1:8000/api/revisions/2/file/"
  },
  "revisions": [
    {
      "path": "Assembly.FCStd",
      "revision": {
        "id": 2,
        "revision_code": "R0002"
      }
    }
  ]
}
```

Der Server bleibt fuehrend fuer Revisionscodes. Wenn `PLMRevision` in der Datei fehlt oder nicht dem erwarteten naechsten Code entspricht, kann der Server mit `409` antworten. Die erste Addon-Version soll diesen Fehler anzeigen und den Checkout aktiv lassen.

### Anmerkungen

`GET /api/parts/<part_id>/annotations/`

Antwort:

```json
{
  "annotations": [
    {
      "id": 1,
      "project_id": 1,
      "part_id": 1,
      "revision_id": 1,
      "object_name": "Body",
      "subelement": "Face12",
      "text": "Kante abrunden.",
      "status": "open",
      "created_by": "addon-user",
      "created_at": "2026-06-28T..."
    }
  ]
}
```

`POST /api/parts/<part_id>/annotations/`

Request:

```json
{
  "revision_id": 1,
  "object_name": "Body",
  "subelement": "Face12",
  "text": "Kante abrunden."
}
```

`revision_id`, `object_name` und `subelement` sind optional. `text` ist Pflicht.

`POST /api/annotations/<annotation_id>/`

Request:

```json
{
  "text": "Erledigt in R0002.",
  "status": "resolved"
}
```

`status` ist `open` oder `resolved`.

`DELETE /api/annotations/<annotation_id>/`

Antwort:

```http
204 No Content
```

Der Endpunkt loescht die Anmerkung, erzeugt keine Revision und schreibt ein
AuditEvent `annotation_deleted`.

## Lokale Workspace-Regeln

Default-Pfad:

```text
~/FreeCAD-PLM/
  <server-slug>/
    <project-code>/
      checkout-<checkout-id>/
        manifest.json
        files/
          <relative-path-from-manifest>
```

Beispiel:

```text
~/FreeCAD-PLM/local-8000/PRJ/checkout-17/
  manifest.json
  files/
    Baugruppe.FCStd
    Unterordner/Teil.FCStd
```

Regeln:

- `manifest.files[].path` ist relativ zu `files/`.
- Das Addon muss Verzeichnisse anlegen.
- Absolute Pfade und `..` in Manifest-Pfaden muessen lokal abgelehnt werden.
- Nach jedem Download SHA-256 pruefen.
- Root-Datei ist `manifest.files[]` mit `is_root == true`.
- Nur die Root-Datei wird in der ersten Version eingecheckt.
- Abhaengige Dateien werden als Referenzdateien lokal abgelegt und nicht automatisch eingecheckt.

## FreeCAD-Workflow

### Verbindung

1. Nutzer oeffnet FreeCAD-PLM-Workbench.
2. Panel fragt Server-URL und Login-Daten ab oder liest gespeicherte Werte.
3. Addon ruft `GET /api/projects/`.
4. Addon ruft `GET /api/checkouts/active/`.
5. Bei Erfolg zeigt das Panel Projekte und aktive Checkouts des Users.
6. Wenn lokale Dateien fuer einen aktiven Checkout fehlen, kann das Addon ueber `manifest_url` das Manifest laden und die Dateien erneut herunterladen.

### Auschecken Und Oeffnen

1. Nutzer waehlt Projekt.
2. Addon ruft `GET /api/projects/<project_id>/parts/`.
3. Nutzer waehlt Teil/Baugruppe.
4. Addon ruft `GET /api/parts/<part_id>/`.
5. Nutzer waehlt Revision.
6. Addon ruft `POST /api/revisions/<revision_id>/checkout/`.
7. Addon ruft `GET /api/checkouts/<checkout_id>/manifest/`.
8. Addon laedt alle Dateien aus `manifest.files[].download_url`.
9. Addon prueft SHA-256.
10. Addon speichert `manifest.json`.
11. Addon oeffnet Root-Datei mit `FreeCAD.openDocument(root_path)`.

### Einchecken

1. Nutzer speichert das FreeCAD-Dokument lokal.
2. Addon erkennt aktuellen Checkout aus `manifest.json`.
3. Addon sendet Root-`.FCStd` an `POST /api/checkouts/<checkout_id>/checkin/`.
4. Bei Erfolg aktualisiert das Addon lokalen Status auf `completed`.
5. Addon zeigt neue Revision an.
6. Bei `409` zeigt Addon die Servermeldung an und laesst Checkout aktiv.

### Abbrechen

1. Nutzer klickt `Checkout abbrechen`.
2. Addon ruft `POST /api/checkouts/<checkout_id>/cancel/`.
3. Bei Erfolg markiert Addon den lokalen Checkout als `canceled`.
4. Lokale Dateien bleiben erhalten, werden aber nicht mehr als aktiver Checkout behandelt.

### Anmerkungen

1. Addon ruft beim Oeffnen eines Teils `GET /api/parts/<part_id>/annotations/`.
2. Nutzer kann eine neue Anmerkung erfassen.
3. Wenn ein FreeCAD-Objekt selektiert ist, nutzt das Addon dessen `Name` als `object_name`.
4. Wenn eine Subauswahl vorhanden ist, nutzt das Addon den Subnamen als `subelement`.
5. Addon sendet `POST /api/parts/<part_id>/annotations/`.

## UI-Anforderungen

Workbench-Elemente:

- Toolbar-Buttons:
  - Verbinden
  - Aktualisieren
  - Auschecken
  - Einchecken
  - Checkout abbrechen
  - Anmerkung erstellen
- Dock/Panel:
  - Serverstatus
  - Projektliste
  - Teileliste
  - Revisionsliste
  - Aktiver Checkout
  - Anmerkungen

Wichtig:

- Keine Landingpage im Addon.
- Erstes Panel muss direkt arbeitsfaehig sein.
- Fehlermeldungen aus der API sichtbar anzeigen.
- Lange Operationen wie Downloads blockieren die UI moeglichst wenig; fuer v1 reicht ein einfacher Fortschrittsdialog.

## Implementierungsdetails

`api_client.py`:

- `PLMClient(base_url)`
- `login(username, password)` oder vorhandene Session konfigurieren.
- `get_projects()`
- `create_project(data)`
- `get_project(project_id)`
- `get_parts(project_id)`
- `create_part(project_id, data)`
- `get_part(part_id)`
- `update_part(part_id, data)`
- `get_revision(revision_id)`
- `get_revision_manifest(revision_id, snapshot_id=None)`
- `download_revision_file(url, target_path, expected_sha256)`
- `checkout_revision(revision_id, snapshot_id=None, workspace_hint="")`
- `get_active_checkouts()`
- `get_checkout_manifest(checkout_id)`
- `checkin(checkout_id, fcstd_path, change_summary)`
- `checkin_files(checkout_id, files_metadata, files, change_summary)`
- `cancel_checkout(checkout_id)`
- `get_annotations(part_id)`
- `create_annotation(part_id, data)`
- `update_annotation(annotation_id, data)`

`workspace.py`:

- `safe_join(root, relative_path)`
- `server_slug(server_url)`
- `checkout_dir(server_url, project_code, checkout_id)`
- `write_manifest(checkout_dir, manifest)`
- `read_manifest(path)`
- `download_manifest_files(client, manifest, checkout_dir)`
- `root_file_path(manifest, checkout_dir)`
- `sha256_file(path)`

`panel.py`:

- Qt-DockWidget oder TaskPanel.
- Listet Projekte, Teile, Revisionen.
- Fuehrt Commands aus und aktualisiert den Zustand.

`commands.py`:

- FreeCAD Command-Klassen fuer Toolbar/Menu.
- Delegiert an Panel/Services.

`fcstd.py`:

- Hilfsfunktionen fuer aktuelles Dokument:
  - `active_document_path()`
  - `save_active_document()`
  - `selected_object_name()`
  - `selected_subelement_name()`

## Tests Fuer Das Addon

Ohne FreeCAD:

- API-Client serialisiert JSON korrekt.
- API-Client behandelt `409`, `403`, `404` mit klaren Exceptions.
- Workspace lehnt unsichere Pfade ab.
- Workspace schreibt und liest `manifest.json`.
- SHA-256-Pruefung erkennt falsche Downloads.

Mit gemocktem Server:

- Projektliste laden.
- Checkout-Manifest laden.
- Dateien aus Manifest herunterladen.
- Root-Datei bestimmen.
- Check-in multipart senden.
- Annotation mit Objekt/Subelement senden.

Manueller FreeCAD-Smoke-Test:

1. Server lokal starten.
2. Projekt mit Teil und Revision im PLM anlegen.
3. Addon in FreeCAD installieren.
4. Server verbinden.
5. Projekt/Teil/Revision anzeigen.
6. Revision auschecken.
7. Root-Datei oeffnet in FreeCAD.
8. Dokument speichern.
9. Check-in mit Aenderungsnotiz.
10. Neue Revision erscheint im PLM-Web.
11. Anmerkung in FreeCAD erfassen.
12. Anmerkung erscheint im PLM-Web.

## Offene Serverpunkte Fuer Spaeter

Diese Punkte soll die Addon-Instanz nicht loesen, sondern hoechstens als TODO dokumentieren:

- API fuer Snapshot-Auswahl je Revision/Baugruppe.
- API fuer Suche ueber Projekte, Teile, Revisionen und Dateinamen.
- Maschinenlesbare PLMRevision-Konfliktantwort mit Option zur serverseitigen Normalisierung.
- Optionaler Download eines kompletten Checkout-ZIPs statt einzelner Datei-Downloads.
