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
- Teilenummern koennen manuell vergeben werden oder leer bleiben; bei leerer Nummer vergibt das PLM pro Projekt automatisch `P-001`, `P-002`, ...
- Die FreeCAD-Dokumenteigenschaft `Id` wird beim Upload mit extrahiert und kann spaeter als Quelle fuer eine Teilenummer genutzt werden.
- Neue Teile/Baugruppen werden in der Weboberflaeche nur mit initialer `FCStd`-Datei angelegt.
- Wenn beim Anlegen die Teilenummer leer bleibt, nutzt das PLM zuerst FreeCAD-`Id`; wenn keine `Id` vorhanden ist, wird automatisch `P-001`, `P-002`, ... vergeben.
- Wenn beim Anlegen der Name leer bleibt, nutzt das PLM FreeCAD-`Label`.
- FreeCAD-Projekte mit mehreren referenzierten `FCStd`-Dateien koennen als Projekt-ZIP importiert werden.
- Ein Projektstand/Snapshot speichert, welche konkreten Dateirevisionen mit welchen relativen Pfaden zusammengehoeren.
- Projektstaende koennen wieder als ZIP mit den urspruenglichen relativen Pfaden heruntergeladen werden.
- FreeCAD-Referenzen aus `XLink` werden ausgelesen und pro Revision als Metadaten gespeichert.
- Einzelne Revisionen koennen heruntergeladen werden; wenn eine FCStd-Datei Referenzen enthaelt, wird sie nur als ZIP mit ihren rekursiv referenzierten Dateien aus demselben Projektstand ausgeliefert.
- FreeCAD-Dateien koennen die Dokumenteigenschaft `PLMRevision` enthalten.
- Das PLM bleibt fuehrend fuer Revisionscodes; `PLMRevision` muss mit dem erwarteten PLM-Revisionscode uebereinstimmen.
- Wenn `PLMRevision` beim Revisionsupload fehlt oder abweicht, meldet die Weboberflaeche den Konflikt und bietet Verwerfen oder Speichern einer PLM-normalisierten Kopie an.
- Bei einer PLM-normalisierten Kopie wird nur `Document.xml` angepasst; Original-Hash, urspruenglicher Wert und Normalisierung werden in Metadaten und Audit-Trail festgehalten.
- FreeCADCmd-Jobs koennen pro Revision eine exportierbare Objektliste und vorhandene VarSet-Parameter auslesen.
- STEP-, STL- und 3MF-Dateien koennen als abgeleitete Artefakte zu einer Revision erzeugt, gespeichert und heruntergeladen werden.
- PNG-Ansichten koennen als abgeleitete Artefakte zu einer Revision erzeugt und als Galerie angezeigt werden.
- Zwei Revisionen desselben Teils koennen anhand gleichnamiger PNG-Ansichten nebeneinander verglichen werden.
- Beim Upload einer Revision kann eine Aenderungsnotiz erfasst werden.
- Das FreeCAD-Addon kann lokale Ordner mit einer oder mehreren `.FCStd`-Dateien als Projektstand importieren.
- Das FreeCAD-Addon kann optional ein neues Projekt mit Code, Name, Status, Datum und Beschreibung anlegen und direkt mit dem Import befuellen.
- Nach einem Addon-Import kann ein importiertes Teil oder eine importierte Baugruppe direkt ausgecheckt werden.
- Wenn der direkte Checkout nach dem Import erfolgreich war, kann das Addon den urspruenglichen lokalen Importordner nach `~/FreeCAD-PLM/imported/...` verschieben.
- Das FreeCAD-Addon kann neue PLM-Teile oder Baugruppen ohne initiale CAD-Datei als Metadatensatz anlegen; die CAD-Quelle entsteht danach ueber Checkout/Check-in oder Ordnerimport.

## Nicht Ziel Fuer V1

- Kein Umbau des alten nanoPLM.
- Kein verpflichtender FreeCADCmd- oder FreeCAD-GUI-Betrieb.
- Keine automatische STEP/STL/PDF/DXF-Erzeugung.
- Keine vollstaendige Stuecklistenverwaltung.
- Kein komplexer mehrstufiger Freigabeprozess.
- Keine Bearbeitung von VarSet-Parametern in der ersten FreeCADCmd-Ausbaustufe.

## Offen

- Soll es getrennte Begriffe fuer Teil und Baugruppe geben oder reicht ein gemeinsamer Typ mit Kategorie?
- Welche Pflichtfelder braucht ein Teil mindestens: Nummer, Name, Beschreibung, Material, Lieferant, Tags?
- Wie soll die Teilenummer entstehen: manuell, Nummernkreis, automatisch?
- Wer darf Revisionen freigeben: nur Admins oder auch Editors?
- Wie gross koennen typische `FCStd`-Dateien werden?
- Welche Metadaten aus `FCStd` sind wirklich nuetzlich?
- Soll die Anwendung deutsch-only starten oder von Anfang an internationalisierbar sein?
