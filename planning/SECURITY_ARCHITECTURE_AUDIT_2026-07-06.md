# Sicherheits- und Architektur-Audit 2026-07-06

## Scope

Audit-Ziel: Sicherheit und Architektur fuer einen produktiven Betrieb des FreeCAD-PLM.

Geprueft wurden:

- Durable Projektkontext in `planning/`
- Django-Settings, URL-Routing, Views, API, Rollenmodell
- Upload-, ZIP-, Storage- und FreeCADCmd-Pfade
- Dockerfile, Docker Compose, Image-Build und Beispielkonfiguration
- vorhandene Tests und Django-Checks

Nicht geprueft wurden:

- Zielserver, Reverse-Proxy-Konfiguration und TLS-Zertifikate live
- echte Benutzer-/Rollenanlage auf dem Zielsystem
- echte FreeCAD-Dateien unter Last
- Backup-/Restore-Prozess
- Registry-/Forgejo-Runner-Haertung ausserhalb dieses Repos

## Kurzfazit

Die Architektur ist fuer ein kleines LAN-PLM grundsaetzlich passend: Django ist hier eine gute Wahl, weil Benutzer, Gruppen, Admin, Sessions, ORM, Migrationen, Uploads und serverseitige UI schon sauber in den Produktfluss passen. Die Trennung von Webprozess und FreeCAD-Worker in Docker Compose ist ebenfalls die richtige Richtung.

Fuer produktiven Betrieb reicht Basic Auth vor der Anwendung aus meiner Sicht nicht als Haupt-Authentifizierung. Sie kann als zusaetzliche aeussere Schranke vor einem internen Dienst sinnvoll sein, aber die Anwendung braucht weiterhin echte Benutzeridentitaeten, Rollen und auditierbare Aktionen. Besonders die FreeCAD-Addon-API sollte vor produktiver Nutzung von sessionbasierter, CSRF-befreiter Authentifizierung auf Token oder Personal Access Tokens umgestellt werden.

## Bereits vorbereiteter Patch

In diesem Audit-Lauf wurden kleine Produktions-Haertungen vorbereitet und angewendet:

- `freecad_plm/settings.py`: ENV-Helfer fuer bool/int Settings, Fail-Fast wenn `DJANGO_DEBUG=0` mit dem bekannten Dev-Secret-Key startet, konfigurierbare HTTPS-/Cookie-Settings.
- `.env.example`: explizite Security-Schalter fuer Cookie-Secure, HSTS und SSL-Redirect.
- `README.md`: Server-Beispiel um dieselben Schalter erweitert.

Verifikation:

- `.venv/bin/python manage.py check`: OK
- Deployment-Check mit gesetztem Secret/Hosts/Cookie-Secure: nur noch bewusste HTTPS-/HSTS-Entscheidungen offen
- Deployment-Check mit aktiviertem SSL-Redirect und HSTS: nur noch HSTS-Subdomain/Preload-Warnungen offen
- `.venv/bin/python manage.py test plm`: 109 Tests OK

## Befunde

### Erledigt: Addon-API ist nicht mehr sessionbasiert

Urspruengliche Evidenz: Mehrere mutierende API-Endpunkte waren mit `@csrf_exempt` und `@login_required` kombiniert, z.B. `projects_api`, `project_api`, `project_parts_api`, `part_api`, `revision_checkout_api`, `checkout_cancel_api`, `checkout_checkin_api`, `part_annotations_api` und `annotation_api` in `plm/api.py`.

Status 2026-07-06: `/api/` ist auf Bearer-Token-only umgestellt. Django-Browser-Sessions reichen fuer API-Zugriff nicht mehr aus. Mutierende API-Endpunkte bleiben CSRF-befreit, akzeptieren aber nur gueltige API-Tokens mit passendem Scope.

Umgesetzt:

- Token nur gehasht speichern.
- Token an Django-User binden.
- Scopes mindestens `read`, `write`, `checkout`, `admin`.
- Letzte Nutzung, Ablaufdatum und Widerruf speichern.
- API per `Authorization: Bearer ...` authentifizieren.
- Tests fuer fehlenden Token, Browser-Session ohne Token, falschen Token, fehlenden Scope, abgelaufenen Token und widerrufenen Token.

### Hoch: Basic Auth sollte nur aeussere Zusatzbarriere sein

Evidenz: Das Repo hat bereits ein internes Rollenmodell (`reader`, `editor`, `admin`) und schreibt AuditEvents fuer relevante Aktionen. Downloads, Uploads, Freigaben und Jobs verwenden Django-Identitaeten.

