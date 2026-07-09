# Security-Audit-Briefing fuer FreeCAD-PLM

## Zweck dieses Dokuments

Dieses Dokument ist der **Einstiegspunkt fuer ein folgendes LLM**, das einen Sicherheitsaudit des FreeCAD-PLM-Ökosystems durchfuehren soll. Es fasst den Projektkontext, die Workspace-Struktur, Architektur, Vertrauensgrenzen, bereits umgesetzte Schutzmassnahmen und bekannte Risikohypothesen zusammen.

**Stand der Analyse:** 2026-07-09  
**Erstellt nach:** Lesen von `planning/README.md` und der dort genannten Lesereihenfolge, plus Code- und Workspace-Review.

---

## 1. Workspace-Uebersicht

Der Cursor-Workspace enthaelt vier relevante Verzeichnisse:

| Pfad | Rolle | Git-Repo | Sicherheitsrelevanz |
|------|-------|----------|---------------------|
| `/home/ralf/devel/freecad-plm` | **Hauptserver** – Django-PLM mit Web-UI, REST-API, Storage, FreeCADCmd-Worker | Ja | **Primaeres Audit-Ziel** |
| `/home/ralf/devel/freecad-plm-addon` | **FreeCAD-Workbench** – HTTP-Client, lokaler Workspace, Checkout/Check-in | Ja | Client-seitige Secrets, Pfadvalidierung, Token-Handling |
| `/home/ralf/freecad-plm-testing` | **Laufende Test-/Staging-Instanz** – Docker Compose, `storage/`, `staticfiles/`, `.env` | Nein | Betriebsgeheimnisse in `.env`; reale CAD-Daten in `storage/` |
| `/home/ralf/FreeCAD-PLM` | **Lokale Addon-Workspaces** – Checkout-Ordner mit `manifest.json` und `.FCStd`-Dateien | Nein | Enthaelt reale Arbeitskopien; keine Server-Logik |

### Empfohlene Audit-Reihenfolge

1. `freecad-plm` (Server)
2. `freecad-plm-addon` (Client)
3. Querverbindungen API-Vertrag ↔ Client-Implementierung
4. `freecad-plm-testing` nur fuer Betriebs-/Deployment-Kontext (keine Secrets in Audit-Output wiedergeben)
5. `FreeCAD-PLM` nur als Beispiel fuer reale Checkout-Daten und Signatur-Edge-Cases

---

## 2. Projektkontext (Kurzfassung)

### Ziel

Eigenes PLM/PDM fuer FreeCAD-`FCStd`-Dateien fuer ein **kleines LAN-Team**. Nicht der Umbau des alten nanoPLM (Referenz liegt unter `old/`, aktuell nicht im Workspace sichtbar).

### Kernfunktionen (V1)

- Projekte, Teile/Baugruppen, **unveraenderliche Revisionen** (`R0001`, `R0002`, …)
- Rollen: `reader`, `editor`, `admin` (+ Django-Superuser)
- Web-Upload/Download, Freigabe (`draft` → `released`), Audit-Trail
- Projektstaende/Snapshots fuer referenzierte FreeCAD-Dateisets (ZIP)
- FreeCADCmd-Jobs: STEP/STL/3MF/PNG-Artefakte
- Manufacturing-Dateien (3MF, G-Code, …) pro Revision
- JSON-API unter `/api/` fuer das FreeCAD-Addon (Checkout, Check-in, Import)
- Web-Verwaltung fuer Benutzer und API-Tokens (seit 2026-07-09)

### Technologie

- **Django 5.2**, serverseitige Templates, Bootstrap 4 (UI-Redesign auf Bootstrap 5 geplant)
- SQLite lokal, PostgreSQL in Docker Compose
- Dateien im Filesystem unter `storage/`, Metadaten in DB
- Docker Compose: `web`, `db` (PostgreSQL 16), `worker` (FreeCADCmd-Job-Schleife)
- Image-Registry: `git.home.schumbi.de/ralf/freecad-plm`

Ausfuehrlicher Kontext: `planning/README.md` bis `planning/BULK_IMPORT_PLAN.md`.

---

## 3. Architektur und Vertrauensgrenzen

