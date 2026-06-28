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

Die Admin-Oberflaeche liegt unter <http://127.0.0.1:8000/admin/>.
Die PLM-Oberflaeche startet unter <http://127.0.0.1:8000/>.

## Serverbetrieb Mit Docker Compose

Der erste Serverpfad nutzt Docker Compose mit PostgreSQL, persistentem Media-Volume und separatem Worker:

```bash
docker compose up --build
```

Vor produktiver Nutzung muessen mindestens `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` und die PostgreSQL-Passwoerter in `docker-compose.yml` angepasst werden. Der Worker wird mit FreeCAD im Image gebaut und verarbeitet Exportjobs in einer Schleife. Fuer PNG/GUI-nahe Jobs nutzt er standardmaessig `xvfb-run -a FreeCADCmd`.

## Rollen

Die V1-Rollen werden als Django-Gruppen angelegt:

```bash
.venv/bin/python manage.py setup_plm_roles
```

- `reader`: ansehen und herunterladen
- `editor`: ansehen, herunterladen und Revisionen hochladen
- `admin`: volle PLM-Verwaltung

## Kurzworkflow

1. Projekt als `admin`/Superuser in der PLM-Oberflaeche anlegen oder vorhandenes Projekt oeffnen.
2. Teil oder Baugruppe im Projekt mit initialer `.FCStd`-Datei anlegen.
3. FreeCAD-Metadaten pruefen. Teilenummer und Name koennen leer bleiben; dann nutzt das PLM FreeCAD-`Id`/`Label` oder automatisch `P-001`, `P-002`, ...
4. Neue Revisionen werden automatisch kanonisch als `R0001`, `R0002`, ... vergeben; alte oder testweise abweichende Codes werden bei der naechsten Nummer ignoriert.
5. Beim Hochladen einer neuen Revision fehlende oder abweichende FreeCAD-Property `PLMRevision` verwerfen oder als PLM-normalisierte Kopie speichern.
6. Optional Anmerkungen ergaenzen.
7. Optional Revision freigeben.

## Projektstaende

FreeCAD-Projekte mit mehreren referenzierten `.FCStd`-Dateien koennen als ZIP importiert werden. Das PLM legt einen Projektstand an und speichert, welche Revisionen unter welchen relativen Pfaden zusammengehoeren. Der Projektstand kann wieder als ZIP heruntergeladen werden.

Der normale Download einer Revision liefert eine einzelne `.FCStd` nur dann, wenn sie keine FreeCAD-Referenzen enthaelt. Hat eine Datei Referenzen, liefert der Download automatisch ein ZIP mit der Datei und ihren rekursiv referenzierten Dateien aus demselben Projektstand.

Projektstand und naechste Schritte stehen in `planning/`.

## FreeCAD-Addon-API

Das PLM stellt erste JSON-Endpunkte unter `/api/` bereit. Sie sind fuer ein vanilla-FreeCAD-Addon gedacht und nutzen zunaechst die bestehende Django-Anmeldung:

- `GET/POST /api/projects/`
- `GET/POST /api/projects/<id>/`
- `GET/POST /api/projects/<id>/parts/`
- `GET/POST /api/parts/<id>/`
- `GET /api/revisions/<id>/`
- `GET /api/revisions/<id>/file/`
- `POST /api/revisions/<id>/checkout/`
- `GET /api/checkouts/<id>/manifest/`
- `POST /api/checkouts/<id>/checkin/`
- `POST /api/checkouts/<id>/cancel/`
- `GET/POST /api/parts/<id>/annotations/`

Checkout ist exklusiv pro Teil/Baugruppe. Das Checkout-Manifest enthaelt Root-Datei, referenzierte Revisionen, relative Pfade, Hashes und Download-URLs. Der Check-in erzeugt immer eine neue unveraenderliche Revision.

## FreeCADCmd

Exportjobs werden mit `FREECADCMD_COMMAND` ausgefuehrt. Ohne eigene Einstellung versucht das PLM zuerst `FreeCADCmd` und faellt auf die Flatpak-Installation `org.freecad.FreeCAD` mit `--command=FreeCADCmd` und `/tmp`-Freigabe zurueck, wenn `flatpak` vorhanden ist. PNG-Jobs nutzen bei Flatpak automatisch den GUI-Binary `FreeCAD`, weil dafuer ein FreeCADGui-Viewport gebraucht wird.

Beispiel fuer eine explizite Flatpak-Konfiguration:

```bash
FREECADCMD_COMMAND='flatpak run --filesystem=/tmp --branch=stable --arch=x86_64 --command=FreeCADCmd org.freecad.FreeCAD' .venv/bin/python manage.py process_export_jobs
```

PNG-Ansichten brauchen ein funktionierendes GUI-/Display-Setup. Der Button `PNG-Ansichten` erzeugt die Bilder im lokalen Prototyp direkt waehrend der Anfrage. Auf einem Server ohne Desktop sollte dieser Pfad spaeter unter `xvfb-run` oder in einen separaten Preview-Worker wandern.

Wartende Analyse- und Exportjobs koennen auf der Teildetailseite mit `Wartende Jobs starten` einmalig verarbeitet werden.

Auf einem Server mit nativer FreeCAD-Installation reicht meistens:

```bash
FREECADCMD_COMMAND=/usr/bin/FreeCADCmd .venv/bin/python manage.py process_export_jobs
```
