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
