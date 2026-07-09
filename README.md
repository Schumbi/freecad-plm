# FreeCAD-PLM

Ein neues Django-basiertes PLM/PDM fuer FreeCAD-Dateien.

## Lokal starten

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py setup_plm_roles
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Die PLM-Oberflaeche startet unter <http://127.0.0.1:8000/> und nutzt
<http://127.0.0.1:8000/login/> fuer die normale Anmeldung. Die technische
Django-Admin-Oberflaeche liegt weiterhin unter <http://127.0.0.1:8000/admin/>.

## Serverbetrieb Mit Docker Compose

Der empfohlene Serverpfad nutzt Docker Compose mit PostgreSQL, lokalen Datenverzeichnissen und einem separaten Worker. Web und Worker laufen aus demselben PLM-Image. Dieses Image enthaelt Django, Gunicorn und FreeCAD/FreeCADCmd.

Der Forgejo-Workflow in `.forgejo/workflows/build-image.yml` baut das Image bei jedem Push nach `main` oder `master` automatisch aus dem lokalen `Dockerfile` und veroeffentlicht:

```text
git.home.schumbi.de/ralf/freecad-plm:latest
git.home.schumbi.de/ralf/freecad-plm:<commit-sha>
```

### Server Mit Fertigem Image Starten

```bash
git clone ssh://home.schumbi.de/ralf/freecad-plm.git /opt/freecad-plm
cd /opt/freecad-plm
cp .env.example .env
$EDITOR .env
```

In `.env` mindestens setzen:

```env
DJANGO_SECRET_KEY=replace-with-a-long-random-secret
DJANGO_ALLOWED_HOSTS=plm.example.local,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://plm.example.local
DJANGO_SECURE_SSL_REDIRECT=0
DJANGO_SECURE_HSTS_SECONDS=0
DJANGO_SESSION_COOKIE_SECURE=1
DJANGO_CSRF_COOKIE_SECURE=1
PLM_LOG_LEVEL=INFO
DJANGO_LOG_LEVEL=INFO
DJANGO_DB_LOG_LEVEL=WARNING
GUNICORN_LOG_LEVEL=info
GUNICORN_ACCESS_LOG=1
POSTGRES_PASSWORD=replace-with-a-strong-database-password
PLM_IMAGE=git.home.schumbi.de/ralf/freecad-plm:latest
PLM_USER=plm
PLM_UID=1000
PLM_GID=1000
FREECADCMD_COMMAND=freecadcmd
PLM_MAX_FCSTD_UPLOAD_BYTES=200000000
PLM_MAX_PROJECT_ZIP_BYTES=500000000
PLM_MAX_ZIP_MEMBERS=2000
PLM_MAX_ZIP_UNCOMPRESSED_BYTES=2147483648
PLM_MAX_ZIP_MEMBER_BYTES=200000000
```

Das Runtime-Image enthaelt den User `plm` mit UID/GID `1000:1000`. `PLM_USER` sollte deshalb auf `plm` bleiben. `PLM_UID` und `PLM_GID` dokumentieren, wem die lokalen Verzeichnisse auf dem Host gehoeren sollen; die Werte zeigt `id` oder `id <user>`.

Die `PLM_MAX_*`-Werte begrenzen `FCStd`-, Projekt-ZIP- und 3MF-Uploads gegen sehr grosse Dateien und ZIP-Bomben. Die Defaults sind fuer ein LAN-Team konservativ und koennen bei Bedarf hoeher gesetzt werden.
Der Compose-Worker laeuft zusaetzlich mit `cap_drop: ALL`, `no-new-privileges`, read-only Root-FS, `tmpfs` fuer `/tmp` und `/var/tmp` sowie einfachen CPU-/RAM-/PID-Grenzen.

Lokale Verzeichnisse fuer Modelle/Uploads und statische Dateien anlegen:

```bash
mkdir -p storage staticfiles
sudo chown -R 1000:1000 storage staticfiles
```

Start:

```bash
docker compose -f docker-compose.image.yml pull
docker compose -f docker-compose.image.yml up -d
```

`storage/` liegt neben der Compose-Datei und enthaelt hochgeladene Modelle, Revisionen und erzeugte Artefakte. `staticfiles/` enthaelt nur neu generierbare Django-Static-Dateien.

Nach dem ersten Start:

