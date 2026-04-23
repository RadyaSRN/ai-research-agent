# Архитектура

Документ раскрывает пункты 2 (система + интерфейс), 3 (инструменты агента) и 4 (логирование) из требований. Подход: инфраструктура в контейнерах (`docker-compose.yml`), бизнес-логика — граф n8n-воркфлоу, состояние — Postgres с pgvector, observability — Langfuse.

## Обзор системы

```
              ┌────────────────┐
              │ Исследователь  │
              │    (Telegram)  │
              └────────┬───────┘
                       │  HTTPS (bot API)
                       ▼
        ┌────────────────────────────┐
        │ Caddy (reverse proxy + TLS)│
        └──────────┬────────────┬────┘
                   │            │
         n8n.*     │            │    langfuse.*
                   ▼            ▼
            ┌───────────┐ ┌───────────────┐
            │    n8n    │ │ Langfuse web  │
            │ (24 wf)   │ │ + worker      │
            └─────┬─────┘ └────┬──────────┘
                  │            │
       ┌──────────┼────────────┴───────┐
       ▼          ▼                    ▼
  ┌────────┐ ┌─────────┐        ┌──────────┐
  │Postgres│ │ Postgres│        │ClickHouse│
  │ (app + │ │(langfuse│        │  (lf)    │
  │  n8n)  │ │  meta)  │        └──────────┘
  │pgvector│ └─────────┘
  └───┬────┘
      │
      │  n8n.execution_data
      ▼
  ┌──────────────────────────┐   OTLP   ┌──────────────┐
  │ n8n-langfuse-shipper     │─────────▶│ Langfuse OTel│
  │ (batch ETL, 60s tick)    │          │   ingest     │
  └──────────────────────────┘          └──────────────┘

  ┌──────────────────────────┐   Ingestion API   ┌────────┐
  │  bench/run_bench.py      │──────────────────▶│Langfuse│
  │  (прямые trace-create)   │                   └────────┘
  └──────────────────────────┘
```

Внешние сервисы, которые дёргают воркфлоу n8n: OpenRouter (chat completions и embeddings), arXiv API (Atom-фид), Telegram Bot API, Langfuse Public API (метрики, промпты), GitHub MCP (отдельный self-hosted или managed сервер).

## n8n-граф (24 воркфлоу)

Полный каталог с описаниями — [`n8n/workflows/README.md`](../n8n/workflows/README.md); на каждую единицу есть своя `.md`-страница в той же папке. Здесь — структурный срез.

**Telegram-интерфейс:**

- `telegram_agent` — главная точка входа. Роутит slash-команды, всё прочее отдаёт LangChain-агенту с memory (Postgres), промптом из Langfuse и большим списком tools (см. ниже). Модель агента — `openai/gpt-5.4-mini`.
- `mcp_server` — MCP Server Trigger. Экспонирует наружу два tool'а из стека (`semantic_search_papers`, `arxiv_search`); любой MCP-совместимый клиент (Cursor, Claude Desktop) может подключиться и пользоваться персональным корпусом.

**Projects / Ideas CRUD:** `add_idea`, `add_project`, `list_ideas`, `list_projects`, `update_idea_status`, `update_project_status`. Все — тонкие обёртки над Postgres; `add_*` дополнительно считают эмбеддинг от title/description/keywords через OpenRouter и сохраняют его рядом с записью.

**Digest scheduling:** `set_digest_schedule`, `get_digest_schedule`, `unset_digest_schedule`, `digest_scheduler_tick` (минутный cron), `daily_digest_for_user` (сам сборщик дайджеста).

**Ingestion / retrieval / ranking:** `arxiv_ingestion` (ежедневный cron из arXiv Atom API), `arxiv_search` (on-demand), `embeddings_backfill` (минутный cron, чинит пропущенные embeddings), `semantic_search_papers` (pgvector HNSW top-K), `relevance_score` (LLM-реранкер, ядро ранжирования).

**Alerting:** `alerts_cost_guard` (каждые 15 мин), `alerts_error_handler` (глобальный Error Workflow n8n), `alerts_smoke_test` (ручной smoke для error-пайплайна).

**Benchmark:** `bench_relevance_wrapper` (webhook-обёртка для `bench/run_bench.py`), `bench_search_helper` (off по умолчанию; включается только на время пересборки датасета).

