#!/bin/bash
# Project-specific logical backup. Never touches other projects or deletes backups.
set -euo pipefail
umask 077
base=/srv/jardines-del-encanto
[[ -f $base/current ]] || exit 0
export RELEASE
RELEASE=$(cat "$base/current")
[[ $RELEASE =~ ^[0-9a-f]{40}$ ]] || exit 2
stamp="$(date -u +%Y%m%dT%H%M%S)-$$"
file="$base/backups/$stamp.sql.gz"
trap 'rm -f "$file.partial"' EXIT
docker compose -p jardines -f "$base/compose.yaml" exec -T db \
  pg_dump -U jardines -d jardines --no-owner --no-acl | gzip > "$file.partial"
gzip -t "$file.partial"
mv "$file.partial" "$file"
sha256sum "$file" > "$file.sha256"
echo "Backup created: $(basename "$file")"
# The dedicated CRM database is additive; do not inspect or back up sibling projects.
crm_exists=$(docker compose -p jardines -f "$base/compose.yaml" exec -T db \
  psql -X -U jardines -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname='jardines_crm'")
if [[ $crm_exists == 1 ]]; then
  file="$base/backups/$stamp.crm.sql.gz"
  docker compose -p jardines -f "$base/compose.yaml" exec -T db \
    pg_dump -U jardines -d jardines_crm --no-owner --no-acl | gzip > "$file.partial"
  gzip -t "$file.partial"
  mv "$file.partial" "$file"
  sha256sum "$file" > "$file.sha256"
  echo "CRM backup created: $(basename "$file")"
fi
