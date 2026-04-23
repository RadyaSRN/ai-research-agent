#!/usr/bin/env bash
# Накатывает postgres/schema.sql в БД `app` запущенного контейнера postgres.
# Использование: scripts/db_apply_schema.sh

source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

: "${POSTGRES_USER:?POSTGRES_USER not set in .env}"

SCHEMA="$REPO_ROOT/postgres/schema.sql"
if [[ ! -f "$SCHEMA" ]]; then
  echo "error: $SCHEMA not found" >&2
  exit 1
fi

echo "[db] applying $SCHEMA to database 'app' as user '$POSTGRES_USER'"
docker compose -f "$REPO_ROOT/docker-compose.yml" exec -T postgres \
  psql -U "$POSTGRES_USER" -d app < "$SCHEMA"
echo "[db] done"
