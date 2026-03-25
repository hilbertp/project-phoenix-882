#!/usr/bin/env sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMPOSE_FILE="$REPO_ROOT/infra/docker/docker-compose.yml"

cd "$REPO_ROOT"
docker compose -f "$COMPOSE_FILE" up -d
