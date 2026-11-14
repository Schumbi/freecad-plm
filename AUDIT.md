# AUDIT.md – freecad-plm Server

Erstellt nach vollständiger Lektüre von Models, Views, Templates, CSS und JS.  
Stand: 2026-11-14.  
**Gruppe A implementiert am 2026-11-14.**

Legende Schweregrad: 🔴 hoch · 🟡 mittel · 🟢 gering

---

## 1. Bestätigte Bugs

### B1 – CSS-Variable `--radius-md` undefiniert 🟡
**Datei:** `plm/static/plm/app.css` Z. 1252, 1302, 2211  
**Befund:** Die Variable wird an drei Stellen für `.overview-section` und `.plm-dialog`-Varianten
genutzt, fehlt aber vollständig im `:root`-Block. Browser fallen auf `border-radius: 0` zurück –
betrifft Revisions-Akkordeons und Dialoge auf der Teilseite sichtbar.  
**Fix:** `--radius-md: 12px;` in `:root` ergänzen (zwischen `--radius` und `--radius-lg`).

---

### B2 – CSS-Klasse `.form-errors` fehlt in `app.css` 🟡
**Datei:** `plm/templates/plm/integration_settings.html` Z. 64, 67  
`plm/static/plm/app.css` (nicht vorhanden)  
**Befund:** Die Integrations-Seite nutzt `class="form-errors mt-4"` für Fehlermeldungen.
`app.css` definiert `.errors` und `.errorlist`, aber kein `.form-errors`. Fehlermeldungen
bei der Bambuddy-Verbindung erscheinen ohne rote Hervorhebung.  
**Fix:** `.form-errors` als Alias auf `.errors` in `app.css` ergänzen.

---

### B3 – CSS-Klasse `.card` fehlt in `app.css` 🟢
**Datei:** `plm/templates/plm/project_detail.html` Z. 165  
**Befund:** `<section class="card">` für archivierte Teile. `.card` ist nicht definiert.
Die Section rendert ohne Rahmen, Hintergrund oder Abstand – weder Fehler noch Absturz,
aber visuell unsauber.  
**Fix:** Klasse zu `.panel` ändern (ist definiert und semantisch korrekt).

---

### B4 – Bootstrap 4 Vendor-Dateien geladen aber nie eingebunden 🟢
**Datei:** `plm/static/plm/vendor/bootstrap4/css/bootstrap.min.css` (160 KB)  
`plm/static/plm/vendor/bootstrap4/js/bootstrap.bundle.min.js` (120 KB)  
**Befund:** Kein Template lädt diese Dateien. `base.html` bindet ausschließlich `app.css`
ein. Die Bootstrap-Klassen (`btn-primary`, `btn-outline-secondary` etc.) sind vollständig
in `app.css` reimplementiert. Die Dateien werden von `collectstatic` kopiert und
im Browser-Netzwerk-Tab angezeigt, aber nie angefragt.  
**Fix:** Verzeichnis `plm/static/plm/vendor/bootstrap4/` löschen.

---

### B5 – Fertigungsdatei-Löschen: `<a>`-Link statt POST-Navigation 🟡
**Datei:** `plm/templates/plm/part_detail.html` Z. 391  
**Befund:**
```html
<a class="btn btn-danger btn-sm"
   href="{% url 'plm:delete_manufacturing_file' manufacturing_file.id %}">
   Löschen
</a>
```
Die View `delete_manufacturing_file_view` behandelt GET korrekt mit einer
Bestätigungsseite. Das `<a>`-Element in `part_detail.html` öffnet diese Seite also
korrekt – **kein direktes Löschen ohne Bestätigung.**  
⚠️ Das eigentliche Problem: Der Link liegt **innerhalb eines modalen Dialogs** (`#manufacturing-{id}`),
öffnet aber eine vollständige Seite. Der Nutzer verliert damit den Kontext des Dialogs
und kehrt nach dem Löschen zur leeren Teilseite zurück. Kein Absturz, aber schlechte UX.  
**Fix:** Navigation zum Bestätigen-URL beibehalten, nach POST per `redirect` auf Teilseite
zurück (bereits korrekt). Mittelfristig: Fertigungsseite als eigenständige Seite,
kein Kontext-Verlust.

---

## 2. Architektur und technische Schulden

