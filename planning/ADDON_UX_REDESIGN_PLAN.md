# FreeCAD-PLM Addon UX-Redesign-Plan

## Ziel

Das FreeCAD-Addon soll sich stärker wie ein Arbeitswerkzeug für Konstruktion anfühlen und weniger wie eine vollständige Datenbankmaske. Die wichtigste Aufgabe im Addon ist:

1. PLM verbinden.
2. Projekt und Teil finden.
3. Revision öffnen oder auschecken.
4. In FreeCAD arbeiten.
5. Änderungen einchecken oder Checkout abbrechen.

Alle ergänzenden Informationen wie Projektstammdaten, technische Metadaten, Notizen und Anmerkungen sollen erreichbar bleiben, aber nicht dauerhaft das Hauptpanel überladen.

## Aktueller Befund

Die zentrale UI liegt in `/home/ralf/devel/freecad-plm-addon/freecad_plm_addon/panel.py`.

Aktuell zeigt das Dock sehr viele Dinge gleichzeitig:

- Verbindungseinstellungen
- Projektliste
- Teileliste
- Revisionsliste
- Projektformular
- Teilformular
- Revisionsübersicht
- Revisionsnotizen
- Anmerkungen
- technische Metadaten
- Read-only-Button
- Checkout-Button
- aktive Checkouts
- Check-in / Checkout abbrechen
- Statusmeldungen

Das ist funktional, aber visuell und mental zu dicht. Für den normalen FreeCAD-Workflow sind vor allem Projekt, Teil, Revision und Checkout-Zustand wichtig.

## Zielbild der Oberfläche

Das Dock wird auf drei Zonen reduziert.

### 1. Kopfbereich

Zeigt nur:

- Verbindungsstatus, z. B. `Verbunden mit plm.lan.schumbi.de`
- Button `Aktualisieren`
- Button `Einstellungen`
- optional später ein lokales Filterfeld

Die Einstellungen bleiben einklappbar. Server-URL, Token und Cache-Limits sollen nicht dauerhaft Platz verbrauchen.

### 2. Browserbereich

Der Browser bleibt links bzw. oben im Dock und enthält:

- Projekte
- Teile/Baugruppen
- Revisionen

Die Listen sollen möglichst kurze, scanbare Labels bekommen.

Empfohlene Labels:

- Projekt: `CODE - Name`
- Teil: `P-001 - Box`
- Revision: `R0001 · Entwurf · Box.FCStd · 10.07.2026`

Die Revisionsliste wird zur primären Arbeitsfläche:

- Einfachklick: Revision auswählen und kurze Zusammenfassung anzeigen.
- Doppelklick: Revision auschecken.
- Rechtsklick/Kontextmenü: `Auschecken`, `Read-only öffnen`, `Details`, `Notizen`, `Anmerkungen`.

### 3. Aktions- und Statusbereich

Unten im Dock steht nur noch:

- kurze Revisionszusammenfassung
- Primärbutton `Auschecken`
- Sekundärbutton `Read-only öffnen`
- Buttons `Details`, `Notizen`, `Anmerkungen`
- Abschnitt `Aktiver Checkout`
- Buttons `Öffnen`, `Einchecken`, `Abbrechen`
- kurze Statuszeile

Projekt- und Teilbearbeitung wandern in Dialoge.

## Verhaltensänderungen

### Doppelklick auf Revision

Ein Doppelklick auf eine Revision soll `Auschecken` auslösen.

Regeln:

1. Kein aktiver Checkout:
   - Revision direkt auschecken.

2. Derselbe Checkout ist bereits aktiv:
   - Root-Datei wieder öffnen oder fokussieren.
   - Kein neuer Checkout.

3. Ein anderer Checkout ist aktiv:
   - Dialog anzeigen:
     - `Aktiven Checkout öffnen`
     - `Einchecken`
     - `Checkout abbrechen`
     - `Nicht starten`
   - Kein stiller neuer Checkout.

4. Server meldet bereits aktiven Checkout:
   - Fehlermeldung handlungsorientiert anzeigen.
   - Aktive Checkouts neu laden.

### Aktive Checkouts

Aktive Checkouts sollen prominenter angezeigt werden.

Anzeige:

```text
Aktiver Checkout
CHIPBOX · P-001 Box · R0001
/home/ralf/FreeCAD-PLM/...
```

Aktionen:

- `Öffnen`
- `Einchecken`
- `Abbrechen`

Die bisherige Liste aktiver Checkouts kann bleiben, soll aber weniger Raum einnehmen. Wenn nur ein Checkout aktiv ist, reicht eine kompakte Karte plus Button.

### Details in Dialoge auslagern

Diese Inhalte gehören nicht dauerhaft ins Hauptpanel:

- Projekt bearbeiten
- Teil bearbeiten
- Revisionsdetails
- technische Metadaten / JSON
- Revisionsnotizen
- Anmerkungen

Stattdessen:

