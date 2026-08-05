# Decisions

## Zweck

Diese Datei dokumentiert wichtige Entscheidungen kurz und nachvollziehbar. Eintraege duerfen spaeter ersetzt oder ergaenzt werden, sollen aber nicht stillschweigend verschwinden.

## 2026-06-26: Neues Projekt Statt nanoPLM-Umbau

Entscheidung: Das eigene FreeCAD-PLM wird neu geplant und nicht als direkter Umbau des alten nanoPLM umgesetzt.

Grund:

- Das alte nanoPLM ist wertvoll als Referenz, aber aktuell demoartig und stark Flask-/Windows-/Beispieldaten-gepraegt.
- Ein sauberes Datenmodell fuer Revisionen, Rollen und Audit ist leichter neu aufzubauen.

Status: entschieden.

## 2026-06-26: `planning/` Als Dauerhafte Kontextablage

Entscheidung: Projektstand, Anforderungen, Architektur, Roadmap, Entscheidungen, TODOs und Session-Kontext werden in `planning/` gepflegt.

Grund:

- Der Chatverlauf soll nicht die einzige Wissensquelle sein.
- Neue Sessions koennen schnell wieder einsteigen.
- Groessere Planungs- und Implementierungsschritte bleiben nachvollziehbar.

Status: entschieden.

## 2026-06-26: Django Als Bevorzugter Kandidat

Entscheidung: Django ist aktuell die bevorzugte Technologie fuer v1.

Grund:

- Auth, Rollen, Admin, ORM, Migrationen und Datei-Handling sind Kernfunktionen fuer das PLM.
- Python bleibt nah an FreeCAD.
- Spaeteres Docker Compose ist gut moeglich.

Status: vorlaeufig entschieden; nach der Anforderungsrunde final pruefen.

## 2026-06-26: Filesystem Plus Datenbank

Entscheidung: CAD-Dateien werden im Dateisystem gespeichert, Metadaten und Beziehungen in der Datenbank.

Grund:

- `FCStd`-Dateien sind Binaer-/ZIP-Dateien und koennen gross werden.
- Dateisystem/Volume ist einfacher zu sichern und zu inspizieren.
- Die Datenbank bleibt fuer strukturierte Daten verantwortlich.

Status: vorlaeufig entschieden.

## 2026-06-26: Immutable Revisionen

Entscheidung: Jeder Upload erzeugt eine neue unveraenderliche Revision.

Grund:

- PLM/PDM braucht nachvollziehbare Dateistaende.
- Freigegebene Daten duerfen nicht versehentlich veraendert werden.
- Audit und Rueckverfolgbarkeit werden einfacher.

Status: vorlaeufig entschieden.

## 2026-06-26: Docker Compose Spaeter, Aber Mitdenken

Entscheidung: Docker Compose ist kein v1-Muss, wird aber in Architektur, Pfaden und Settings vorbereitet.

Grund:

- Der Dienst soll spaeter sauber deploybar sein.
- Ein spaeterer Wechsel auf PostgreSQL und Volumes soll nicht zum Umbau werden.

Status: entschieden.

## 2026-06-26: Gleicher Datei-Hash Pro Teil Wird Nicht Erneut Hochgeladen

Entscheidung: Eine `FCStd`-Datei mit identischem SHA-256 darf fuer dasselbe Teil nicht als neue Revision hochgeladen werden.

Grund:

- Eine neue Revision soll einen neuen Dateistand repraesentieren.
- Versehentliche Doppeluploads sollen frueh sichtbar werden.
- Die Revisionshistorie bleibt aussagekraeftiger.

Status: entschieden.

## 2026-06-26: Einfache Rollen Fuer V1

Entscheidung: V1 startet mit drei Django-Gruppen: `admin`, `editor`, `reader`.

Regeln:

- `reader`: ansehen und herunterladen.
- `editor`: ansehen, herunterladen und Revisionen hochladen.
- `admin`: volle PLM-Verwaltung innerhalb der Anwendung.
- Superuser duerfen immer alles.

Grund:

- Das Modell ist einfach genug fuer ein kleines LAN-Team.
- Django-Gruppen bleiben transparent im Admin wartbar.
- Upload-Rechte sind fuer den ersten produktiven Pfad sofort durchsetzbar.

Status: entschieden.

## 2026-06-26: Nur Einfache Freigabe Fuer V1

Entscheidung: V1 bekommt nur eine einfache Freigabe von `draft` nach `released`.

Regeln:

- Nur Superuser und Rolle `admin` duerfen freigeben.
- Beim Freigeben wird `released_at` gesetzt.
- Die Aktion wird im Audit-Trail protokolliert.
- Es gibt vorerst keinen mehrstufigen Review-, Pruef- oder Approval-Prozess.

Grund:

- Der fachliche Nutzen einer klaren Freigabe ist wichtig.
- Mehr Workflow-Tiefe wuerde aktuell zu frueh Komplexitaet erzeugen.
- Der Fokus soll danach wieder auf praktischer Nutzbarkeit liegen.

Status: entschieden.

