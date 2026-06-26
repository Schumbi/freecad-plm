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

1. Projekt im Admin oder in vorhandenen Daten oeffnen.
2. Teil oder Baugruppe im Projekt mit initialer `.FCStd`-Datei anlegen.
3. FreeCAD-Metadaten pruefen. Teilenummer und Name koennen leer bleiben; dann nutzt das PLM FreeCAD-`Id`/`Label` oder automatisch `P-001`, `P-002`, ...
5. Optional Anmerkungen ergaenzen.
6. Optional Revision freigeben.

## Projektstaende

FreeCAD-Projekte mit mehreren referenzierten `.FCStd`-Dateien koennen als ZIP importiert werden. Das PLM legt einen Projektstand an und speichert, welche Revisionen unter welchen relativen Pfaden zusammengehoeren. Der Projektstand kann wieder als ZIP heruntergeladen werden.

Einzelne Dateien aus einem Projektstand koennen ebenfalls als ZIP mit Referenzen heruntergeladen werden. Bei einer Baugruppe wie `Druck.FCStd` nimmt das PLM die referenzierten Dateien aus demselben Projektstand mit, inklusive transitiver Referenzen wie Parameterdateien.

Projektstand und naechste Schritte stehen in `planning/`.
