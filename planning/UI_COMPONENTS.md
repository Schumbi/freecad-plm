# UI-Komponenten und Interaktionsmuster

Dieses Dokument beschreibt die verbindlichen Muster der PLM-Oberfläche. Neue
Ansichten sollen diese Bausteine verwenden, statt eigene Varianten zu bauen.
Grundlage ist das UX-Audit vom 2026-11-14 (`UX_AUDIT_2026-11-14.md`).

## Listen und Tabellen

- **Eine Entität, ein Link:** Der Name/die Nummer einer Zeile ist immer ein
  echtes `<a>`-Element. Zeilenklick ist nur eine Zugabe für die Maus.
- **Zeilenklick:** `tr data-row-href="…"`, Handler in `app.js`
  (`setupClickableRows`). Klicks auf Links, Buttons, Eingaben, Labels und
  Textauswahl lösen keine Navigation aus.
- **Aktionsspalte:** Sekundäre Aktionen als Textlink (`.link-button`),
  destruktive Aktionen als `.danger-link`.
- **Mobile Tabellen:** Unter 700 px werden Projekt-Detailtabellen zu Karten
  (`td::before { content: attr(data-label) }`). Neue Tabellen brauchen
  `data-label` an jeder Zelle.

## Formulare

- Alle Felder über `includes/form_field.html` rendern. Das liefert
  Pflichtfeld-Sternchen, Hilfe- und Fehlertexte inklusive `aria-describedby`.
- Fehlerzusammenfassung über `includes/form_fields.html`
  (`role="alert"`, Fokus auf das erste fehlerhafte Feld via `app.js`).
- Labels ohne Doppelpunkt; Einheiten in Klammern (`Düse (mm)`).
- Feldgruppen mit `<fieldset>`/`<legend>` und einem Raster
  (`.form-grid.two-columns`), nicht als lange Einspaltenliste.

## Dialoge

- Native `<dialog>` + `showModal()`; Öffnen über `data-dialog-target="#id"`,
  Schließen über `data-dialog-close`.
- Titel über `aria-labelledby`; Schließen-Button mit `aria-label`.
- Bestätigungen: Formular mit `data-confirm="Text"`; der gemeinsame Dialog
  `#confirm-dialog` übernimmt Anzeige und Fokus.
- Felder in Dialogen brauchen eindeutige IDs (`id_prefix` an Formularen),
  wenn mehrere Dialoge gleichzeitig im DOM liegen.

## Filter und Suche

- Filterzustand steht in der URL und wird als entfernbare Chips angezeigt
  (`.active-filters`, `.filter-chip`).
- Leerzustände nennen die Ursache und bieten eine primäre Aktion
  (Filter zurücksetzen bzw. Objekt anlegen).
- Ein Suchfeld pro Seite. Facetten ändern die URL und wenden sich sofort an
  (Enter bzw. Änderung), nicht über einen separaten „Suchen“-Schritt.

## Status und Rückmeldung

- Servermeldungen: `role="status"`/`role="alert"`; Fehler verschwinden nicht
  automatisch.
- Laufende Hintergrundjobs: Seitenleiste mit `aria-live="polite"`.
- Toggles: `aria-pressed` plus sichtbarer „gedrückt“-Zustand
  (`.model-viewer-toolbar-actions button[aria-pressed="true"]`).

## Navigation

- Aktiver Bereich kommt aus `plm.context_processors.navigation`
  (`active_section`), inklusive `aria-current="page"`.
- Mobile: Off-Canvas-Drawer, Standard geschlossen, Zustand in
  `localStorage`, Fokus-Falle und `Esc`.
- Breadcrumbs beginnen im jeweiligen Bereich (Projekte bzw. Verwaltung).

## Barrierefreiheit

- Skip-Link (`#main`) ist das erste fokussierbare Element.
- Kontrast: Text auf `--accent` erfüllt AA (5,47:1); `--muted` wurde
  abgedunkelt. Neue Farben immer gegen `--surface` und `--app-bg` prüfen.
- Seitentitel über `{% block title %}` setzen: „Objekt · FreeCAD-PLM“.