## 2026-06-26: Teilanlage Nur Mit Initialer FreeCAD-Datei

Entscheidung: Neue Teile oder Baugruppen werden in der Weboberflaeche nur zusammen mit einer initialen `.FCStd`-Datei angelegt.

Regeln:

- Die initiale Datei erzeugt direkt Revision `R0001`.
- Wenn die Teilenummer leer bleibt, nutzt das PLM zuerst die FreeCAD-Property `Id`.
- Wenn keine FreeCAD-`Id` vorhanden ist, vergibt das PLM automatisch `P-001`, `P-002`, ...
- Wenn der Name leer bleibt, nutzt das PLM FreeCAD-`Label`.

Grund:

- Ein PLM-Teil ohne CAD-Dateistand ist fuer den aktuellen V0-Alltag wenig nuetzlich.
- FreeCAD bleibt die Quelle fuer CAD-nahe Dokumentdaten.
- PLM-spezifische Daten wie Revision, Status, Audit und Notizen bleiben in der Datenbank.

Status: entschieden.

## 2026-06-26: Projektstaende Fuer Referenzierte FreeCAD-Dateisets

Entscheidung: Referenzierte FreeCAD-Projekte werden als Projektstaende/Snapshots abgebildet.

Regeln:

- Ein Snapshot enthaelt konkrete Revisionen mehrerer `FCStd`-Dateien.
- Der Snapshot speichert die relativen Pfade aus dem importierten ZIP.
- Beim Download wird der Snapshot wieder als ZIP mit diesen Pfaden ausgegeben.
- Einzelne Dateien aus einem Snapshot koennen als ZIP mit ihren rekursiv referenzierten Dateien heruntergeladen werden.
- Einzelne Dateien behalten ihre eigene Revisionshistorie.
- Aenderungen an einer Datei erzeugen neue Revisionen; ein neuer Projektstand kann dann eine neue Kombination dieser Revisionen festhalten.

Grund:

- FreeCAD-Assemblies referenzieren externe `FCStd`-Dateien.
- Ein einzelner Download einer Baugruppendatei reicht nicht, wenn relative Referenzen erhalten bleiben sollen.
- Snapshots ermoeglichen reproduzierbare Projektstaende ohne die Einzelhistorie der Dateien zu verlieren.

Status: entschieden.

## 2026-06-26: Kanonisches Revisionsformat `R0001`

Entscheidung: Neue Revisionscodes werden zentral im Service als `R0001`, `R0002`, ... mit Prefix `R` und vierstelliger Nummer erzeugt.

Regeln:

- `R0001` ist die erste gueltige Revision.
- Gueltige Codes reichen bis `R9999`.
- Nicht-kanonische Alt-/Testcodes werden bei der Ermittlung der naechsten Nummer ignoriert.
- `next_revision_code(part)` bleibt die zentrale Quelle fuer automatisch erzeugte Revisionscodes.

Grund:

- Das Format ist fuer Nutzer gut lesbar und sortierbar.
- Alte Experimente oder manuelle Testcodes sollen die laufende Nummerierung nicht stoeren.
- Die Formatregel soll an einer Stelle im Code wartbar bleiben.

Status: entschieden.

## 2026-06-26: PLM Fuehrt Revision, FreeCAD Spiegelt `PLMRevision`

Entscheidung: Das PLM bleibt die fuehrende Quelle fuer Revisionscodes. FreeCAD-Dateien spiegeln den Code in der Dokumenteigenschaft `PLMRevision`.

Regeln:

- `Id` bleibt Teil-/Dokumentkennung und wird nicht als Revision verwendet.
- Beim Revisionsupload muss `PLMRevision` zum erwarteten PLM-Code passen.
- Fehlt `PLMRevision` oder weicht sie ab, zeigt die Weboberflaeche den Konflikt.
- Der Nutzer kann den Upload verwerfen oder eine normalisierte Kopie speichern.
- Bei der Normalisierung wird nur `Document.xml` im gespeicherten FCStd-ZIP angepasst.
- Original-Hash, hochgeladener Wert, erwarteter Wert und gespeicherter Hash werden in Metadaten und Audit-Trail abgelegt.

Grund:

- FreeCAD soll im Alltag die PLM-Revision sichtbar mittragen.
- Das PLM darf die Revisionshistorie trotzdem eindeutig und fortlaufend fuehren.
- Konflikte werden nicht stillschweigend akzeptiert, sondern bewusst entschieden.

Status: entschieden.

## 2026-06-27: FreeCADCmd-Artefakte Bleiben Abgeleitet

Entscheidung: STEP-, STL-, 3MF- und PNG-Dateien werden als abgeleitete Artefakte einer bestehenden Revision gespeichert, nicht als neue PLM-Revisionen.

Regeln:

- Die originale `.FCStd`-Revision bleibt unveraendert.
- Exportjobs werden persistiert und koennen per Management-Command verarbeitet werden.
- Reader duerfen vorhandene Artefakte herunterladen.
- Editor, Admin und Superuser duerfen FreeCADCmd-Jobs anlegen.
- VarSet-Parameter werden in der ersten Ausbaustufe nur ausgelesen und angezeigt.
- Parameterbearbeitung und Neurendern mit geaenderten Parametern werden als Folgeausbau geplant.

