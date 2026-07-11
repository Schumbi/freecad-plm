# Review: Softwarequalitaet, Wartbarkeit, Nachvollziehbarkeit und Sicherheit

---

## UPDATE 2026-07-11 — Nachkontrolle

Seit dem urspruenglichen Review (2026-07-09) wurde deutlich nachgebessert. Verifiziert per Git-Historie und Code-Review.
**Neuer Teststand:** `manage.py test plm` = **184 Tests, alle OK** (vorher 150). `manage.py check` = 0 Issues.

### Erledigt seit dem Review

| # | Finding | Status | Nachweis |
|---|---------|--------|----------|
| 0 | `.dockerignore` schliesst `.env` aus | **Erledigt** | `.dockerignore` enthaelt `.env`, `.env.*`, `!.env.example`, zusaetzlich `.git/` |
| 4.1 | Upload-/ZIP-Budgets (DoS/Zip-Bomb) | **Erledigt** | `PLM_MAX_*` in `settings.py`; Enforcement in `fcstd.py`/`services.py`; Tests (`PLM_MAX_FCSTD_UPLOAD_BYTES`, `PLM_MAX_ZIP_MEMBERS`, `PLM_MAX_PROJECT_ZIP_BYTES`) |
| 4.2 | Worker-Container haerten | **Erledigt** | `docker-compose.image.yml`: `cap_drop: [ALL]`, `no-new-privileges`, `read_only`, `tmpfs`, `mem_limit`, `cpus`, `pids_limit`, `init` |
| 4.3 | Snapshot-Projektpruefung im Checkout-API | **Erledigt** | `revision_checkout_api` filtert jetzt `ProjectSnapshot` mit `project=revision.part.project` (Commit `4c5e03c`) |
| 4.4 | XML-Haertung | **Erledigt** | `defusedxml` in `fcstd.py`, `fcstd_signature.py`, `services.py`; `requirements.txt` erweitert |
| 4.6 | Login haengt am Django-Admin | **Erledigt** | Eigene `LoginView` unter `/login/` + `logout_view`; `LOGIN_URL='plm:login'`, `LOGIN_REDIRECT_URL='plm:project_list'`, `LOGOUT_REDIRECT_URL='plm:login'` |
| 3.2 | Zu wenig Observability bei Jobs | **Teilweise** | Haengengebliebene Exportjobs werden automatisch als fehlgeschlagen markiert (`EXPORT_JOB_STALE_SECONDS`, Commit `cc4d044`); Live-Jobstatus in der Sidebar |
| A7 | CI fuehrt Tests aus | **Erledigt** | `.forgejo/workflows/build-image.yml`: Schritt `Run tests` fuehrt `manage.py test --parallel` im gebauten Image aus; Push nur bei gruenen Tests. Testlauf beschleunigt (MD5-Hasher im Testmodus + `--parallel`): ~266s → ~5s |
| A1 | Web-Image ohne FreeCAD | **Erledigt** | Getrennte Images: Web (`INSTALL_FREECAD=0`) und Worker (`INSTALL_FREECAD=1`). CI baut/pusht beide; Compose nutzt `PLM_WEB_IMAGE`/`PLM_WORKER_IMAGE`. Zusaetzlich `build-essential` entfernt (Wheels genuegen). Web-Image: ~2 GB → **279 MB**, verifiziert; 184 Tests laufen im Web-Image gruen. |

Zusaetzlich neu (Funktion/UX, nicht sicherheitskritisch): globale PLM-Suche, Obsolet-Markierung fuer Revisionen, automatische Analyse-/PNG-Jobs nach API-Check-in, Live-Vergleichsansicht, modernisiertes Web-UI. Der urspruenglich von mir gesetzte Klein-Fix (`.dockerignore`) ist eingecheckt.

### Noch offen

