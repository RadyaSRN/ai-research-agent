# Развёртывание

Полный how-to для поднятия стека локально или на виртуалке. Требования минимальные: Docker Engine + compose-plugin, открытые наружу 80/443 (если нужен HTTPS через Caddy) и домен с A-записями на обе поддомена (n8n и Langfuse).

## Обзор стека

Всё описано в [`docker-compose.yml`](../docker-compose.yml). Контейнеры:

| Сервис                | Образ                                   | Назначение                                                 |
|---|---|---|
| `caddy`               | `caddy:2-alpine`                        | Reverse-proxy + автоматический HTTPS через Let's Encrypt   |
| `postgres`            | `pgvector/pgvector:pg16`                | Основная БД: `app` (наше состояние) + `n8n` (внутр. n8n)   |
| `n8n`                 | `n8nio/n8n:latest`                      | Воркфлоу-движок                                             |
| `langfuse-postgres`   | `postgres:17`                           | Метаданные Langfuse (пользователи, проекты, etc.)          |
| `langfuse-clickhouse` | `clickhouse/clickhouse-server:24`       | Основное storage Langfuse (events, observations)           |
| `langfuse-redis`      | `redis:7`                               | Кэш / очереди Langfuse                                      |
| `langfuse-minio`      | `cgr.dev/chainguard/minio`              | S3-совместимое storage для payload'ов                       |
| `langfuse-worker`     | `langfuse/langfuse-worker:3`            | Фоновые задачи Langfuse (включая LAAJ-эвалуаторы)           |
| `langfuse-web`        | `langfuse/langfuse:3`                   | Web UI + API Langfuse                                       |
| `shipper`             | build from `./shipper`                  | ETL n8n execution_data → Langfuse OTLP (см. `shipper/README.md`) |

## Переменные окружения

Всё хранится в `.env` в корне репозитория (оттуда читают docker-compose, `bench/*.py`, `.agent-memory/refresh.sh`).

### Обязательные для стартa стека