Граф вызовов между воркфлоу:

```
telegram_agent
 ├─ add_idea / add_project / list_* / update_*_status
 ├─ set/get/unset_digest_schedule
 ├─ semantic_search_papers
 ├─ arxiv_search
 └─ daily_digest_for_user → relevance_score

digest_scheduler_tick → daily_digest_for_user → relevance_score
bench_relevance_wrapper → relevance_score
bench_search_helper     → semantic_search_papers
mcp_server              → semantic_search_papers, arxiv_search
```

Автономные cron'ы без зависимостей: `arxiv_ingestion`, `embeddings_backfill`, `alerts_cost_guard`, `alerts_error_handler` (глобальный error-hook n8n).

## <a id="tools"></a>Инструменты LLM-агента

Главный агент собирает tool'ы из `@n8n/n8n-nodes-langchain.agent` + `toolWorkflow`-нод. Каждый tool — это вызов через API (Postgres / OpenRouter / arXiv API / GitHub MCP), т.е. соответствует определению "конкретное действие через API" из требований.

| Tool                        | Что делает                                                              | API под капотом           |
|---|---|---|
| `add_idea`                  | INSERT в `ideas` + embedding                                            | Postgres, OpenRouter emb. |
| `add_project`               | INSERT в `projects` + embedding                                         | Postgres, OpenRouter emb. |
| `list_ideas`                | SELECT идей пользователя (опц. фильтр по project_id)                     | Postgres                  |
| `list_projects`             | SELECT проектов пользователя                                            | Postgres                  |
| `update_idea_status`        | UPDATE статуса с валидацией ownership                                   | Postgres                  |
| `update_project_status`     | UPDATE статуса с валидацией ownership                                   | Postgres                  |
| `set_digest_schedule`       | UPSERT расписания дайджеста (local time + TZ)                            | Postgres                  |
| `get_digest_schedule`       | SELECT расписания                                                        | Postgres                  |
| `unset_digest_schedule`     | UPDATE (выкл.) расписания                                                | Postgres                  |
| `semantic_search_papers`    | Embedding запроса → pgvector HNSW top-K                                 | OpenRouter emb., Postgres |
| `arxiv_search`              | arXiv Atom API → upsert в corpus + enqueue эмбеддинги                   | arXiv API, Postgres       |
| `daily_digest_for_user`     | Полный дайджест-пайплайн (on-demand через `/digest`)                     | Postgres, OpenRouter, TG  |
| `GitHub MCP`                | Поиск по репозиториям/коду/issue через внешний MCP-сервер               | GitHub API (через MCP)    |