| # | Finding | Schwere | Bemerkung |
|---|---------|---------|-----------|
| 4.5 | Kein Rate-Limiting / Login-Lockout | Mittel | Weder `django-axes` noch `django-ratelimit`; relevant v.a. hinter Reverse Proxy. Alternativ nginx `limit_req`. |
| 3.1 | Audit-Events ohne Request-Kontext | Mittel | `AuditEvent` hat weiterhin keine `ip_address`/`user_agent`/`api_token_id`. `request.api_token` ist verfuegbar und leicht ergaenzbar. |
| 4.7 | Media-Guard fehlt | Niedrig | `freecad_plm/urls.py` haengt `static(MEDIA_URL, ...)` unbedingt an. Bei versehentlichem `DJANGO_DEBUG=1` auf erreichbarer Instanz waeren CAD-Dateien unter `/media/` ohne Auth erreichbar. Empfehlung: nur unter `if settings.DEBUG` anhaengen. |
| 2.1 | Uebergrosse Module | Mittel | **Eher verschlechtert:** `views.py` 1600→**1790**, `services.py` 1475→**1659** Zeilen. Package-Split weiterhin empfohlen. |
| 2.2/2.3/2.5 | Boilerplate-/Pfad-/Serialisierungs-Duplizierung | Mittel | Unveraendert. |
| 2.7 | Dev-Tooling/Linting | Mittel | Kein `ruff`/`black`/`mypy`, keine `requirements-dev.txt`. |

### Aktualisierte Kurzbewertung

Die als **Hoch** eingestuften Sicherheitsrisiken (Upload-Budgets, Worker-Haertung) sind erledigt, ebenso die konkrete Code-Inkonsistenz bei der Snapshot-Zuordnung und die XML-Haertung. Der Sicherheitsstand ist damit fuer einen LAN-/Reverse-Proxy-Betrieb **deutlich verbessert** und aus meiner Sicht produktionstauglich, sofern der Betrieb (HTTPS, `.env`-Secrets, `/admin/`-Abschottung) sauber ist.

Die verbleibenden Punkte sind ueberwiegend **Wartbarkeit und Betriebsreife**: die zwei Kernmodule wachsen weiter (Refactoring lohnt zunehmend). CI fuehrt die 184 Tests inzwischen aktiv aus (A7 erledigt) und das Web-Image ist von ~2 GB auf ~279 MB geschrumpft (A1 erledigt). Noch offen sind die guenstigen Haertungen (Media-Guard, Rate-Limiting, Audit-Request-Kontext). Priorisierte Sofortmaßnahme jetzt: **Media-Guard (4.7)** — klein und risikoarm.

Der Rest dieses Dokuments ist der urspruengliche Review-Stand vom 2026-07-09 und bleibt zur Nachvollziehbarkeit erhalten.

---

**Datum:** 2026-07-09
**Scope:** `freecad-plm` (Server), `freecad-plm-addon` (Client), Betriebskontext `freecad-plm-testing`.
**Betriebsmodell:** interner LAN-Dienst bzw. hinter Reverse Proxy.
**Grundlage:** `planning/SECURITY_AUDIT_BRIEFING.md` und Code-Review.
**Teststand:** `manage.py test plm` = 150 Tests, alle OK. `manage.py check` = 0 Issues.

> Hinweis: Es wurden inzwischen zwei kleine Sofortpunkte umgesetzt (siehe Abschnitt 0). Alles andere sind Vorschlaege.

---

## 0. Bereits umgesetzter Klein-Fix

**`.dockerignore` schliesst jetzt `.env`-Dateien aus.**

Vorher listete `.dockerignore` weder `.env` noch `.env.*`. Beim `docker build` wird der gesamte Build-Kontext (`COPY . /app/`) ins Image kopiert. Lag eine lokale `.env` mit `DJANGO_SECRET_KEY` / `POSTGRES_PASSWORD` neben dem Dockerfile, landete sie im Image-Layer. Ergaenzt wurde:

```text
.env
.env.*
!.env.example
```

Verifikation: `manage.py check` weiterhin fehlerfrei. Kein Verhalten der App betroffen.

Update 2026-07-09: Der erste Sofortpunkt der Roadmap ist inzwischen umgesetzt:
Upload-/ZIP-Budgets sind als Settings und Validierung in `plm/` vorhanden und
mit Tests abgesichert.

Update 2026-07-09: Der zweite Sofortpunkt der Roadmap ist ebenfalls umgesetzt:
der Compose-Worker laeuft jetzt mit `cap_drop: ALL`, `no-new-privileges`,
read-only Root-FS, `tmpfs` fuer `/tmp` und `/var/tmp` sowie einfachen
CPU-/RAM-/PID-Limits.

