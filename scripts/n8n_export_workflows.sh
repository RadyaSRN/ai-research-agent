#!/usr/bin/env bash
# Экспортирует все воркфлоу из n8n Public API в n8n/workflows/<slug>.json
# (flat-layout: JSON и hand-maintained .md лежат рядом). Перед использованием —
# закоммитить текущее состояние, чтобы потом было что diff'ать.
#
# Требует N8N_API_KEY в .env (Settings → API → Create API key в UI n8n).
#
# Публичный аналог .agent-memory/refresh.sh (который остаётся приватным кэшем
# агента). .md-файлы с описаниями не трогает — только *.json.

source "$(cd "$(dirname "$0")" && pwd)/_common.sh"

: "${N8N_API_KEY:?N8N_API_KEY not set in .env (Settings → API → Create API key)}"
: "${N8N_HOST:?N8N_HOST not set in .env}"

TARGET_DIR="$REPO_ROOT/n8n/workflows"
export TARGET_DIR API="https://${N8N_HOST}/api/v1" N8N_API_KEY

python3 - <<'PY'
import json
import os
import pathlib
import re
import urllib.request

TARGET = pathlib.Path(os.environ["TARGET_DIR"])
API = os.environ["API"]
KEY = os.environ["N8N_API_KEY"]
HEADERS = {"X-N8N-API-KEY": KEY, "Accept": "application/json"}


def http_get(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "unnamed"


TARGET.mkdir(parents=True, exist_ok=True)
for f in TARGET.glob("*.json"):
    f.unlink()

listing = http_get(f"{API}/workflows?limit=250")["data"]
count = 0
for w in sorted(listing, key=lambda x: x["name"].lower()):
    full = http_get(f"{API}/workflows/{w['id']}")
    slug = slugify(w["name"])
    (TARGET / f"{slug}.json").write_text(
        json.dumps(full, indent=2, ensure_ascii=False)
    )
    count += 1

print(f"[n8n-export] refreshed {count} workflows in {TARGET}")
PY

echo "[n8n-export] готово. Прогони 'git diff n8n/workflows/' и закоммить только релевантные изменения."
echo "[n8n-export] Hand-maintained .md-описания и README.md не тронуты."