```text
                    ┌─────────────────────────────────────┐
  Browser (HTTPS)   │  Reverse Proxy (nginx, optional     │
  ───────────────►  │  Basic Auth als aeussere Schranke)  │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │  Django Web (Gunicorn)              │
                    │  - Session-Auth + CSRF (Web-UI)     │
                    │  - Bearer Token (API /api/)         │
                    │  - Datei-Uploads, ZIP-Verarbeitung  │
                    └──────────────┬──────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
     ┌────────▼────────┐  ┌────────▼────────┐  ┌───────▼────────┐
     │  PostgreSQL     │  │  storage/       │  │  Worker        │
     │  Metadaten,     │  │  FCStd, ZIP,    │  │  FreeCADCmd    │
     │  Tokens (hash)  │  │  Artefakte,     │  │  subprocess    │
     │                 │  │  Manufacturing  │  │  (gleiches Vol)│
     └─────────────────┘  └─────────────────┘  └────────────────┘

  FreeCAD + Addon  ──Bearer Token──►  /api/*
  Lokaler Workspace: ~/FreeCAD-PLM/<server>/<projekt>/checkout-*/
```

### Vertrauensannahmen

- **LAN-intern**, kleines vertrauenswuerdiges Team
- CAD-Dateien (`.FCStd`, ZIP, 3MF) sind **nicht vertrauenswuerdig** – muessen als potenzielle Angriffseingabe behandelt werden
- FreeCADCmd verarbeitet diese Dateien in einem Subprozess mit Zugriff auf `storage/`
- API-Tokens sind aeussere Credentials mit Scope-Modell; Django-Rollen gelten zusaetzlich fuer manche API-Aktionen

---

## 4. Authentifizierung und Autorisierung

### Web-UI

| Aspekt | Implementierung |
|--------|-----------------|
| Auth | Django-Session via `@login_required` auf allen PLM-Views |
| Login-URL | `LOGIN_URL = 'plm:login'`; Nutzer melden sich ueber `/login/` an und landen im PLM-WebUI |
| CSRF | Aktiv fuer Web-Forms (`CsrfViewMiddleware`) |
| Rollen | Django-Gruppen `reader`, `editor`, `admin`; Logik in `plm/permissions.py` |
| Admin-UI | Django `/admin/` bleibt als technischer Fallback aktiv und ist von der PLM-Login-Seite verlinkt |
| Benutzerverwaltung | `/verwaltung/` – nur PLM-Admins; Self-Lockout-Schutz fuer letzten Admin |

Relevante Dateien:

- `plm/permissions.py` – `can_upload_revision`, `can_release_revision`, `is_plm_admin`
- `plm/views.py` – `admin_required_response`, `validate_user_admin_safety`
- `plm/forms.py` – User-/Token-Formulare

### REST-API (`/api/`)

| Aspekt | Implementierung |
|--------|-----------------|
| Auth | **Nur** `Authorization: Bearer <token>` – keine Browser-Sessions |
| Token-Speicher | SHA-256-Hash in DB; Klartext nur bei Erstellung sichtbar |
| Scopes | `read`, `write`, `checkout`, `admin` |
| CSRF | `@csrf_exempt` auf mutierenden Endpunkten (bewusst, da token-only) |
| Scope `admin` | Impliziert Vollzugriff auf alle Scopes |

Relevante Dateien:

- `plm/auth.py` – Token-Erzeugung, `api_auth_required`-Decorator
- `plm/models.py` – `ApiToken`
- `plm/api.py` – alle API-Endpunkte
- `plm/management/commands/create_api_token.py`

### Bekannte Autorisierungs-Einschraenkung

- **Keine objektbezogene Zugriffskontrolle:** Jeder eingeloggte Nutzer mit passender Rolle sieht alle Projekte/Teile/Revisionen.
- Fuer V1/LAN akzeptiert; relevant bei Mandantenfaehigkeit oder externen Nutzern.

### API + Django-Rollen-Kopplung

Tests bestaetigen: Ein API-Token mit Scope `write` reicht nicht aus, wenn der gebundene Django-User nur `reader` ist (`test_write_token_still_respects_django_roles`). Das Audit soll pruefen, ob diese Kopplung **konsistent auf allen Endpunkten** gilt.

---

## 5. Angriffsflaechen (priorisiert)

### Kritisch / Hoch

1. **Datei-Uploads ohne Ressourcenbudget**
   - `validate_fcstd_upload()` liest komplette Uploads in den Speicher (`read_uploaded_file` → `BytesIO`)
   - `fcstd_with_plm_revision()` liest alle ZIP-Member
   - Projekt-ZIP-Import iteriert alle `.FCStd`-Member vollstaendig
   - `PLM_MAX_*`-Limits sind in `settings.py` implementiert und werden aus ENV gelesen.
   - Risiko: Zip-Bomb, Speicher-DoS, CPU-Last