```bash
# Домены (должны разрезолвиться в IP хоста)
N8N_HOST=n8n.example.com
LANGFUSE_HOST=langfuse.example.com
ACME_EMAIL=admin@example.com

# Postgres (основной — для app + n8n)
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<strong-password>
POSTGRES_DB=n8n             # стартовая БД; app создаётся через postgres/init.sql

# n8n
N8N_ENCRYPTION_KEY=<64-hex>
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=<strong-password>

# n8n — отключить телеметрию (опционально, но рекомендовано)
N8N_DIAGNOSTICS_ENABLED=false
N8N_VERSION_NOTIFICATIONS_ENABLED=false
N8N_TEMPLATES_ENABLED=false
EXTERNAL_FRONTEND_HOOKS_URLS=
N8N_DIAGNOSTICS_CONFIG_FRONTEND=
N8N_DIAGNOSTICS_CONFIG_BACKEND=

# Langfuse — служебные БД
LANGFUSE_POSTGRES_USER=langfuse
LANGFUSE_POSTGRES_PASSWORD=<strong-password>
LANGFUSE_POSTGRES_DB=langfuse
LANGFUSE_CLICKHOUSE_USER=clickhouse
LANGFUSE_CLICKHOUSE_PASSWORD=<strong-password>
LANGFUSE_MINIO_ROOT_USER=minio
LANGFUSE_MINIO_ROOT_PASSWORD=<strong-password>
LANGFUSE_REDIS_AUTH=<strong-password>

# Langfuse — приложение
LANGFUSE_SALT=<random-string>
LANGFUSE_ENCRYPTION_KEY=<64-hex>
LANGFUSE_NEXTAUTH_SECRET=<random-string>
LANGFUSE_TELEMETRY_ENABLED=false

# Langfuse API keys — выдаются в UI после первого логина (project settings → API keys).
# Нужны shipper'у и бенчмарку.
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

### Для административных скриптов (bench, `scripts/*`)

```bash
# для scripts/n8n_export_workflows.sh и .agent-memory/refresh.sh
N8N_API_KEY=<из n8n UI → Settings → API → Create API key>

# для alerts_cost_guard и админских уведомлений
ADMIN_TELEGRAM_CHAT_ID=<chat id админа>
```

### Не читаются docker-compose, но лежат в `.env` как единый источник правды

Эти секреты не попадают в окружение контейнеров автоматически — их нужно вручную перенести в соответствующие n8n credentials (таблица в шаге 6). `.env.example` держит их в одном месте, чтобы не разбегались по сервис-паролям / менеджерам:

```bash
# OpenRouter — для openrouter_header_auth и openrouter_chat_model credentials
OPENROUTER_API_KEY=

# GitHub PAT (scope: public_repo) — для github_mcp credential
GITHUB_PAT=

# OpenAlex (необязательно; повышает rate limit) — можно использовать вручную
OPENALEX_API_KEY=
```

Telegram bot token в `.env` не хранится — его достаточно один раз ввести в n8n UI при создании credential `telegram_bot`.

## Шаги развёртывания

### 1. Поднять стек

```bash
git clone <this-repo> && cd ai-research-agent
cp .env.example .env        # или создать вручную по чеклисту выше
docker compose up -d
docker compose ps           # убедиться, что всё healthy
```

Caddy автоматически запросит TLS-сертификаты для `N8N_HOST` и `LANGFUSE_HOST` (при корректных A-записях).

### 2. Накатить схему `app`

```bash
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d app < postgres/schema.sql
```

БД `app` создаётся автоматически при первом старте postgres (через `postgres/init.sql`), `postgres/schema.sql` наполняет её таблицами.

### 3. Настроить Langfuse (в UI)

1. Открыть `https://$LANGFUSE_HOST`, зарегистрировать root-пользователя.
2. Создать organization + project.
3. В Project Settings → API keys сгенерировать пару ключей. Записать `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` в `.env` → перезапустить `shipper` (`docker compose up -d shipper`).
4. Создать два **production-промпта** в Prompt Management:
   - `relevance_score` — rubric для реранкера;
   - `telegram_agent_system` — system для главного агента.

   Либо залить оба промпта из репозитория одной командой:

   ```bash
   python3 -m venv .venv                              # при первом запуске
   .venv/bin/pip install -r scripts/requirements.txt  # при первом запуске
   .venv/bin/python scripts/prompts_sync.py push
   ```

   Скрипт прочитает [`prompts/*.md`](../prompts/) и создаст соответствующие версии в Langfuse с label `production`. Venv-прослойка нужна из-за PEP 668 — на современных Debian/Ubuntu системный `pip` блокирует установку в system-Python.
5. Создать двух LLM-judge **эвалуаторов** на одном rubric'е (имена фиксированы):
   - `relevance_score_judge_experiments`:
     - Run on: `Experiments`;
     - Filter: `Dataset = relevance_score_bench`;
     - Variable mapping: `{{output}}` → Trace → Output;
     - Run on new experiments: ON.
   - `relevance_score_judge_traces`:
     - Run on: `Traces`;
     - Filter: `Tags` содержит `production` или соответствующий тег воркфлоу `relevance_score`;
     - Sampling: 100% (при росте трафика — понизить).
   - В обоих эвалуаторах модель-судья: `anthropic/claude-sonnet-4.6`.

### 4. Установить n8n community nodes

Наш стек использует один community-пакет — `@langfuse/n8n-nodes-langfuse` (нода `Get system prompt from Langfuse` в `relevance_score` и `telegram_agent`, плюс credential-тип `langfuseApi`). Без него импортируемые воркфлоу будут показывать красные "Unknown node type" индикаторы.

В UI n8n: Settings → Community Nodes → Install → `@langfuse/n8n-nodes-langfuse`.

Полный список — [`n8n/community-packages.txt`](../n8n/community-packages.txt) (поддерживается вручную).

### 5. Импортировать n8n-воркфлоу

```bash
scripts/n8n_import_workflows.sh
```

Под капотом — `docker cp n8n/workflows → n8n` container + `n8n import:workflow --separate`.

### 6. Создать credentials в n8n (UI → Credentials)

Имена credentials захардкожены в JSON-экспорте, поэтому создавать их нужно **именно с такими именами**:

| Credential               | Тип n8n                                   | Откуда брать                                                                 |
|---|---|---|
| `postgres_main`          | Postgres                                   | host/port/user/password из `.env` (`POSTGRES_*`), `database=app`, `schema=public` |
| `openrouter_header_auth` | HTTP Header Auth                           | `Authorization: Bearer $OPENROUTER_API_KEY` — для embeddings-вызовов          |
| `openrouter_chat_model`  | OpenRouter (`n8n-nodes-langchain`)         | `$OPENROUTER_API_KEY` — для chat-completions                                  |
| `telegram_bot`           | Telegram API                               | Bot token из BotFather (в `.env` не хранится)                                 |
| `langfuse_api`           | HTTP Basic Auth                            | user=`$LANGFUSE_PUBLIC_KEY`, pass=`$LANGFUSE_SECRET_KEY`                      |
| `github_mcp` (опц.)      | MCP Client                                 | `$GITHUB_PAT` (scope `public_repo`) — только если используется GitHub MCP    |

После импорта: открыть каждый воркфлоу и убедиться, что красных "Credential missing" индикаторов не осталось. Для nested `Execute Workflow`-нод (есть в `telegram_agent`, `digest_scheduler_tick`, `daily_digest_for_user`, `bench_relevance_wrapper`, `bench_search_helper`, `mcp_server`) — убедиться, что workflow резолвится по ID, а не показывает "not found".

### 7. Настроить глобальный Error Workflow

В Settings → Workflows каждого production-воркфлоу (`telegram_agent`, `daily_digest_for_user`, `arxiv_ingestion`, `embeddings_backfill`, `alerts_cost_guard`, `digest_scheduler_tick`, `relevance_score`, `semantic_search_papers`, `arxiv_search`) выставить **Error Workflow** = `alerts_error_handler`.

Проверить smoke-тест: включить `alerts_smoke_test` на 1 прогон, убедиться, что алерт доехал в админский чат, выключить обратно.

### 8. Настроить админский чат для алертов

В `alerts_cost_guard` и `alerts_error_handler` в нодах `Send ... alert` / `Format ... msg` подставлен chat_id админа (или переменная `ADMIN_TELEGRAM_CHAT_ID`). Бот должен быть добавлен в этот чат и иметь право писать.

### 9. Подключить MCP (опционально)

- **GitHub MCP как client:** credential `github_mcp` в n8n → tool `GitHub MCP Client` в `telegram_agent`. Агент через инструмент ходит в GitHub API.
- **Наш `mcp_server` как server:** у MCP Server Trigger в n8n есть публичный URL вида `https://$N8N_HOST/mcp/<uuid>/sse`. Эту ссылку прописать в MCP-клиентах (Cursor / Claude Desktop). Путь после `/mcp/` — рандомный UUID, регенерируется при импорте.

## Эксплуатация

### Обновление воркфлоу

После правок в UI — снять свежий экспорт в репозиторий:

```bash
scripts/n8n_export_workflows.sh    # переписывает n8n/workflows/*.json из n8n API
git diff n8n/workflows/             # убедиться, что изменились только ожидаемые воркфлоу
```

`.md`-описания воркфлоу (`n8n/workflows/<name>.md`) и `README.md` скриптом не трогаются — их нужно править вручную, когда меняется поведение ноды. `.agent-memory/` остаётся приватным кэшем агента и в git не попадает.

### Обновление промптов

```bash
# отредактировать prompts/<name>.md (frontmatter или тело), затем:
.venv/bin/python scripts/prompts_sync.py push   # создаёт новую версию в Langfuse с label production
# воркфлоу начнут тянуть новую версию на следующем запуске (не нужен перезапуск n8n)
```

### Бэкапы

Достаточно сохранять тома `postgres_data`, `langfuse_postgres_data`, `langfuse_clickhouse_data`, `langfuse_minio_data`, `n8n_data`. Остальные (redis, caddy) — stateless-по-сути.

### Мониторинг

- Падения воркфлоу → админский чат (`alerts_error_handler`).
- Стоимость LLM → админский чат (`alerts_cost_guard`).
- Любые глубокие разборы → Langfuse Dashboards (traces/latency/cost/error/LAAJ).

## Известные подводные камни

- **Telemetry n8n по умолчанию включена.** Если `N8N_DIAGNOSTICS_ENABLED` не выключен явно — n8n шлёт анонимную телеметрию. Для приватного инстанса принудительно выключить все 6 env-флагов из блока выше.
- **Langfuse-эвалуаторы не делают backfill.** Если эвалуатор включён *после* того, как dataset-run был завершён, скоров на старые run'ы не появится — нужен новый прогон.
- **MCP-путь регенерируется.** При импорте `mcp_server.json` UUID в пути MCP Server Trigger меняется — внешние клиенты придётся обновить один раз.
- **`shipper` requires checkpoint volume.** Том `shipper_data:/data` держит курсор — если его снести, shipper пере-загрузит всю историю n8n-executions заново (дешёво на свежем инстансе, дорого на старом).
