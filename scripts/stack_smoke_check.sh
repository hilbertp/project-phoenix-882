#!/usr/bin/env sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMPOSE_FILE="$REPO_ROOT/infra/docker/docker-compose.yml"

cd "$REPO_ROOT"
services=$(docker compose -f "$COMPOSE_FILE" ps --status running --services)

for service in api worker postgres; do
  if ! printf '%s\n' "$services" | grep -Fx "$service" >/dev/null 2>&1; then
    printf 'Expected running service missing: %s\n' "$service" >&2
    exit 1
  fi
done

printf 'Local stack smoke check passed: api, worker, and postgres are running.\n'
