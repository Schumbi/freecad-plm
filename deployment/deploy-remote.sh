#!/usr/bin/env bash
set -Eeuo pipefail
sha=$1; minutes=$2
[[ $sha =~ ^[0-9a-f]{40}$ && $minutes =~ ^[0-9]+$ ]] || exit 1
cd /opt/freecad-plm
compose=(docker compose -f docker-compose.image.yml)
web="git.home.schumbi.de/ralf/freecad-plm-web:$sha"
worker="git.home.schumbi.de/ralf/freecad-plm-worker:$sha"
deadline=$((SECONDS + minutes * 60))
until docker pull "$web" && docker pull "$worker"; do
  (( SECONDS < deadline )) || { echo 'Images nicht verfügbar; Build prüfen.' >&2; exit 1; }
  sleep 30
done
backup="/opt/freecad-plm/backups/deploy-$(date +%Y%m%d-%H%M%S)-${sha:0:12}"
mkdir -m 700 "$backup"
storage_bytes=$(du -sb storage | cut -f1)
db_bytes=$("${compose[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT pg_database_size(current_database())"' | tr -d '\r')
free_bytes=$(df -PB1 "$backup" | awk 'NR==2 {print $4}')
(( free_bytes > storage_bytes + db_bytes + 1073741824 )) || { echo 'Nicht genügend Backup-Speicher.' >&2; exit 1; }
env_snapshot=$(mktemp .env.rollback.XXXXXXXX)
chmod 600 "$env_snapshot"
cp -p .env "$env_snapshot"
rollback() {
  status=$?
  trap - EXIT
  if (( status != 0 )); then
    echo 'Deployment fehlgeschlagen; alte Image-Tags und Dienste werden wiederhergestellt.' >&2
    if cp -p "$env_snapshot" .env && "${compose[@]}" up -d --force-recreate web worker; then
      rm -f "$env_snapshot"
    else
      echo "Automatischer Wiederanlauf fehlgeschlagen. Gesicherte Konfiguration: $PWD/$env_snapshot" >&2
    fi
  else
    rm -f "$env_snapshot"
  fi
  exit "$status"
}
trap rollback EXIT
"${compose[@]}" stop web worker
"${compose[@]}" exec -T db sh -c 'pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom' > "$backup/postgres.dump"
tar -czf "$backup/storage.tar.gz" storage
(cd "$backup" && sha256sum postgres.dump storage.tar.gz > SHA256SUMS && sha256sum -c SHA256SUMS && tar -tzf storage.tar.gz >/dev/null)
"${compose[@]}" exec -T db pg_restore --list < "$backup/postgres.dump" >/dev/null
python3 - "$sha" <<'PY'
import os, pathlib, re, sys, tempfile
p = pathlib.Path('.env')
s = p.read_text()
for name, image in [('PLM_WEB_IMAGE', 'freecad-plm-web'), ('PLM_WORKER_IMAGE', 'freecad-plm-worker')]:
    s, count = re.subn(r'^' + name + r'=.*$', name + '=git.home.schumbi.de/ralf/' + image + ':' + sys.argv[1], s, flags=re.M)
    if count != 1: raise SystemExit(name + ' muss genau einmal in .env stehen')
fd, tmp = tempfile.mkstemp(dir='.', prefix='.env.deploy-')
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as f: f.write(s)
    os.replace(tmp, p)
finally:
    if os.path.exists(tmp): os.unlink(tmp)
PY
"${compose[@]}" up -d
for i in {1..60}; do
  w=$("${compose[@]}" ps -q web); d=$("${compose[@]}" ps -q db); x=$("${compose[@]}" ps -q worker)
  if [[ -n $w && -n $d && -n $x ]] && [[ $(docker inspect -f '{{.State.Health.Status}}' "$w") == healthy && $(docker inspect -f '{{.State.Health.Status}}' "$d") == healthy && $(docker inspect -f '{{.State.Status}}' "$x") == running ]]; then break; fi
  (( i < 60 )) || { echo 'Dienste nicht gesund.' >&2; exit 1; }
  sleep 5
done
"${compose[@]}" exec -T web python manage.py check
"${compose[@]}" exec -T web python manage.py migrate --check
"${compose[@]}" exec -T worker python manage.py check
"${compose[@]}" exec -T worker freecadcmd --version
"${compose[@]}" exec -T web python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/", timeout=10)'
"${compose[@]}" ps
echo "Deployment $sha abgeschlossen. Backup: $backup"
