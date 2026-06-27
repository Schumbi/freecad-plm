# Acceptance Criteria

## Zweck

Diese Datei beschreibt, wann V0 und V1 als fachlich akzeptiert gelten. Die Kriterien sind bewusst pruefbar formuliert, damit Implementierung, Tests und manuelle Browserpruefung gegen denselben Zielzustand laufen.

## V0: Fundament

V0 ist erreicht, wenn das lokale Django-PLM den Kernpfad fuer einzelne FreeCAD-Dateien demonstrierbar abbildet.

- Das Projekt laesst sich lokal mit SQLite starten.
- Die Django-Migrationen laufen auf einer leeren lokalen Datenbank durch.
- Die Rollen-Gruppen `admin`, `editor` und `reader` koennen per Management-Command angelegt werden.
- Ein Admin oder Superuser kann ein Projekt in der PLM-Oberflaeche anlegen.
- Ein Editor, Admin oder Superuser kann in einem Projekt ein Teil oder eine Baugruppe nur mit initialer `.FCStd`-Datei anlegen.
- Die initiale Datei erzeugt automatisch Revision `R0001`.
- Wenn die Teilenummer leer bleibt, nutzt das PLM zuerst FreeCAD-`Id`; fehlt diese, wird projektweit `P-001`, `P-002`, ... vergeben.
- Wenn der Name leer bleibt, nutzt das PLM FreeCAD-`Label`.
- Ein Upload wird mindestens als nicht-leere `.FCStd`-ZIP-Datei validiert.
- Pro Revision werden Originaldateiname, Dateigroesse, SHA-256 und extrahierbare FreeCAD-Dokumentmetadaten gespeichert.
- Ein identischer Datei-Hash kann fuer dasselbe Teil nicht erneut als neue Revision hochgeladen werden.
- Angemeldete Nutzer koennen gespeicherte Revisionen herunterladen.
- Wichtige Aktionen erzeugen Audit-Eintraege, mindestens Teilanlage, Revisionsupload, Download und Freigabe.
- `manage.py test plm` laeuft erfolgreich.

## V0 Browser-Abnahme

Diese Punkte muessen mindestens einmal in der laufenden lokalen Oberflaeche geprueft werden, bevor V0 als praktisch abgenommen gilt.

- Projektanlage als Admin oder Superuser.
- Teil-/Baugruppenanlage mit initialer `.FCStd` und leeren Feldern fuer Nummer und Name.
- Blockade eines doppelten Uploads mit identischem SHA-256.
- Download einer gespeicherten Revision.
- Sichtbarkeit der FreeCAD-Metadaten auf der Teildetailseite.
- Bearbeitung und Sichtbarkeit von Revisionsanmerkungen mit Editor/Admin und nur-lesender Zugriff mit Reader.
- Freigabe einer Draft-Revision als Admin oder Superuser.
- Kein Upload und keine Freigabe mit Reader-Rechten.

## V1: Nutzbares LAN-PLM

V1 ist erreicht, wenn ein kleines LAN-Team Projekte, Teile/Baugruppen und referenzierte FreeCAD-Dateisets im Alltag nachvollziehbar verwalten kann.

- Login schuetzt alle PLM-Ansichten und Downloads.
- Rollen `reader`, `editor` und `admin` decken die erwarteten V1-Rechte ab.
- Projekte koennen angelegt, bearbeitet und archiviert werden.
- Teile und Baugruppen koennen je Projekt gelistet und auf Detailseiten geoeffnet werden.
- Jede neue Revision erhaelt zentral den naechsten kanonischen Code `R0001`, `R0002`, ...
- Revisionen haben mindestens die Status `draft`, `released` und `obsolete`.
- Nur Admins und Superuser koennen eine Revision von `draft` nach `released` freigeben.
- Freigegebene Revisionen bleiben unveraenderlich; Aenderungen erfolgen durch neue Revisionen.
- FreeCAD-`PLMRevision` wird gegen den erwarteten PLM-Revisionscode geprueft.
- Bei fehlender oder abweichender `PLMRevision` kann der Nutzer den Upload verwerfen oder eine normalisierte Kopie speichern.
- Die Normalisierung veraendert nur `Document.xml` und speichert Original-Hash, hochgeladenen Wert, erwarteten Wert und gespeicherten Hash als Metadaten.
- FreeCAD-Projekte mit mehreren referenzierten `.FCStd`-Dateien koennen als Projekt-ZIP importiert werden.
- Ein Projektstand speichert konkrete Revisionen mit relativen Pfaden.
- Projektstaende koennen wieder als ZIP mit den gespeicherten relativen Pfaden heruntergeladen werden.
- Einzelne referenzierte Revisionen werden nur mit Snapshot-Kontext als ZIP inklusive rekursiv referenzierter Dateien ausgeliefert.
- FreeCADCmd-Analyse kann exportierbare Objekte und VarSet-Parameter zu einer Revision speichern.
- STEP-, STL- und 3MF-Artefakte koennen zu einer Revision erzeugt und heruntergeladen werden.
- PNG-Ansichten koennen zu einer Revision erzeugt und als Galerie angezeigt werden.
- Zwei Revisionen desselben Teils koennen anhand gleichnamiger PNG-Ansichten verglichen werden.
- Suche nach Projekten, Teilen, Revisionen und Dateinamen ist vorhanden.
- Die lokale Installation ist so dokumentiert, dass sie auf einem frischen Rechner nachvollziehbar ist.

## V1 Browser-Abnahme

- Voller Kurzworkflow aus der Root-`README.md` mit Testnutzern fuer `admin`, `editor` und `reader`.
- PLMRevision-Konfliktfall: fehlende Property verwerfen.
- PLMRevision-Konfliktfall: fehlende oder abweichende Property als normalisierte Kopie speichern.
- Projekt-ZIP importieren und erzeugten Projektstand pruefen.
- Snapshot-Download oeffnen und Pfade mit dem Import-ZIP vergleichen.
- Einzeldatei-Download einer referenzierten Baugruppe pruefen; Ergebnis muss ein ZIP mit rekursiven Referenzen sein.
- FreeCADCmd-Analyse mit echter `.FCStd`-Datei ausfuehren.
- STEP-, STL-, 3MF- und PNG-Artefakte mit echtem FreeCADCmd erzeugen und herunterladen.
- Suche mit mindestens Projektcode, Teilenummer, Revisionscode und Dateiname pruefen.
