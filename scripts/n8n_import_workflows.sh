#!/usr/bin/env bash
# Импортирует все JSON-воркфлоу из n8n/workflows/ в запущенный контейнер n8n.
# Использование: scripts/n8n_import_workflows.sh

source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

cd "$REPO_ROOT"

SERVICE="n8n"
CONTAINER="$(docker compose ps -q "$SERVICE" || true)"
if [[ -z "$CONTAINER" ]]; then
  echo "error: контейнер сервиса '$SERVICE' не запущен. Сначала 'docker compose up -d'" >&2
  exit 1
fi

echo "[n8n] container id: $CONTAINER"
echo "[n8n] copying n8n/workflows/ → container:/tmp/wfimport"
docker cp n8n/workflows "$CONTAINER:/tmp/wfimport"

echo "[n8n] n8n import:workflow --separate --input=/tmp/wfimport"
docker exec "$CONTAINER" n8n import:workflow --separate --input=/tmp/wfimport

echo "[n8n] cleanup: rm -rf /tmp/wfimport"
docker exec "$CONTAINER" rm -rf /tmp/wfimport

echo "[n8n] done. Открой UI и проверь, что credentials подхватились и nested 'Execute Workflow' ноды резолвят по ID."