2. **FreeCADCmd-Verarbeitung nicht vertrauenswuerdiger CAD-Dateien**
   - `plm/freecadcmd.py`: `subprocess.run()` ohne Shell, mit Timeout (300s)
   - Worker und Web teilen `storage/`-Volume
   - FreeCAD im Web-Image installiert (`Dockerfile`, `INSTALL_FREECAD=1`)
   - Risiko: FreeCAD-Parser-/Importer-Schwachstellen, Container-Escape, Ressourcen-Erschoepfung

3. **API-Token als Bearer-Credentials**
   - Kein Rate-Limiting, kein Brute-Force-Schutz auf Token-Validierung
   - Token-Prefix `plm_pat_` + `secrets.token_urlsafe(32)` – ausreichend Entropie, aber kein Rotation-/Lockout-Mechanismus
   - Scope `admin` ermoeglicht Projektanlage, Import, Metadaten-Aenderung

### Mittel

4. **HTTPS-/Cookie-Haertung abhaengig vom Betrieb**
   - Settings vorbereitet (`DJANGO_SESSION_COOKIE_SECURE`, `DJANGO_CSRF_COOKIE_SECURE`, HSTS, SSL-Redirect)
   - Default in Dev: `DEBUG=True`, bekannter Dev-Secret-Key
   - Fail-Fast wenn `DEBUG=0` ohne `DJANGO_SECRET_KEY`

5. **XML-Verarbeitung in User-Uploads**
   - `Document.xml` und 3MF-Configs werden serverseitig geparst.
   - Die Parserpfade nutzen inzwischen die echte `defusedxml`-Dependency.
   - Gefaehrliche `Document.xml`-Inhalte sind per Regressionstest abgedeckt.

6. **Pfad-Traversal in Snapshots/Manifesten**
   - Server: `safe_snapshot_path()` in `plm/services.py` blockiert `..` und absolute Pfade
   - Addon: `safe_join()` / `safe_zip_path()` in `freecad_plm_addon/workspace.py`
   - Tests fuer `../Box.FCStd` vorhanden – Audit soll End-to-End und Check-in-Pfade pruefen

7. **Django-Admin parallel zur PLM-Verwaltung**
   - Superuser und Staff-Zugang koennen DB direkt manipulieren
   - Kein separates Admin-Hardening dokumentiert

8. **Inline-Job-Verarbeitung im Webprozess**
   - `PROCESS_EXPORT_JOBS_INLINE` kann FreeCADCmd im Web-Container starten (lokal Default `1`, Docker `0`)
   - Erhoeht Angriffsoberflaeche des oeffentlich erreichbaren Web-Containers

### Niedrig / Informativ

9. **Addon speichert API-Token in FreeCAD-Parametern** (`config.py` → `FreeCAD.ParamGet`)
   - Lokal auf dem Client-Rechner; Schutz haengt von OS/File-Permissions ab
   - Panel zeigt Token als Password-Feld, speichert aber Klartext in Preferences

10. **Keine Rate-Limits / Account-Lockout** fuer Django-Login

11. **Three.js lokal** (0.160.0) – Supply-Chain bei Updates pruefen; kein CDN

12. **`freecad-plm-testing/.env`** enthaelt Betriebsgeheimnisse – nicht committen, nicht in Audit-Outputs zitieren

---

## 6. Bereits umgesetzte Sicherheitskontrollen

