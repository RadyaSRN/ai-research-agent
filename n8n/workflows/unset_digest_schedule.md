# unset_digest_schedule

**Trigger**: `executeWorkflow`
**Active by default**: yes

## Назначение

Выключает daily-digest у пользователя: ставит `is_enabled = false` в `digest_schedules`. Запись не удаляется, чтобы сохранить прошлое расписание для возможной реактивации. Tool-ручка для LLM-агента.

## Входы

- `user_id` (UUID)

## Выходы

- `{success: true, enabled: false}`

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: `telegram_agent` (tool)
- **Credentials в n8n**: `postgres_main`
- **Таблицы БД**: пишет `digest_schedules`
