#!/usr/bin/env bash
# Общий bootstrap для shell-скриптов в scripts/:
# - находит корень репо (..)
# - подгружает переменные из .env в окружение
# Подключается через `source "$(dirname "$0")/_common.sh"`.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPTS_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: $ENV_FILE not found (скопируй .env.example → .env и заполни)" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

export REPO_ROOT SCRIPTS_DIR
