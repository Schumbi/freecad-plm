# FreeCAD-PLM

Ein neues Django-basiertes PLM/PDM fuer FreeCAD-Dateien.

## Lokal starten

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Die Admin-Oberflaeche liegt unter <http://127.0.0.1:8000/admin/>.

Projektstand und naechste Schritte stehen in `planning/`.
