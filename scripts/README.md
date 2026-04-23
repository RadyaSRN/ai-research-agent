# scripts/

Публичные утилиты для разворачивания и сопровождения проекта. Все скрипты:

- Читают корневой `.env` (паттерн `scripts/_common.sh`).
- Работают относительно корня репозитория (можно вызывать из любой рабочей директории).

## Shell-утилиты

| Скрипт                              | Что делает                                                                 |
|---|---|
| `db_apply_schema.sh`                | Прогоняет `postgres/schema.sql` через `docker compose exec postgres psql` в БД `app`. |
| `n8n_import_workflows.sh`           | Копирует `n8n/workflows/` в контейнер n8n и вызывает `n8n import:workflow --separate`. |
| `n8n_export_workflows.sh`           | Выгружает все воркфлоу через n8n Public API в `n8n/workflows/<slug>.json`. Требует `N8N_API_KEY` в `.env`. Не трогает `*.md`. |

## Python-утилиты

| Скрипт               | Что делает                                                                      |
|---|---|
| `prompts_sync.py`    | Синхронизация `prompts/*.md` (YAML-frontmatter + тело) с Langfuse Prompt Management. |

Python-зависимости — в `scripts/requirements.txt`. На современных Debian/Ubuntu (Python 3.11+) системный `pip` блокирует установку по PEP 668, поэтому используем venv в корне репо (он уже в `.gitignore`):

```bash
python3 -m venv .venv                              # однократно
.venv/bin/pip install -r scripts/requirements.txt  # однократно / при обновлении deps
.venv/bin/python scripts/prompts_sync.py push      # пример вызова
```

Если `python3 -m venv` ругается на отсутствие `ensurepip`, предварительно: `apt-get install -y python3-venv`.

## Типовые сценарии

```bash
# холодный старт проекта
docker compose up -d
scripts/db_apply_schema.sh                     # накатить schema.sql
scripts/n8n_import_workflows.sh                # импортировать все воркфлоу
.venv/bin/python scripts/prompts_sync.py push  # залить промпты в Langfuse (production-label)

# после правок в UI — выгрузить свежее состояние воркфлоу
scripts/n8n_export_workflows.sh
git diff n8n/workflows/

# проверка, что локальные промпты не разъехались с Langfuse (для CI)
.venv/bin/python scripts/prompts_sync.py check
```