```bash
docker compose -f docker-compose.image.yml exec web python manage.py setup_plm_roles
docker compose -f docker-compose.image.yml exec web python manage.py createsuperuser
```

### Betrieb Hinter Nginx

Wenn Django hinter einem Reverse Proxy per HTTPS erreichbar ist, muessen die
oeffentlichen Hosts und Origins in `.env` stehen:

```env
DJANGO_ALLOWED_HOSTS=jellyfin.schumbi.de,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://jellyfin.schumbi.de
PLM_HTTP_PORT=8000
```

Eine einfache nginx-Site fuer den lokalen Compose-Port:

```nginx
server {
    listen 443 ssl http2;
    server_name jellyfin.schumbi.de;

    ssl_certificate /etc/letsencrypt/live/jellyfin.schumbi.de/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/jellyfin.schumbi.de/privkey.pem;

    client_max_body_size 512m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Port $server_port;
    }
}
```

Nach Aenderungen an `.env` den Web-Container neu erstellen:

```bash
docker compose -f docker-compose.image.yml up -d --force-recreate web worker
```

### Debugging Und Logs

Web- und Worker-Logs landen auf stdout/stderr und sind direkt ueber Docker
Compose abrufbar:

```bash
cd /opt/freecad-plm
docker compose -f docker-compose.image.yml logs -f --tail=200 web
docker compose -f docker-compose.image.yml logs -f --tail=200 worker
docker compose -f docker-compose.image.yml logs -f --tail=300 web worker
```

Fuer die lokale Testing-Instanz entsprechend:

```bash
cd ~/freecad-plm-testing
docker compose -f docker-compose.image.yml logs -f --tail=300 web worker
```

Die Ausfuehrlichkeit laesst sich in `.env` steuern:

```env
PLM_LOG_LEVEL=DEBUG
DJANGO_LOG_LEVEL=DEBUG
DJANGO_DB_LOG_LEVEL=WARNING
GUNICORN_LOG_LEVEL=debug
GUNICORN_ACCESS_LOG=1
```

- `PLM_LOG_LEVEL`: App-Logger fuer `plm.*` und Root-Logger.
- `DJANGO_LOG_LEVEL`: Django-Logger inklusive Request-/Exception-Logging.
- `DJANGO_DB_LOG_LEVEL`: SQL-Logging ueber `django.db.backends`; `DEBUG` ist
  sehr laut und nur fuer gezielte Datenbankdiagnose gedacht.
- `GUNICORN_LOG_LEVEL`: Gunicorn-Loglevel.
- `GUNICORN_ACCESS_LOG`: `1` schreibt HTTP-Access-Logs nach stdout, `0`
  deaktiviert sie.

Nach Aenderungen an diesen Werten:

```bash
docker compose -f docker-compose.image.yml up -d --force-recreate web worker
```

`DJANGO_DEBUG=1` kann in einer lokalen Testumgebung zusaetzlich helfen, sollte
aber nicht fuer oeffentlich erreichbare Instanzen gesetzt werden.

### Image Manuell Bauen

Normalerweise baut der Forgejo-Workflow in diesem Repo das Image. Manuell geht es so:

```bash
git clone ssh://home.schumbi.de/ralf/freecad-plm.git /opt/freecad-plm-build
cd /opt/freecad-plm-build
docker build -t git.home.schumbi.de/ralf/freecad-plm:latest .
docker push git.home.schumbi.de/ralf/freecad-plm:latest
```

### Image-Build Ausloesen

Im Normalfall reicht ein Push ins App-Repo:

```bash
cd /home/ralf/devel/freecad-plm
git push
```

Der Forgejo-Workflow `Build FreeCAD PLM Image` startet bei Push nach `main` oder
`master` automatisch. Den Lauf findest du in Forgejo unter:

```text
ralf/freecad-plm -> Actions -> Build FreeCAD PLM Image
```

Wenn ein Build ohne neuen Commit erneut laufen soll, kann der Workflow dort auch
manuell ueber `Run workflow` gestartet werden. Nach einem erfolgreichen Lauf ist
das Registry-Image aktualisiert:

```text
git.home.schumbi.de/ralf/freecad-plm:latest
git.home.schumbi.de/ralf/freecad-plm:<commit-sha>
```

### Updates

Wenn das Image neu gebaut wurde:

```bash
cd /opt/freecad-plm
git pull
docker compose -f docker-compose.image.yml pull
docker compose -f docker-compose.image.yml up -d
```