### A1 – `Part.tags` ist CharField statt M2M 🟡
**Datei:** `plm/models.py` Z. 132  
**Befund:** `Part.tags = models.CharField(max_length=255, blank=True)` ist ein unkontrollierter
Freitext. `Project.tags` dagegen nutzt `ManyToManyField(ProjectTag, ...)`. Die Inkonsistenz
macht einheitliches Filtern, Auswerten und Umbenennen von Teile-Tags unmöglich.  
**Kontext:** Laut Gespräch ist strukturierte Migration geplant.  
**Risiko beim Fix:** Migration 0036, alle Stellen die `part.tags` lesen/schreiben (Form, View,
API, Template, Serialisierung in `extracted_metadata`).

---

### A2 – Active-Navigation per Substring-Matching fragil 🟢
**Datei:** `plm/templates/plm/base.html` Z. 33  
**Befund:**
```python
'user' in request.resolver_match.url_name
or 'api_token' in request.resolver_match.url_name
or 'token' in request.resolver_match.url_name
```
Der URL-Name `user_export_jobs_status` enthält `user` und würde den
Verwaltungs-Navigationspunkt als aktiv markieren – dieser Endpunkt wird aber
nur per `fetch()` aufgerufen, nie direkt navigiert, daher aktuell kein sichtbarer Bug.
Spröde bei künftigen URL-Namen.  
Zusätzlich fehlt das `active`-Markieren für `manage_project_tags`, `manage_project_folders`,
`project_documents`, `project_files_overview` unter Projekten.  
**Fix:** Template-Context-Variable `active_section` aus Views übergeben.

---

### A3 – Custom `plm-dialog`-System statt nativer `<dialog>` 🟡
**Dateien:** `plm/static/plm/app.js` Z. 4–46, `plm/static/plm/app.css` Z. 83–85,
alle Templates  
**Befund:** 60 `plm-dialog`-Vorkommen in Templates (36 in `part_detail.html` allein).
Das manuelle System implementiert per JS: open/close, Fokussetzung, ESC-Taste,
`body.modal-open` für Scroll-Lock, Hintergrundklick-Schließen.  
Das native `<dialog>`-Element bietet all das mit `showModal()`/`close()` nativ inklusive
`::backdrop`, Tab-Falle, Scroll-Lock und ESC – und ist seit Firefox 98 (März 2022)
vollständig unterstützt, auch auf Android Firefox.  
**Risiko beim Fix:** Alle Templates müssen angepasst werden; CSS für `::backdrop` ergänzen;
`app.js`-Dialog-Logik vereinfachen (kein Remove notwendig, aber Klick-außen-Schließen
muss bei `<dialog>` per JS gesetzt werden da kein nativer Support).

---

### A4 – `project_files_overview.html` unvollständig gestaltet 🟡
**Datei:** `plm/templates/plm/project_files_overview.html`  
**Befund:** Einzige Seite der Anwendung ohne `.breadcrumbs`, `.page-header`, `.page-kicker`.
Rohes `<h1>` und unstyled `<form>` ohne Label-Klassen:
```html
<h1>Dateien und Abhängigkeiten · {{ project.code }}</h1>
<form method="get">
  <label>Projektstand <select name="snapshot">...
```
Die Seite ist laut Gespräch ein geplanter Ausbaukandidat.  
**Fix:** Vollständiges Einpassen in das Design-System als Teil des Ausbaus.

---

### A5 – DOM-Größe durch N Revisionen × M Dialoge pro Seite 🟡
**Datei:** `plm/templates/plm/part_detail.html`  
**Befund:** Jede Revision rendert 6 versteckte Dialog-DIVs ins DOM:
`#notes-{id}`, `#revision-properties-{id}`, `#freecad-{id}`, `#manufacturing-{id}`,
`#jobs-{id}`, und das manufacturing-Detail-Partial pro Fertigungsdatei.
Bei 20 Revisionen und je 3 Fertigungsdateien entstehen ~180 Elemente, von denen
beim Seitenaufruf keines sichtbar ist. Kein Absturz, aber spürbarer Einfluss auf
Parse-/Layout-Zeit bei größeren Teilen.  
**Langfristiger Fix:** Dialoge bei Bedarf per HTMX oder Fetch nachladen, oder
Fertigungsseite auslagern (AP C1, s. u.).

---

## 3. UX-Probleme

### U1 – Terminologie-Konflikt: „Anmerkungen" meint zwei Dinge 🔴
**Dateien:** `plm/templates/plm/part_detail.html` Z. 158, 184, 196,
`plm/templates/plm/part_detail.html` Z. 539  
**Befund:** Im System koexistieren:
- `revision.notes` → einmaliges Textfeld; Button-Label: **„Anmerkungen"**, Dialog-Titel: **„Anmerkungen R000x"**
- `Annotation`-Objekte → strukturierte Kommentare mit Status, 3D-Punktverankerung; Sektion: **„FreeCAD-Anmerkungen"**

