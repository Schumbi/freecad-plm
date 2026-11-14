# AP-D1 – Browserprüfung (14.11.2026)

Testumgebung: Django-Entwicklungsserver auf `127.0.0.1:8765`, separate SQLite-Datenbank und
Uploads unter `/tmp/opencode/d1-browser`, ausschließlich eigens angelegte Testnutzer
(`reader`, `editor`, `admin`) und Testobjekte. Browser: Playwright MCP / Chrome for Testing.

## Bestandsaufnahme

- Bestehende Teilseite: Fertigung je Revision in einem Dialog, Upload über
  `upload_manufacturing_file`; Navigation über Projekt → Teil, Breadcrumbs und Seitenleiste.
- Design: dunkle Seitenleiste, helle Inhaltskarten, `page-header`, `toolbar`, `table-wrap`,
  `form-card`; neue Seite verwendet diese vorhandenen Bausteine.
- Screenshots: `../.playwright-mcp/d1-baseline-login.png`,
  `../.playwright-mcp/d1-baseline-part.png`.

## Durchführung und Ergebnisse

- Editor: `/parts/1/manufacturing/` geöffnet, Breadcrumbs und Rücklink geprüft;
  Dateitypfilter auf „Fertigungs-PDF“ zeigt korrekt leeren Zustand.
- Editor: `.gcode` hochgeladen; neue Datei erschien sofort in der Liste.
  Wiederholung desselben Uploads ergab HTTP 400 mit sichtbarer Meldung
  „Diese Fertigungsdatei ist fuer diese Revision bereits vorhanden.“
- Teil ohne Revision: Hinweis „Keine aktive Revision vorhanden. Upload nicht möglich.“;
  manipulierter POST wurde mit HTTP 400 und Fehlermeldung abgewiesen.
- Reader: Liste lesbar; Uploadformular und Löschen-Links fehlen. Admin:
  Löschlinks vorhanden (nur die bestehende Bestätigungsseite, kein Löschvorgang ausgeführt).
- 1440 × 900 und 390 × 844 geprüft: keine horizontale Seitenüberbreite;
  Tabelle ist auf Mobilgeräten innerhalb von `.table-wrap` horizontal scrollbar.
  Screenshots: `../.playwright-mcp/d1-desktop-1440.png`,
  `../.playwright-mcp/d1-mobile-390.png`, finaler Reader-Screenshot
  `../.playwright-mcp/d1-reader-final.png`.
- Browserkonsole/Netzwerk: zwei HTTP-400-Einträge stammen ausschließlich aus den
  absichtlich fehlerhaften POST-Tests. Sonstige sichtbare Requests (Jobs-Status)
  waren erfolgreich. Nach dem abschließenden, frischen Seitenaufruf: null
  Konsolenfehler und nur HTTP 200 für den Jobs-Status.

## Bestehende Einschränkung außerhalb AP-D1

Die bereits bestehende CSS-Regel `.plm-dialog { display: flex; }` zeigt den
**geschlossenen** globalen 3D-Dialog auf der bisherigen Teilseite über dem
eigentlichen Inhalt. Das ist Teil der separaten `<dialog>`-Migration AP-C1.
Für die erste D1-Prüfung wurde ausschließlich in der Test-Browsersitzung
`dialog.plm-dialog:not([open]) { display: none !important; }` injiziert.
Anschließend wurde der geschlossene Dialog **nur im neuen D1-Template**
ausgeblendet; der frische Browseraufruf bestätigt `display: none` ohne Injektion.
Die globale CSS-Regel und die bisherigen Seiten wurden nicht verändert.

**Nachtrag (14.11.2026):** Der seither beauftragte globale Dialog-CSS-Fix
ersetzt den oben beschriebenen lokalen Workaround. Geschlossene Dialoge sind
nun auf allen Seiten verborgen; die bisherigen Klickblockaden entfallen.
Der unveränderte Ist-Zustand ist im Screenshot `../.playwright-mcp/d1-desktop.png`
dokumentiert; der Screenshot mit Browser-Workaround unter
`../.playwright-mcp/d1-desktop-workaround.png`.

Automatisierte Tests: `python manage.py test plm --noinput` → 410 Tests erfolgreich,
1 übersprungen (inkl. fünf neuen AP-D1-Tests).