---

## 1. Executive Summary

Das Projekt ist fuer ein V1-LAN-PLM erstaunlich reif: klares immutable Revisionsmodell, durchgaengiger Audit-Trail, saubere Token-Auth, ordentliche Testabdeckung (150 Tests) und bewusste Designentscheidungen, die in `planning/` dokumentiert sind. Die groessten Baustellen sind **nicht** akute Loecher, sondern strukturelle Themen:

- **Wartbarkeit:** `views.py` (~1600 Zeilen) und `services.py` (~1475 Zeilen) sind zu gross; Permission-/Audit-/Serialisierungs-Boilerplate wiederholt sich dutzendfach.
- **Sicherheit (Betrieb):** Upload-/ZIP-Budgets und Worker-Haertung sind inzwischen umgesetzt; offen bleibt u.a. FreeCAD im Web-Image.
- **Sicherheit (Code):** Snapshot-Zuordnungspruefung und XML-Haertung sind inzwischen umgesetzt; offen bleibt u.a. Rate-Limiting/Login-Lockout.
- **Nachvollziehbarkeit:** Audit-Trail gut, aber ohne Request-Kontext (IP, User-Agent) und mit wenig aktivem Logging.

Priorisierte Sofortmaßnahmen: Upload-Budgets, Worker-Haertung, Snapshot-Projektpruefung und `defusedxml` sind umgesetzt; naechster Sofortpunkt ist der CI-Test-Job.

---

## 2. Softwarequalitaet und Wartbarkeit

### 2.1 Übergroße Module (Hoch)

- `plm/views.py` ~1600 Zeilen, `plm/services.py` ~1475 Zeilen, `plm/api.py` ~690 Zeilen.
- `services.py` mischt Revisionen, Checkout/Check-in, Snapshots, Manufacturing-3MF-Parsing, Projektloeschung und Manifest-Erzeugung in einer Datei.

**Vorschlag:** In ein Package aufteilen, z.B.:

```text
plm/services/__init__.py
plm/services/revisions.py
plm/services/checkout.py
plm/services/snapshots.py
plm/services/manufacturing.py
plm/views/  (analog: projects.py, parts.py, revisions.py, admin.py, viewer.py)
plm/api/    (projects.py, parts.py, checkout.py, annotations.py)
```

Reine Umschichtung ohne Verhaltensaenderung, testgestuetzt schrittweise moeglich.

### 2.2 Wiederholte Permission-Boilerplate (Mittel)

In `views.py` erscheint dutzendfach:

```python
if not can_upload_revision(request.user):
    return HttpResponseForbidden("...")
if request.method != "POST":
    return redirect(...)
```

In `api.py` analog:

```python
if not user_can_mutate_models(request.user):
    return JsonResponse({"error": "..."}, status=403)
```

**Vorschlag:** Kleine Decorators einfuehren, z.B. `@require_plm_permission(can_upload_revision)` und `@require_plm_admin`. Reduziert Copy-Paste-Fehlerrisiko und vereinheitlicht Fehlermeldungen. Die Kopplung „API-Scope **und** Django-Rolle“ laesst sich damit an einer Stelle konsistent erzwingen.

### 2.3 Dreifach duplizierte Pfad-Sicherung (Mittel)

Dieselbe „kein `..`, nicht absolut"-Logik existiert dreimal, leicht unterschiedlich:

- `plm/services.py` → `safe_snapshot_path()`
- `plm/freecadcmd.py` → `safe_relative_fcstd_path()`
- `freecad-plm-addon/workspace.py` → `safe_join()` / `safe_zip_path()`

**Vorschlag:** Server-seitig in ein `plm/paths.py` zusammenführen. Divergenz zwischen den Kopien ist ein latentes Sicherheitsrisiko (eine wird gehaertet, die andere vergessen).

### 2.4 Duplizierte Signatur-Konstanten (Niedrig)