Grund:

- FreeCADCmd-Laeufe koennen langsam oder lokal nicht verfuegbar sein.
- Artefakte sind nutzbare Ableitungen, aber keine neue CAD-Quelle.
- Ein Jobmodell laesst sich spaeter ohne Datenmodellbruch in einen Worker verschieben.

Status: entschieden.

## 2026-07-02: Browser-3D-Viewer Nutzt Gecachte Preview-Quellen

Entscheidung: Der Web-Viewer zeigt Modell-Dateien in einem schwebenden Dialog. Direkt browserfaehige Dateien wie STL und 3MF werden direkt geladen; FCStd- und STEP-Kontexte nutzen ein serverseitig erzeugtes STL-Preview-Artefakt.

Regeln:

- Three.js wird lokal ausgeliefert, nicht per CDN.
- Der Viewer ist eine Vorschau- und Inspektionsfunktion; Downloads bleiben die fuehrende Dateiuebergabe.
- FCStd wird nicht im Browser geparst.
- STEP wird nicht direkt im Browser geparst.
- Die vorhandene FreeCADCmd-/Preview-Pipeline erzeugt das STL-Preview-Artefakt.
- Das STL-Preview-Artefakt ist ein abgeleitetes Artefakt und keine neue PLM-Revision.

Grund:

- Browserseitiges FCStd-/STEP-Parsing waere deutlich schwerer und weniger robust.
- Das PLM hat bereits einen Headless-FreeCADCmd-Pfad, der aus FCStd ein Vorschau-Mesh erzeugt.
- Gecachte Preview-Dateien vermeiden wiederholte schwere Konvertierungen beim Anzeigen.

Status: entschieden.

## 2026-08-05: STEP und STL dürfen primäre CAD-Revisionen sein

Entscheidung: Wenn für ein Teil kein FreeCAD-Modell existiert, darf eine STEP-, STP- oder STL-Datei die primäre, unveränderliche CAD-Revision bilden. Die bestehende Rolle von STEP/STL als abgeleitete Artefakte einer FCStd-Revision bleibt daneben erhalten.

Regeln:

- Der Dateityp wird pro Revision als `fcstd`, `step` oder `stl` gespeichert.
- FCStd behält die PLMRevision-Normalisierung, XLink-Auswertung und technische Änderungssignatur.
- STEP/STL werden strukturell validiert, aber nicht als FCStd behandelt.
- Primäre STL-Dateien kann der Browser direkt anzeigen; primäre STEP-Dateien erhalten ihre Vorschau über den Worker.
- Nur FCStd-Revisionen können Checkout-Root sein und neue Revisionen durch Check-in erzeugen.
- STEP/STL dürfen als schreibgeschützte Begleitdateien in einem FCStd-Projektstand und Checkout enthalten sein.
- Die Übernahme einer späteren FCStd-Revision in einen bestehenden STEP/STL-Projektstand erfolgt nur nach expliziter Auswahl beim Upload. Dabei wird der alte Stand nicht verändert, sondern ein neuer Stand mit passender FCStd-Dateiendung erzeugt.

Grund:

- Zuliefer- und Bestandsgeometrie liegt häufig nur als neutrales Austauschformat oder Mesh vor.
- Diese Dateien brauchen trotzdem Teilezuordnung, Revision, Projektstand, Download und Vorschau.
- Ein neutraler Import soll nicht künstlich in eine leere FCStd-Hülle verpackt werden müssen.

Status: entschieden.

## 2026-08-05: Addon legt neue FreeCAD-Teile ohne vorherige lokale Datei an

Entscheidung: Die Addon-Aktion `Neues Teil` verlangt keine bereits gespeicherte
Benutzerdatei. Das Addon erzeugt eine leere FCStd-Datei temporär mit FreeCAD und
übergibt sie zusammen mit Name, optionaler Teilenummer und Typ an das PLM.

Regeln:

- Der Server legt Teil und initiale Revision `R0001` in einem gemeinsamen
  Vorgang an.
- Ein lokal geöffneter Projekt-Checkout wird ausdrücklich als Ziel übergeben;
  die neue Datei wird dort als zusätzliche, bearbeitbare FCStd aufgenommen.
- Ohne aktiven Projekt-Checkout erzeugt der Server einen eigenen Checkout für
  das neue Teil.
- Ein serverseitig aktiver Checkout muss im Addon zuerst lokal geöffnet werden,
  bevor `Neues Teil` ihn erweitert.
- Die Aktion benötigt sowohl `write` als auch `checkout`.

Grund:

- Die erste lokale Speicherung war ein unnötiger Medienbruch und ließ den
  eigentlichen PLM-Vorgang unfertig wirken.
- Teil, erste Revision und Checkout sollen als ein verständlicher Arbeitsschritt
  erscheinen.
- Die vom PLM geführte Revision und der Workspace bleiben dadurch von Anfang an
  eindeutig.

Status: entschieden.