### Lokaler Compose-Build

Alternativ kann das App-Repo lokal ein Image bauen. Das ist fuer Entwicklung praktisch, auf dem Server aber langsamer als das fertige Registry-Image:

```bash
docker compose up -d --build
```

## Rollen

Die V1-Rollen werden als Django-Gruppen angelegt:

```bash
.venv/bin/python manage.py setup_plm_roles
```

- `reader`: ansehen und herunterladen
- `editor`: ansehen, herunterladen und Revisionen hochladen
- `admin`: volle PLM-Verwaltung

PLM-Admins koennen Benutzer und Addon-Tokens in der normalen Weboberflaeche
unter `Verwaltung` pflegen. Die normale Anmeldung fuehrt direkt in das PLM-WebUI.
Der Django-Admin unter `/admin/` bleibt als technische Fallback-Verwaltung
erhalten und ist von der Login-Seite aus verlinkt.

Die Web-Verwaltung kann:

- Benutzer anlegen, aktivieren/deaktivieren und Rollen setzen.
- Passwoerter fuer Benutzer neu setzen.
- API-Tokens fuer Benutzer anlegen, bearbeiten und widerrufen.

Token-Rechte werden ueber Presets vergeben:

- `Nur Lesen`: `read`
- `Addon Standard`: `read`, `write`, `checkout`
- `Admin/Vollzugriff`: `read`, `write`, `checkout`, `admin`

`Admin/Vollzugriff` kann nur fuer Benutzer mit PLM-Admin-Rolle oder Superuser
vergeben werden. Der Klartext eines API-Tokens wird nur direkt nach dem
Anlegen angezeigt; danach bleibt nur der Prefix sichtbar.

## Kurzworkflow

1. Projekt als `admin`/Superuser in der PLM-Oberflaeche anlegen oder vorhandenes Projekt oeffnen.
2. Teil oder Baugruppe im Projekt mit initialer `.FCStd`-Datei anlegen.
3. FreeCAD-Metadaten pruefen. Teilenummer und Name koennen leer bleiben; dann nutzt das PLM FreeCAD-`Id`/`Label` oder automatisch `P-001`, `P-002`, ...
4. Neue Revisionen werden automatisch kanonisch als `R0001`, `R0002`, ... vergeben; alte oder testweise abweichende Codes werden bei der naechsten Nummer ignoriert.
5. Beim Hochladen einer neuen Revision fehlende oder abweichende FreeCAD-Property `PLMRevision` verwerfen oder als PLM-normalisierte Kopie speichern.
6. Optional Anmerkungen ergaenzen.
7. Optional Revision freigeben (nur `admin`/Superuser).
8. Aeltere freigegebene Revision als obsolet markieren (nur `admin`/Superuser), wenn eine neuere Revision gueltig ist.
9. Globale Suche in der Topbar nutzen: Projekte, Teile, Revisionen und Dateipfade finden (`/search/?q=...`).

## Suche

Die globale Suche in der Topbar durchsucht Projekte, Teile, Revisionen und Dateipfade in Projektstaenden. Auf Listen-Seiten (Projekte, Teile, Revisionen) gibt es zusaetzlich einen lokalen Filter in der jeweiligen Toolbar.

## Projektstaende

FreeCAD-Projekte mit mehreren referenzierten `.FCStd`-Dateien koennen als ZIP importiert werden. Das PLM legt einen Projektstand an und speichert, welche Revisionen unter welchen relativen Pfaden zusammengehoeren. Der Projektstand kann wieder als ZIP heruntergeladen werden.

Der normale Download einer Revision liefert eine einzelne `.FCStd` nur dann, wenn sie keine FreeCAD-Referenzen enthaelt. Hat eine Datei Referenzen, liefert der Download automatisch ein ZIP mit der Datei und ihren rekursiv referenzierten Dateien aus demselben Projektstand.

Projektstand, Planung und V1-Abnahme-Checkliste stehen in `planning/`; fuer die manuelle V1-Abnahme siehe `planning/V1_ACCEPTANCE.md`.

## FreeCAD-Addon-API

Das PLM stellt JSON-Endpunkte unter `/api/` bereit. Sie sind fuer ein vanilla-FreeCAD-Addon gedacht und unterstuetzen Bearer Tokens:

```bash
.venv/bin/python manage.py create_api_token addon-user "FreeCAD Addon" --scope read --scope write --scope checkout
```

