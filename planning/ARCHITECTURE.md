# Architecture

## Zweck

Diese Datei beschreibt die technische Zielrichtung. Sie ist ein Arbeitsstand, keine finale Spezifikation.

## Technologieentscheidung

Aktuell favorisiert: Django.

Gruende:

- Eingebaute Benutzer, Gruppen, Rechte und Sessions.
- Eingebaute Admin-Oberflaeche fuer interne Verwaltung.
- ORM und Migrationen sind Standardbestandteile.
- Datei-Uploads und Storage-Abstraktion passen zum PLM-Kern.
- Python bleibt nah an FreeCAD und spaeteren FreeCADCmd-Workern.
- Docker Compose ist umgesetzt und fuer den Betrieb vorgesehen.

Nicht favorisiert fuer v1:

- Flask als Hauptframework: zu viel eigene Zusammensetzung fuer Auth, Admin, Rollen, Migrationen und robuste Projektstruktur.
- FastAPI als Hauptframework: stark fuer API-first, aber fuer ein internes PLM mit serverseitiger UI mehr Eigenbau.
- Go als Hauptbackend: gutes Deployment-Modell, aber weniger passend fuer FreeCAD-nahe Automatisierung und interne Admin-/Formularfunktionen.

## UI-Ansatz

- Serverseitige Django-Templates als Basis.
- Eigenes schlichtes CSS ohne Bootstrap; die Vendor-Assets wurden entfernt.
- Dialoge nutzen das native `<dialog>`-Element mit `showModal()`/`close()`
  und werden ueber `data-dialog-target`/`data-dialog-close` in
  `plm/static/plm/app.js` gesteuert.
- Optional HTMX fuer dynamische Bereiche ohne grosse Frontend-SPA.
- Keine React/Vue/Svelte-SPA fuer v1, solange kein klarer Bedarf entsteht.

## Datenhaltung

- Entwicklung zuerst mit SQLite moeglich.
- Datenmodell PostgreSQL-kompatibel halten.
- Docker Compose mit PostgreSQL ist umgesetzt.
- CAD-Dateien nicht in der Datenbank speichern.
- Dateien in einem Storage-Verzeichnis oder Docker-Volume ablegen.
- Datenbank speichert Metadaten, Pfade, Hashes, Status und Beziehungen.
- Projekt-Tags und Teile-Tags sind getrennte relationale Modelle
  (`ProjectTag`, `PartTag`); Teile-Tags werden ueber eine M2M-Zuordnung mit
  casefold-basiertem `identity_hash` eindeutig gehalten.

## Dateispeicher

Vorlaeufiges Layout:

```text
storage/
  projects/
    <project_uuid>/
      parts/
        <part_uuid>/
          revisions/
            R0001/
              <sha256>.FCStd
```

Details koennen sich aendern. Wichtig bleibt: Dateinamen duerfen nicht allein aus Benutzereingaben entstehen, und gespeicherte Dateien muessen eindeutig, nachvollziehbar und nicht versehentlich ueberschreibbar sein.

## FreeCAD-Integration

V1 (umgesetzt):

- `FCStd` als Datei validieren.
- `FCStd` als ZIP lesen.
- Basis-Metadaten extrahieren, soweit ohne FreeCAD moeglich.
- FreeCADCmd-Joblauf fuer abgeleitete Artefakte:
  - Analyse von exportierbaren Objekten und VarSet-Parametern.
  - Export nach STEP, STL und 3MF.
  - PNG-Ansichten fuer visuelle Vergleiche.
- Lokale Flatpak-Installationen werden ueber `FREECADCMD_COMMAND` unterstuetzt, z.B. `flatpak run --branch=stable --arch=x86_64 --command=FreeCADCmd org.freecad.FreeCAD`.
- STEP/STL/3MF-Exporte sind der robuste Headless-Pfad.
- PNG-Ansichten nutzen ebenfalls keinen FreeCAD-GUI-Viewport mehr: FreeCADCmd exportiert ein STEP-Artefakt und ein temporaeres STL-Vorschau-Mesh, danach rendert das PLM deterministische PNG-Ansichten aus dem STL.
- Vor dem FreeCADCmd-Aufruf werden referenzierte FCStd-Dateien aus demselben Projekt in den temporaeren Arbeitsordner kopiert, damit einfache Baugruppenlinks aufgeloest werden koennen.

Spaeter:

- Exporte nach PDF, DXF und weiteren Formaten.
- Bearbeitung von VarSet-Parametern und Neurendern mit Varianten.
- Weitere Verfeinerung von Status- und Logdarstellung fuer Exportjobs.

## Docker-Compose-Betrieb

Der Docker-Compose-Betrieb ist umgesetzt. Das Zielbild:

```text
web       Django-App (Build-Target web, ohne FreeCAD)
db        PostgreSQL
media     Volume fuer FCStd- und Exportdateien
worker    FreeCADCmd-Worker (Build-Target worker)
```

Zusaetzlich gibt es `.forgejo/workflows/build-image.yml` fuer den automatischen
Image-Build und `docker-compose.image.yml` fuer den Betrieb mit fertigen Images.
