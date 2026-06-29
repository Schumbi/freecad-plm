# FreeCAD-PLM Planning

## Zweck

Dieser Ordner ist die dauerhafte Kontextablage fuer das neue FreeCAD-PLM. Neue Sessions sollen zuerst diese Datei lesen, damit der Chatverlauf nicht die einzige Quelle fuer Projektstand, Entscheidungen und offene Punkte ist.

## Projektziel

Wir planen ein eigenes PLM/PDM fuer FreeCAD-Dateien. Es soll nicht das alte nanoPLM umbauen, sondern als neues Projekt entstehen. Das alte nanoPLM liegt als Referenz unter `old/`.

Der erste fachliche Schwerpunkt ist die robuste Verwaltung von FreeCAD-`FCStd`-Dateien fuer ein kleines LAN-Team:

- Projekte verwalten
- Teile und Baugruppen verwalten
- `FCStd`-Dateien hochladen
- unveraenderliche Revisionen anlegen
- Freigabestatus nachvollziehen
- Dateien suchen, anzeigen und herunterladen
- Benutzer und Rollen abbilden

## Aktueller Stand

- Das vorhandene nanoPLM wurde grob analysiert.
- Der alte nanoPLM-Code wurde nach `old/` verschoben.
- Flask wurde als Default-Technologie infrage gestellt.
- Django ist aktuell der bevorzugte Kandidat, weil Auth, Admin, Rollen, Migrationen und Datei-Handling Kernfunktionen fuer ein PLM sind.
- Docker Compose ist ein spaeteres Ziel, soll aber bei der Architektur von Anfang an mitgedacht werden.

## Lesereihenfolge

1. `planning/README.md`
2. `planning/REQUIREMENTS.md`
3. `planning/ARCHITECTURE.md`
4. `planning/ROADMAP.md`
5. `planning/ACCEPTANCE_CRITERIA.md`
6. `planning/DECISIONS.md`
7. `planning/TODO.md`
8. `planning/SESSION_NOTES.md`
9. `planning/FREECAD_ADDON_PLAN.md`
10. `planning/UI_REDESIGN_PLAN.md`

## Arbeitsregel

Wenn wichtige Anforderungen, Entscheidungen oder erledigte Schritte entstehen, werden sie hier im `planning/`-Ordner nachgezogen. Die Dateien muessen nicht perfekt sein; wichtiger ist, dass sie den aktuellen Stand vernuenftig konservieren.