Risiko: Basic Auth vor Django kennt keine PLM-Rollen und erzeugt keine fachlich verwertbare Identitaet im Audit-Trail. Wenn mehrere Personen denselben Basic-Auth-Login nutzen, sind Downloads, Checkouts, Check-ins und Freigaben nicht personenbezogen nachvollziehbar.

Empfehlung: Django-Auth als fuehrende Authentifizierung behalten. Basic Auth kann davor bleiben, wenn du den Dienst zusaetzlich gegen versehentliche Exposition schuetzen willst. Fuer produktive Nutzung pro Person einen Django-Account verwenden.

### Mittel: Upload- und ZIP-Verarbeitung hat noch kein Ressourcenbudget

Evidenz: `validate_fcstd_upload()` liest komplette Uploads in den Speicher und oeffnet danach das ZIP. `fcstd_with_plm_revision()` liest beim Normalisieren alle ZIP-Member. `iter_fcstd_zip_members()` liest Projekt-ZIP und jedes passende `.FCStd`-Member komplett.

Risiko: Grosse Dateien, viele ZIP-Member oder stark komprimierte Inhalte koennen Speicher/CPU belasten. Das ist im LAN weniger dramatisch als oeffentlich, aber produktiv trotzdem ein DoS-Risiko.

Empfehlung:

- Django `DATA_UPLOAD_MAX_MEMORY_SIZE` und `FILE_UPLOAD_MAX_MEMORY_SIZE` setzen.
- App-eigene Limits fuer FCStd, Projekt-ZIP, 3MF, einzelne ZIP-Member und entpackte Gesamtsumme einfuehren.
- ZIP-Infos vor `archive.read()` gegen `file_size`, Member-Anzahl und Gesamtbudget pruefen.
- Fehler als saubere `ValidationError` melden.

### Mittel: FreeCADCmd verarbeitet nicht vertrauenswuerdige CAD-Dateien im App-Kontext

Evidenz: Jobs starten FreeCADCmd per `subprocess.run()` mit Timeout, temporaerem Arbeitsordner und ohne Shell. Das ist gut. Web und Worker teilen aber das Media-Volume; der Worker hat Zugriff auf alle gespeicherten CAD-Dateien und Artefakte.

Risiko: CAD-Dateien sind komplexe Eingaben fuer FreeCAD. Falls FreeCAD oder ein Importer abstuerzt oder ausgenutzt wird, laeuft der Prozess im Containerkontext mit Zugriff auf das Medienvolume.

Empfehlung:

- Worker als eigener Container ohne eingehenden Port beibehalten.
- Webcontainer ohne FreeCAD bauen, sobald Worker im Serverbetrieb verpflichtend ist.
- Worker-Container mit `read_only`, `cap_drop`, `security_opt`, CPU-/Memory-Limits und eigenem Temp-Volume haerten.
- FreeCADCmd-Ausgabe und Artefaktgroessen begrenzen.

### Mittel: Produktions-HTTPS ist vorbereitet, aber Betriebsentscheidung bleibt offen

Evidenz: Settings nutzen `SECURE_PROXY_SSL_HEADER` und `USE_X_FORWARDED_HOST`. Nach Patch sind Cookie-Secure, SSL-Redirect und HSTS per ENV schaltbar.

Risiko: Wenn der Dienst ueber HTTP erreichbar bleibt, koennen Session-Cookies und CSRF-Cookies je nach Proxy-/Cookie-Konfiguration riskanter werden. HSTS sollte nur gesetzt werden, wenn HTTPS dauerhaft korrekt ist.

Empfehlung:

- Reverse Proxy soll HTTP auf HTTPS umleiten.
- `DJANGO_SESSION_COOKIE_SECURE=1` und `DJANGO_CSRF_COOKIE_SECURE=1` produktiv setzen.
- `DJANGO_SECURE_SSL_REDIRECT=1` nur setzen, wenn `X-Forwarded-Proto` korrekt an Django uebergeben wird.
- HSTS erst nach erfolgreichem HTTPS-Test aktivieren, z.B. spaeter `DJANGO_SECURE_HSTS_SECONDS=31536000`.

### Mittel: Autorisierung ist rollenbasiert, aber nicht objektbezogen

Evidenz: Login-Nutzer koennen Projekt-, Teil-, Revision- und Download-Ansichten generell sehen. Mutationen werden ueber `admin`/`editor`/`reader` getrennt.

Risiko: Fuer ein kleines LAN-Team ist das passend. Sobald externe Nutzer, Kundenprojekte oder getrennte Teams dazukommen, fehlt projektbezogene Zugriffskontrolle.