- `Projekt bearbeiten` öffnet einen Dialog mit Code, Name, Status, Datum, Beschreibung.
- `Teil bearbeiten` öffnet einen Dialog mit Name, Kategorie, Beschreibung, Material, Tags.
- `Details` öffnet einen Dialog mit kompakten Revisionsdaten.
- `Technik` bzw. technische Metadaten liegen als Tab im Detaildialog.
- `Notizen` öffnet einen kleinen Editor-Dialog.
- `Anmerkungen` öffnet einen eigenen Dialog mit Filter und Aktionen.

## Technische Umsetzung

### Neue reine Helferfunktionen in `panel.py`

Einführen:

```python
def active_checkout_revision_id(checkout): ...
def checkout_guard_action(active_checkout, target_revision): ...
def compact_revision_summary(revision): ...
```

Erwartete Rückgaben von `checkout_guard_action`:

- `missing_revision`
- `checkout`
- `same_checkout`
- `blocked_by_other_checkout`

Diese Funktionen sind ohne Qt testbar.

### Signalverdrahtung

In `PLMPanel.__init__` ergänzen:

```python
self.revisions.itemDoubleClicked.connect(self.checkout_selected_revision)
```

Optional später:

```python
self.revisions.setContextMenuPolicy(...)
```

### Checkout-Guard

`checkout_selected_revision()` darf nicht mehr blind `checkout_revision_to_workspace()` aufrufen.

Stattdessen:

1. Projekt und Revision prüfen.
2. `checkout_guard_action(self.active_checkout, revision)` auswerten.
3. Bei `checkout`: normal auschecken.
4. Bei `same_checkout`: aktiven Checkout öffnen/fokussieren.
5. Bei `blocked_by_other_checkout`: Entscheidungsdialog anzeigen.

### Dialoge

Neue Methoden in `PLMPanel`:

```python
def show_project_dialog(self): ...
def show_part_dialog(self): ...
def show_revision_details_dialog(self): ...
def show_revision_notes_dialog(self): ...
def show_annotations_dialog(self): ...
def ask_checkout_conflict_action(self, target_revision): ...
```

Die vorhandenen Widgets können zunächst weiter intern genutzt werden, sollten aber nicht dauerhaft im Hauptpanel sichtbar sein. Für den ersten Schritt reicht:

- `detail_tabs.setVisible(False)`
- neue kompakte Action-Widgets im Hauptpanel
- Dialoge mit neuen lokalen Widgets für Bearbeitung

### Bestehende API bleibt unverändert

Keine Serveränderungen nötig.

Weiter genutzt werden:

- `GET /api/projects/`
- `GET /api/projects/<id>/parts/`
- `GET /api/parts/<id>/`
- `POST /api/revisions/<id>/checkout/`
- `GET /api/checkouts/active/`
- `GET /api/checkouts/<id>/manifest/`
- `POST /api/checkouts/<id>/checkin/`
- `POST /api/checkouts/<id>/cancel/`

## Tests

Automatische Tests in `tests/test_panel.py` ergänzen:

- `active_checkout_revision_id()` erkennt verschachtelte Revision.
- `active_checkout_revision_id()` erkennt `revision_id` und `base_revision_id`.
- `checkout_guard_action(None, revision)` ergibt `checkout`.
- `checkout_guard_action(active_same, revision)` ergibt `same_checkout`.
- `checkout_guard_action(active_other, revision)` ergibt `blocked_by_other_checkout`.
- `checkout_guard_action(active, {})` ergibt `missing_revision`.
- `compact_revision_summary()` zeigt Revision, Status, Datei, Datum.

Bestehende Tests weiter ausführen:

```bash
cd /home/ralf/devel/freecad-plm-addon
python3 -m unittest discover -s tests
```

## Manuelle Abnahme in FreeCAD

1. FreeCAD starten.
2. Workbench `FreeCAD-PLM` aktivieren.
3. Verbinden und Projektliste laden.
4. Projekt auswählen.
5. Teil auswählen.
6. Revision doppelklicken.
7. Erwartung: Checkout startet und Root-Datei öffnet sich.
8. Dieselbe Revision erneut doppelklicken.
9. Erwartung: kein neuer Checkout; vorhandener Checkout wird geöffnet/fokussiert.
10. Bei aktivem Checkout eine andere Revision doppelklicken.
11. Erwartung: Dialog fragt nach gewünschter Aktion.
12. Einchecken mit Änderung testen.
13. Einchecken ohne modellrelevante Änderung testen.
14. Checkout abbrechen testen.
15. Read-only öffnen testen.
16. Notizen und Anmerkungen über Dialoge testen.

## Nicht in diesem Schritt

- Keine Server-API ändern.
- Keine neue Authentifizierung.
- Kein vollständiger grafischer Redesign-Stil.
- Keine neue FreeCAD-Viewport-Annotation.
- Keine Änderung am Check-in-Protokoll.

## Empfohlene Commit-Struktur

1. `Refactor addon panel around primary workflow`
   - Layout, Dialoge, Doppelklick, Checkout-Guard.

2. `Add tests for addon checkout UX helpers`
   - reine Helfertests.

Wenn die Änderung klein genug bleibt, kann beides auch ein Commit sein:

```text
Improve FreeCAD addon checkout UX
```
