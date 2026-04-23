# get_digest_schedule

**Trigger**: `executeWorkflow`
**Active by default**: yes

## Назначение

Возвращает текущее расписание daily-digest пользователя (время отправки и таймзону) или признак отсутствия расписания. Tool-ручка для LLM-агента.

## Входы

- `user_id` (UUID)

## Выходы

- Если расписание есть: `{success: true, enabled, send_time, timezone, next_run_at}`
- Если нет: `{success: true, enabled: false}`

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: `telegram_agent` (tool)
- **Credentials в n8n**: `postgres_main`
- **Таблицы БД**: читает `digest_schedules`
