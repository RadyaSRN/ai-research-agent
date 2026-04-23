# add_idea

**Trigger**: `executeWorkflow` (вызывается из `telegram_agent`)
**Active by default**: yes

## Назначение

Добавляет новую research-idea пользователя в таблицу `ideas`: считает embedding (1536-dim) от `title + description + keywords` и сохраняет вместе с метаданными. Одна из tool-ручек LLM-агента.

## Входы

- `user_id` (UUID) — владелец идеи
- `project_id` (UUID) — проект, к которому относится идея
- `title` (text) — короткое название
- `description` (text) — развёрнутое описание идеи
- `keywords` (text[] или comma-separated string) — ключевые слова для retrieval

## Выходы

Возвращает вставленную строку `ideas` (`id, project_id, title, status='active', created_at`).

## Что делает по шагам

1. `Set` склеивает `title + description + keywords` в `embedding_text`.
2. `HTTP Request (embeddings)` — POST на OpenRouter `/v1/embeddings` с моделью `openai/text-embedding-3-small`.
3. `Code in JavaScript` — сериализует vector в pgvector-литерал.
4. `Insert idea` — `INSERT INTO ideas(...) RETURNING *`.

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: `telegram_agent` (tool)
- **Credentials в n8n**: `postgres_main`, `openrouter_header_auth` (HTTP Header Auth с `Authorization: Bearer ${OPENROUTER_API_KEY}`)
- **Внешние сервисы**: OpenRouter embeddings API
- **Таблицы БД**: пишет `ideas`; использует column `embedding vector(1536)` (pgvector)

## Примечания

Поле `embedding_model_version` хардкодится как `openai/text-embedding-3-small`. При смене модели нужно обновить и эту строку, и параметры HTTP-ноды.