| Kontrolle | Status | Referenz |
|-----------|--------|----------|
| API token-only (keine Session-Auth auf `/api/`) | Umgesetzt 2026-07-06 | `plm/auth.py`, `plm/api.py` |
| Gehashte API-Tokens, Widerruf, Ablauf | Umgesetzt | `plm/models.ApiToken` |
| Scope-basierte API-Autorisierung | Umgesetzt | `@api_auth_required` |
| Rollenmodell Web-UI | Umgesetzt | `plm/permissions.py` |
| Audit-Trail fuer zentrale Aktionen | Umgesetzt | `plm/models.AuditEvent` |
| SHA-256-Integritaet fuer Revisionen | Umgesetzt | Upload-Service, Addon-Download-Pruefung |
| Sichere Snapshot-Pfade | Umgesetzt | `safe_snapshot_path()` |
| Subprocess ohne Shell, mit Timeout | Umgesetzt | `plm/freecadcmd.py` |
| Production Secret-Key Fail-Fast | Umgesetzt | `freecad_plm/settings.py` |
| HTTPS/Cookie-Settings per ENV | Umgesetzt | `.env.example` |
| Docker: Postgres-Passwort/Secret erzwungen | Umgesetzt | `docker-compose.image.yml` |
| Container-User `plm` (UID 1000) | Umgesetzt | `Dockerfile`, Compose |
| `.dockerignore` schliesst Secrets/Storage aus | Umgesetzt | `.dockerignore` |
| Self-Lockout-Schutz Admin-Verwaltung | Umgesetzt 2026-07-09 | `validate_user_admin_safety()` |
| FCStd-Technische Signatur gegen No-op-Check-ins | Umgesetzt 2026-07-07 | `plm/fcstd_signature.py` |
| G-Code/3MF nur speichern, nicht ausfuehren | Designentscheidung | `planning/MANUFACTURING_FILES_PLAN.md` |

Vorheriger Audit-Bericht: `planning/SECURITY_ARCHITECTURE_AUDIT_2026-07-06.md`

---

## 7. Offene Punkte aus dem Audit 2026-07-06

| Empfehlung | Status 2026-07-09 |
|------------|-------------------|
| API-Token-Auth statt Session-API | **Erledigt** |
| Upload-/ZIP-Budgets (`PLM_MAX_*`) | **Erledigt 2026-07-09** – Settings + Validierung + Tests |
| Worker-Haertung (cap_drop, read_only, Limits) | **Erledigt 2026-07-09** – Compose gehärtet |
| Getrennte Web-/Worker-Images (Web ohne FreeCAD) | **Offen** – `INSTALL_FREECAD` existiert, Default `1` |
| `planning/PRODUCTION_CHECKLIST.md` | **Offen** – Datei fehlt |
| Basic Auth nur als aeussere Schranke | Betriebsentscheidung |
| Objektbezogene ACL | Bewusst V2/spaeter |

---

## 8. API-Endpunkte (Vollstaendige Liste fuer Review)

Basis: `plm/urls.py` und `README.md`.

### Lesen (Scope `read`)

- `GET /api/projects/`
- `GET /api/projects/<id>/`
- `GET /api/projects/<id>/parts/`
- `GET /api/parts/<id>/`
- `GET /api/revisions/<id>/`
- `GET /api/revisions/<id>/file/`
- `GET /api/revisions/<id>/manifest/` (optional `snapshot_id`)
- `GET /api/parts/<id>/annotations/`

### Schreiben (Scope `write` + Django-Rolle)

- `POST /api/projects/<id>/parts/` – Teilanlage
- `POST /api/parts/<id>/` – Teil bearbeiten
- `POST /api/revisions/<id>/notes/`
- `POST /api/parts/<id>/annotations/`
- `POST /api/annotations/<id>/`
- `DELETE /api/annotations/<id>/`
- `POST /api/projects/<id>/snapshots/import/` – ZIP-Upload

### Checkout (Scope `checkout`)

- `POST /api/revisions/<id>/checkout/`
- `GET /api/checkouts/active/`
- `GET /api/checkouts/<id>/manifest/`
- `POST /api/checkouts/<id>/checkin/` – Multipart, Single- und Multi-File
- `POST /api/checkouts/<id>/cancel/`

### Admin (Scope `admin`)

- `POST /api/projects/` – Projekt anlegen
- `POST /api/projects/<id>/` – Projekt bearbeiten
- `POST /api/projects/import/` – Projekt + ZIP atomar

**Audit-Fokus:** Jeder Endpunkt auf AuthZ-Luecken, IDOR (fehlende Objektpruefung bei fremden IDs), Mass-Assignment, unsichere Deserialisierung (`json_body`), Multipart-Validierung.

---

## 9. Web-UI-Endpunkte (Auswahl)

Alle unter `@login_required`. Besonders pruefen:

- Uploads: `upload_revision`, `upload_project_snapshot`, `upload_manufacturing_file`
- Downloads: `download_revision`, `download_project_snapshot`, Artefakt-/Manufacturing-Downloads
- Viewer: `revision_viewer_source`, `artifact_viewer_source` – liefern Dateien an Browser
- Job-Trigger: `create_revision_png_job`, `process_export_jobs_once` – starten FreeCADCmd
- Verwaltung: `/verwaltung/*` – nur Admin
- Projektloeschung: `delete_project` – Storage-Aufraeumung

