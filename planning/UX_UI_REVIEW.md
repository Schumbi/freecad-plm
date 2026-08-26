# UX/UI-Umsetzung 2026-08-26

## Ziel

Die sieben priorisierten UX-Verbesserungen verbinden den täglichen
FreeCAD-Arbeitsfluss stärker mit Suche, Revisionen, Fertigung und visueller
Prüfung im Web. Die fachlichen Regeln für unveränderliche Revisionen,
Checkouts und Berechtigungen bleiben dabei erhalten.

## Umgesetzte Punkte

1. **Ein hierarchischer Browser im Add-on**
   - Projekte, Teile/Baugruppen und Revisionen stehen in einem einzigen,
     aufklappbaren Baum.
   - Teile und Revisionen werden erst beim Aufklappen geladen.
   - Doppelklick und Kontextmenüs bieten die zum Knoten passenden Aktionen.

2. **Checkouts im Projektbaum und eine kontextabhängige Arbeitsleiste**
   - Aktive Checkouts werden an ihrer Revision markiert und deren Projekt- und
     Teilpfad automatisch aufgeklappt.
   - Grün und fett kennzeichnet den lokal geöffneten Checkout, Orange einen nur
     serverseitig aktiven Checkout und Rot einen inkonsistenten Zustand.
   - Die Arbeitsleiste zeigt genau eine Hauptaktion für die aktuelle Auswahl;
     seltenere oder riskante Aktionen liegen unter `Mehr`.

3. **Facettierte globale Suche**
   - `/search/` kann zusätzlich nach Projekt, Revisionsstatus, CAD-Format und
     Teilekategorie filtern.
   - Facetten funktionieren auch ohne freien Suchtext.

4. **Drag-and-drop für Uploads**
   - Neue CAD-Revisionen und Fertigungsdateien können in die jeweiligen
     Uploadbereiche gezogen werden.
   - Die serverseitige Validierung und Dateigrößenbegrenzung bleibt
     unverändert maßgeblich.

5. **Slicer-Status direkt an Revisionen**
   - Revisionskarten zeigen, ob und wann zuletzt ein synchronisierter
     3MF-Slicer-Arbeitsstand gespeichert wurde.

6. **Gemeinsamer Teile-Lebenszyklus**
   - Die Teilseite führt CAD-Revisionen, Freigaben, Slicer-Stände,
     Fertigungsdateien und Fertigungsläufe in einer chronologischen Ansicht
     zusammen.
   - Später aus Bambuddy importierte Fertigungsläufe erscheinen über dasselbe
     Datenmodell automatisch in dieser Ansicht.

7. **Baugruppenstruktur, sichere Deep Links und 3D-Anmerkungen**
   - Baugruppen zeigen aus dem historischen Projektstand abgeleitete,
     aufklappbare Referenzbäume. Nicht auflösbare Referenzen werden sichtbar
     markiert und nicht geraten.
   - Revisionskarten bieten `freecad-plm://revision/...`-Links. Das Add-on
     akzeptiert nur bekannte Parameter und Aktionen, prüft Projekt/Teil gegen
     die Serverantwort und bestätigt einen Checkout nochmals.
   - Im Web-Viewer können berechtigte Nutzer einen Punkt am Modell wählen und
     dort eine normale PLM-Anmerkung verankern. Die Koordinaten und optionale
     Kameraposition werden zusammen mit der Anmerkung gespeichert.

## Sicherheits- und Konsistenzregeln

- Deep Links enthalten keine Token oder sonstigen Zugangsdaten.
- Unbekannte URL-Parameter, Aktionen und ungültige IDs werden abgewiesen.
- Der Server entscheidet weiterhin über Berechtigungen, Locks und gültige
  Beziehungen.
- 3D-Punkte und Kamerawerte werden auf endliche, begrenzte Zahlen reduziert.
- Die BOM verwendet ausschließlich Revisionen aus einem gespeicherten
  Projektstand. Ohne eindeutige Zuordnung bleibt ein Eintrag `Nicht aufgelöst`.

## Automatisierte Abnahme

- Server: 241 Tests erfolgreich.
- Add-on: 163 Tests erfolgreich.
- `manage.py check` und `makemigrations --check --dry-run` erfolgreich.
- Python- und JavaScript-Syntaxprüfungen erfolgreich.

## Noch manuell zu prüfen

- Baum-Navigation und Kontextmenüs im echten FreeCAD-Dock.
- Drag-and-drop in den verwendeten Desktop-Browsern.
- Erstellen und Wiederanzeigen eines 3D-Hotspots mit einer echten
  Worker-Vorschau.
- Betriebssystem-Zuordnung des Schemas `freecad-plm://`. Ohne Zuordnung kann
  derselbe Link über den FreeCAD-Befehl `PLM-Link öffnen` eingefügt werden.
