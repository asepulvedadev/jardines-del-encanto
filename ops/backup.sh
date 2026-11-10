#!/bin/bash
# Project-specific logical backup. Never touches other projects or deletes backups.
set -euo pipefail
umask 077
base=/srv/jardines-del-encanto
[[ -f $base/current ]] || exit 0
export RELEASE
RELEASE=$(cat "$base/current")
[[ $RELEASE =~ ^[0-9a-f]{40}$ ]] || exit 2
file="$base/backups/$(date -u +%Y%m%dT%H%M%S)-$$.sql.gz"
trap 'rm -f "$file.partial"' EXIT
docker compose -p jardines -f "$base/compose.yaml" exec -T db \
  pg_dump -U jardines -d jardines --no-owner --no-acl | gzip > "$file.partial"
gzip -t "$file.partial"
mv "$file.partial" "$file"
sha256sum "$file" > "$file.sha256"
echo "Backup created: $(basename "$file")"
