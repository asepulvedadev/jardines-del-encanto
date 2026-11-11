#!/bin/sh
# Administrator-only, stdin prompt; no gateway or background agent is started.
set -eu
policy=/srv/jardines-del-encanto/hermes-active.compose.yaml
if [ "$(id -u)" != 0 ]; then
  echo "Run as the authorized project administrator." >&2
  exit 1
fi
docker compose -f "$policy" up -d --wait provider >&2
exec timeout 150 docker compose -f "$policy" run --rm -T --no-deps hermes
