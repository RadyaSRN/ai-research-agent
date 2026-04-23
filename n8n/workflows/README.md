# n8n workflows

23 воркфлоу n8n, реализующие логику AI Research Agent. Экспорт сделан штатной командой
`n8n export:workflow --all --separate --pretty`, затем отфильтрованы только production-воркфлоу
(тестовые и вспомогательные опущены).

## Как импортировать

Предполагается, что стек уже поднят через корневой `[docker-compose.yml](../../docker-compose.yml)`
и контейнер `n8n` доступен под именем `research-agent-stack-n8n-1` (если у вас другой `COMPOSE_PROJECT_NAME`,
поправьте имя).

```bash
docker cp n8n/workflows research-agent-stack-n8n-1:/tmp/wfimport
docker exec research-agent-stack-n8n-1 n8n import:workflow --separate --input=/tmp/wfimport
docker exec research-agent-stack-n8n-1 rm -rf /tmp/wfimport
```

После импорта воркфлоу появятся в UI с теми же именами, что и имена файлов.
Статус `active` у каждого воркфлоу — как в `active` поле JSON-файла: production-воркфлоу
импортятся уже активированными; выключенными остаются только `alerts_smoke_test` и
`bench_search_helper` (включаются вручную на время конкретных проверок/пересборок).

## Обязательные credentials в n8n

Настраиваются один раз вручную в UI `Credentials → New`. Имена credentials в экспорте захардкожены —
если создадите с такими же названиями, воркфлоу подхватят их автоматически.

| Имя credential | Тип в n8n | Что внутри |
|---|---|---|
| `postgres_main` | Postgres | host/port/user/password/database из `.env` (секция Postgres); `database=app`, `schema=public` |
| `openrouter_header_auth` | HTTP Header Auth | `Authorization: Bearer ${OPENROUTER_API_KEY}` — для embeddings-вызовов |
| `openrouter_chat_model` | OpenRouter (n8n-nodes-langchain) | тот же OpenRouter API-ключ — для chat-completions в `telegram_agent` и `relevance_score` |
| `telegram_bot` | Telegram API | Bot token из `@BotFather` |
| `langfuse_api` | HTTP Basic Auth | user = Langfuse public key (`pk-lf-...`), pass = secret key (`sk-lf-...`) — для вызовов Langfuse REST/Metrics API |
| `github_mcp` | MCP Client (опционально) | Если используется GitHub MCP tool в `telegram_agent` — токен с scope `public_repo` |

Проверить после импорта: открыть каждый воркфлоу в UI, убедиться, что все красные индикаторы
"Credential missing" заменены на зелёные. Для nested `Execute Workflow` нод (есть в `telegram_agent`,
`digest_scheduler_tick`, `daily_digest_for_user`, `bench_relevance_wrapper`, `bench_search_helper`,
`mcp_server`) — проверить, что выбранные workflow резолвятся по ID (а не "not found").

## Обязательные Langfuse prompts

В Langfuse UI нужно создать два production-промпта (активная версия `production`):

- `relevance_score` — system для `relevance_score` (LLM-as-judge-подобный rubric)
- `telegram_agent_system` — system для главного агента

Имена и версии подхватываются из node `Get system prompt from Langfuse` внутри соответствующих воркфлоу.

## Таблица-индекс

### Telegram-интерфейс

| name | trigger | описание | документ |
|---|---|---|---|
| `telegram_agent` | telegramTrigger | Главный вход бота: роутинг slash-команд + LangChain-агент с 12 tools, chat memory и GitHub MCP | [telegram_agent.md](telegram_agent.md) |
| `mcp_server` | mcpTrigger | MCP-сервер, отдающий наружу `semantic_search_papers` и `arxiv_search` для внешних MCP-клиентов | [mcp_server.md](mcp_server.md) |

### Projects / Ideas CRUD

| name | trigger | описание | документ |
|---|---|---|---|
| `add_idea` | executeWorkflow | Insert idea + embedding в `ideas` | [add_idea.md](add_idea.md) |
| `add_project` | executeWorkflow | Insert project + embedding в `projects` | [add_project.md](add_project.md) |
| `list_ideas` | executeWorkflow | Список идей пользователя (опционально по project_id) | [list_ideas.md](list_ideas.md) |
| `list_projects` | executeWorkflow | Список проектов пользователя | [list_projects.md](list_projects.md) |
| `update_idea_status` | executeWorkflow | Меняет `ideas.status` с валидацией owner'а | [update_idea_status.md](update_idea_status.md) |
| `update_project_status` | executeWorkflow | Меняет `projects.status` с валидацией owner'а | [update_project_status.md](update_project_status.md) |

