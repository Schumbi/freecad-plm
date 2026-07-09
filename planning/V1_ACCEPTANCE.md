# V1 Browser-Abnahme

## Zweck

Diese Checkliste ergaenzt `planning/ACCEPTANCE_CRITERIA.md` um eine dokumentierbare manuelle Abnahme. Sie dient als Nachweis, dass V1 im Alltag nutzbar ist — nicht nur in Tests und auf dem Papier.

**Stand der Implementierung:** 2026-07-10 — alle V1-Kriterien sind im Code umgesetzt; die Browser-Abnahme steht noch aus.

## Vorbereitung

- Testnutzer mit Rollen `admin`, `editor` und `reader` anlegen (`manage.py setup_plm_roles`).
- Laufende Instanz: lokal oder Zielserver mit Docker Compose und FreeCADCmd-Worker.
- Echte `.FCStd`-Testdateien bereithalten, idealerweise inklusive referenzierter Baugruppe.

| Feld | Wert |
|------|------|
| Instanz | |
| Datum | |
| Tester | |
| Image/Commit | |

## V0 Browser-Abnahme

| # | Pruefpunkt | admin | editor | reader | OK |
|---|------------|-------|--------|--------|-----|
| 1 | Projekt anlegen | x | | | |
| 2 | Teil/Baugruppe mit initialer FCStd, leere Nummer/Name | | x | | |
| 3 | Doppel-Upload mit gleichem SHA-256 blockiert | | x | | |
| 4 | Revision herunterladen | x | x | x | |
| 5 | FreeCAD-Metadaten sichtbar | x | x | x | |
| 6 | Revisionsanmerkungen lesen/bearbeiten | x | x | lesen | |
| 7 | Draft-Revision freigeben | x | | | |
| 8 | Reader: kein Upload, keine Freigabe | | | x | |

## V1 Browser-Abnahme

| # | Pruefpunkt | admin | editor | reader | OK |
|---|------------|-------|--------|--------|-----|
| 1 | Kurzworkflow aus Root-`README.md` komplett | x | x | x | |
| 2 | PLMRevision-Konflikt: Upload verwerfen | | x | | |
| 3 | PLMRevision-Konflikt: normalisierte Kopie speichern | | x | | |
| 4 | Projekt-ZIP importieren, Projektstand pruefen | x | x | | |
| 5 | Snapshot-ZIP herunterladen, Pfade vergleichen | x | x | x | |
| 6 | Referenzierte Revision: ZIP mit rekursiven Referenzen | x | x | x | |
| 7 | Freigegebene Revision als obsolet markieren | x | | | |
| 8 | Globale Suche: Projektcode | x | x | x | |
| 9 | Globale Suche: Teilenummer | x | x | x | |
| 10 | Globale Suche: Revisionscode | x | x | x | |
| 11 | Globale Suche: Dateiname / Projektpfad | x | x | x | |
| 12 | FreeCADCmd-Analyse mit echter FCStd | x | x | | |
| 13 | STEP-, STL-, 3MF-Artefakte erzeugen und laden | x | x | | |
| 14 | PNG-Ansichten erzeugen und Galerie anzeigen | x | x | x | |
| 15 | Revisionsvergleich ueber PNG-Ansichten | x | x | x | |
| 16 | 3D-Viewer mit FCStd/STEP/STL/3MF | x | x | x | |
| 17 | Hintergrundjobs in Sidebar sichtbar (Polling) | x | x | | |
| 18 | FreeCAD-Addon: Checkout, Bearbeitung, Check-in E2E | x | x | | |

## Betrieb Zielserver

| # | Pruefpunkt | OK |
|---|------------|-----|
| 1 | Docker Compose mit PostgreSQL und Media-Volume | |
| 2 | Worker verarbeitet Exportjobs mit echtem FreeCADCmd | |
| 3 | Haengengebliebene Jobs werden als fehlgeschlagen recovered | |
| 4 | `docker compose pull && up -d` nach Image-Update | |
| 5 | Logs ueber `docker compose logs web worker` auswertbar | |

## Ergebnis

- [ ] V0 fachlich abgenommen
- [ ] V1 fachlich abgenommen
- [ ] Offene Punkte dokumentiert (siehe unten)

### Offene Punkte / Abweichungen

_(Hier Eintraege mit Datum und kurzer Begruendung, falls etwas nicht OK ist.)_

### Freigabe V1.0

_(Datum und Name, wenn alle Must-have-Punkte erfuellt sind.)_