`IGNORED_DOCUMENT_PROPERTIES`, `CHECKOUT_FILE_REFERENCE_RE`, `FLOAT_RE` stehen sowohl in `plm/fcstd_signature.py` als auch in `freecad-plm-addon/workspace.py`. Server und Addon müssen synchron bleiben (Rules-Version). **Vorschlag:** Als bewusst dokumentierten „geteilten Vertrag" markieren und Rules-Version in beiden Repos in einem Test gegeneinander prüfen.

### 2.5 Duplizierte Serialisierung (Mittel)

`api.py` baut Payloads manuell (`project_payload`, `part_payload`, `revision_payload`, `manifest_file_payload`, …). Bei Modelländerungen müssen mehrere Stellen mitgezogen werden.

**Vorschlag:** Entweder zentralisieren (ein Serializer-Modul) oder mittelfristig **Django REST Framework** einführen. DRF würde Auth, Permissions, Serialisierung, Validierung und Fehlerantworten vereinheitlichen und einen Großteil des `@csrf_exempt`/`json_body`/`JsonResponse`-Boilerplates ersetzen. Für ein wachsendes API ein klarer Wartbarkeitsgewinn.

### 2.6 Fehlende Typannotationen und Docstrings (Niedrig)

Kaum Type-Hints, wenige Docstrings. Für ein Projekt dieser Größe erschwert das Onboarding.

**Vorschlag:** Schrittweise Type-Hints in `services.py`/`api.py`, dazu `ruff` + `mypy` (siehe 2.7).

### 2.7 Fehlendes Tooling für Qualitätssicherung (Mittel)

- `requirements.txt` enthält nur Laufzeit-Abhängigkeiten; keine `requirements-dev.txt`.
- Kein Linter/Formatter (`ruff`, `black`), kein `pre-commit`.
- Der Forgejo-Workflow baut nur das Image; er führt **keine Tests** aus.

**Vorschlag:**
1. `requirements-dev.txt` mit `ruff`, `black`, `mypy`, `coverage`.
2. `pyproject.toml` mit Ruff/Black-Konfiguration.
3. Forgejo-Workflow um einen Test-Job erweitern (`manage.py test plm` + `check --deploy`), der bei jedem Push läuft. Das ist der größte Hebel für dauerhafte Qualität und verhindert Regressionen der 150 bestehenden Tests.

### 2.8 Konsistenz kleinerer Dinge (Niedrig)

- `settings.py` hat `FREECADCMD_COMMAND` **und** `FREECADCMD_PATH` (redundant).
- Einrückungsunsauberkeit in `services.py` `extract_slicer_fields` (Zeilen 299–305, verschobene Einrückung der `first_config_value`-Argumente — funktional korrekt, aber irritierend).
- `freecadcmd.py` liest Artefakt-Inhalte komplett in den Speicher (`path.read_bytes()`), was bei großen STEP/STL-Exporten Speicher kostet.

---

## 3. Nachvollziehbarkeit / Observability

### 3.1 Audit-Trail ohne Request-Kontext (Mittel)

`AuditEvent` protokolliert Actor, Action, `object_repr` und JSON-Metadata — gut. Es fehlen aber **IP-Adresse, User-Agent und Token-ID**. Bei einem LAN-Dienst mit mehreren Nutzern und API-Tokens erhöht das die forensische Nachvollziehbarkeit erheblich (welcher Token, von wo).

**Vorschlag:** `AuditEvent` um `ip_address`, `user_agent` (optional) und bei API-Zugriffen `api_token_id` ergänzen. Da `request.api_token` bereits gesetzt wird (`plm/auth.py`), ist die Token-ID leicht verfügbar.

### 3.2 Wenig aktives Logging (Niedrig)

Logging ist in `settings.py` sauber konfigurierbar (`PLM_LOG_LEVEL` etc.), aber im Code gibt es kaum `logger.info/warning`-Aufrufe. Fehlerpfade (fehlgeschlagene Uploads, FreeCADCmd-Fehler, 403/409) werden nicht geloggt.

**Vorschlag:** In Schlüsselstellen (Upload-Fehler, Checkout-Konflikte, FreeCADCmd-Fehlschläge, Admin-Aktionen) `logging` ergänzen. `ExportJob.log` speichert bereits das FreeCADCmd-Log — das ist vorbildlich.