### Digest scheduling

| name | trigger | описание | документ |
|---|---|---|---|
| `get_digest_schedule` | executeWorkflow | Возвращает текущее расписание дайджеста | [get_digest_schedule.md](get_digest_schedule.md) |
| `set_digest_schedule` | executeWorkflow | UPSERT расписания (локальное время + TZ) | [set_digest_schedule.md](set_digest_schedule.md) |
| `unset_digest_schedule` | executeWorkflow | Выключает дайджест (без удаления записи) | [unset_digest_schedule.md](unset_digest_schedule.md) |
| `digest_scheduler_tick` | schedule (1 мин) | Минутный cron: находит due-юзеров и зовёт `daily_digest_for_user` | [digest_scheduler_tick.md](digest_scheduler_tick.md) |
| `daily_digest_for_user` | executeWorkflow | Двухуровневая фильтрация (cosine → LLM) + отправка digest в Telegram | [daily_digest_for_user.md](daily_digest_for_user.md) |

### Ingestion / retrieval / ranking

| name | trigger | описание | документ |
|---|---|---|---|
| `arxiv_ingestion` | schedule (daily 09:10) | Cron ingestion новых arXiv-препринтов (cs.LG/CL/CV/AI) | [arxiv_ingestion.md](arxiv_ingestion.md) |
| `arxiv_search` | executeWorkflow | On-demand поиск на arXiv, апсертит новые статьи + embeddings | [arxiv_search.md](arxiv_search.md) |
| `embeddings_backfill` | schedule (1 мин) | Догоняет отсутствующие embeddings в `paper_embeddings` | [embeddings_backfill.md](embeddings_backfill.md) |
| `semantic_search_papers` | executeWorkflow | pgvector HNSW-поиск top-K по корпусу `papers` | [semantic_search_papers.md](semantic_search_papers.md) |
| `relevance_score` | executeWorkflow | LLM-reranker (idea × paper) → 0..10 score + reasoning | [relevance_score.md](relevance_score.md) |

### Benchmark

| name | trigger | описание | документ |
|---|---|---|---|
| `bench_relevance_wrapper` | webhook (POST /webhook/bench-relevance) | HTTP-вход для `bench/run_bench.py`, прокидывает trace_id в `relevance_score` | [bench_relevance_wrapper.md](bench_relevance_wrapper.md) |
| `bench_search_helper` | webhook (POST /webhook/bench-search, off) | HTTP-вход для `bench/run_semantic.py`, оборачивает `semantic_search_papers` (включается только на время пересборки датасета) | [bench_search_helper.md](bench_search_helper.md) |

### Alerting

| name | trigger | описание | документ |
|---|---|---|---|
| `alerts_cost_guard` | schedule (15 мин) | Следит за стоимостью LLM через Langfuse metrics, алерт в TG с дедупом по `alert_buckets` | [alerts_cost_guard.md](alerts_cost_guard.md) |
| `alerts_error_handler` | errorTrigger | Глобальный error workflow — уведомляет в TG при падениях | [alerts_error_handler.md](alerts_error_handler.md) |
| `alerts_smoke_test` | schedule (off) | Ручной тест error-пути — включать только для проверки | [alerts_smoke_test.md](alerts_smoke_test.md) |

## Связи между воркфлоу (граф вызовов)

```
telegram_agent
├── add_idea, add_project
├── list_ideas, list_projects
├── update_idea_status, update_project_status
├── set/get/unset_digest_schedule
├── semantic_search_papers
├── arxiv_search
└── daily_digest_for_user → relevance_score

digest_scheduler_tick → daily_digest_for_user → relevance_score

bench_relevance_wrapper → relevance_score
bench_search_helper     → semantic_search_papers

mcp_server
├── semantic_search_papers
└── arxiv_search

arxiv_ingestion (stand-alone cron)
embeddings_backfill (stand-alone cron)
alerts_cost_guard (stand-alone cron)
alerts_error_handler (global error workflow)
```

## Замечания по портированию

- Все SQL в воркфлоу написаны под схему из [`postgres/schema.sql`](../../postgres/schema.sql). Перед импортом прогнать её в Postgres (`docker compose exec -T postgres psql -U postgres -d app < postgres/schema.sql`).
- `n8n_chat_histories` таблицу создаст сам n8n при первом запуске `telegram_agent`'а (через `Postgres Chat Memory`).
- Если вы подняли Langfuse локально с другим хостом, замените `https://langfuse.ai-research-agent.com` в URL-параметрах HTTP-нод (`alerts_cost_guard` использует его явно) на свой.
- `relevance_score` и `telegram_agent` тянут промпты из Langfuse по имени; без заведённых промптов они упадут.