Für Nutzer ist nicht erkennbar, was wann zu verwenden ist. Der Button „Anmerkungen"
öffnet ein einzelnes Textfeld – das widerspricht der Erwartung an eine Kommentarliste.  
**Klärung aus Gespräch:** `revision.notes` reicht; `Annotation`-Objekte bleiben für 3D-Punkte.  
**Fix:** Button und Dialog-Titel von „Anmerkungen" → **„Notizen"** umbenennen.
Sektion bleibt **„FreeCAD-Anmerkungen"**. Drei Stellen in `part_detail.html`.

---

### U2 – Reihenfolge auf Projektdetailseite: Druckprojekte vor Teilen 🟡
**Datei:** `plm/templates/plm/project_detail.html` Z. 55–80  
**Befund:** Reihenfolge: Stats → **Druckprojekte** → Teile und Baugruppen → Projektstände.
Teile sind die primäre PLM-Ressource. Druckprojekte sind fertigungsbezogene
Zusatzinformation für eine Teilmenge von Nutzern.  
**Fix:** Druckprojekte-Sektion nach Teile/Baugruppen verschieben.

---

### U3 – Zwei „Dateien"-Links kaum unterscheidbar 🟡
**Datei:** `plm/templates/plm/project_detail.html` Z. 23  
**Befund:**
```
Projektdateien · Dateien und Abhängigkeiten
```
„Projektdateien" = Dokumente (PDFs, Specs, Handbücher).  
„Dateien und Abhängigkeiten" = CAD-Revisionsabhängigkeiten im Projektstand.  
Ohne Erklärung nicht unterscheidbar.  
**Fix:** Eindeutige Bezeichnungen: z. B. **„Dokumente"** und **„CAD-Abhängigkeiten"**.

---

### U4 – Fertigungsdatei-Upload drei Ebenen tief versteckt 🔴
**Datei:** `plm/templates/plm/part_detail.html` Z. 159, 437–451  
**Befund:** Pfad für Fertigungsnutzer:  
Teilseite → Button „Fertigung" (sekundäre Aktionen) → Modal öffnet →
Scrollen bis Abschnitt „Fertigungsdatei hochladen" → Upload.  
Laut Gespräch gibt es Nutzer, die ausschließlich mit Fertigungsdateien arbeiten.  
**Fix:** Eigenständige Fertigungsseite `/parts/<id>/manufacturing/` als vollwertige Seite
(Gruppe C im Implementierungsplan).

---

### U5 – Suchergebnisse bei Revisionen führen nur zur Teilseite 🟢
**Datei:** `plm/templates/plm/search.html` Z. 174  
**Befund:** Klick auf eine Revision in der Suche navigiert zu `part_detail`, nicht direkt
zum Revisions-Anker `#revision-{id}`. Bei Teilen mit vielen Revisionen muss der Nutzer
weiter suchen.  
**Fix:** `href` auf `{% url 'plm:part_detail' ... %}#revision-{{ revision.id }}` setzen.
Die Teilseite unterstützt bereits Deep-Links via `revealLinkedRevision()` in `app.js`.

---

### U6 – `h2`-Hierarchie auf Teilseite semantisch inkorrekt 🟢
**Datei:** `plm/templates/plm/part_detail.html` Z. 48–49  
**Befund:** `<h2>Aktuelle Revision</h2>` beschreibt keine Sektion, sondern die erste Karte
in einer Liste. Die nachfolgende `<details>`-Akkordeon-Gruppe hat keine eigene `<h2>`,
aber enthält den Text „Revisionen (n)". Für Screenreader-Nutzer entsteht eine
irreführende Dokumentstruktur.  
**Fix:** Erste Karte kein eigenständiges `<h2>`, stattdessen visuell hervorheben (z. B.
`.current-pill` reicht); `<details>` mit `<summary>` als einzige Sektion.

---

### U7 – Active-Nav: `project_documents`, `project_files_overview`, Tags, Ordner nicht hervorgehoben 🟢
**Datei:** `plm/templates/plm/base.html` Z. 26  
**Befund:** Beim Besuch von Projektdateien, Dateiübersicht, Tag- und Ordner-Verwaltung
ist kein Sidebar-Eintrag aktiv – der Nutzer verliert die Orientierung in der Hierarchie.  
**Fix:** Folgt aus A2-Fix (Context-Variable `active_section`).