Empfehlung: Fuer V1 akzeptabel lassen. Erst erweitern, wenn mehrere Mandanten/Projektgruppen wirklich gebraucht werden.

### Niedrig: Deployment-Artefakte sind grundsaetzlich sauber

Evidenz: `.dockerignore` schliesst `.git/`, `.venv/`, `db.sqlite3`, `storage/`, `staticfiles/`, `test-model/` und `old/` aus. Compose verlangt Secret, Allowed Hosts und Postgres-Passwort per `.env`. Web und Worker laufen im Image-Compose als User `plm`.

Risiko: Das Dockerfile installiert FreeCAD im Standardimage und laesst Build-Abhaengigkeiten im Runtime-Image. Das ist eher Angriffsoberflaeche und Image-Groesse als akuter Fehler.

Empfehlung: Spaeter Multi-Stage oder getrennte Web-/Worker-Images pruefen: schlankes Webimage ohne FreeCAD, Workerimage mit FreeCAD.

## Auth-Entscheidung

Empfohlene Entscheidung:

1. Django-Login und Rollen bleiben fuehrend.
2. Basic Auth darf davor, aber nur als zweite Tuer, nicht als fachliche Auth.
3. Vor produktiver FreeCAD-Addon-Nutzung Token-Auth einbauen.
4. Keine gemeinsamen Benutzer fuer produktive Arbeit verwenden, weil sonst Audit und Checkout-Verantwortung unscharf werden.

Minimal produktiv im Heim-/LAN-Kontext:

- HTTPS-Reverse-Proxy
- Basic Auth optional davor
- Django-Accounts pro Person
- `reader`, `editor`, `admin` sauber vergeben
- API nur mit Bearer Token nutzen

Besserer produktiver Zielzustand:

- HTTPS-Reverse-Proxy
- Django-Accounts pro Person
- Personal Access Tokens fuer Addon/API
- Session-API ist deaktiviert; mutierende API-Zugriffe laufen ueber Bearer Token
- Worker gehaertet und ressourcenbegrenzt
- Upload-/ZIP-Limits
- Backup-/Restore getestet

## Naechste konkrete Patches

### 1. API-Token-Modell

- `ApiToken` mit gehashtem Token, Prefix, Name, User, Scopes, `last_used_at`, `expires_at`, `revoked_at`.
- Auth-Helfer fuer `Authorization: Bearer`.
- Tests: kein Token -> 401, falscher Token -> 401, `read` darf GET, `write` darf mutieren, widerrufen/abgelaufen blockiert.
- Status 2026-07-06: umgesetzt. `/api/` ist token-only; Session-Auth ist fuer API-Zugriffe entfernt.

### 2. CSRF-Strategie fuer API

- Status 2026-07-06: erledigt durch token-only API.
- Browser-Sessions werden von `/api/` nicht mehr akzeptiert.
- Mutierende API-Endpunkte bleiben CSRF-befreit, weil sie nicht mit Browser-Session-Cookies authentifizieren.

### 3. Upload-/ZIP-Budgets

- Settings: `PLM_MAX_FCSTD_UPLOAD_BYTES`, `PLM_MAX_PROJECT_ZIP_BYTES`, `PLM_MAX_ZIP_MEMBERS`, `PLM_MAX_ZIP_UNCOMPRESSED_BYTES`, `PLM_MAX_ZIP_MEMBER_BYTES`.
- Pruefung in `fcstd.py` und `services.py`.
- Tests fuer zu grosse Datei, zu viele ZIP-Member, zu grosse entpackte Summe.

### 4. Worker-Haertung

- Compose-Optionen fuer Worker: `cap_drop`, `security_opt`, `read_only`, `tmpfs`, Memory-/CPU-Limits.
- Webimage spaeter ohne FreeCAD bauen oder `INSTALL_FREECAD=0` fuer Web nutzen.

### 5. Betriebscheckliste

- `planning/PRODUCTION_CHECKLIST.md` mit ENV, Proxy, User/Rollen, Backup, Restore, Updates, Worker und Rollback.

## Referenzen Im Code

- Settings-Haertung: `freecad_plm/settings.py`
- API-CSRF-/Session-Thema: `plm/api.py`
- FCStd-Upload/ZIP-Verarbeitung: `plm/fcstd.py`
- Projekt-ZIP-Import: `plm/services.py`
- FreeCADCmd-Worker: `plm/freecadcmd.py`
- Docker-Kontext: `Dockerfile`, `docker-compose.image.yml`, `.dockerignore`