Der ausgegebene Token wird nur einmal angezeigt und danach als Header gesendet:

```http
Authorization: Bearer plm_pat_...
```

Token-Scopes:

- `read`: Projekte, Teile, Revisionen und Dateien lesen
- `write`: Teile bearbeiten/anlegen und Anmerkungen schreiben
- `checkout`: Checkout, Check-in und Cancel
- `admin`: Projektanlage/-bearbeitung ueber API

- `GET/POST /api/projects/`
- `POST /api/projects/import/`
- `GET/POST /api/projects/<id>/`
- `POST /api/projects/<id>/snapshots/import/`
- `GET/POST /api/projects/<id>/parts/`
- `GET/POST /api/parts/<id>/`
- `GET /api/revisions/<id>/`
- `POST /api/revisions/<id>/notes/`
- `GET /api/revisions/<id>/file/`
- `POST /api/revisions/<id>/checkout/`
- `GET /api/checkouts/<id>/manifest/`
- `POST /api/checkouts/<id>/checkin/`
- `POST /api/checkouts/<id>/cancel/`
- `GET/POST /api/parts/<id>/annotations/`
- `POST/DELETE /api/annotations/<id>/`

Projektbearbeitung ueber `POST /api/projects/<id>/` braucht Scope `admin` und
akzeptiert dieselben Stammdaten wie das WebUI: `code`, `name`, `status`,
`project_date`, `description` und `is_archived`.

Lokale FreeCAD-Dateisets koennen als Projektstand importiert werden. Das Addon
sendet dafuer ein ZIP mit relativen `.FCStd`-Pfaden an
`POST /api/projects/<id>/snapshots/import/` mit Scope `write`. Fuer den
Kombiflow "Projekt anlegen und ZIP importieren" nutzt es
`POST /api/projects/import/` mit Scope `admin`.

Checkout ist exklusiv pro Teil/Baugruppe. Das Checkout-Manifest enthaelt Root-Datei, referenzierte Revisionen, relative Pfade, Hashes und Download-URLs. Der Check-in erzeugt nur fuer modellrelevante FCStd-Aenderungen neue unveraenderliche Revisionen; reine FreeCAD-Speicherartefakte wie `GuiDocument.xml`, `ShapeAppearance*`, `LastModified*`, `PLMRevision`, lokale Checkout-Pfade in BOM-/XML-Attributen und winziges Placement-Floating-Point-Rauschen werden durch die technische Signatur ignoriert.

## FreeCADCmd

Exportjobs werden mit `FREECADCMD_COMMAND` ausgefuehrt. Ohne eigene Einstellung versucht das PLM zuerst `FreeCADCmd` und faellt auf die Flatpak-Installation `org.freecad.FreeCAD` mit `--command=FreeCADCmd` und `/tmp`-Freigabe zurueck, wenn `flatpak` vorhanden ist.

Beispiel fuer eine explizite Flatpak-Konfiguration:

```bash
FREECADCMD_COMMAND='flatpak run --filesystem=/tmp --branch=stable --arch=x86_64 --command=FreeCADCmd org.freecad.FreeCAD' .venv/bin/python manage.py process_export_jobs
```

PNG-Ansichten werden ohne FreeCAD-GUI erzeugt. Der Worker exportiert die Revision mit `FreeCADCmd` zuerst als STEP-Artefakt und als temporaeres STL-Vorschau-Mesh. Danach rendert das PLM aus dem STL-Mesh feste PNG-Ansichten. Dafuer wird kein FreeCAD-Fenster, kein Qt-Viewport und kein `xvfb-run` benoetigt.

Empfohlene Server-Konfiguration:

```bash
FREECADCMD_COMMAND='freecadcmd'
PREVIEW_PNG_WIDTH=400
PREVIEW_PNG_HEIGHT=300
PROCESS_EXPORT_JOBS_INLINE=0
```

Mit `PROCESS_EXPORT_JOBS_INLINE=0` legt die Weboberflaeche Export- und PNG-Jobs nur an. Der Docker-Worker verarbeitet sie im Hintergrund. So muss der Webprozess kein FreeCAD starten.

Auf einem Server mit nativer FreeCAD-Installation reicht meistens:

```bash
FREECADCMD_COMMAND=/usr/bin/FreeCADCmd .venv/bin/python manage.py process_export_jobs
```
