# list_projects

**Trigger**: `executeWorkflow`
**Active by default**: yes

## Назначение

Возвращает все проекты пользователя. Tool-ручка для LLM-агента и для команды `/projects`.

## Входы

- `user_id` (UUID)

## Выходы

Массив `{id, title, description, status, keywords, created_at}`, сортировка `created_at DESC`.

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: `telegram_agent` (tool и команда `/projects`)
- **Credentials в n8n**: `postgres_main`
- **Таблицы БД**: читает `projects`