### 3.3 Audit-Retention / Auswertung (Niedrig)

Kein Konzept für Aufbewahrung/Rotation von `AuditEvent`. Für LAN unkritisch, aber langfristig wächst die Tabelle unbegrenzt. **Vorschlag:** Später Management-Command zum Archivieren/Exportieren.

---

## 4. Sicherheit

### 4.1 Keine Upload-/ZIP-Budgets — DoS/Zip-Bomb (Hoch)

Unverändert offen aus dem Audit 2026-07-06.

- `read_uploaded_file()` liest **komplette** Uploads in den Speicher (`BytesIO`).
- `iter_fcstd_zip_members()` liest jedes `.FCStd`-Member vollständig; `fcstd_with_plm_revision()` liest alle Member; `inspect_manufacturing_upload()` liest 3MF-Container komplett.
- Weder in `settings.py` noch in der Validierung existieren `DATA_UPLOAD_MAX_MEMORY_SIZE`-Anpassung oder App-Limits.

**Risiko:** Ein `editor`/Token mit `write` kann per verschachteltem ZIP oder sehr großer Datei den Web-/Worker-Prozess in Speicher/CPU-Erschöpfung treiben.

**Vorschlag (schnell umsetzbar, aber verhaltensändernd — daher hier nur empfohlen):**
1. In `settings.py`:
   ```python
   PLM_MAX_FCSTD_UPLOAD_BYTES = env_int('PLM_MAX_FCSTD_UPLOAD_BYTES', 200 * 1024 * 1024)
   PLM_MAX_PROJECT_ZIP_BYTES = env_int('PLM_MAX_PROJECT_ZIP_BYTES', 500 * 1024 * 1024)
   PLM_MAX_ZIP_MEMBERS = env_int('PLM_MAX_ZIP_MEMBERS', 2000)
   PLM_MAX_ZIP_UNCOMPRESSED_BYTES = env_int('PLM_MAX_ZIP_UNCOMPRESSED_BYTES', 2 * 1024**3)
   ```
2. Vor `archive.read()` die `ZipInfo.file_size`-Summe und Member-Anzahl prüfen, sonst `ValidationError`.
3. Reverse-Proxy: `client_max_body_size` ist im README-Beispiel gesetzt (512m) — gut, aber die App darf sich nicht darauf verlassen.

### 4.2 Worker/FreeCADCmd nicht gehärtet (Hoch)

- `docker-compose.image.yml`: `worker` ohne `security_opt`, `cap_drop`, `read_only`, Memory-/CPU-Limits.
- Web und Worker teilen dasselbe `./storage`-Volume (read-write).
- `Dockerfile` installiert FreeCAD auch im Web-Image (`INSTALL_FREECAD=1`).

**Risiko:** FreeCAD parst nicht vertrauenswürdige CAD-Dateien. Ein Absturz/Exploit im Importer läuft im Container mit Vollzugriff auf alle gespeicherten CAD-Daten.

**Vorschlag:**
- Worker-Service härten:
  ```yaml
  worker:
    cap_drop: ["ALL"]
    security_opt: ["no-new-privileges:true"]
    mem_limit: 2g
    cpus: "2.0"
    tmpfs:
      - /tmp
  ```
- Web-Image ohne FreeCAD bauen (`INSTALL_FREECAD=0`), da der Worker die Verarbeitung übernimmt (`PROCESS_EXPORT_JOBS_INLINE=0` ist im Compose bereits gesetzt). Verkleinert Angriffsfläche und Image.
- Optional: Storage für den Worker read-only mounten und nur ein Output-Verzeichnis beschreibbar halten (erfordert Anpassung des Job-Flows).

### 4.3 Snapshot-Zuordnung ohne Projektprüfung — Konsistenz/IDOR (Mittel)

In `revision_checkout_api` (`plm/api.py`, ~Zeile 475):

```python
if data.get("snapshot_id"):
    snapshot = get_object_or_404(ProjectSnapshot, id=data["snapshot_id"])
```

Hier wird — anders als in `revision_manifest_api`, das korrekt `project=revision.part.project` filtert — **nicht** geprüft, ob der Snapshot zum Projekt der Revision gehört. Ein authentifizierter Nutzer mit `checkout`-Scope kann eine fremde `snapshot_id` angeben.