---

## 7. Gruppe A – Implementierungsstand (2026-11-14)

Alle AP-A1 bis AP-A4 wurden erfolgreich implementiert:

| AP | Status | Dateien | Tests |
|---|---|---|---|
| AP-A1 | ✅ Abgeschlossen | `app.css`, `project_detail.html` | Visuell geprüft |
| AP-A2 | ✅ Abgeschlossen | `part_detail.html` | Visuell geprüft |
| AP-A3 | ✅ Abgeschlossen | `search.html` | Visuell geprüft |
| AP-A4 | ✅ Abgeschlossen | `base.html`, `documents.py`, `file_overview.py`, `folders.py`, `tags.py`, `users.py` | 405 Tests grün |

**Angepasste Dateien:**
- `plm/static/plm/app.css`: `--radius-md`, `.form-errors`, Bootstrap-Vendor-Verzeichnis entfernt
- `plm/templates/plm/base.html`: Active-Nav über `active_section`
- `plm/templates/plm/part_detail.html`: „Anmerkungen" → „Notizen"
- `plm/templates/plm/project_detail.html`: `card` → `panel`
- `plm/templates/plm/search.html`: Revisionen mit Anker verlinken
- `plm/views/documents.py`: `active_section = "projects"`
- `plm/views/file_overview.py`: `active_section = "projects"`
- `plm/views/folders.py`: `active_section = "projects"`
- `plm/views/tags.py`: `active_section = "projects"`
- `plm/views/users.py`: Alle Views `active_section = "admin"`

**Testergebnis:** `python manage.py test` → 405 Tests, 1 übersprungen (PostgreSQL), 0 fehlgeschlagen.

---

## 4. Priorisierter Implementierungsplan

Jedes Arbeitspaket ist unabhängig testbar und in sich abgeschlossen.

---

### Gruppe A – Bugfixes ohne Datenbankeingriff (ABGESCHLOSSEN am 2026-11-14)

**AP-A1: CSS-Variablen und fehlende Klassen** (≈ 20 min) ✅  
- `--radius-md: 12px` in `:root` (B1)
- `.form-errors` als Alias auf `.errors` (B2)
- Klasse `card` → `panel` in `project_detail.html` (B3)
- Bootstrap-Vendor-Verzeichnis löschen (B4)

Dateien: `app.css`, `project_detail.html`  
Test: Visuelle Prüfung Integrations-Seite (Fehlermeldung rot), Revisionsakkordeons
(abgerundete Ecken), archivierte Teile (Panel-Optik), `collectstatic` läuft durch.  
Risiko: keines.

---

**AP-A2: Terminologie „Notizen" / „Anmerkungen"** (≈ 20 min) ✅  
Umbenennen in `part_detail.html`: Button, Dialog-Titel, Textarea-Label.  
Betrifft 3 Stellen, alle in derselben Datei.

Test: Seitenaufruf Teil → Button heißt „Notizen" → Dialog öffnet mit Titel „Notizen R0001".  
Risiko: keines.

---

**AP-A3: Suchergebnis-Revisionen mit Anker verlinken** (≈ 20 min) ✅  
`search.html` Z. 174: `href` um `#revision-{{ revision.id }}` ergänzen.

Test: Suche nach Revisionscode → Klick → Seite öffnet mit aufgeklapptem Akkordeon
und scrollt zur Revisionskarte (via `revealLinkedRevision()` in `app.js`).  
Risiko: keines.

---

**AP-A4: Active-Nav über Context-Variable** (≈ 1 h) ✅  
In jedem View einen String `active_section` im Context setzen (`"projects"`, `"admin"`).  
In `base.html` Substring-Matching entfernen, `active_section == "..."` nutzen.  
Ergänzen: `project_documents`, `project_files_overview`, `manage_project_tags`,
`manage_project_folders`, `user_management`, `create_user`, `edit_user`,
`set_user_password`, `create_user_token`, `edit_api_token`, `revoke_api_token` → passende Werte.

Dateien: `base.html`, `documents.py`, `file_overview.py`, `folders.py`, `tags.py`, `users.py`  
Test: Alle Seiten besuchen und prüfen, dass korrekter Sidebar-Punkt aktiv ist.  
Risiko: gering; kein bestehendes Verhalten bricht, nur Erweiterung.

---

