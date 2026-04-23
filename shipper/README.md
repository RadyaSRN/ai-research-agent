# shipper

Self-hosted экземпляр [`n8n-langfuse-shipper`](https://github.com/rwb-truelime/n8n-langfuse-shipper) — community-интеграции, которая батчами читает execution_data из Postgres-БД n8n, превращает её в OTLP-спаны и отправляет в Langfuse. На стороне Langfuse эта интеграция упомянута в [официальной странице интеграции с n8n](https://langfuse.com/integrations/no-code/n8n) (раздел *Community Supported*).

## Зачем нужен

У n8n нет нативной интеграции с Langfuse, которая бы переносила всю исполняемую трассу воркфлоу со всеми нодами и run-data. Langfuse-нода n8n умеет посылать только отдельные ingest-вызовы; этого мало, чтобы видеть в Langfuse полноценные иерархические трассы LangChain-агента (с ветвлениями, retry-ами, nested workflow). Shipper решает это через post-hoc-ETL: читает n8n's `execution_data` (где лежит весь run-data) и пере-собирает из неё OTLP-граф спанов с правильной иерархией.

## Что в этой папке

- `Dockerfile` — образ на базе python:3.12-slim. Клонирует [`rwb-truelime/n8n-langfuse-shipper`](https://github.com/rwb-truelime/n8n-langfuse-shipper) (по `SHIPPER_REF`, по умолчанию `main`), накладывает локальный патч на pydantic-модель `NodeRunData` (нужен, чтобы корректно фильтровать `null`-элементы в `source` без падения валидации), ставит пакет.
- `entrypoint.sh` — простой while-loop, дёргает `n8n-shipper shipper --limit $SHIPPER_BATCH_LIMIT --no-dry-run` каждые `$SHIPPER_SLEEP_SECONDS` секунд. Чекпоинт-файл (`/data/.shipper_checkpoint`) гарантирует, что после рестарта shipper продолжит с того же места.

Сам контейнер описан в `docker-compose.yml` как сервис `shipper` (build из этой папки).

## Конфигурация (env-переменные сервиса)

Передаются в `docker-compose.yml` → `services.shipper.environment`:

| Переменная                       | Назначение                                                                                          |
|---|---|
| `PG_DSN`                         | Подключение к Postgres-БД n8n (читается `execution_data`)                                            |
| `DB_TABLE_PREFIX`                | Префикс таблиц n8n (по умолчанию пустой)                                                             |
| `LANGFUSE_HOST`                  | Внутренний URL Langfuse (`http://langfuse-web:3000`)                                                 |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Project API keys из Langfuse UI                                                          |
| `LANGFUSE_ENV`                   | Тег среды (`production` / `staging`)                                                                 |
| `FILTER_AI_ONLY`                 | `false` — слать все executions; `true` — только те, где есть LangChain/AI-ноды                       |
| `SHIPPER_SLEEP_SECONDS`          | Период между батчами (по умолчанию 60)                                                               |
| `SHIPPER_BATCH_LIMIT`            | Сколько executions брать за один тик (по умолчанию 500)                                              |
| `SHIPPER_CHECKPOINT_DIR`         | Директория для cursor-файла (примонтирован volume `shipper_data`)                                    |
| `ROOT_SPAN_INPUT_NODE`           | Имя ноды, чей input станет input-ом root-спана трассы (`When Executed by Another Workflow`)          |
| `ROOT_SPAN_OUTPUT_NODE`          | Имя ноды, чей output станет output-ом root-спана трассы (`Return`)                                   |
| `LANGFUSE_TRACE_ID_FIELD_NAME`   | Имя поля в run-data, в котором искать готовый trace_id для merge с внешним трейсом (`langfuse_trace_id`) |

Последняя переменная — ключ к интеграции с бенчмарком. `bench/run_bench.py` сначала создаёт трассу напрямую через Ingestion API, получает `trace_id`, и кладёт его в input воркфлоу под именем `langfuse_trace_id`. Когда shipper потом обрабатывает то же execution, он находит это поле, использует его как OTLP `trace_id` для своих спанов — и в Langfuse получается одна склеенная трасса, в которой видны и preflight-`generation` от bench, и весь n8n-граф от shipper. Подробнее см. [`bench/README.md`](../bench/README.md) и [`n8n/workflows/relevance_score.md`](../n8n/workflows/relevance_score.md#примечания).

## Эксплуатация

- Логи: `docker compose logs -f shipper` — на каждой итерации печатается `[shipper] tick <ISO>`.
- Сброс курсора (если нужно перелить всё с нуля): `docker compose down shipper && docker volume rm research-agent-stack_shipper_data && docker compose up -d shipper`.
- Обновление до свежей версии shipper: пересобрать с другим `SHIPPER_REF` — `docker compose build --build-arg SHIPPER_REF=<branch_or_tag> shipper && docker compose up -d shipper`.