**Impact:** In der Praxis meist unkritisch, weil `manifest_entries_for_revision()` bei nicht passendem Snapshot entweder leer/single-file zurückgibt oder mit 409 abbricht. Es entsteht aber potenziell ein Checkout mit projektfremdem `snapshot_id` (Datenintegrität) und die Prüf-Inkonsistenz ist ein Einfallstor bei künftigen Änderungen.

**Vorschlag (klein, konsistent zu `revision_manifest_api`):**
```python
snapshot = get_object_or_404(
    ProjectSnapshot, id=data["snapshot_id"], project=revision.part.project
)
```

### 4.4 XML-Parsing ohne Härtung (Mittel, umgesetzt)

`Document.xml` und 3MF-Configs werden jetzt mit `defusedxml.ElementTree` aus der echten `defusedxml`-Abhaengigkeit geparst (`fcstd.py`, `fcstd_signature.py`, `services.py`). DTDs, Entities und externe Referenzen werden fuer diese Parserpfade blockiert.

**Status:** umgesetzt mit echter `defusedxml`-Dependency und Regressionstest fuer gefaehrliche `Document.xml`.

### 4.5 Kein Rate-Limiting / Login-Lockout (Mittel)

- Kein Brute-Force-Schutz für Django-Login und für die Bearer-Token-Prüfung (`authenticate_api_token`).
- Für LAN geringer, hinter Reverse Proxy exponiert höher.

**Vorschlag:** `django-axes` (Login-Lockout) und/oder `django-ratelimit` für `/api/` und Login. Alternativ Rate-Limiting im Reverse Proxy (nginx `limit_req`).

### 4.6 Web-UI-Login hängt am Django-Admin (Mittel, Architektur, umgesetzt)

Frueher: `settings.py`: `LOGIN_URL = 'admin:login'`, `LOGIN_REDIRECT_URL = 'admin:index'`.

Der Django-Admin-Login weist nicht-`is_staff`-Nutzer ab bzw. leitet sie in den Admin. Das koppelte die PLM-Anmeldung an das Admin-Interface und machte `/admin/` zur zentralen Login-Fläche.

**Status:** umgesetzt. `/login/` nutzt eine eigene PLM-Login-Seite (`LoginView`) und `LOGIN_REDIRECT_URL='plm:project_list'`. `/admin/` bleibt als technischer Fallback verlinkt, ist aber nicht mehr der normale PLM-Login.

### 4.7 Media-Auslieferung (Niedrig, aber Betriebsfalle)

