# Deployment

Aufruf: `python deployment/deploy.py`.

Der saubere, bereits committete Branch main oder master wird nach origin gepusht. Das Skript wartet bis zu 60 Minuten auf beide getesteten Forgejo-Images mit Commit-SHA und erstellt auf jellyfin.schumbi.de ein geprüftes konsistentes Datenbank- und Storage-Backup. Danach startet es Web und Worker neu und prüft deren Zustand. SSH- und Docker-Zugriff, genügend Speicher und eine kurze Unterbrechung sind erforderlich. Die bestehende Compose-Datei auf dem Server wird weiterverwendet; Änderungen an der lokalen Compose-Datei werden nicht übertragen. Die Wartezeit ist mit `--build-timeout-minutes 90` einstellbar.

Bei einem Fehler stellt das Skript die vorherigen Image-Tags wieder her und startet Web und Worker erneut. Falls auch dieser Wiederanlauf scheitert, bleibt die gesicherte `.env` auf dem Server erhalten und der Fehler wird gemeldet. Datenbankmigrationen werden nicht automatisch zurückgesetzt; bei einer nicht rückwärtskompatiblen Migration kann ein Restore nötig sein. Backup und Meldungen prüfen. Der Worker wird mit Django-Systemcheck und `freecadcmd --version` geprüft; Restore-Test sowie echte Export- und Downloadprüfungen aus `planning/PRODUCTION_CHECKLIST.md` sind manuell auszuführen.

