# embeddings_backfill

**Trigger**: Schedule (каждую минуту)
**Active by default**: yes

## Назначение

Догоняющий воркфлоу: находит статьи в `papers`, у которых нет записи в `paper_embeddings` (например, если OpenRouter упал во время `arxiv_ingestion` или `arxiv_search`), и дозаполняет embeddings для них. Работает по одной пачке за тик, постепенно восстанавливая консистентность.

## Входы

- Внешних входов нет — триггер по расписанию.

## Выходы

- Новые строки в `paper_embeddings` для ранее пропущенных статей.

## Что делает по шагам

1. `Find papers without embeddings` — `SELECT p.id, p.title, p.abstract FROM papers p LEFT JOIN paper_embeddings pe ON pe.paper_id = p.id WHERE pe.paper_id IS NULL LIMIT N`.
2. `HTTP Request (embeddings)` — батч на OpenRouter.
3. `IF got embedding` — пропускает пустые ответы.
4. `Postgres (paper_embeddings)` — `INSERT ... ON CONFLICT DO NOTHING`.

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: нет (автономный cron)
- **Credentials в n8n**: `postgres_main`, `openrouter_header_auth`
- **Внешние сервисы**: OpenRouter embeddings
- **Таблицы БД**: читает `papers`, `paper_embeddings`; пишет `paper_embeddings`

## Примечания

Крутится ежеминутно — безопасно, т.к. работает только когда действительно есть пропуски. Это исключает необходимость повторно ingesting всё при сбоях.