Vollstaendige Routen: `plm/urls.py`

---

## 10. Datenmodell (sicherheitsrelevant)

Kernmodelle in `plm/models.py`:

- `Project`, `Part`, `Revision` – Revisionen immutable nach Freigabe
- `Checkout` – exklusiver Lock pro Teil
- `ProjectSnapshot`, `ProjectSnapshotEntry` – referenzierte Dateisets
- `ApiToken` – gehashte Tokens
- `AuditEvent` – Nachvollziehbarkeit
- `ExportJob`, `RevisionArtifact` – abgeleitete Dateien
- `ManufacturingFile`, `ManufacturingMachine`, `ManufacturingRun` – Fertigungsdateien
- `Annotation` – objektbezogene Anmerkungen

Storage-Layout (vereinfacht):

```text
storage/projects/<project_id>/parts/<part_id>/revisions/<code>/
storage/projects/.../revisions/<code>/artifacts/
storage/projects/.../revisions/<code>/manufacturing/<id>/
```

Dateinamen im Storage nutzen SHA-256-basierte Namen (nicht reine Benutzereingabe) – in `plm/services.py` pruefen.

---

## 11. FreeCAD-Addon (Client-Audit)

Repository: `/home/ralf/devel/freecad-plm-addon`

| Modul | Aufgabe | Audit-Fokus |
|-------|---------|-------------|
| `api_client.py` | HTTP mit `urllib`, Bearer-Header | TLS-Verifikation, Fehlerbehandlung, Timeout (30s) |
| `workspace.py` | Lokale Checkout-Verzeichnisse, SHA-256, Signatur-Vorfilter | Path-Traversal, Symlinks, Import-ZIP-Erzeugung |
| `config.py` | Token/URL in FreeCAD-Parametern | Secret-Storage, Backup-Risiko |
| `panel.py` | UI, Verbindung, Workflows | Token in UI, Fehlermeldungen mit sensitiven Daten |
| `fcstd.py` | Lokale FCStd-Hilfen | Parallele Signatur-Logik zum Server |

API-Vertrag: `planning/FREECAD_ADDON_PLAN.md`, `SERVER_API_REQUIREMENTS.md`

Tests (ohne FreeCAD): `python3 -m unittest discover -s tests`

---

## 12. Deployment und Betrieb

### Docker Compose (`docker-compose.image.yml`)

- Services: `db`, `web`, `worker`
- `web` exponiert Port 8000
- `worker` hat **keinen** Port, aber gleiches Image und Storage-Zugriff
- `worker` laeuft mit `cap_drop: ["ALL"]`, `security_opt: ["no-new-privileges:true"]`, `read_only: true`, `tmpfs` fuer `/tmp` und `/var/tmp` sowie CPU-/RAM-/PID-Limits

### Umgebungsvariablen (`.env.example`)

Sicherheitsrelevant: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, Cookie-Secure, HSTS, `POSTGRES_PASSWORD`

### CI/CD

- `.forgejo/workflows/build-image.yml` – Image-Build bei Push

### Testing-Instanz

- `~/freecad-plm-testing` – produktionsnaher Compose-Stack mit echten Daten in `storage/`
- Fuer dynamische Tests nutzen, aber **keine Secrets aus `.env` extrahieren oder dokumentieren**

---

## 13. Test- und Verifikationskommandos

```bash
# Server (Entwicklung)
cd /home/ralf/devel/freecad-plm
.venv/bin/python manage.py check
.venv/bin/python manage.py test plm

# Deployment-Check (Beispiel)
DJANGO_DEBUG=0 DJANGO_SECRET_KEY=test-secret DJANGO_ALLOWED_HOSTS=localhost \
  .venv/bin/python manage.py check --deploy

# Addon
cd /home/ralf/devel/freecad-plm-addon
python3 -m unittest discover -s tests
```

**Aktueller Teststand Server:** 150 Tests, alle OK (2026-07-09).

Vorhandene Security-Tests (Auswahl in `plm/tests.py`):

- API-Token: fehlend, ungueltig, widerrufen, abgelaufen, falscher Scope
- Browser-Session auf API abgelehnt
- Rollen: Reader darf nicht uploaden/freigeben
- Admin-Verwaltung: Self-Lockout, Token-Presets
- Pfad-Traversal in Manifesten
- Check-in-Signatur / No-op-Check-in

**Fehlende Test-Hypothesen fuer Audit:**