Минимум из требований (>3 tool'ов) перекрыт в ~4 раза. Внутри tools покрыты обе роли "базового примера" из п. 3.2:

- **API источника данных:** `arxiv_search`, `semantic_search_papers`, `GitHub MCP`.
- **GPT:** `relevance_score` (через `daily_digest_for_user` внутри tool'а `/digest`) + сам `telegram_agent` как LLM-диспетчер.
- **MCP для соединения:** внешний GitHub MCP (агент-клиент) + собственный `mcp_server` (сервер, отдающий `semantic_search_papers` и `arxiv_search` наружу).
- **API выхода:** Telegram Bot API (ответы пользователю), Postgres (персистентность состояния).

### Retrieval в дайджесте (RAG + LLM rerank)

`daily_digest_for_user` — не просто вызов одного tool'а, а двухуровневый pipeline:

1. **Retrieval.** LATERAL JOIN по `ideas` пользователя, для каждой активной идеи — cosine top-N свежих недоставленных статей из `papers` через HNSW-индекс `idx_paper_embeddings_hnsw`. Это классический RAG-подход: грубый отбор эмбеддингами, без LLM-затрат.
2. **Rerank.** Каждая пара `(idea, paper)` отправляется в `relevance_score` (LLM-чейн с system-промптом из Langfuse и structured output). Выдаёт `relevance_score` 0–10, `reasoning`, `key_concepts_matched`.
3. **Threshold + сборка.** Отсекаются пары со скором ниже порога, оставшиеся группируются по идее, формируются в Markdown-сообщение с ссылками на arXiv и reasoning'ом, отправляются в Telegram, сам результат записывается в `idea_paper_matches` и `digest_history` для дедупа на следующий день.

## Модель данных

Полная схема — [`postgres/schema.sql`](../postgres/schema.sql). Ключевые таблицы:

| Таблица              | Назначение                                                                 |
|---|---|
| `users`              | 1:1 с Telegram chat_id                                                      |
| `projects`           | Исследовательские проекты; `embedding vector(1536)` (title+desc+keywords)   |
| `ideas`              | Идеи/направления внутри проектов; `embedding vector(1536)`                  |
| `papers`             | Корпус arXiv-статей (unique arxiv_id с версией)                             |
| `paper_embeddings`   | 1536-dim эмбеддинги (title+abstract), HNSW-индекс `idx_paper_embeddings_hnsw` |
| `idea_paper_matches` | Дедуп-слой: какие пары уже доставлялись в дайджесте (с LLM-скором)          |
| `digest_history`     | История отправленных дайджестов: paper_ids, message_text, telegram_message_id |
| `digest_schedules`   | Пер-пользовательские расписания (local time + TZ)                           |
| `alert_buckets`      | Идемпотентность алертов (UNIQUE constraint на `alert_key + bucket_id`)       |
| `n8n_chat_histories` | Chat memory для `telegram_agent` (управляется n8n Postgres Chat Memory)     |

## <a id="observability"></a>Логирование и observability

### Что пишется

- **Трейсы LLM-вызовов** — в Langfuse (модель, токены, стоимость, latency, вложенность в workflow-spans).
- **Промпты** — в Langfuse Prompt Management: `relevance_score`, `telegram_agent_system`. Воркфлоу на каждом запуске тянут активную production-версию через ноду `Get system prompt from Langfuse`. Source of truth для редактуры — папка [`prompts/`](../prompts/) в этом репозитории; синк с Langfuse — `scripts/prompts_sync.py`.
- **Состояние домена** — в Postgres (`app`-DB).
- **Служебные алерты** — в Telegram (отдельный админский чат).

### Как трейсы попадают в Langfuse

Два канала, сливающихся в одну и ту же трассу:

1. **n8n → shipper → Langfuse (OTLP).** В стек встроен self-hosted [`n8n-langfuse-shipper`](https://github.com/rwb-truelime/n8n-langfuse-shipper) — community-интеграция, указанная в [Langfuse docs / n8n integration](https://langfuse.com/integrations/no-code/n8n). Он батчами (раз в `SHIPPER_SLEEP_SECONDS=60`) читает `execution_data` из n8n-Postgres, превращает его в OTLP-спаны и отправляет в Langfuse. Подробнее: [`shipper/README.md`](../shipper/README.md).

2. **bench / Langfuse Ingestion API.** Скрипт `bench/run_bench.py` сам создаёт `trace-create` и `generation-create` события через REST (preflight — до вызова воркфлоу, чтобы OTLP-спаны shipper'а не успели создать "чистый production"-трейс). Шипер распознаёт в `execution_data` поле `langfuse_trace_id` (по переменной `LANGFUSE_TRACE_ID_FIELD_NAME`), использует его как `trace_id` для своих OTLP-спанов — и оба канала оказываются в одной траесе. Подробнее: [`bench/README.md`](../bench/README.md).

### Алерты в Telegram

- `alerts_error_handler` — глобальный Error Workflow n8n (настраивается в Workflow Settings → Error Workflow для каждого production-воркфлоу). Падения отправляются в админский чат с именем воркфлоу, нодой и error message.
- `alerts_cost_guard` — cron раз в 15 минут: читает Langfuse Metrics API, суммирует стоимость за последний час и сутки, сравнивает с порогами, шлёт алерт при превышении. Дедуп — через `alert_buckets` (`INSERT ... ON CONFLICT DO NOTHING RETURNING *`: если возвращённой строки нет, значит, алерт уже слали в этот бакет).
- `alerts_smoke_test` — выключенный по умолчанию smoke для пути через error-handler (включается вручную на 1 прогон, чтобы убедиться, что цепочка живая).

### Дашборды

В Langfuse Dashboards собраны:

- **Traces + Cost** — общее число трассировок в сутки и стоимость;
- **Error rate** — доля error-трассировок;
- **LAAJ-скоры + штрафные метрики** — онлайн-оценка релевантности/полезности от второго эвалуатора, плюс штрафы за ошибки / таймауты.

Скриншоты — в [`docs/evals.md`](evals.md).