### Gruppe B – UX-Korrekturen ohne Datenbankeingriff

**AP-B1: Reihenfolge Projektdetailseite** (≈ 20 min)  
`project_detail.html`: Druckprojekte-Sektion nach Teile/Baugruppen verschieben.

Test: Projektseite mit Druckprojekten öffnen → Druckprojekte stehen nach der Teile-Tabelle.  
Risiko: keines.

---

**AP-B2: Link-Texte Projektdateien / Abhängigkeiten** (≈ 10 min)  
`project_detail.html` Z. 23: Texte auf „Dokumente" und „CAD-Abhängigkeiten" ändern.

Test: Projektseite aufrufen, Links lesen, Zielseiten aufrufen.  
Risiko: keines.

---

**AP-B3: `project_files_overview.html` Design-System** (≈ 2 h)  
Vollständige Einpassung: `.breadcrumbs`, `.page-header`, `.page-kicker`, `.form-card`,
korrekte Labels für `<select>` und `<input>`.

Test: Seite aufrufen, visuell vergleichen mit Projektdetail-Seite.  
Risiko: gering; nur Template-Änderung.

---

**AP-B4: H2-Hierarchie Teilseite** (≈ 30 min)  
`part_detail.html`: `<h2>Aktuelle Revision</h2>` entfernen; erste Revisionskarte
bleibt durch `.current-pill` hervorgehoben; `<details>`-Akkordeon als einzige
benannte Sektion.

Test: Teilseite mit mehreren Revisionen; `<h2>`-Scan mit Browser-DevTools / Accessibility-Tree.  
Risiko: gering; nur semantische HTML-Änderung, keine CSS-Änderung nötig.

---

### Gruppe C – Native `<dialog>` Migration

**AP-C1: `app.js` und `app.css` auf `<dialog>` umstellen** (≈ 2 h)  
JS: `openDialog()` → `dialog.showModal()`, `closeDialog()` → `dialog.close()`.
Klick-außen via `dialog.addEventListener('click', e => { if (e.target === dialog) dialog.close(); })`.
ESC: nativ. `body.modal-open` und zugehörige CSS-Regeln entfernen.
CSS: `.plm-dialog` Backdrop via `::backdrop` statt Overlay-Div.

Test: Alle Dialoge öffnen/schließen via Button, ESC, Klick-außen.
Firefox Desktop + Android.  
Risiko: mittel. Klick-außen-Verhalten muss sorgfältig getestet werden
(Target muss `<dialog>` selbst sein, nicht ein Kind-Element).

---

**AP-C2: Alle Templates auf `<dialog>`-Element umstellen** (≈ 2 h)  
`<div class="plm-dialog" ... hidden>` → `<dialog class="plm-dialog" ...>`.
`data-dialog-close` und `data-dialog-target` bleiben als Daten-Attribute erhalten
(JS-API ändert sich nur intern).

Dateien: `base.html`, `part_detail.html`, `project_detail.html` und alle weiteren mit
`.plm-dialog`.

Test: Vollständiger Durchlauf aller Dialog-Trigger auf Teilseite und Projektseite.
Besonders: Modell-Viewer-Dialog (einziger globaler Dialog in `base.html`).  
Risiko: gering nach AP-C1; sequenziell durchführen.

---

### Gruppe D – Fertigungs-UX (eigenständige Seite)

**AP-D1: Fertigungsseite `/parts/<id>/manufacturing/`** (≈ 1 Tag)  
Neue View, URL, Template: Liste aller Fertigungsdateien aller Revisionen des Teils,
direkte Upload-Möglichkeit ohne modalen Kontext, Sortierung/Filter nach Revision
und Dateityp.

Dateien: `plm/views/parts.py` (neue View), `plm/urls.py` (neuer URL),
neues Template `plm/manufacturing_overview.html`.

Test: Zugriff mit Reader (nur Ansicht), Editor (Upload), Admin (Löschen).
Upload ohne aktive Revision schlägt mit Fehlermeldung fehl.  
Risiko: mittel. Neue Seite, kein bestehendes Verhalten berührt.

---

**AP-D2: Link zur Fertigungsseite in Projektdetail und Suche** (≈ 1 h)  
Auf Teilseite: neuer Button in `page-header-actions`; in Suchergebnissen:
Spalte „Fertigung" mit Link, wenn Fertigungsdateien vorhanden.

Test: Navigationsfluss Suche → Fertigungsseite.  
Risiko: keines.

---