- Upload-Groessenlimits / Zip-Bomb
- Rate-Limiting
- IDOR ueber Projekt-/Teil-IDs bei API
- Concurrent Checkout-Races
- Manufacturing-File-Upload-Grenzen

---

## 14. Empfohlene Audit-Methodik fuer das folgende LLM

### Phase 1: Statische Code-Review

1. `freecad_plm/settings.py` – alle Security-Settings, Defaults, Debug-Pfade
2. `plm/auth.py`, `plm/api.py` – AuthN/AuthZ jedes Endpunkts
3. `plm/views.py`, `plm/permissions.py` – Web-AuthZ-Luecken
4. `plm/fcstd.py`, `plm/services.py` – Upload/ZIP/Storage
5. `plm/freecadcmd.py` – Subprocess, Pfade, Timeouts, Output-Groessen
6. `plm/fcstd_signature.py` – Bypass-Moeglichkeiten der Signatur
7. `Dockerfile`, `docker-compose*.yml`, `.dockerignore`
8. Addon: `api_client.py`, `workspace.py`, `config.py`

### Phase 2: Threat Modeling

STRIDE oder aehnlich auf:

- Authentifizierter `reader` versucht zu eskalieren
- Kompromittierter `editor`-Account
- Gestohlener API-Token (read vs. write vs. admin)
- Boerser Upload (FCStd, Projekt-ZIP, 3MF, G-Code)
- Worker-Kompromittierung via FreeCADCmd
- Insider mit Admin-Rechten

### Phase 3: Dynamische Tests (optional)

- Gegen lokale Instanz oder `freecad-plm-testing`
- Upload-Grenzfaelle, parallele Checkouts, Token-Scope-Grenzen
- **Kein** produktives Exfiltrieren von `.env`-Werten

### Phase 4: Bericht

Struktur:

1. Executive Summary
2. Findings nach Schweregrad (Critical/High/Medium/Low/Info)
3. Pro Finding: Evidenz (Datei/Zeile), Risiko, Exploit-Szenario, Empfehlung, Aufwand
4. Abgleich mit `SECURITY_ARCHITECTURE_AUDIT_2026-07-06.md`
5. Priorisierte Patch-Roadmap

---

## 15. Bewusst ausserhalb des Scopes

- Live-Zielserver, nginx/TLS-Zertifikate, Basic-Auth-Konfiguration
- Backup/Restore-Prozess
- Forgejo-Runner-Haertung
- Penetrationstest gegen FreeCAD selbst (CVE-Recherche optional)
- Vollstaendige Stuecklisten-/Workflow-Sicherheit (V2)
- UI-Redesign (`planning/UI_REDESIGN_PLAN.md`) – kein neues Angriffsmodell erwartet

---

## 16. Referenz-Dokumente (Lesereihenfolge)

1. `planning/README.md`
2. `planning/REQUIREMENTS.md`
3. `planning/ARCHITECTURE.md`
4. `planning/DECISIONS.md`
5. `planning/FREECAD_ADDON_PLAN.md`
6. `planning/MANUFACTURING_FILES_PLAN.md`
7. `planning/FCSTD_TECHNICAL_SIGNATURE_PLAN.md`
8. `planning/SECURITY_ARCHITECTURE_AUDIT_2026-07-06.md` (Vorgaenger)
9. Root-`README.md` (Betrieb, API, Rollen)

---

## 17. Kurz-Fazit fuer den Audit-Einstieg

FreeCAD-PLM ist ein **reifes V1-LAN-PLM** mit durchdachtem Revisionsmodell, Audit-Trail und inzwischen **solider API-Token-Authentifizierung**. Die groessten verbleibenden Risiken liegen typischerweise bei:

1. **Unbegrenzten Uploads und ZIP-Verarbeitung** (DoS)
2. **FreeCADCmd als Angriffsvektor** fuer boesartige CAD-Dateien
3. **Fehlender Worker-/Container-Haertung** im Docker-Betrieb
4. **Globalem Zugriffsmodell** ohne Projekt-Isolation
5. **Client-seitiger Token-Speicherung** im FreeCAD-Addon

Das folgende LLM sollte mit `plm/api.py`, `plm/services.py`, `plm/fcstd.py`, `plm/freecadcmd.py` und `freecad_plm/settings.py` beginnen und die Findings aus `SECURITY_ARCHITECTURE_AUDIT_2026-07-06.md` auf aktuellen Code-Stand validieren.
