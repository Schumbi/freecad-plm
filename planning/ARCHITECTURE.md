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
- Docker Compose ist spaeter gut moeglich.

Nicht favorisiert fuer v1:

- Flask als Hauptframework: zu viel eigene Zusammensetzung fuer Auth, Admin, Rollen, Migrationen und robuste Projektstruktur.
- FastAPI als Hauptframework: stark fuer API-first, aber fuer ein internes PLM mit serverseitiger UI mehr Eigenbau.
- Go als Hauptbackend: gutes Deployment-Modell, aber weniger passend fuer FreeCAD-nahe Automatisierung und interne Admin-/Formularfunktionen.

## UI-Ansatz

- Serverseitige Django-Templates als Basis.
- Bootstrap oder ein vergleichbar schlichter CSS-Ansatz fuer eine robuste Arbeitsoberflaeche.
- Optional HTMX fuer dynamische Bereiche ohne grosse Frontend-SPA.
- Keine React/Vue/Svelte-SPA fuer v1, solange kein klarer Bedarf entsteht.

## Datenhaltung

- Entwicklung zuerst mit SQLite moeglich.
- Datenmodell PostgreSQL-kompatibel halten.
- Spaeteres Docker-Compose-Ziel mit PostgreSQL vorsehen.
- CAD-Dateien nicht in der Datenbank speichern.
- Dateien in einem Storage-Verzeichnis oder Docker-Volume ablegen.
- Datenbank speichert Metadaten, Pfade, Hashes, Status und Beziehungen.

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

V1:

- `FCStd` als Datei validieren.
- `FCStd` als ZIP lesen.
- Basis-Metadaten extrahieren, soweit ohne FreeCAD moeglich.
- Optionaler FreeCADCmd-Joblauf fuer abgeleitete Artefakte:
  - Analyse von exportierbaren Objekten und VarSet-Parametern.
  - Export nach STEP, STL und 3MF.
  - PNG-Ansichten fuer visuelle Vergleiche.
- Lokale Flatpak-Installationen werden ueber `FREECADCMD_COMMAND` unterstuetzt, z.B. `flatpak run --branch=stable --arch=x86_64 --command=FreeCADCmd org.freecad.FreeCAD`.
- STEP/STL/3MF-Exporte sind der robuste Headless-Pfad.
- PNG-Ansichten nutzen ebenfalls keinen FreeCAD-GUI-Viewport mehr: FreeCADCmd exportiert ein STEP-Artefakt und ein temporaeres STL-Vorschau-Mesh, danach rendert das PLM deterministische PNG-Ansichten aus dem STL.
- Vor dem FreeCADCmd-Aufruf werden referenzierte FCStd-Dateien aus demselben Projekt in den temporaeren Arbeitsordner kopiert, damit einfache Baugruppenlinks aufgeloest werden koennen.

Spaeter:

- Separater dauerhafter Worker fuer FreeCADCmd.
- Exporte nach PDF, DXF und weiteren Formaten.
- Bearbeitung von VarSet-Parametern und Neurendern mit Varianten.
- Status und Logs fuer Exportjobs.
- Worker als eigener Docker-Compose-Service denkbar.

## Spaeteres Docker-Compose-Zielbild

```text
web       Django-App
db        PostgreSQL
media     Volume fuer FCStd- und Exportdateien
worker    optionaler FreeCADCmd-Worker mit konfigurierbarem FREECADCMD_COMMAND
```

Docker Compose ist kein v1-Muss, aber Architektur und Pfade sollen so gewaehlt werden, dass ein spaeterer Umzug nicht weh tut.