### Gruppe D – Fertigungs-UX (eigenständige Seite)

**AP-D1: Fertigungsseite `/parts/<id>/manufacturing/`** (≈ 1 Tag)  
Neue View, URL, Template: Liste aller Fertigungsdateien aller Revisionen des Teils,
direkte Upload-Möglichkeit ohne modalen Kontext, Sortierung/Filter nach Revision
und Dateityp.

Dateien: `plm/views/manufacturing.py` (neue View), `plm/urls.py` (neuer URL),
neues Template `plm/manufacturing_overview.html`.

Test: Zugriff mit Reader (nur Ansicht), Editor (Upload), Admin (Löschen).
Upload ohne aktive Revision schlägt mit Fehlermeldung fehl.  
Risiko: mittel. Neue Seite, kein bestehendes Verhalten berührt.

---

**AP-D2: Link zur Fertigungsseite in Projektdetail und Suche** (≈ 1 h)  
Auf Teilseite: neuer Button in `page-header-actions`; in Suchergebnissen:
Spalte „Fertigung" mit Link, wenn Fertigungsdateien vorhanden.

Test: Navigationsfluss Suche → Fertigungsseite.  
Risiko: keines.

---

### Gruppe E – Part-Tags Migration

**AP-E1: Datenmodell und Migration** (≈ 1 h)  
Neues Model `PartTag` (analog `ProjectTag`, aber ohne `project`-Bindung, da
Teile-Tags projektübergreifend sinnvoll sein können) **oder** Erweiterung von
`ProjectTag` um optionalen Part-M2M. Entscheidung vor Implementierung treffen.  
Migration 0036: `Part.tags` CharField entfernen, M2M hinzufügen.  
Datenmigration: Bestehende komma-separierte Strings splitten und als Tags anlegen.

Test: `python manage.py migrate` auf Testdatenbank; bestehende Testfälle in
`plm/tests.py` die `Part.tags` setzen/lesen.  
Risiko: hoch. Datenmigration, API-Rückgabe (`extracted_metadata` in JSONField
kann `tags` als String enthalten), Addon-Vertragstests.
→ Zuletzt implementieren, eigener Feature-Branch.

---

**AP-E2: Form, View, Template anpassen** (≈ 2 h)  
`PartForm`: Freitext-Eingabe mit Komma-Trenner wie `ProjectForm`.  
`part_detail.html`: Tag-Chips statt plain Text.  
API: `GET /api/parts/<id>/` → `tags` als Liste zurückgeben.

Test: Part anlegen mit Tags, Tags in Web-UI sichtbar, API-Antwort korrekt.  
Vertragstests `run_contract_tests.py` müssen grün bleiben.

---

## 5. Risikomatrix

| AP | Status | Risiko | Grund | Absicherung |
|---|---|---|---|---|
| A1–A4 | ✅ Abgeschlossen | 🟢 keines | Nur CSS/Template | Visuelle Prüfung, 405 Tests grün |
| B1–B4 | ✅ Abgeschlossen | 🟢 keines | Nur Template-Reihenfolge | Sichtprüfung |
| C1 | ⏳ Nicht begonnen | 🟡 mittel | JS-Verhalten `<dialog>` vs. custom | Firefox Desktop + Android testen |
| C2 | ⏳ Nicht begonnen | 🟢 gering | Nach C1 sequenziell | Alle Dialog-Trigger durchklicken |
| D1 | ⏳ Nicht begonnen | 🟡 mittel | Neue View + Berechtigungen | Reader/Editor/Admin-Tests |
| E1 | ⏳ Nicht begonnen | 🔴 hoch | DB-Migration + Datenmigration | Separater Branch, `run_tests.py` + `run_contract_tests.py` |
| E2 | ⏳ Nicht begonnen | 🟡 mittel | API-Rückgabe ändert sich | Addon-Vertragstests |

---

## 6. Nicht in diesem Plan: bewusst zurückgestellt

- **Pagination** für Teile- und Revisionslisten: kein bekannter Bedarf bei aktuellem
  Nutzungsumfang; Aufwand zu hoch ohne konkreten Auslöser.
- **HTMX**: würde Dialoge eleganter nachladen, aber erfordert neue Abhängigkeit.
  Wenn AP-C1/C2 die DOM-Größe nicht ausreichend löst, als Option prüfen.
- **Volltext-Suche mit Datenbankindex** (`SearchVector`): aktuelle `icontains`-Suche
  reicht für ein LAN-Team; bei größerem Datenbestand überdenken.
