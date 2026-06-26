# Requirements

## Zweck

Diese Datei sammelt fachliche Anforderungen, Annahmen und offene Fragen fuer das neue FreeCAD-PLM.

## Zielgruppe

Primaere Zielgruppe ist ein kleines LAN-Team, das FreeCAD-Dateien gemeinsam verwalten will. Die Anwendung soll lokal oder im lokalen Netzwerk laufen und spaeter per Docker Compose deploybar sein.

## Kernobjekte

- `Project`: ein Entwicklungsprojekt oder Produktkontext.
- `Part`: ein Teil oder eine Baugruppe innerhalb eines Projekts.
- `Revision`: ein unveraenderlicher Dateistand eines Teils oder einer Baugruppe.
- `User`: ein Benutzer mit Rolle.
- `AuditEvent`: ein nachvollziehbarer Eintrag fuer relevante Aktionen.

## V1-Anforderungen

- Benutzer koennen sich anmelden.
- Rollenmodell mit mindestens `admin`, `editor`, `reader`.
- Admins koennen Benutzer verwalten.
- Projekte koennen angelegt, bearbeitet und archiviert werden.
- Teile oder Baugruppen koennen einem Projekt zugeordnet werden.
- `FCStd`-Dateien koennen manuell ueber die Weboberflaeche hochgeladen werden.
- Jeder Upload erzeugt eine neue unveraenderliche Revision.
- Revisionen haben Status, mindestens `draft`, `released`, `obsolete`.
- Freigegebene Revisionen duerfen nicht ueberschrieben werden.
- Dateien werden im Dateisystem abgelegt.
- Metadaten und Beziehungen werden in der Datenbank gespeichert.
- Downloads sind nur fuer angemeldete Benutzer moeglich.
- Wichtige Aktionen werden in einem Audit-Trail protokolliert.
- `FCStd`-Uploads werden mindestens als ZIP-Datei validiert.
- Soweit ohne FreeCAD-Installation moeglich, werden Metadaten aus der `FCStd`-Datei extrahiert.
- Revisionen koennen Freitext-Anmerkungen enthalten, z.B. naechste Schritte, Einbauhinweise oder kurze Arbeitsnotizen.
- FreeCAD-Dokumentmetadaten aus `Document.xml` sollen beim Upload ausgelesen und pro Revision gespeichert werden.
- Aenderungen an FreeCAD-Dokumentmetadaten wie License, Label oder Comment erzeugen durch erneuten Upload eine neue Revision; bestehende Revisionen werden nicht veraendert.

## Nicht Ziel Fuer V1

- Kein Umbau des alten nanoPLM.
- Kein automatischer Import bestehender Ordner.
- Kein verpflichtender FreeCADCmd- oder FreeCAD-GUI-Betrieb.
- Keine automatische STEP/STL/PDF/DXF-Erzeugung.
- Keine vollstaendige Stuecklistenverwaltung.
- Kein komplexer mehrstufiger Freigabeprozess.

## Offen

- Soll es getrennte Begriffe fuer Teil und Baugruppe geben oder reicht ein gemeinsamer Typ mit Kategorie?
- Welche Pflichtfelder braucht ein Teil mindestens: Nummer, Name, Beschreibung, Material, Lieferant, Tags?
- Wie soll die Teilenummer entstehen: manuell, Nummernkreis, automatisch?
- Wer darf Revisionen freigeben: nur Admins oder auch Editors?
- Wie gross koennen typische `FCStd`-Dateien werden?
- Welche Metadaten aus `FCStd` sind wirklich nuetzlich?
- Soll die Anwendung deutsch-only starten oder von Anfang an internationalisierbar sein?
