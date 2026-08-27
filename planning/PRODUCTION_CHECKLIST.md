# Produktionscheckliste

## Zweck

Diese Checkliste beschreibt den kleinsten reproduzierbaren Ablauf für Update,
Zustandsprüfung, konsistentes Backup und Restore-Test einer Image-basierten
FreeCAD-PLM-Installation. Sie gilt für `docker-compose.image.yml` mit lokalem
`storage/` und PostgreSQL-Volume. Zugangsdaten bleiben ausschließlich in
`.env`; sie gehören weder in Backupdateinamen noch in Protokolle.

## Vor einem Update

- Aktuellen Server-Commit und die vorgesehenen Web-/Worker-Image-Tags notieren.
  Für eine Freigabe nach Möglichkeit die Tags mit vollständiger Commit-SHA
  statt `latest` verwenden.
- Freien Platz für PostgreSQL-Dump und vollständiges `storage/`-Archiv prüfen.
- Sicherstellen, dass das Backupziel nicht innerhalb von `storage/` liegt.
- Wartungsfenster ankündigen: Für einen konsistenten Stand werden Web und Worker
  während des Backups gestoppt; PostgreSQL bleibt erreichbar.

## Konsistentes Backup

Einen neuen, ausdrücklich aufgelösten Zielordner verwenden, zum Beispiel:

```bash
PLM_BACKUP_DIR=/srv/backups/freecad-plm/2026-08-27T1400
install -d -m 0700 "$PLM_BACKUP_DIR"
docker compose -f docker-compose.image.yml stop web worker
docker compose -f docker-compose.image.yml exec -T db \
  sh -c 'pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom' \
  > "$PLM_BACKUP_DIR/postgres.dump"
tar -czf "$PLM_BACKUP_DIR/storage.tar.gz" storage
sha256sum "$PLM_BACKUP_DIR/postgres.dump" \
  "$PLM_BACKUP_DIR/storage.tar.gz" > "$PLM_BACKUP_DIR/SHA256SUMS"
docker compose -f docker-compose.image.yml up -d
```

`staticfiles/` muss nicht gesichert werden; `collectstatic` erzeugt den Inhalt
beim Webstart neu. `.env` separat verschlüsselt sichern und nie zusammen mit
allgemein lesbaren CAD-Backups ablegen.

## Backup prüfen

```bash
sha256sum -c "$PLM_BACKUP_DIR/SHA256SUMS"
docker compose -f docker-compose.image.yml exec -T db pg_restore --list \
  < "$PLM_BACKUP_DIR/postgres.dump"
tar -tzf "$PLM_BACKUP_DIR/storage.tar.gz"
```

Mindestens Dateigrößen, SHA-256, Anzahl der Storage-Dateien, PostgreSQL-Version
und Zeitpunkt protokollieren. Ein Backup gilt erst nach einem Restore-Test als
nachgewiesen.

## Restore-Test ohne Produktionsdaten zu ersetzen

Der Test nutzt eine eindeutig benannte, vorher nachweislich nicht vorhandene
Datenbank. Vor `dropdb` nochmals den exakten Namen prüfen; gelöscht wird nur die
für diesen Test neu angelegte Datenbank.

```bash
docker compose -f docker-compose.image.yml exec -T db \
  sh -c 'createdb --username "$POSTGRES_USER" freecad_plm_restore_check_20260827'
docker compose -f docker-compose.image.yml exec -T db \
  sh -c 'pg_restore --username "$POSTGRES_USER" --dbname freecad_plm_restore_check_20260827 --no-owner --no-privileges' \
  < "$PLM_BACKUP_DIR/postgres.dump"
docker compose -f docker-compose.image.yml exec -T db \
  sh -c 'psql --username "$POSTGRES_USER" --dbname freecad_plm_restore_check_20260827 --command "SELECT count(*) AS projects FROM plm_project; SELECT count(*) AS revisions FROM plm_revision;"'
docker compose -f docker-compose.image.yml exec -T db \
  sh -c 'dropdb --username "$POSTGRES_USER" freecad_plm_restore_check_20260827'
```

Für einen echten Restore der Produktionsdaten ist ein eigenes Wartungsfenster
mit zusätzlichem Vorher-Backup erforderlich. Produktionsdatenbank und
`storage/` müssen aus demselben Sicherungslauf stammen.

## Update und Betriebsprüfung

```bash
docker compose -f docker-compose.image.yml pull
docker compose -f docker-compose.image.yml up -d
docker compose -f docker-compose.image.yml ps
docker compose -f docker-compose.image.yml logs --tail=200 web worker db
curl -fsSL -o /dev/null http://127.0.0.1:8000/
```

Abzuhaken sind:

- PostgreSQL `healthy`, Web `healthy`, Worker `Up`.
- Alle Migrationen angewendet; keine fehlenden Migrationen.
- Webseite vollständig geladen, einschließlich Redirect zur Login-Seite.
- Worker erst nach gesundem Webdienst gestartet; keine Tracebacks im aktuellen
  Startlog.
- Echter FCStd-Analysejob sowie STEP-, STL-, 3MF- und PNG-Ableitung erfolgreich.
- Frisch erzeugte Artefakte herunterladbar und nicht leer.
- Backup- und Restore-Nachweis mit Pfad, Datum und Prüfer dokumentiert.

## Aufbewahrung

- Mehrere Generationen außerhalb des PLM-Hosts aufbewahren.
- Regelmäßig einen Restore aus einer älteren Generation testen.
- Löschung abgelaufener Generationen nur anhand eines ausdrücklich
  aufgelösten Backup-Pfads durchführen; niemals mit einem breiten Pfad oder
  einer ungeprüften Variablen.
