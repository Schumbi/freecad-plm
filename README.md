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

## FreeCADCmd

Exportjobs werden mit `FREECADCMD_COMMAND` ausgefuehrt. Ohne eigene Einstellung versucht das PLM zuerst `FreeCADCmd` und faellt auf die Flatpak-Installation `org.freecad.FreeCAD` mit `--command=FreeCADCmd` zurueck, wenn `flatpak` vorhanden ist.

Beispiel fuer eine explizite Flatpak-Konfiguration:

```bash
FREECADCMD_COMMAND='flatpak run --branch=stable --arch=x86_64 --command=FreeCADCmd org.freecad.FreeCAD' .venv/bin/python manage.py process_export_jobs
```

Auf einem Server mit nativer FreeCAD-Installation reicht meistens:

```bash
FREECADCMD_COMMAND=/usr/bin/FreeCADCmd .venv/bin/python manage.py process_export_jobs
```