`freecad_plm/urls.py`:
```python
urlpatterns = [...] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

`static()` liefert nur bei `DEBUG=True` Routen — in Produktion also inaktiv, und Downloads laufen korrekt über die `@login_required`-Views. **Aber:** Wird versehentlich `DJANGO_DEBUG=1` in einer erreichbaren Instanz gesetzt, werden **alle** CAD-Dateien unter `/media/` **ohne Authentifizierung** ausgeliefert.

**Vorschlag:** Kommentar/Guard, dass `MEDIA` niemals über Django in Produktion ausgeliefert wird, und im README explizit vor `DJANGO_DEBUG=1` auf erreichbaren Instanzen warnen (steht dort teils schon). Reverse Proxy sollte `/media/` nicht direkt auf das Volume mappen.

### 4.8 Keine objektbezogene Zugriffskontrolle (bewusst, V2)

Jeder eingeloggte Nutzer sieht/lädt alle Projekte/Teile/Revisionen. Für ein kleines vertrauenswürdiges LAN-Team bewusst akzeptiert (siehe Briefing). Erst relevant bei Mandantenfähigkeit/externen Nutzern.

### 4.9 Addon-Client (Niedrig)

- `api_client.py` nutzt `urllib` mit Default-SSL-Kontext → **Zertifikatsprüfung ist aktiv** (gut). Bei self-signed LAN-Zertifikaten muss der Nutzer ein CA importieren.
- Token wird im Klartext in FreeCAD-Preferences gespeichert (dokumentiert, Panel maskiert die Eingabe). Für einen lokalen Client akzeptabel; Hinweis in Doku genügt.
- Multipart-Bodys werden komplett im Speicher gebaut (`_multipart_files` → `path.read_bytes()`). Bei großen Baugruppen speicherintensiv, aber unkritisch.

---

## 5. Architekturempfehlungen (Zusammenfassung)

| # | Empfehlung | Nutzen | Aufwand |
|---|------------|--------|---------|
| A1 | Web-/Worker-Images trennen (Web ohne FreeCAD) | kleinere Angriffsfläche, schlankeres Image | mittel |
| A2 | Worker-Container härten (cap_drop, limits, tmpfs) | Eindämmung bei FreeCAD-Exploit | klein |
| A3 | Upload-/ZIP-Budgets in Settings + Validierung | DoS/Zip-Bomb-Schutz | klein |
| A4 | Eigene Login-View statt Admin-Login | Entkopplung, Admin separat abschottbar | klein |
| A5 | `services.py`/`views.py`/`api.py` in Packages splitten | Wartbarkeit | mittel |
| A6 | Mittelfristig DRF für die API | weniger Boilerplate, konsistente AuthZ | groß |
| A7 | Test- + `check --deploy`-Job in Forgejo-CI | Regressionsschutz | klein |
| A8 | `defusedxml`, `django-axes`/ratelimit | XML-/Brute-Force-Härtung | klein |
| A9 | Audit-Events um IP/Token-ID erweitern | Forensik/Nachvollziehbarkeit | klein |
| A10 | `planning/PRODUCTION_CHECKLIST.md` erstellen | reproduzierbarer sicherer Betrieb | klein |

---

## 6. Priorisierte Roadmap

**Sofort (klein, hoher Nutzen):**
1. Upload-/ZIP-Budgets (4.1) — umgesetzt; Settings, Validierung und Tests fuer zu grosse Datei / zu viele Member.
2. Worker-Härtung im Compose (4.2 / A2) — umgesetzt; Worker mit `cap_drop`, `read_only`, `tmpfs`, `no-new-privileges`, Limits.
3. Snapshot-Projektprüfung in `revision_checkout_api` (4.3) — umgesetzt; Checkout akzeptiert nur Snapshots aus dem gleichen Projekt wie die Revision.
4. `defusedxml` einführen (4.4) -- umgesetzt.
5. CI-Test-Job (A7).

**Kurzfristig:**
6. Eigene Login-View, `/admin/` separat absichern (4.6) -- Login-View umgesetzt; Admin-Absicherung bleibt Betriebs-/Proxy-Thema.
7. Web-Image ohne FreeCAD (A1).
8. Rate-Limiting/Lockout (4.5).
9. Audit-Events um Request-Kontext erweitern (3.1).

**Mittelfristig (Refactoring, verhaltensneutral):**
10. Module splitten (2.1), Permission-Decorators (2.2), Pfad-Helfer zusammenführen (2.3).
11. Serialisierung zentralisieren / DRF evaluieren (2.5 / A6).
12. Linting/Typing-Tooling + `requirements-dev.txt` (2.7).

---

## 7. Positiv hervorzuheben

- Immutable Revisionen mit SHA-256 und zentraler Codevergabe (`next_revision_code`).
- Durchgängiger Audit-Trail für praktisch alle mutierenden Aktionen.
- Token-only API mit gehashten Tokens, Scopes, Ablauf und Widerruf; Tests decken fehlend/ungültig/abgelaufen/widerrufen/falscher Scope ab.
- Self-Lockout-Schutz in der Benutzerverwaltung.
- FCStd-Signatur gegen No-op-Check-ins (durchdacht, versioniert).
- Subprocess ohne Shell, mit Timeout und temporärem Arbeitsverzeichnis.
- Konsequente `planning/`-Dokumentation, die Entscheidungen nachvollziehbar macht.
- 150 grüne Tests und fehlerfreier System-Check.

---

## 8. Verifikation

```bash
cd /home/ralf/devel/freecad-plm
.venv/bin/python manage.py check          # 0 issues (nach .dockerignore-Fix)
.venv/bin/python manage.py test plm       # 150 Tests OK (Referenzstand)
```
