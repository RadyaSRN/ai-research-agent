# add_project

**Trigger**: `executeWorkflow` (вызывается из `telegram_agent`)
**Active by default**: yes

## Назначение

Создаёт новый research-project пользователя в таблице `projects` с посчитанным embedding-ом. Точно такая же схема, как у `add_idea`, но без `project_id` и с записью в другую таблицу.

## Входы

- `user_id` (UUID)
- `title` (text)
- `description` (text)
- `keywords` (text[] или comma-separated)

## Выходы

Вставленная строка `projects` (`id, user_id, title, status='active', created_at`).

## Что делает по шагам

1. `Set` готовит `embedding_text = title + description + keywords`.
2. `HTTP Request (embeddings)` — OpenRouter `/v1/embeddings` (`openai/text-embedding-3-small`).
3. `Code in JavaScript` — конвертирует embedding в pgvector-литерал.
4. `Insert project` — `INSERT INTO projects(...) RETURNING *`.

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: `telegram_agent` (tool)
- **Credentials в n8n**: `postgres_main`, `openrouter_header_auth`
- **Внешние сервисы**: OpenRouter embeddings API
- **Таблицы БД**: пишет `projects`
