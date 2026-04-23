# list_ideas

**Trigger**: `executeWorkflow`
**Active by default**: yes

## Назначение

Возвращает список idea пользователя, опционально отфильтрованный по `project_id`. Tool-ручка для LLM-агента и напрямую для команды `/ideas`.

## Входы

- `user_id` (UUID) — обязательный
- `project_id` (UUID) — опционально; если задан, возвращает только идеи внутри этого проекта

## Выходы

Массив объектов `{id, project_id, title, description, status, keywords, created_at}`, отсортирован по `created_at DESC`.

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: `telegram_agent` (tool и команда `/ideas`)
- **Credentials в n8n**: `postgres_main`
- **Таблицы БД**: читает `ideas`
