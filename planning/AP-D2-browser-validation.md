# AP-D2 – Navigation zur Fertigung (14.11.2026)

## Bestandsaufnahme

AP-D1 war bereits umgesetzt: `/parts/<id>/manufacturing/` ist für angemeldete
Reader, Editor und Admin erreichbar. Die Projektseite führt zu Teilen; die
Teilseite hat `page-header-actions`, die Suche Tabellen für Teil- und
Revisionstreffer. Ausgangszustand im Playwright-MCP-Browser dokumentiert:
`../.playwright-mcp/d2-before-project.png`,
`../.playwright-mcp/d2-before-part.png`,
`../.playwright-mcp/d2-before-search.png`,
`../.playwright-mcp/d2-before-manufacturing.png`.

## Änderungen

- Ein Button in der Kopfzeile jedes Teils (auch ohne Fertigungsdateien).
- „Fertigung“-Spalte in den Teil- und Revisions-Suchergebnissen; ein Link
  erscheint nur, wenn das jeweilige Teil Fertigungsdateien hat. Die Spalte
  steht direkt neben der Teilenummer, damit sie mobil sichtbar bleibt.
- `Exists`-Annotationen in den bestehenden Such-Querysets vermeiden zusätzliche
  Abfragen je Treffer. Bestehende APIs und Modelle blieben unverändert.
- Das vorhandene zweispaltige Suchformular wurde für Mobilansichten
  einspaltig gemacht.

## Browserprüfung

Playwright MCP / Chrome for Testing, ausschließlich isolierte Testdaten in
`/tmp/opencode/d1-browser` (Reader-Session; Projektdaten aus AP-D1).

- Leser: Teil mit Dateien → Kopfzeilenbutton → Fertigungsseite: erfolgreich.
- Suche → Link im Teiltreffer und im Revisionstreffer → Fertigungsseite:
  beide Klickpfade erfolgreich. Teil ohne Dateien: in der Suche nur „–“
  statt Link. Projekt → Teil ohne Revision → Kopfzeilenbutton →
  Fertigungsseite: erfolgreich, leere Liste sichtbar.
- Bei der ursprünglichen D2-Prüfung blockierte ein vorbestehender Dialog-CSS-
  Fehler den Schritt Projekt → Teil; damals wurde im Test-Browser temporär
  eine Regel für geschlossene Dialoge injiziert. Der anschließend beauftragte
  **globale Dialog-CSS-Fix** beseitigte die Ursache; Projekt → Teil und
  Suche → Fertigung wurden danach ohne Injektion erneut im Browser geprüft.
- Visuelle Kontrolle bei 1440 × 900 und 390 × 844: Kopfzeile und Links
  lesbar; Suche mobil ohne Seitenüberbreite, Tabellen intern scrollbar.
  Screenshots: `../.playwright-mcp/d2-part-desktop.png`,
  `../.playwright-mcp/d2-part-no-files-mobile.png`,
  `../.playwright-mcp/d2-search-desktop-final.png`,
  `../.playwright-mcp/d2-search-mobile-final.png`.
- Browserkonsole: 0 Fehler; beobachtete Jobs-Status-Requests: HTTP 200.

Automatisierte Tests: vier neue Navigationstests einschließlich
Reader/Editor/Admin, positiver/negativer Treffer und konstantem
SQL-Abfragezähler. Gesamtsuite nach dem globalen Dialog-CSS-Fix:
**415 Tests erfolgreich, 1 übersprungen** (einschließlich CSS-Regressionstest).
